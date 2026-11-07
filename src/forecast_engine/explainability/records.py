"""Private numerical records. Never serialize these into responses or diagnostics.

All collections produced by the helpers are tuples of frozen records/scalars.
Numeric fields can disclose restricted market information; repr omits every field.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, repr=False)
class SignedContribution:
    name: str
    value: float


@dataclass(frozen=True, repr=False)
class Transformation:
    kind: str
    input_value: float
    output_value: float
    input_unit: str
    output_unit: str
    offset: float | None = None
    category: str | None = None
    context: tuple[SignedContribution, ...] = ()


@dataclass(frozen=True, repr=False)
class ContributionRecord:
    forecast_origin_utc: datetime
    delivery_start_utc: datetime
    step: int
    head: str
    class_name: str | None
    component_id: str
    model_id: str
    model_sha256: str
    native_version: str
    recipe: tuple[tuple[str, int | float | str | bool], ...]
    iterations: int
    registry_version: str
    target_mode: str
    scope: str
    unit: str
    output_unit: str
    base_value: float
    raw_output: float
    output_value: float
    features: tuple[SignedContribution, ...]
    categories: tuple[SignedContribution, ...]
    transformations: tuple[Transformation, ...]


@dataclass(frozen=True, repr=False)
class UnavailableContribution:
    forecast_origin_utc: datetime
    delivery_start_utc: datetime
    step: int
    component_id: str
    reason: str


@dataclass(frozen=True, repr=False)
class ExplanationBatch:
    records: tuple[ContributionRecord, ...]
    unavailable: tuple[UnavailableContribution, ...]


@dataclass(frozen=True, repr=False)
class ContributionComparison:
    earlier: ContributionRecord
    later: ContributionRecord
    base_delta: float
    raw_output_delta: float
    output_delta: float
    features: tuple[SignedContribution, ...]
    categories: tuple[SignedContribution, ...]
    reconstruction_offset_delta: float
