"""Shared data shapes and structural interfaces, independent of any predictor.

Only declarations live at import time. pandas is imported when a caller explicitly
creates/checks a forecast table. Schema checks are intentionally structural;
complete-horizon/value enforcement and CSV export belong to the prediction step.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .config import RunConfig

if TYPE_CHECKING:
    import pandas as pd

FORECAST_COLUMNS = (
    "forecast_origin_utc", "delivery_start_utc", "step", "p10", "p50", "p90",
    "p_up", "p_down", "p_none", "p_spike_high", "p_spike_low",
    "data_cutoff_utc", "top_drivers",
)
_TIMESTAMP_COLUMNS = ("forecast_origin_utc", "delivery_start_utc", "data_cutoff_utc")
_NUMERIC_COLUMNS = FORECAST_COLUMNS[3:11]


def empty_forecast_frame() -> "pd.DataFrame":
    """Create a typed schema container, not a completed forecast.

    Optional values use datetime64[ns, UTC] / pandas string from the outset;
    callers can populate them later without changing the public result schema.
    """
    import pandas as pd

    dtypes = {name: "float64" for name in _NUMERIC_COLUMNS}
    dtypes.update({name: "datetime64[ns, UTC]" for name in _TIMESTAMP_COLUMNS})
    dtypes.update(step="int64", top_drivers="string")
    return pd.DataFrame({name: pd.Series(dtype=dtypes[name]) for name in FORECAST_COLUMNS})


def check_forecast_schema(frame: "pd.DataFrame") -> None:
    """Check column order and types without coercion, repairs, or value validation.

    This is a foundation schema check, not the official validator or a guarantee
    of complete/valid forecasts. Prediction will add those checks in Step 4.
    """
    import pandas as pd
    from pandas.api.types import is_bool_dtype, is_complex_dtype, is_integer_dtype, is_numeric_dtype

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("forecasts must be a pandas DataFrame")
    if tuple(frame.columns) != FORECAST_COLUMNS:
        raise ValueError("forecasts must contain the 13 official columns in template order")
    for name in _TIMESTAMP_COLUMNS:
        dtype = frame[name].dtype
        if not isinstance(dtype, pd.DatetimeTZDtype) or str(dtype.tz) != "UTC":
            raise ValueError(f"{name} must have a timezone-aware UTC datetime dtype")
    if not is_integer_dtype(frame["step"].dtype):
        raise ValueError("step must have an integer dtype")
    for name in _NUMERIC_COLUMNS:
        dtype = frame[name].dtype
        if not is_numeric_dtype(dtype) or is_bool_dtype(dtype) or is_complex_dtype(dtype):
            raise ValueError(f"{name} must have a real numeric dtype")
    if not isinstance(frame["top_drivers"].dtype, pd.StringDtype):
        raise ValueError("top_drivers must have a nullable pandas string dtype")


@dataclass(frozen=True)
class ForecastInputs:
    """In-memory long-format inputs and optional spot rows; never scoring actuals.

    No loading, selection, or copying happens here. Implementations must treat the
    caller-owned tables as read-only and enforce the agreed as-of rules.
    """

    series: "pd.DataFrame"
    spot: "pd.DataFrame | None" = None


@dataclass(frozen=True)
class FitProvenance:
    """Model-independent fitting evidence; counts/metadata must contain no prices.

    Evidence construction and availability checks are introduced in Step 2.
    Count keys can describe model-specific components without changing the API.
    """

    config: RunConfig
    predictor_id: str
    counts: Mapping[str, int] = field(default_factory=dict)
    max_first_usable_origin_utc: datetime | None = None
    latest_label_delivery_utc: datetime | None = None


@dataclass(frozen=True)
class OriginProvenance:
    """Per-origin evidence, separate from optional submission fields.

    Named source timestamps can later identify observations and their ages without
    making this public contract depend on a persistence model or exposing prices.
    """

    forecast_origin_utc: datetime
    max_first_usable_origin_utc: datetime | None = None
    source_timestamps_utc: Mapping[str, datetime] = field(default_factory=dict)


@dataclass(frozen=True)
class ForecastProvenance:
    fitting: FitProvenance
    inference: tuple[OriginProvenance, ...] = ()


@dataclass(frozen=True)
class ForecastResult:
    """Forecast table plus separately accessible audit evidence.

    The table remains a mutable pandas object; consumers own their edits and must
    not treat the frozen envelope as a claim of deep immutability or validation.
    """

    forecasts: "pd.DataFrame"
    provenance: ForecastProvenance


@runtime_checkable
class FittedPredictor(Protocol):
    """A fitted model; prediction must not change fitted state or refit.

    origins contains one or more full-hour aware UTC datetimes. Every requested
    origin must receive all 40 steps or the call must fail clearly. Implementations
    select inputs available at each origin and return sorted official-schema rows.
    No implementation is provided by the Step 1 foundation.
    """

    @property
    def provenance(self) -> FitProvenance: ...

    def predict(
        self, data: ForecastInputs, *, origins: Sequence[datetime]
    ) -> ForecastResult: ...


@runtime_checkable
class Predictor(Protocol):
    """Fit a model independently of its algorithm; no notebook or file-path API.

    Return separate reusable fitted state. Both the initial baseline and a future
    gradient-boosted predictor implement this boundary without changing callers.
    """

    def fit(self, data: ForecastInputs, *, config: RunConfig) -> FittedPredictor: ...
