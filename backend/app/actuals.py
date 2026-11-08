"""Read-only retrospective validation outcomes, isolated from fitting/prediction."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re
from types import MappingProxyType
from typing import Literal
from uuid import uuid4

from forecast_engine import RunConfig
from .config import HistoryConfig
from .schemas import HistoryMetrics, HistoryPoint, HistoryResponse, utc_text

HISTORY_COLUMNS = ("delivery_start_utc", "imbalance_price", "direction")
_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|\+00:00)")


class HistoryUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Historical outcomes are unavailable. Check validation actuals setup.")


@dataclass(frozen=True, slots=True, repr=False)
class ActualOutcome:
    price: float | None
    direction: Literal["up", "down", "none"] | None


@dataclass(frozen=True, slots=True, repr=False)
class ActualsStore:
    _outcomes: Mapping[datetime, ActualOutcome] = field(repr=False)
    snapshot_id: str
    loaded_at_utc: datetime

    def history_for(self, forecast: dict) -> HistoryResponse:
        """Join outcomes to an already-prepared public forecast, preserving every row."""
        points, errors = [], []
        covered = direction_count = 0
        for point in forecast["points"]:
            delivery = datetime.fromisoformat(point["delivery_start_utc"].replace("Z", "+00:00"))
            actual = self._outcomes.get(delivery, ActualOutcome(None, None))
            points.append(HistoryPoint(point["delivery_start_utc"], point["step"], actual.price, actual.direction))
            if actual.price is not None:
                errors.append(abs(actual.price - point["p50"]))
                covered += int(point["p10"] <= actual.price <= point["p90"])
            direction_count += int(actual.direction is not None)
        count, total = len(errors), len(points)
        mae = math.fsum(errors) / count if count else None
        if mae is not None and not math.isfinite(mae):
            raise ValueError("History summary is unavailable.")
        metrics = HistoryMetrics(total, count, total - count, direction_count, total - direction_count,
                                 mae, covered / count if count else None, covered)
        return HistoryResponse(
            schema_version=forecast["schema_version"], run_id=forecast["run_id"], model_id=forecast["model_id"],
            predictor_id=forecast["predictor_id"], engine_revision=forecast["engine_revision"],
            generated_at_utc=forecast["generated_at_utc"], forecast_origin_utc=forecast["forecast_origin_utc"],
            fit_cutoff_utc=forecast["fit_cutoff_utc"], comparison_mode="retrospective",
            actuals_snapshot_id=self.snapshot_id, actuals_loaded_at_utc=utc_text(self.loaded_at_utc),
            metrics=metrics, points=tuple(points),
        )


def load_actuals(config: HistoryConfig) -> ActualsStore:
    """Materialize only three approved columns; reject bad source data atomically."""
    try:
        import pandas as pd

        raw = pd.read_csv(config.actuals_path, usecols=list(HISTORY_COLUMNS), dtype=str,
                          keep_default_na=False, encoding="utf-8-sig")
        start, end = RunConfig.validation().fit_cutoff_utc, RunConfig.test().fit_cutoff_utc
        outcomes = {}
        for row in raw.loc[:, list(HISTORY_COLUMNS)].itertuples(index=False, name=None):
            text, price_text, direction = (value.strip() for value in row)
            if not _UTC_TIMESTAMP.fullmatch(text):
                raise ValueError("Invalid outcome timestamp.")
            delivery = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if (delivery.minute % 15 or delivery.second or not start <= delivery < end
                    or delivery in outcomes):
                raise ValueError("Invalid or duplicate validation delivery.")
            price = float(price_text) if price_text else None
            if price is not None and not math.isfinite(price):
                raise ValueError("Invalid observed price.")
            direction = direction.lower() if direction else None
            if direction not in (None, "up", "down", "none"):
                raise ValueError("Invalid observed direction.")
            outcomes[delivery] = ActualOutcome(price, direction)
        return ActualsStore(MappingProxyType(outcomes), str(uuid4()),
                            datetime.now(timezone.utc).replace(microsecond=0))
    except Exception:
        raise HistoryUnavailableError() from None
