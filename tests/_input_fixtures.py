"""Small invented long rows; never derived from restricted challenge values."""

import pandas as pd

from forecast_engine.data import LONG_COLUMNS


def long_rows(*records):
    """Records are (series_id, delivery, first_usable_origin, value)."""
    frame = pd.DataFrame([
        {
            "series_id": series, "source": "nordpool" if series == "fi_spot_price" else "fingrid",
            "dataset_id": "319" if series == "fi_imbalance_price" else "",
            "timestamp_utc": delivery, "first_usable_origin_utc": usable,
            "value": value, "unit": "EUR/MWh" if "price" in series else "MW",
        }
        for series, delivery, usable, value in records
    ], columns=LONG_COLUMNS)
    frame["value"] = frame["value"].astype("float64")
    return frame
