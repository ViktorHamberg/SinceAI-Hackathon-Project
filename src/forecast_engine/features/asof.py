"""One feature path for supplied historical or inference origins; no fitting or I/O.

build_features returns private model inputs, including restricted spot values if
supplied. Do not serialize its frame into logs, application responses or public
artifacts. Evidence contains timestamps/identifiers only. NaN features have no source
evidence; deterministic calendar/horizon features need no input rows. A frozen batch
envelope does not make the returned, caller-owned DataFrame deeply immutable.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from ..availability import select_available
from ..config import HORIZON_STEPS, STEP_MINUTES
from ..contracts import ForecastInputs
from ..provenance import DependencyEvidence, evidence_from_rows
from .registry import DEFAULT_FEATURE_NAMES, FEATURE_REGISTRY, REGISTRY_VERSION

if TYPE_CHECKING:
    import pandas as pd


@dataclass(frozen=True)
class FeatureRowEvidence:
    forecast_origin_utc: datetime
    delivery_start_utc: datetime
    step: int
    dependencies: tuple[DependencyEvidence, ...]


@dataclass(frozen=True, repr=False)
class FeatureBatch:
    frame: "pd.DataFrame" = field(repr=False)
    evidence: tuple[FeatureRowEvidence, ...] = field(repr=False)
    feature_names: tuple[str, ...]
    registry_version: str = REGISTRY_VERSION


def build_features(
    data: ForecastInputs, *, origins: Sequence[datetime],
    feature_names: Sequence[str] = DEFAULT_FEATURE_NAMES,
) -> FeatureBatch:
    """Build 40 ordered rows per origin with per-feature, value-free lineage.

    Origins must be unique aware full hours (explicit offsets normalize to UTC).
    Feature order follows registry order, independently of caller ordering. Optional
    groups are enabled by selecting registered names; unknown/duplicate names fail.
    Latest uses the newest finite eligible past observation with no invented maximum
    age; the separate age feature makes staleness visible. Rolling windows use all
    finite eligible past rows, minimum one observation, population standard deviation.
    Missing windows remain NaN. No data-derived statistics are fitted here.
    """
    import numpy as np
    import pandas as pd
    from zoneinfo import ZoneInfo

    names = tuple(feature_names)
    if not names or len(set(names)) != len(names) or any(n not in FEATURE_REGISTRY for n in names):
        raise ValueError("feature selection requires unique registered names")
    selected_names = set(names)
    definitions = tuple(d for n, d in FEATURE_REGISTRY.items() if n in selected_names)
    names = tuple(d.name for d in definitions)
    requested = []
    for origin in origins:
        if not isinstance(origin, datetime) or pd.isna(origin) or origin.utcoffset() is None:
            raise ValueError("feature origins require aware full-hour datetimes")
        value = pd.Timestamp(origin).tz_convert("UTC")
        if value != value.floor("h"):
            raise ValueError("feature origins require aware full-hour datetimes")
        requested.append(value)
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("feature origins must be nonempty and unique")

    rows, evidence = [], []
    local_zone = ZoneInfo("Europe/Helsinki")
    for origin in sorted(requested):
        available = select_available(data.series, origin)
        if available["series_id"].eq("fi_spot_price").any() or available["source"].eq("nordpool").any():
            raise ValueError("spot inputs must be supplied separately")
        if data.spot is not None:
            spot = select_available(data.spot, origin)
            if not (spot["series_id"].eq("fi_spot_price") & spot["source"].eq("nordpool")).all():
                raise ValueError("spot input requires nordpool fi_spot_price rows")
            available = pd.concat([available, spot], ignore_index=True)
        groups = {series: group.dropna(subset=["value"])
                  for series, group in available.groupby("series_id", sort=False)}
        empty = available.iloc[:0]
        # Origin-only calculations and evidence are reused across the 40 deliveries.
        history = {}
        for definition in definitions:
            if definition.operation not in {"latest", "age", "mean", "std"}:
                continue
            source = groups.get(definition.source_series[0], empty)
            source = source.loc[source["timestamp_utc"] < origin]
            if definition.window_minutes is not None:
                source = source.loc[source["timestamp_utc"] >= origin - timedelta(minutes=definition.window_minutes)]
            else:
                source = source.tail(1)
            history[definition.name] = _source_value(definition, source, origin)

        for step in range(1, HORIZON_STEPS + 1):
            delivery = origin + timedelta(minutes=(step - 1) * STEP_MINUTES)
            local = delivery.to_pydatetime().astimezone(local_zone)
            row = {"forecast_origin_utc": origin, "delivery_start_utc": delivery, "step": step}
            dependencies = []
            for definition in definitions:
                operation = definition.operation
                dependency = None
                if operation == "step":
                    value = step
                elif operation == "lead":
                    value = (step - 1) * STEP_MINUTES
                elif operation.startswith("calendar_"):
                    value = {
                        "calendar_hour_local": local.hour,
                        "calendar_weekday_local": local.weekday(),
                        "calendar_quarter": local.minute // STEP_MINUTES,
                        "calendar_is_dst": int(bool(local.dst())),
                    }[operation]
                elif operation == "delivery":
                    source = groups.get(definition.source_series[0], empty)
                    source = source.loc[source["timestamp_utc"] == delivery]
                    value, dependency = _source_value(definition, source, origin)
                else:
                    value, dependency = history[definition.name]
                row[definition.name] = float(value)
                if dependency is not None:
                    dependencies.append(dependency)
            rows.append(row)
            evidence.append(FeatureRowEvidence(origin, delivery, step, tuple(dependencies)))
    frame = pd.DataFrame(rows, columns=["forecast_origin_utc", "delivery_start_utc", "step", *names])
    if np.isinf(frame[list(names)].to_numpy()).any():
        raise ValueError("feature calculation produced nonfinite values")
    return FeatureBatch(frame, tuple(evidence), names)


def _source_value(definition, source, origin):
    """Aggregate only selected rows; retain every finite row contributing to a value."""
    if source.empty:
        return float("nan"), None
    operation = definition.operation
    if operation == "mean":
        value = source["value"].mean()
    elif operation == "std":
        value = source["value"].std(ddof=0)
    elif operation == "age":
        value = (origin - source["timestamp_utc"].iloc[0]).total_seconds() / 60
    else:
        value = source["value"].iloc[0]
    return value, evidence_from_rows(source, name=definition.name, used_at_utc=origin)
