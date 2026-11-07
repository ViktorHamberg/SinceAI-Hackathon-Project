"""Price label/reconstruction utilities; no LightGBM import, fitting or filesystem I/O.

These records are private numerical inputs, not new application/result contracts.
They can contain restricted spot values or reconstruct them from differences: never
log/serialize the tables or publish them as explanations. Evidence is value-free.
Frozen envelopes do not make caller-owned pandas objects deeply immutable.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from ..config import HORIZON_STEPS, STEP_MINUTES
from ..features.asof import FeatureBatch
from ..features.training import TrainingExamples
from ..provenance import DependencyEvidence, derive_evidence

if TYPE_CHECKING:
    import pandas as pd

PriceTargetMode = Literal["direct", "spot_relative"]
_SPOT_FEATURE = "fi_spot_price_delivery"
_QUANTILES = ("p10", "p50", "p90")


@dataclass(frozen=True, repr=False)
class PriceTargets:
    mode: PriceTargetMode
    values: "pd.Series" = field(repr=False)
    eligible: "pd.Series" = field(repr=False)
    label_evidence: tuple[DependencyEvidence | None, ...] = field(repr=False)
    unit: str = "EUR/MWh"


@dataclass(frozen=True, repr=False)
class ReconstructedPrices:
    """Unresolved relative rows need the separately fitted direct model in Step 2C.

    prices has p10/p50/p90 columns in EUR/MWh. For relative rows without published
    delivery spot all three values are NaN and requires_direct_backup is true. Such
    rows are NOT a completed forecast and cannot be exported without resolving them.
    spot_evidence records the deterministic reconstruction offset, not a learned
    feature contribution. Quantile crossing is intentionally left to model policy.
    """

    mode: PriceTargetMode
    prices: "pd.DataFrame" = field(repr=False)
    requires_direct_backup: "pd.Series" = field(repr=False)
    spot_evidence: tuple[DependencyEvidence | None, ...] = field(repr=False)
    unit: str = "EUR/MWh"


def _check_mode(mode):
    if mode not in ("direct", "spot_relative"):
        raise ValueError("price target mode must be direct or spot_relative")


def _numeric(series):
    import numpy as np
    from pandas.api.types import is_bool_dtype, is_complex_dtype, is_numeric_dtype

    if (not is_numeric_dtype(series.dtype) or is_bool_dtype(series.dtype)
            or is_complex_dtype(series.dtype)):
        raise ValueError("price values must have real numeric dtypes")
    values = series.to_numpy(dtype=float, na_value=np.nan, copy=True)
    if np.isinf(values).any():
        raise ValueError("price values must be finite or missing")
    return values


def _check_features(features):
    """Check row identity before combining mutable tables with separate evidence."""
    import pandas as pd

    if not isinstance(features, FeatureBatch):
        raise TypeError("target utilities require FeatureBatch")
    frame = features.frame
    if (frame.empty or not frame.index.is_unique or len(frame) != len(features.evidence)
            or not {"forecast_origin_utc", "delivery_start_utc", "step"}.issubset(frame.columns)):
        raise ValueError("feature rows and evidence must be aligned")
    for name in ("forecast_origin_utc", "delivery_start_utc"):
        if not isinstance(frame[name].dtype, pd.DatetimeTZDtype) or str(frame[name].dt.tz) != "UTC":
            raise ValueError("feature timestamps must be timezone-aware UTC")
        if frame[name].isna().any():
            raise ValueError("feature timestamps must be nonmissing")
    for origin, part in frame.groupby("forecast_origin_utc", sort=False):
        if origin != origin.floor("h") or list(part["step"]) != list(range(1, HORIZON_STEPS + 1)):
            raise ValueError("feature rows must contain ordered complete horizons")
    for row, record in zip(frame.itertuples(index=False), features.evidence):
        if (row.forecast_origin_utc != record.forecast_origin_utc
                or row.delivery_start_utc != record.delivery_start_utc or row.step != record.step
                or row.delivery_start_utc != row.forecast_origin_utc + pd.Timedelta(minutes=(row.step - 1) * STEP_MINUTES)):
            raise ValueError("feature rows and evidence must be aligned")


def _check_label(evidence, series, delivery, config):
    if evidence is None or len(evidence.sources) != 1:
        raise ValueError("eligible price components require exact label evidence")
    source = evidence.sources[0]
    if (source.series_id != series or source.timestamp_utc != delivery
            or not config.label_start_utc <= delivery < config.label_end_utc
            or not source.first_usable_origin_utc <= source.used_at_utc <= evidence.used_at_utc <= config.fit_cutoff_utc):
        raise ValueError("price label evidence violates fitting boundaries")


def build_price_targets(examples: TrainingExamples, *, mode: PriceTargetMode = "direct") -> PriceTargets:
    """Detach direct labels, or eligible imbalance-minus-spot pairs, from Step 1B.

    Preserve row order/index and missing values. Direct labels do not depend on spot
    availability or any direction/spike mask. Relative labels require both original
    fitting-eligible components and carry their transitive source evidence. These
    fitting-time labels are never used as historical reconstruction features.
    """
    import numpy as np
    import pandas as pd
    from pandas.api.types import is_bool_dtype

    _check_mode(mode)
    if not isinstance(examples, TrainingExamples):
        raise TypeError("price targets require TrainingExamples")
    _check_features(examples.features)
    index = examples.features.frame.index
    if (not examples.labels.index.equals(index) or not examples.eligible.index.equals(index)
            or len(examples.label_evidence) != len(index)):
        raise ValueError("training labels and feature rows must be aligned")
    prices = _numeric(examples.labels["imbalance_price"])
    mask = examples.eligible["price"]
    if not is_bool_dtype(mask.dtype) or mask.isna().any() or not np.array_equal(mask.to_numpy(), np.isfinite(prices)):
        raise ValueError("price eligibility must match nonmissing labels")
    spots = _numeric(examples.labels["spot_price"]) if mode == "spot_relative" else None
    values, dependencies = [], []
    for position, row in enumerate(examples.features.frame.itertuples(index=False)):
        evidence = examples.label_evidence[position]
        if evidence.delivery_start_utc != row.delivery_start_utc:
            raise ValueError("training label evidence must match delivery rows")
        eligible = bool(mask.iloc[position])
        if eligible:
            _check_label(evidence.price, "fi_imbalance_price", row.delivery_start_utc, examples.config)
        elif evidence.price is not None:
            raise ValueError("missing price labels must not carry evidence")
        dependency = evidence.price if eligible else None
        value = prices[position]
        if spots is not None:
            if np.isfinite(spots[position]):
                _check_label(evidence.spot, "fi_spot_price", row.delivery_start_utc, examples.config)
            elif evidence.spot is not None:
                raise ValueError("missing spot labels must not carry evidence")
            eligible = eligible and np.isfinite(spots[position])
            if eligible:
                with np.errstate(over="ignore", invalid="ignore"):
                    value = prices[position] - spots[position]
                if not np.isfinite(value):
                    raise ValueError("relative target calculation produced a nonfinite value")
                dependency = derive_evidence("price_target_spot_relative", evidence.price, evidence.spot,
                                             used_at_utc=examples.config.fit_cutoff_utc)
            else:
                value, dependency = np.nan, None
        values.append(value)
        dependencies.append(dependency)
    result = pd.Series(values, index=index, name="price_target", dtype="float64")
    return PriceTargets(mode, result, result.notna().rename("eligible"), tuple(dependencies))


def reconstruct_prices(raw_quantiles: "pd.DataFrame", *, features: FeatureBatch,
                       mode: PriceTargetMode = "direct") -> ReconstructedPrices:
    """Reconstruct all price heads using origin-time features, never fitting labels.

    raw_quantiles must be finite p10/p50/p90 columns aligned with the FeatureBatch.
    Relative mode needs the registered fi_spot_price_delivery feature. If a head's
    feature subset omits it, construct a separate spot-only batch with build_features
    for the same origins. Every finite offset needs exact delivery/source availability
    evidence; missing offsets explicitly request direct-model backup. No model is
    fitted or invoked here, and no quantile repair/calibration is applied.
    """
    import numpy as np
    import pandas as pd

    _check_mode(mode)
    _check_features(features)
    if (not isinstance(raw_quantiles, pd.DataFrame) or tuple(raw_quantiles.columns) != _QUANTILES
            or not raw_quantiles.index.equals(features.frame.index)):
        raise ValueError("raw quantiles must match feature rows and p10/p50/p90 columns")
    prices = np.column_stack([_numeric(raw_quantiles[name]) for name in _QUANTILES])
    if not np.isfinite(prices).all():
        raise ValueError("raw quantiles must be finite before reconstruction")
    backup = np.zeros(len(prices), dtype=bool)
    dependencies = [None] * len(prices)
    if mode == "spot_relative":
        if _SPOT_FEATURE not in features.feature_names or _SPOT_FEATURE not in features.frame:
            raise ValueError("relative reconstruction requires the delivery spot feature")
        offsets = _numeric(features.frame[_SPOT_FEATURE])
        for position, record in enumerate(features.evidence):
            matches = [e for e in record.dependencies if e.name == _SPOT_FEATURE]
            if not np.isfinite(offsets[position]):
                if matches:
                    raise ValueError("missing spot offsets must not carry evidence")
                backup[position] = True
                continue
            if len(matches) != 1 or len(matches[0].sources) != 1:
                raise ValueError("relative reconstruction requires exact spot evidence")
            evidence, source = matches[0], matches[0].sources[0]
            if (source.series_id != "fi_spot_price" or source.timestamp_utc != record.delivery_start_utc
                    or not source.first_usable_origin_utc <= source.used_at_utc <= evidence.used_at_utc <= record.forecast_origin_utc):
                raise ValueError("reconstruction spot was unavailable at forecast origin")
            dependencies[position] = evidence
        with np.errstate(over="ignore", invalid="ignore"):
            prices = prices + offsets[:, None]
        if not np.isfinite(prices[~backup]).all():
            raise ValueError("price reconstruction produced a nonfinite value")
    return ReconstructedPrices(
        mode, pd.DataFrame(prices, index=raw_quantiles.index, columns=_QUANTILES),
        pd.Series(backup, index=raw_quantiles.index, name="requires_direct_backup"), tuple(dependencies),
    )
