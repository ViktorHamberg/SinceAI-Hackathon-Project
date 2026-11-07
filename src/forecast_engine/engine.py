"""Model-independent in-memory prediction dispatch and forecast contract checks.

No filesystem work or official tool invocation belongs here. These checks enforce
our returned-table contract; they do not replace official submission validation.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from .availability import MissingEvidenceError, _origin
from .config import HORIZON_STEPS, STEP_MINUTES
from .contracts import (
    FitProvenance, FittedPredictor, ForecastInputs, ForecastResult, check_forecast_schema,
)

if TYPE_CHECKING:
    import pandas as pd


def _prepare_origins(origins: Sequence[datetime]) -> tuple[datetime, ...]:
    """Require a nonempty unique request; normalize explicit offsets and sort in UTC."""
    normalized = []
    for index, value in enumerate(origins):
        try:
            normalized.append(_origin(value))
        except (ValueError, TypeError):
            raise ValueError(f"invalid forecast origin at position {index}: expected an aware full-hour datetime") from None
    result = tuple(normalized)
    if not result:
        raise ValueError("forecast request requires at least one origin")
    if len(set(result)) != len(result):
        raise ValueError("duplicate requested forecast origin")
    return tuple(sorted(result))


def _fail_row(frame: "pd.DataFrame", mask, component: str) -> None:
    if mask.any():
        row = frame.loc[mask].iloc[0]
        raise ValueError(
            f"{component} at origin {row['forecast_origin_utc']} step {row['step']}"
        )


def validate_forecasts(
    frame: "pd.DataFrame", *, origins: Sequence[datetime] | None = None,
    probability_tolerance: float = 1e-12,
) -> None:
    """Check complete, sorted official-schema rows without repairing them.

    Pass requested origins to detect a completely omitted origin. Without them,
    require full horizons for every origin present. In-memory probabilities sum to
    one to numerical precision; CSV round-trip checks may use official tolerance .001.
    """
    import numpy as np
    import pandas as pd

    if not 0 <= probability_tolerance <= 0.001:
        raise ValueError("probability tolerance must be between 0 and the official 0.001")
    check_forecast_schema(frame)
    if frame.empty:
        raise ValueError("forecast table must contain at least one complete origin")
    _fail_row(frame, frame["forecast_origin_utc"].isna(), "missing forecast origin")
    _fail_row(frame, frame["delivery_start_utc"].isna(), "missing delivery timestamp")
    _fail_row(frame, frame["step"].isna(), "missing step")
    _fail_row(frame, ~frame["forecast_origin_utc"].eq(frame["forecast_origin_utc"].dt.floor("h")),
              "forecast origin must be a full hour")
    _fail_row(frame, ~frame["step"].between(1, HORIZON_STEPS), "step outside 1–40")
    _fail_row(frame, frame.duplicated(["forecast_origin_utc", "step"], keep=False),
              "duplicate forecast key")
    expected_origins = _prepare_origins(
        origins if origins is not None else list(frame["forecast_origin_utc"].unique())
    )
    expected = pd.MultiIndex.from_product(
        [pd.DatetimeIndex(expected_origins).as_unit("ns"), range(1, HORIZON_STEPS + 1)],
        names=["forecast_origin_utc", "step"],
    )
    actual = pd.MultiIndex.from_arrays([
        pd.DatetimeIndex(frame["forecast_origin_utc"]).as_unit("ns"),
        frame["step"].to_numpy(dtype="int64"),
    ], names=["forecast_origin_utc", "step"])
    missing, extra = expected.difference(actual), actual.difference(expected)
    if len(missing):
        raise ValueError(f"missing forecast at origin {missing[0][0]} step {missing[0][1]}")
    if len(extra):
        raise ValueError(f"unexpected forecast at origin {extra[0][0]} step {extra[0][1]}")
    if not actual.equals(expected):
        raise ValueError("forecasts must be sorted by origin and step")
    expected_delivery = frame["forecast_origin_utc"] + pd.to_timedelta(
        (frame["step"] - 1) * STEP_MINUTES, unit="min"
    )
    _fail_row(frame, ~frame["delivery_start_utc"].eq(expected_delivery), "incorrect delivery timestamp")
    for name in ("p10", "p50", "p90", "p_up", "p_down", "p_none", "p_spike_high", "p_spike_low"):
        finite = np.isfinite(frame[name].to_numpy(dtype=float, na_value=np.nan))
        _fail_row(frame, ~finite, f"nonfinite {name}")
    _fail_row(frame, (frame["p10"] > frame["p50"]) | (frame["p50"] > frame["p90"]),
              "unordered price quantiles")
    for name in ("p_up", "p_down", "p_none", "p_spike_high", "p_spike_low"):
        _fail_row(frame, ~frame[name].between(0, 1), f"{name} probability outside [0,1]")
    direction = frame["p_up"] + frame["p_down"] + frame["p_none"]
    _fail_row(frame, (direction - 1).abs() > probability_tolerance + 1e-15,
              "direction probabilities must sum to one")
    spikes = frame["p_spike_high"] + frame["p_spike_low"]
    _fail_row(frame, spikes > 1 + probability_tolerance + 1e-15,
              "spike probabilities must sum to at most one")
    cutoff = frame["data_cutoff_utc"]
    _fail_row(frame, cutoff.notna() & (cutoff > frame["forecast_origin_utc"]),
              "data_cutoff_utc exceeds forecast origin")
    _fail_row(frame, cutoff.notna() & ~cutoff.eq(cutoff.dt.floor("s")),
              "data_cutoff_utc must have whole-second precision")


def _check_fitting_availability(fitting: FitProvenance, origin: datetime) -> None:
    context = f"at origin {origin.isoformat()} (all steps)"
    if fitting.config.fit_cutoff_utc > origin:
        raise ValueError(f"fitted statistics unavailable at origin {origin.isoformat()} (all steps)")
    if not fitting.dependencies or any(not e.sources for e in fitting.dependencies):
        raise MissingEvidenceError(f"fitted statistics require complete dependency evidence {context}")
    for evidence in fitting.dependencies:
        if evidence.used_at_utc > fitting.config.fit_cutoff_utc:
            raise ValueError(f"fitted dependency used after the fitting cutoff {context}")
        for source in evidence.sources:
            if not (source.first_usable_origin_utc <= source.used_at_utc <= evidence.used_at_utc):
                raise ValueError(f"fitted dependency was unavailable when used {context}")


def _validate_result(result: ForecastResult, origins: Sequence[datetime]) -> None:
    if not isinstance(result, ForecastResult):
        raise TypeError("prediction must return ForecastResult")
    validate_forecasts(result.forecasts, origins=origins)
    _check_fitting_availability(result.provenance.fitting, min(origins))
    records = result.provenance.inference
    if tuple(record.forecast_origin_utc for record in records) != tuple(origins):
        raise ValueError("inference provenance must cover every requested origin in order")
    for record in records:
        if not record.dependencies or any(not e.sources for e in record.dependencies):
            raise MissingEvidenceError(f"inference evidence missing at origin {record.forecast_origin_utc}")
        for evidence in record.dependencies:
            if evidence.used_at_utc > record.forecast_origin_utc:
                raise ValueError(f"inference dependency unavailable at origin {record.forecast_origin_utc}")
            for source in evidence.sources:
                if not (source.first_usable_origin_utc <= source.used_at_utc <= evidence.used_at_utc):
                    raise ValueError(f"inference dependency unavailable at origin {record.forecast_origin_utc}")


def forecast(
    fitted: FittedPredictor, data: ForecastInputs, *, origins: Sequence[datetime]
) -> ForecastResult:
    """Call any fitted predictor through the shared application contract; never fit."""
    requested = _prepare_origins(origins)
    _check_fitting_availability(fitted.provenance, requested[0])
    result = fitted.predict(data, origins=requested)
    _validate_result(result, requested)
    if result.provenance.fitting != fitted.provenance:
        raise ValueError("prediction returned different fitting provenance")
    return result
