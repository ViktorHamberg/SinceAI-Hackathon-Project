"""Historical selection, adapted from baseline.ipynb rows_available_at().

Keep long rows and publication metadata until explicitly pivoting. No model-specific
feature calculation, interpolation or future-dependent backfill is performed here.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from .config import RunConfig, _as_utc
from .data import normalize_long

if TYPE_CHECKING:
    import pandas as pd


class MissingEvidenceError(ValueError):
    """An explicitly required series/component has no finite eligible evidence."""


def _origin(value: datetime) -> datetime:
    value = _as_utc(value, "origin_utc")
    if value.minute or value.second or value.microsecond or getattr(value, "nanosecond", 0):
        raise ValueError("origin_utc must be a full hour")
    return value


def _require(rows: "pd.DataFrame", required_series: Sequence[str], context: str) -> None:
    usable = set(rows.loc[rows["value"].notna(), "series_id"])
    for name in required_series:
        if name not in usable:
            raise MissingEvidenceError(f"no finite eligible evidence for {name} at {context}")


def select_available(
    rows: "pd.DataFrame", origin_utc: datetime, *, required_series: Sequence[str] = ()
) -> "pd.DataFrame":
    """Return copied long rows with publication <= origin (inclusive).

    Delivery is NOT restricted to the past: forecasts and spot prices already published
    for future delivery are eligible. Only request evidence a caller actually requires;
    absent optional series are left absent and NaN values remain missing.
    """
    origin = _origin(origin_utc)
    frame = normalize_long(rows)
    selected = frame.loc[frame["first_usable_origin_utc"] <= origin].reset_index(drop=True)
    _require(selected, required_series, origin.isoformat())
    return selected


def select_fitting_labels(
    rows: "pd.DataFrame", config: RunConfig, *, required_series: Sequence[str] = ()
) -> "pd.DataFrame":
    """Keep label deliveries in [start, end) AND published <= fit cutoff.

    This selects evidence only; it does not fit statistics. Historical feature inputs
    must separately be selected at each historical forecast origin, not at this cutoff.
    """
    frame = normalize_long(rows)
    selected = frame.loc[
        (frame["timestamp_utc"] >= config.label_start_utc)
        & (frame["timestamp_utc"] < config.label_end_utc)
        & (frame["first_usable_origin_utc"] <= config.fit_cutoff_utc)
    ].reset_index(drop=True)
    _require(selected, required_series, config.fit_cutoff_utc.isoformat())
    return selected


def rows_available_at(rows: "pd.DataFrame", origin_utc: datetime) -> "pd.DataFrame":
    """Reference-compatible wide view, after availability selection; never fill gaps.

    Use select_available's long rows when constructing dependency evidence; a wide
    table alone does not retain publication provenance.
    """
    selected = select_available(rows, origin_utc)
    return selected.pivot(index="timestamp_utc", columns="series_id", values="value").sort_index()
