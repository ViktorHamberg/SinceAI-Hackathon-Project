"""Model-independent forecasting contracts; no data loading or model execution on import."""

from .config import HORIZON_STEPS, STEP_MINUTES, RunConfig
from .engine import forecast, validate_forecasts
from .submission import export_forecasts
from .data import load_input_data, load_inputs, load_spot_prices, normalize_long
from .availability import (
    MissingEvidenceError, rows_available_at, select_available, select_fitting_labels,
)
from .provenance import (
    DependencyEvidence, SourceDependency, derive_evidence, evidence_from_rows,
    fitting_provenance, origin_provenance,
)
from .contracts import (
    FORECAST_COLUMNS,
    FitProvenance,
    FittedPredictor,
    ForecastInputs,
    ForecastProvenance,
    ForecastResult,
    OriginProvenance,
    Predictor,
    check_forecast_schema,
    empty_forecast_frame,
)

__all__ = [
    "FORECAST_COLUMNS", "HORIZON_STEPS", "STEP_MINUTES", "RunConfig",
    "FitProvenance", "FittedPredictor", "ForecastInputs", "ForecastProvenance",
    "ForecastResult", "OriginProvenance", "Predictor", "check_forecast_schema",
    "empty_forecast_frame",
    "load_input_data", "load_inputs", "load_spot_prices", "normalize_long",
    "MissingEvidenceError", "rows_available_at", "select_available", "select_fitting_labels",
    "DependencyEvidence", "SourceDependency", "derive_evidence", "evidence_from_rows",
    "fitting_provenance", "origin_provenance",
    "forecast", "validate_forecasts", "export_forecasts",
]
