"""Explicit preparation and read-only retrieval; no HTTP or import-time execution."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import TYPE_CHECKING
from types import MappingProxyType
from uuid import uuid4

import forecast_engine
from forecast_engine import RunConfig, forecast, load_inputs
from forecast_engine.models import PersistencePredictor

from .config import ForecastConfig
from .schemas import OriginsResponse, build_response, utc_text

if TYPE_CHECKING:
    from forecast_engine import FittedPredictor, ForecastResult, Predictor


class ForecastPreparationError(RuntimeError):
    """A safe failure stage, without input values, filenames or parser diagnostics."""

    def __init__(self, stage: str) -> None:
        self.stage = stage
        super().__init__(f"Forecast preparation failed during {stage}; see backend troubleshooting.")


def _engine_revision() -> str:
    """Fingerprint installed Python sources, including local uncommitted changes.

    Relative names and file content, not absolute paths/mtime/Git state, define the
    digest. No Git executable, network or optional model imports are needed.
    """
    directory = Path(forecast_engine.__file__).resolve().parent
    sources = sorted(directory.rglob("*.py"))
    if not sources:
        raise ValueError("Engine source files are unavailable.")
    digest = hashlib.sha256()
    for source in sources:
        name = source.relative_to(directory).as_posix().encode("utf-8")
        content = source.read_bytes()
        digest.update(len(name).to_bytes(8, "big") + name)
        digest.update(len(content).to_bytes(8, "big") + content)
    return "sha256:" + digest.hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class ForecastService:
    """A successfully prepared snapshot. Construct via prepare_forecast().

    Fitted state/evidence are private, never part of the response. Cached JSON is
    immutable; response() returns detached containers safe for an HTTP consumer.
    No input DataFrame is retained beyond the engine's own fitted/result objects.
    """

    _fitted: "FittedPredictor" = field(repr=False)
    _result: "ForecastResult" = field(repr=False)
    _json_by_origin: Mapping[datetime, str] = field(repr=False)
    _origins_json: str = field(repr=False)
    default_origin_utc: datetime
    preparation_seconds: float

    def response(self, origin: datetime | None = None) -> dict:
        return json.loads(self.response_json(origin))

    def response_json(self, origin: datetime | None = None) -> str:
        return self._json_by_origin[self.default_origin_utc if origin is None else origin]

    def origins_response(self) -> dict:
        return json.loads(self._origins_json)

    @property
    def cached_json_bytes(self) -> int:
        return sum(len(value.encode("utf-8")) for value in self._json_by_origin.values()) + len(self._origins_json.encode("utf-8"))


def prepare_forecast(
    config: ForecastConfig | None = None, *, predictor: "Predictor | None" = None,
    model_id: str | None = None,
) -> ForecastService:
    """Load, fit once and batch-generate the configured validation-origin snapshots.

    Step 1B can call this during lifespan and reuse the returned service in routes.
    Alternative models use the same public engine contract and require an explicit
    application recipe label. No fallbacks, actuals, disk exports or official tools.
    """
    started = time.perf_counter()
    stage = "configuration"
    try:
        config = config if config is not None else ForecastConfig.from_data_dir()
        if predictor is None:
            predictor = PersistencePredictor()
            model_id = model_id or "persistence-v1"
        elif model_id is None:
            raise ValueError("An alternative predictor requires a model recipe identifier.")
        run_config = RunConfig.validation()
        stage = "engine identity"
        revision = _engine_revision()
        stage = "loading inputs"
        data = load_inputs(config.inputs_path, spot_path=config.spot_path)
        stage = "fitting"
        fitted = predictor.fit(data, config=run_config)
        stage = "prediction"
        result = forecast(fitted, data, origins=config.origins)
        stage = "response serialization"
        run_id = str(uuid4())
        generated = datetime.now(timezone.utc).replace(microsecond=0)
        payloads = {}
        for origin, record in zip(config.origins, result.provenance.inference, strict=True):
            single = replace(result,
                             forecasts=result.forecasts.loc[result.forecasts["forecast_origin_utc"].eq(origin)].copy(),
                             provenance=replace(result.provenance, inference=(record,)))
            response = build_response(
                single, origin=origin, config=run_config, model_id=model_id,
                engine_revision=revision, run_id=run_id, generated_at_utc=generated,
            )
            payloads[origin] = response.to_json()
        catalog = OriginsResponse(
            schema_version=response.schema_version, run_id=run_id, model_id=response.model_id,
            predictor_id=response.predictor_id, engine_revision=revision,
            generated_at_utc=utc_text(generated), fit_cutoff_utc=utc_text(run_config.fit_cutoff_utc),
            default_origin_utc=utc_text(config.origins[0]),
            origins=tuple(utc_text(origin) for origin in config.origins),
        )
        stage = "engine integrity"
        if _engine_revision() != revision:
            raise ValueError("Engine sources changed during preparation.")
        return ForecastService(fitted, result, MappingProxyType(payloads), catalog.to_json(),
                               config.origins[0], time.perf_counter() - started)
    except Exception:
        # Suppress chained parser/model exceptions, including private values in
        # ordinary tracebacks. Do not log exception text or partially built data.
        raise ForecastPreparationError(stage) from None
