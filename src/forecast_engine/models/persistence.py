"""Fit the baseline from baseline.ipynb (calibrate and persistence_at, source cell 5).

Preserve persistence residuals, linear empirical quantiles and six-decimal historical
frequencies. Unlike the reference, enforce delivery-period bounds, require evidence
for every component, and retain complete value-free dependency lineage. Prediction
reuses fitted statistics and the reference's deliberate quantile construction.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from math import isfinite
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..availability import MissingEvidenceError, select_available, select_fitting_labels
from ..config import HORIZON_STEPS, STEP_MINUTES, RunConfig
from ..contracts import (
    FitProvenance, ForecastInputs, ForecastProvenance, ForecastResult, empty_forecast_frame,
)
from ..data import normalize_long
from ..provenance import derive_evidence, evidence_from_rows, fitting_provenance, origin_provenance

if TYPE_CHECKING:
    import pandas as pd

_IMBALANCE = "fi_imbalance_price"
_DIRECTION = "fi_mfrr_direction"
_SPOT = "fi_spot_price"
_SPIKE_MARGIN = 50.0


@dataclass(frozen=True)
class FittedPersistence:
    """Detached immutable statistics; q10/q90 are raw offsets, not price forecasts.

    Evidence contains timestamps/counts only. repr excludes fitted numeric statistics
    and the potentially large lineage; no raw input DataFrames or prices are retained.
    """

    q10: tuple[float, ...] = field(repr=False)
    q90: tuple[float, ...] = field(repr=False)
    p_up: float = field(repr=False)
    p_down: float = field(repr=False)
    p_none: float = field(repr=False)
    p_spike_high: float = field(repr=False)
    p_spike_low: float = field(repr=False)
    provenance: FitProvenance = field(repr=False)

    def __post_init__(self) -> None:
        for name in ("q10", "q90"):
            values = tuple(float(v) for v in getattr(self, name))
            if len(values) != HORIZON_STEPS or not all(isfinite(v) for v in values):
                raise ValueError(f"{name} needs 40 finite calibrated offsets")
            object.__setattr__(self, name, values)
        if any(a > b for a, b in zip(self.q10, self.q90)):
            raise ValueError("calibrated offsets must be ordered")
        probabilities = (self.p_up, self.p_down, self.p_none, self.p_spike_high, self.p_spike_low)
        if not all(isfinite(p) and 0 <= p <= 1 for p in probabilities):
            raise ValueError("calibration produced invalid probabilities")
        if abs(self.p_up + self.p_down + self.p_none - 1) > 1e-12:
            raise ValueError("direction calibration probabilities must sum to one")
        if self.p_spike_high + self.p_spike_low > 1 + 1e-12:
            raise ValueError("spike calibration probabilities must sum to at most one")
        # FitProvenance is frozen but its default counts mapping is mutable. Detach
        # and freeze that mapping for returned fitted state without changing its API.
        object.__setattr__(self, "provenance", replace(
            self.provenance, counts=MappingProxyType(dict(self.provenance.counts)),
            dependencies=tuple(self.provenance.dependencies),
        ))

    @property
    def error_counts(self) -> tuple[int, ...]:
        return tuple(self.provenance.counts[f"error_step_{step:02}"] for step in range(1, 41))

    def predict(self, data: ForecastInputs, *, origins: Sequence[datetime]) -> ForecastResult:
        """Return all requested horizons and observation evidence without refitting."""
        import numpy as np
        import pandas as pd
        from ..engine import _check_fitting_availability, _prepare_origins, _validate_result

        requested = _prepare_origins(origins)
        _check_fitting_availability(self.provenance, requested[0])
        inputs = normalize_long(data.series)
        imbalance = inputs.loc[inputs["series_id"] == _IMBALANCE]
        offsets = pd.to_timedelta(np.arange(HORIZON_STEPS) * STEP_MINUTES, unit="min")
        low, high = np.minimum(self.q10, 0.), np.maximum(self.q90, 0.)
        parts, records = [], []
        for origin in requested:
            observed = _historical_observation(imbalance, origin)
            if observed.empty:
                raise MissingEvidenceError(
                    f"persistence observation unavailable at origin {origin.isoformat()} (steps 1–40)"
                )
            p50 = round(float(observed["value"].iloc[0]), 4)
            frame = empty_forecast_frame().reindex(range(HORIZON_STEPS))
            frame["forecast_origin_utc"] = pd.Series([origin] * HORIZON_STEPS, dtype="datetime64[ns, UTC]")
            frame["delivery_start_utc"] = origin + offsets
            frame["step"] = np.arange(1, HORIZON_STEPS + 1, dtype="int64")
            with np.errstate(over="ignore", invalid="ignore"):
                frame["p10"] = np.round(p50 + low, 4)
                frame["p90"] = np.round(p50 + high, 4)
            frame["p50"] = p50
            for name in ("p_up", "p_down", "p_none", "p_spike_high", "p_spike_low"):
                frame[name] = getattr(self, name)
            parts.append(frame)
            observed_evidence = evidence_from_rows(
                observed, name="persistence_observation", used_at_utc=origin,
            )
            records.append(origin_provenance(origin, [observed_evidence]))
        result = ForecastResult(
            pd.concat(parts, ignore_index=True), ForecastProvenance(self.provenance, tuple(records)),
        )
        _validate_result(result, requested)
        return result


def _historical_observation(imbalance: "pd.DataFrame", origin: datetime) -> "pd.DataFrame":
    """Reference three-day search then all-earlier fallback, shared by fit/predict."""
    timestamps = imbalance["timestamp_utc"]
    lo = timestamps.searchsorted(origin - timedelta(days=3))
    hi = timestamps.searchsorted(origin, side="right")
    for candidate in (imbalance.iloc[lo:hi], imbalance.iloc[:hi]):
        usable = select_available(candidate, origin).dropna(subset=["value"])
        if not usable.empty:
            return usable.tail(1)
    return imbalance.iloc[:0]


def _error_calibration(imbalance: "pd.DataFrame", config: RunConfig):
    import numpy as np
    import pandas as pd

    targets = imbalance.set_index("timestamp_utc")["value"]
    offsets = pd.to_timedelta(np.arange(HORIZON_STEPS) * STEP_MINUTES, unit="min")
    errors = []
    target_dates = [set() for _ in range(HORIZON_STEPS)]
    historical = [[] for _ in range(HORIZON_STEPS)]
    # Later origins cannot target an earlier delivery (step 1 starts at the origin).
    # Excluded/missing labels cannot change the origin range or fitted evidence.
    first = imbalance["timestamp_utc"].min().ceil("h")
    last = imbalance["timestamp_utc"].max().floor("h")
    for origin in pd.date_range(first, last, freq="h"):
        deliveries = origin + offsets
        actual = targets.reindex(deliveries).to_numpy(dtype=float)
        if not np.isfinite(actual).any():
            continue
        observed = _historical_observation(imbalance, origin)
        if observed.empty:
            continue  # An unforecastable early origin is not an invented persistence value.
        value = float(observed["value"].iloc[0])
        error = actual - value
        if not np.isfinite(error[np.isfinite(actual)]).all():
            raise ValueError(f"nonfinite persistence errors at historical origin {origin.isoformat()}")
        errors.append(error)
        input_evidence = evidence_from_rows(
            observed, name=f"persistence_at_{origin.isoformat()}", used_at_utc=origin,
        )
        for index in np.flatnonzero(np.isfinite(actual)):
            target_dates[index].add(deliveries[index])
            historical[index].append(input_evidence)
    labels, derived, q10, q90 = [], [], [], []
    for index in range(HORIZON_STEPS):
        if not target_dates[index]:
            raise MissingEvidenceError(f"no finite eligible persistence errors for step {index + 1}")
        samples = np.array([row[index] for row in errors], dtype=float)
        samples = samples[np.isfinite(samples)]
        lower, upper = np.quantile(samples, [0.10, 0.90], method="linear")
        q10.append(float(lower))
        q90.append(float(upper))
        label_evidence = evidence_from_rows(
            imbalance.loc[imbalance["timestamp_utc"].isin(target_dates[index])],
            name=f"error_step_{index + 1:02}", used_at_utc=config.fit_cutoff_utc,
        )
        labels.append(label_evidence)
        derived.append(derive_evidence(
            f"quantile_offsets_step_{index + 1:02}", label_evidence, *historical[index],
            used_at_utc=config.fit_cutoff_utc,
        ))
    return tuple(q10), tuple(q90), labels, derived, len(errors)


class PersistencePredictor:
    """Fit the reference algorithm behind the existing model-independent interface."""

    def fit(self, data: ForecastInputs, *, config: RunConfig) -> FittedPersistence:
        import pandas as pd

        # Select before any aggregation/statistic; holdout/test outcomes are never fitted.
        labels = select_fitting_labels(data.series, config, required_series=[_IMBALANCE, _DIRECTION])
        imbalance = labels.loc[labels["series_id"] == _IMBALANCE].dropna(subset=["value"])
        direction = labels.loc[labels["series_id"] == _DIRECTION].dropna(subset=["value"])
        if not direction["value"].isin([-1, 0, 1]).all():
            raise ValueError("direction calibration requires only -1, 0, or 1 labels")
        if data.spot is None:
            raise MissingEvidenceError("spike calibration requires eligible imbalance/spot pairs")
        spot = normalize_long(data.spot)
        if not (spot["series_id"].eq(_SPOT) & spot["source"].eq("nordpool")).all():
            raise ValueError("spike calibration requires nordpool fi_spot_price rows")
        spot = select_fitting_labels(spot, config).dropna(subset=["value"])
        common = imbalance["timestamp_utc"].isin(spot["timestamp_utc"])
        spike_imbalance = imbalance.loc[common]
        spike_spot = spot.loc[spot["timestamp_utc"].isin(spike_imbalance["timestamp_utc"])]
        if spike_imbalance.empty:
            raise MissingEvidenceError("spike calibration has no finite eligible imbalance/spot pairs")
        # Use aligned delivery indices, never row order, for paired comparisons.
        paired = pd.concat([
            spike_imbalance.set_index("timestamp_utc")["value"].rename("imbalance"),
            spike_spot.set_index("timestamp_utc")["value"].rename("spot"),
        ], axis=1)
        p_high = round(float((paired["imbalance"] > paired["spot"] + _SPIKE_MARGIN).mean()), 6)
        p_low = round(float((paired["imbalance"] < paired["spot"] - _SPIKE_MARGIN).mean()), 6)
        p_up = round(float(direction["value"].eq(1).mean()), 6)
        p_down = round(float(direction["value"].eq(-1).mean()), 6)
        p_none = round(1.0 - p_up - p_down, 6)
        q10, q90, error_labels, historical, n_origins = _error_calibration(imbalance, config)
        component_labels = [
            *error_labels,
            evidence_from_rows(direction, name="direction_rows", used_at_utc=config.fit_cutoff_utc),
            evidence_from_rows(spike_imbalance, name="spike_imbalance_rows", used_at_utc=config.fit_cutoff_utc),
            evidence_from_rows(spike_spot, name="spike_spot_rows", used_at_utc=config.fit_cutoff_utc),
        ]
        spike_evidence = derive_evidence(
            "spike_frequencies", component_labels[-2], component_labels[-1],
            used_at_utc=config.fit_cutoff_utc,
        )
        provenance = fitting_provenance(
            config, predictor_id="persistence", labels=component_labels,
            historical_inputs=[*historical, spike_evidence],
        )
        provenance = replace(provenance, counts={
            **provenance.counts, "historical_origins": n_origins,
            "error_pairs": sum(provenance.counts[f"error_step_{step:02}"] for step in range(1, 41)),
            "spike_pairs": len(paired),
        })
        return FittedPersistence(q10, q90, p_up, p_down, p_none, p_high, p_low, provenance)
