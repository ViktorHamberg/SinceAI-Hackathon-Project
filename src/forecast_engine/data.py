"""Explicit long-format input adapters, adapted from baseline.ipynb read_long().

Unlike the reference, reject ambiguous timestamps, duplicate keys and scoring-table
schemas. Never infer publication times, fill gaps, or print offending data values.
"""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .contracts import ForecastInputs

if TYPE_CHECKING:
    import pandas as pd

LONG_COLUMNS = (
    "series_id", "source", "dataset_id", "timestamp_utc", "value", "unit",
    "first_usable_origin_utc",
)


def _utc_column(values: "pd.Series", name: str) -> "pd.Series":
    import pandas as pd
    from pandas.api.types import infer_dtype

    try:
        # utc=True alone silently treats naive strings as UTC; require an offset.
        if infer_dtype(values, skipna=False) == "string":
            explicit_offset = (
                r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
                r"(?:Z|[+-]\d{2}:?\d{2})"
            )
            if not values.astype("string").str.fullmatch(explicit_offset).all():
                raise ValueError
        elif not isinstance(values.dtype, pd.DatetimeTZDtype):
            for value in values:
                if not isinstance(value, (str, datetime)) or pd.Timestamp(value).tzinfo is None:
                    raise ValueError
        parsed = pd.to_datetime(values, utc=True, format="mixed", errors="raise")
        if parsed.isna().any():
            raise ValueError
        return parsed.astype("datetime64[ns, UTC]")
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"{name} requires nonmissing timezone-aware timestamps") from None


def normalize_long(frame: "pd.DataFrame") -> "pd.DataFrame":
    """Copy/normalize the official seven-column schema; do not fill missing values.

    This also supports callers supplying in-memory long-format tables. Missing values
    are retained, while malformed/nonfinite values and ambiguous keys fail explicitly.
    """
    import numpy as np
    import pandas as pd
    from pandas.api.types import is_bool_dtype, is_complex_dtype

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("expected a long-format pandas DataFrame")
    if set(frame.columns) != set(LONG_COLUMNS) or len(frame.columns) != len(LONG_COLUMNS):
        raise ValueError("expected the official seven-column input schema, not scoring actuals")
    result = frame.loc[:, list(LONG_COLUMNS)].copy()
    for name in ("series_id", "source", "dataset_id", "unit"):
        result[name] = result[name].astype("string")
    # CSV decodes empty metadata as missing; Parquet can preserve empty strings.
    result["dataset_id"] = result["dataset_id"].mask(result["dataset_id"].str.strip().eq(""), pd.NA)
    for name in ("series_id", "source"):
        if result[name].isna().any() or result[name].str.strip().eq("").any():
            raise ValueError(f"{name} must be nonmissing and nonempty")
    for name in ("timestamp_utc", "first_usable_origin_utc"):
        result[name] = _utc_column(result[name], name)
        frequency = "15min" if name == "timestamp_utc" else "h"
        if not result[name].eq(result[name].dt.floor(frequency)).all():
            raise ValueError(f"{name} must align to {frequency}")
    if is_bool_dtype(result["value"].dtype) or is_complex_dtype(result["value"].dtype):
        raise ValueError("value must contain real numbers or missing values")
    try:
        result["value"] = pd.to_numeric(result["value"], errors="raise").astype("float64")
    except (ValueError, TypeError, OverflowError):
        raise ValueError("value must contain real numbers or missing values") from None
    if np.isinf(result["value"]).any():
        raise ValueError("value must not contain infinity")
    if result.duplicated(["series_id", "timestamp_utc"]).any():
        raise ValueError("duplicate series_id/timestamp_utc input keys")
    return result.sort_values(["timestamp_utc", "series_id"]).reset_index(drop=True)


def _read_long(path: str | Path) -> "pd.DataFrame":
    import pandas as pd

    path = Path(path)
    if path.stem.lower().startswith("actuals"):
        raise ValueError("scoring actuals cannot be loaded as prediction inputs")
    if path.suffix.lower() not in {".csv", ".parquet"}:
        raise ValueError("input files must be CSV or Parquet")
    try:
        if path.suffix.lower() == ".parquet":
            frame = pd.read_parquet(path)
        else:
            frame = pd.read_csv(path, dtype={"dataset_id": "string"})
    except ImportError:
        raise ImportError("Parquet loading requires pyarrow from the starter requirements") from None
    except (ValueError, TypeError, pd.errors.ParserError):
        raise ValueError("could not parse the supplied long-format input file") from None
    return normalize_long(frame)


def load_input_data(path: str | Path) -> "pd.DataFrame":
    """Load the supplied inputs.csv/inputs.parquet from an explicit path."""
    frame = _read_long(path)
    if frame["series_id"].eq("fi_spot_price").any() or frame["source"].eq("nordpool").any():
        raise ValueError("load spot prices separately with load_spot_prices")
    return frame


def load_spot_prices(path: str | Path) -> "pd.DataFrame":
    """Load restricted spot rows without publishing/logging their values.

    Missing files raise normally. Omit spot_path in load_inputs only when the caller
    explicitly chooses no spot data; absence is not silently converted to prices.
    """
    frame = _read_long(path)
    if not (frame["series_id"].eq("fi_spot_price") & frame["source"].eq("nordpool")).all():
        raise ValueError("spot input must contain only nordpool fi_spot_price rows")
    return frame


def load_inputs(inputs_path: str | Path, *, spot_path: str | Path | None = None) -> ForecastInputs:
    """Load only explicitly named source files; never discover/read scoring actuals."""
    return ForecastInputs(
        series=load_input_data(inputs_path),
        spot=None if spot_path is None else load_spot_prices(spot_path),
    )
