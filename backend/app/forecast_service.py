"""Explicit preparation and read-only retrieval; no HTTP or import-time execution."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import TYPE_CHECKING
from uuid import uuid4

import forecast_engine
from forecast_engine import RunConfig, forecast, load_inputs
from forecast_engine.models import PersistencePredictor

from .config import ForecastConfig
from .schemas import build_response

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
    _json: str = field(repr=False)
    preparation_seconds: float

    def response(self) -> dict:
        return json.loads(self._json)

    def response_json(self) -> str:
        return self._json


def prepare_forecast(
    config: ForecastConfig | None = None, *, predictor: "Predictor | None" = None,
    model_id: str | None = None,
) -> ForecastService:
    """Load, fit once and cache one genuine forecast for the first validation origin.

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
        origin = run_config.fit_cutoff_utc
        stage = "engine identity"
        revision = _engine_revision()
        stage = "loading inputs"
        data = load_inputs(config.inputs_path, spot_path=config.spot_path)
        stage = "fitting"
        fitted = predictor.fit(data, config=run_config)
        stage = "prediction"
        result = forecast(fitted, data, origins=[origin])
        stage = "response serialization"
        response = build_response(
            result, origin=origin, config=run_config, model_id=model_id,
            engine_revision=revision, run_id=str(uuid4()),
            generated_at_utc=datetime.now(timezone.utc).replace(microsecond=0),
        )
        payload = response.to_json()
        stage = "engine integrity"
        if _engine_revision() != revision:
            raise ValueError("Engine sources changed during preparation.")
        return ForecastService(fitted, result, payload, time.perf_counter() - started)
    except Exception:
        # Suppress chained parser/model exceptions, including private values in
        # ordinary tracebacks. Do not log exception text or partially built data.
        raise ForecastPreparationError(stage) from None
