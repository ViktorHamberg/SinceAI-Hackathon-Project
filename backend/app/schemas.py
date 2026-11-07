"""The application's allowlisted forecast response, independent of HTTP tooling."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import re
from typing import TYPE_CHECKING
from uuid import UUID

from forecast_engine import RunConfig, validate_forecasts

if TYPE_CHECKING:
    from forecast_engine import ForecastResult

SCHEMA_VERSION = "1.0"
# These names describe inputs, not measured feature-importance rankings.
APPROVED_DRIVER_NAMES = frozenset({"last_imbalance_price"})
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,63}")


def utc_text(value: datetime) -> str:
    """Whole-second UTC without guessing naive timestamps or rounding prices."""
    if not isinstance(value, datetime) or value != value or value.utcoffset() is None:
        raise ValueError("Response timestamps must be aware and nonmissing.")
    if value.microsecond or getattr(value, "nanosecond", 0):
        raise ValueError("Response timestamps require whole-second precision.")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True, repr=False)
class ForecastPoint:
    forecast_origin_utc: str
    delivery_start_utc: str
    step: int
    p10: float
    p50: float
    p90: float
    p_up: float
    p_down: float
    p_none: float
    p_spike_high: float
    p_spike_low: float
    data_cutoff_utc: str | None
    top_drivers: str | None


@dataclass(frozen=True, slots=True, repr=False)
class ForecastResponse:
    schema_version: str
    run_id: str
    model_id: str
    predictor_id: str
    engine_revision: str
    generated_at_utc: str
    forecast_origin_utc: str
    fit_cutoff_utc: str
    points: tuple[ForecastPoint, ...] = field(repr=False)

    def to_json(self) -> str:
        """Serialize only declared response fields; reject non-JSON numeric values."""
        return json.dumps(asdict(self), allow_nan=False, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True, slots=True, repr=False)
class OriginsResponse:
    schema_version: str
    run_id: str
    model_id: str
    predictor_id: str
    engine_revision: str
    generated_at_utc: str
    fit_cutoff_utc: str
    default_origin_utc: str
    origins: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), allow_nan=False, ensure_ascii=False, separators=(",", ":"))


def parse_origin(value: str) -> datetime:
    """Accept whole-second UTC ISO timestamps, then require a full-hour origin."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|\+00:00)", value):
        raise ValueError("Origin must be a full-hour UTC timestamp.")
    origin = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if origin.minute or origin.second:
        raise ValueError("Origin must be a full-hour UTC timestamp.")
    return origin


def build_response(
    result: "ForecastResult", *, origin: datetime, config: RunConfig,
    model_id: str, engine_revision: str, run_id: str, generated_at_utc: datetime,
) -> ForecastResponse:
    """Validate the engine result and copy only approved fields into the response.

    Errors are sanitized by the service boundary. Neither pandas objects, source
    prices nor arbitrary provenance/driver text are serialized.
    """
    import pandas as pd

    validate_forecasts(result.forecasts, origins=[origin])
    if result.provenance.fitting.config != config:
        raise ValueError("Forecast fitting configuration does not match the application run.")
    predictor_id = result.provenance.fitting.predictor_id
    if not _IDENTIFIER.fullmatch(model_id) or not _IDENTIFIER.fullmatch(predictor_id):
        raise ValueError("Model and predictor identifiers must be short application labels.")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", engine_revision):
        raise ValueError("Engine revision requires a source fingerprint.")
    if str(UUID(run_id)) != run_id:
        raise ValueError("Run identity must be a canonical UUID.")
    points = []
    for row in result.forecasts.itertuples(index=False):
        drivers = None
        if not pd.isna(row.top_drivers):
            names = row.top_drivers.split(";")
            if names and all(name in APPROVED_DRIVER_NAMES for name in names):
                drivers = ";".join(dict.fromkeys(names))
        points.append(ForecastPoint(
            forecast_origin_utc=utc_text(row.forecast_origin_utc),
            delivery_start_utc=utc_text(row.delivery_start_utc), step=int(row.step),
            p10=float(row.p10), p50=float(row.p50), p90=float(row.p90),
            p_up=float(row.p_up), p_down=float(row.p_down), p_none=float(row.p_none),
            p_spike_high=float(row.p_spike_high), p_spike_low=float(row.p_spike_low),
            data_cutoff_utc=None if pd.isna(row.data_cutoff_utc) else utc_text(row.data_cutoff_utc),
            top_drivers=drivers,
        ))
    return ForecastResponse(
        schema_version=SCHEMA_VERSION, run_id=run_id, model_id=model_id,
        predictor_id=predictor_id, engine_revision=engine_revision,
        generated_at_utc=utc_text(generated_at_utc), forecast_origin_utc=utc_text(origin),
        fit_cutoff_utc=utc_text(config.fit_cutoff_utc), points=tuple(points),
    )
