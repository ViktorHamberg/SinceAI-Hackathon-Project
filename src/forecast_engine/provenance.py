"""Value-free dependency evidence for historical inputs and fitting labels.

Evidence records identify rows, their publication times, and when they were used.
Derived evidence flattens ALL transitive source uses, rather than trusting an assigned
feature timestamp. These utilities verify declared lineage, not arbitrary user code.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from .availability import MissingEvidenceError, _origin
from .config import RunConfig, _as_utc
from .contracts import FitProvenance, OriginProvenance
from .data import normalize_long

if TYPE_CHECKING:
    import pandas as pd


@dataclass(frozen=True)
class SourceDependency:
    series_id: str
    timestamp_utc: datetime
    first_usable_origin_utc: datetime
    used_at_utc: datetime

    def __post_init__(self) -> None:
        if not self.series_id:
            raise ValueError("source dependency requires a series_id")
        for name in ("timestamp_utc", "first_usable_origin_utc", "used_at_utc"):
            object.__setattr__(self, name, _as_utc(getattr(self, name), name))
        if self.first_usable_origin_utc > self.used_at_utc:
            raise ValueError("source dependency was unavailable when used")


@dataclass(frozen=True)
class DependencyEvidence:
    name: str
    used_at_utc: datetime
    sources: tuple[SourceDependency, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "used_at_utc", _origin(self.used_at_utc))
        object.__setattr__(self, "sources", tuple(self.sources))
        for source in self.sources:
            if source.used_at_utc > self.used_at_utc:
                raise ValueError("dependency was used after the evidence's declared use time")

    @property
    def max_first_usable_origin_utc(self) -> datetime | None:
        return max((s.first_usable_origin_utc for s in self.sources), default=None)


def evidence_from_rows(
    rows: "pd.DataFrame", *, name: str, used_at_utc: datetime
) -> DependencyEvidence:
    """Record only rows actually used by a component, without retaining prices.

    Empty/all-missing evidence fails; optional unavailable inputs should remain absent,
    rather than being presented as successful evidence for a derived feature.
    """
    origin = _origin(used_at_utc)
    frame = normalize_long(rows)
    if frame.empty or frame["value"].isna().any():
        raise MissingEvidenceError(f"{name} requires nonmissing source evidence")
    sources = tuple(
        SourceDependency(row.series_id, row.timestamp_utc, row.first_usable_origin_utc, origin)
        for row in frame.itertuples(index=False)
    )
    return DependencyEvidence(name, origin, sources)


def derive_evidence(
    name: str, *dependencies: DependencyEvidence, used_at_utc: datetime
) -> DependencyEvidence:
    """Compose lineage for a derived input/statistic; no feature value is computed."""
    origin = _origin(used_at_utc)
    if not dependencies or any(not d.sources for d in dependencies):
        raise MissingEvidenceError(f"{name} requires evidence for every dependency")
    if any(d.used_at_utc > origin for d in dependencies):
        raise ValueError("derived evidence cannot use a dependency from a later origin")
    # Preserve repeated row uses at different historical origins, deduplicating only
    # identical source-use records. Nested derived components retain transitive lineage.
    sources = tuple(dict.fromkeys(s for d in dependencies for s in d.sources))
    return DependencyEvidence(name, origin, sources)


def origin_provenance(
    origin_utc: datetime, dependencies: Sequence[DependencyEvidence]
) -> OriginProvenance:
    """Verify each declared dependency and retain exact lineage in the public record."""
    origin = _origin(origin_utc)
    evidence = tuple(dependencies)
    if not evidence or any(not e.sources for e in evidence):
        raise MissingEvidenceError("origin provenance requires nonempty dependency evidence")
    if any(e.used_at_utc > origin for e in evidence):
        raise ValueError("origin provenance includes evidence from a later origin")
    sources = tuple(s for e in evidence for s in e.sources)
    timestamps = {}
    for source in sources:
        timestamps[source.series_id] = max(
            timestamps.get(source.series_id, source.timestamp_utc), source.timestamp_utc
        )
    return OriginProvenance(
        forecast_origin_utc=origin,
        max_first_usable_origin_utc=max(s.first_usable_origin_utc for s in sources),
        source_timestamps_utc=timestamps,
        dependencies=evidence,
        source_ages={name: origin - timestamp for name, timestamp in timestamps.items()},
    )


def fitting_provenance(
    config: RunConfig, *, predictor_id: str, labels: Sequence[DependencyEvidence],
    historical_inputs: Sequence[DependencyEvidence] = (),
) -> FitProvenance:
    """Verify fitting evidence only; no fitting or calibration is performed.

    Each label dependency must obey both bounds. Historical input evidence must be
    created at its actual historical origin before composition here. Its recorded
    source-use times are retained, so publication <= fitting cutoff alone cannot hide
    an input that was unavailable at that historical origin.
    """
    labels = tuple(labels)
    inputs = tuple(historical_inputs)
    all_evidence = labels + inputs
    if not labels or any(not e.sources for e in all_evidence):
        raise MissingEvidenceError("fitting provenance requires nonempty label/input evidence")
    if len({e.name for e in labels}) != len(labels):
        raise ValueError("label component names must be unique for evidence counts")
    if any(e.used_at_utc > config.fit_cutoff_utc for e in all_evidence):
        raise ValueError("fitting evidence was used after the fitting cutoff")
    label_sources = tuple(s for e in labels for s in e.sources)
    if any(not (config.label_start_utc <= s.timestamp_utc < config.label_end_utc)
           for s in label_sources):
        raise ValueError("fitting label dependency is outside the permitted delivery interval")
    return FitProvenance(
        config=config,
        predictor_id=predictor_id,
        counts={e.name: len(e.sources) for e in labels},
        max_first_usable_origin_utc=max(
            s.first_usable_origin_utc for e in all_evidence for s in e.sources
        ),
        latest_label_delivery_utc=max(s.timestamp_utc for s in label_sources),
        dependencies=all_evidence,
    )
