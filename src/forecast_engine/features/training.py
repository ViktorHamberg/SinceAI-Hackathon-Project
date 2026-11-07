"""Historical examples and pre-validation folds; no fitting, scoring or I/O.

Feature inputs are selected at each historical origin by the unchanged as-of builder.
Labels are selected independently by delivery interval AND publication at fitting
time. Keep all feature rows, masking ineligible labels rather than dropping an entire
origin/horizon or intersecting task masks. Consumers MUST use the relevant eligible
column when fitting a head. Raw labels and features are private, potentially restricted
data: never log, publish, or pass this object to an application response serializer.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..availability import select_fitting_labels
from ..config import RunConfig
from ..contracts import ForecastInputs
from ..provenance import DependencyEvidence, derive_evidence, evidence_from_rows
from .asof import FeatureBatch, build_features
from .registry import DEFAULT_FEATURE_NAMES

if TYPE_CHECKING:
    import pandas as pd


@dataclass(frozen=True)
class TrainingLabelEvidence:
    delivery_start_utc: datetime
    price: DependencyEvidence | None
    direction: DependencyEvidence | None
    spot: DependencyEvidence | None
    spike: DependencyEvidence | None


@dataclass(frozen=True, repr=False)
class TrainingExamples:
    """Aligned caller-owned frames; frozen envelope, not deeply immutable tables.

    labels columns: imbalance_price (EUR/MWh), direction (-1/0/1), spot_price
    (EUR/MWh), spike_class (high/low/neither). eligible columns: price/direction/spike.
    The spot label is independently cutoff-eligible; it may be used with eligible
    price labels for later relative-target experiments, never as an origin-time
    feature. A usable fitting-time label can be unavailable at its historical origin.
    FeatureBatch already records that separate origin-time feature evidence.
    """

    features: FeatureBatch = field(repr=False)
    labels: "pd.DataFrame" = field(repr=False)
    eligible: "pd.DataFrame" = field(repr=False)
    label_evidence: tuple[TrainingLabelEvidence, ...] = field(repr=False)
    config: RunConfig


def build_training_examples(
    data: ForecastInputs, *, config: RunConfig, origins: Sequence[datetime],
    feature_names: Sequence[str] = DEFAULT_FEATURE_NAMES,
) -> TrainingExamples:
    """Build aligned features, task labels/masks and exact feature/label evidence.

    Origins are explicit, unique aware full hours within the label delivery interval.
    This avoids letting held-out target rows determine which examples are generated.
    Each of their 40 delivery labels is checked separately. No labels from outside
    config's interval, or published after its fitting cutoff, are retained in labels
    or label_evidence. Missing labels yield false masks and no evidence. This module
    never reads actuals_validation.csv or infers publication times.
    """
    import pandas as pd

    if not isinstance(config, RunConfig):
        raise TypeError("training examples require RunConfig")
    # Materialize/validate before building features; don't silently drop origins.
    requested = tuple(origins)
    for origin in requested:
        normalized = _full_hour(origin)
        if not config.label_start_utc <= normalized < config.label_end_utc:
            raise ValueError("training origin must be within the fitting label interval")
    features = build_features(data, origins=requested, feature_names=feature_names)
    rows = select_fitting_labels(data.series, config)
    rows = rows.loc[rows["series_id"].isin(["fi_imbalance_price", "fi_mfrr_direction"])]
    rows = rows.dropna(subset=["value"])
    direction = rows.loc[rows["series_id"].eq("fi_mfrr_direction")]
    if not direction["value"].isin([-1, 0, 1]).all():
        raise ValueError("direction labels require -1, 0, or 1")
    spot = None
    if data.spot is not None:
        spot = select_fitting_labels(data.spot, config).dropna(subset=["value"])
        if not (spot["series_id"].eq("fi_spot_price") & spot["source"].eq("nordpool")).all():
            raise ValueError("spot labels require nordpool fi_spot_price rows")

    # Reuse evidence for repeated deliveries, preserving feature evidence at each
    # distinct historical origin separately in features.evidence.
    indexed = {}
    for series in ("fi_imbalance_price", "fi_mfrr_direction"):
        selected = rows.loc[rows["series_id"].eq(series)]
        indexed[series] = selected.set_index("timestamp_utc", drop=False)
    if spot is not None:
        indexed["fi_spot_price"] = spot.set_index("timestamp_utc", drop=False)

    label_rows, evidence = [], []
    cache = {}
    for delivery in features.frame["delivery_start_utc"]:
        if delivery not in cache:
            values, dependencies = {}, {}
            for name, series in (("price", "fi_imbalance_price"),
                                 ("direction", "fi_mfrr_direction"), ("spot", "fi_spot_price")):
                table = indexed.get(series)
                if table is not None and delivery in table.index:
                    selected = table.loc[[delivery]].reset_index(drop=True)
                    values[name] = float(selected["value"].iloc[0])
                    dependencies[name] = evidence_from_rows(
                        selected, name=f"training_{name}", used_at_utc=config.fit_cutoff_utc,
                    )
                else:
                    values[name] = float("nan")
                    dependencies[name] = None
            spike = pd.NA
            spike_evidence = None
            if dependencies["price"] is not None and dependencies["spot"] is not None:
                price, reference = values["price"], values["spot"]
                spike = "high" if price > reference + 50 else "low" if price < reference - 50 else "neither"
                spike_evidence = derive_evidence(
                    "training_spike", dependencies["price"], dependencies["spot"],
                    used_at_utc=config.fit_cutoff_utc,
                )
            cache[delivery] = (
                (values["price"], values["direction"], values["spot"], spike),
                TrainingLabelEvidence(delivery, dependencies["price"], dependencies["direction"],
                                      dependencies["spot"], spike_evidence),
            )
        values, record = cache[delivery]
        label_rows.append(values)
        evidence.append(record)
    labels = pd.DataFrame(label_rows, columns=["imbalance_price", "direction", "spot_price", "spike_class"])
    labels["spike_class"] = labels["spike_class"].astype("string")
    eligible = pd.DataFrame({
        "price": labels["imbalance_price"].notna(),
        "direction": labels["direction"].notna(),
        "spike": labels["spike_class"].notna(),
    })
    return TrainingExamples(features, labels, eligible, tuple(evidence), config)


def _full_hour(value: datetime) -> datetime:
    """Validate explicit aware instants without guessing UTC for naive values."""
    import pandas as pd

    if not isinstance(value, datetime) or pd.isna(value) or value.utcoffset() is None:
        raise ValueError("chronological boundaries require aware full-hour datetimes")
    result = pd.Timestamp(value).tz_convert("UTC")
    if result != result.floor("h"):
        raise ValueError("chronological boundaries require aware full-hour datetimes")
    return result.to_pydatetime()


@dataclass(frozen=True)
class ChronologicalFold:
    """Expanding fit ending before an assessment window; no assessment labels loaded.

    A training origin near the boundary may have only some eligible horizon labels.
    build_training_examples masks its crossing labels individually; it does not
    pretend all 40 are eligible because the origin precedes assessment_start_utc.
    """

    config: RunConfig
    assessment_start_utc: datetime
    assessment_end_utc: datetime

    def __post_init__(self) -> None:
        start = _full_hour(self.assessment_start_utc)
        end = _full_hour(self.assessment_end_utc)
        validation = RunConfig.validation()
        if not (self.config.label_start_utc == validation.label_start_utc
                and self.config.label_end_utc == self.config.fit_cutoff_utc == start
                and start < end <= validation.fit_cutoff_utc):
            raise ValueError("fold must fit before its pre-validation assessment window")
        object.__setattr__(self, "assessment_start_utc", start)
        object.__setattr__(self, "assessment_end_utc", end)

    @property
    def training_origins(self) -> tuple[datetime, ...]:
        import pandas as pd

        return tuple(pd.date_range(self.config.label_start_utc, self.config.label_end_utc,
                                   freq="h", inclusive="left").to_pydatetime())

    @property
    def assessment_origins(self) -> tuple[datetime, ...]:
        import pandas as pd

        return tuple(pd.date_range(self.assessment_start_utc, self.assessment_end_utc,
                                   freq="h", inclusive="left").to_pydatetime())


def expanding_window_folds(
    *, assessment_windows: Sequence[tuple[datetime, datetime]] | None = None,
) -> tuple[ChronologicalFold, ...]:
    """Default Finnish local weeks 24–30 Aug and 31 Aug–6 Sep, converted to UTC.

    Custom windows must be ordered, nonoverlapping, full-hour aware intervals and
    end by the official validation start. All folds expand from the same training
    start. This defines boundaries only; no fitting, calibration or scoring occurs.
    """
    if assessment_windows is None:
        boundaries = tuple(datetime(2026, month, day, 21, tzinfo=timezone.utc)
                           for month, day in ((8, 23), (8, 30), (9, 6)))
        assessment_windows = tuple(zip(boundaries, boundaries[1:]))
    windows = tuple(assessment_windows)
    if not windows:
        raise ValueError("at least one assessment window is required")
    validation = RunConfig.validation()
    folds = []
    for start, end in windows:
        start, end = _full_hour(start), _full_hour(end)
        if folds and start < folds[-1].assessment_end_utc:
            raise ValueError("assessment windows must be ordered and nonoverlapping")
        config = RunConfig(validation.label_start_utc, start, start)
        folds.append(ChronologicalFold(config, start, end))
    return tuple(folds)
