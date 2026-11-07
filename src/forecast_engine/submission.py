"""Explicit optional CSV export with an in-memory round-trip check before writing."""

from collections.abc import Sequence
from datetime import datetime
from io import StringIO
import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING

from .engine import validate_forecasts

if TYPE_CHECKING:
    import pandas as pd


def _round_trip(payload: str) -> "pd.DataFrame":
    import pandas as pd

    try:
        frame = pd.read_csv(StringIO(payload), dtype="string", keep_default_na=False)
        for name in ("forecast_origin_utc", "delivery_start_utc", "data_cutoff_utc"):
            frame[name] = pd.to_datetime(
                frame[name].mask(frame[name].eq("")), format="%Y-%m-%dT%H:%M:%SZ", utc=True,
            )
        frame["step"] = pd.to_numeric(frame["step"], errors="raise")
        for name in ("p10", "p50", "p90", "p_up", "p_down", "p_none", "p_spike_high", "p_spike_low"):
            frame[name] = pd.to_numeric(frame[name], errors="raise").astype("float64")
        frame["top_drivers"] = frame["top_drivers"].mask(frame["top_drivers"].eq(""))
    except (ValueError, TypeError, KeyError):
        raise ValueError("CSV round-trip could not recover the forecast schema") from None
    return frame


def export_forecasts(
    frame: "pd.DataFrame", path: str | Path, *, origins: Sequence[datetime] | None = None
) -> Path:
    """Validate and atomically write UTF-8 official-schema CSV with no index.

    No forecast generation or provenance calculation occurs here. Preserve supplied
    optional values. Caller-provided origins detect a completely omitted origin; when
    omitted, check complete horizons for all origins present. Existing targets remain
    untouched if validation/serialization fails.
    """
    validate_forecasts(frame, origins=origins)
    serialized = frame.copy()
    for name in ("forecast_origin_utc", "delivery_start_utc", "data_cutoff_utc"):
        serialized[name] = serialized[name].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    buffer = StringIO()
    serialized.to_csv(buffer, index=False, float_format="%.6f", lineterminator="\n")
    payload = buffer.getvalue()
    recovered = _round_trip(payload)
    expected_origins = list(frame["forecast_origin_utc"].unique()) if origins is None else origins
    validate_forecasts(recovered, origins=expected_origins, probability_tolerance=0.001)
    # Prevent loss of optional metadata, including literal strings such as "NA".
    for name in ("data_cutoff_utc", "top_drivers"):
        actual, expected = recovered[name].reset_index(drop=True), frame[name].reset_index(drop=True)
        if name == "top_drivers":
            expected = expected.mask(expected.eq(""))
        same = actual.eq(expected).fillna(False) | (actual.isna() & expected.isna())
        if not same.all():
            raise ValueError(f"CSV round-trip changed {name}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload.encode("utf-8"))
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return path
