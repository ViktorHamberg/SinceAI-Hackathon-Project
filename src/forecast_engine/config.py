"""Explicit, immutable fitting boundaries. Selection of eligible rows comes later."""

from dataclasses import dataclass
from datetime import datetime, timezone

HORIZON_STEPS = 40
STEP_MINUTES = 15
_TRAINING_START = datetime(2026, 5, 31, 21, tzinfo=timezone.utc)
_TRAINING_END = datetime(2026, 10, 4, 21, tzinfo=timezone.utc)


def _as_utc(value: datetime, name: str) -> datetime:
    """Normalize an aware datetime; never guess a timezone for a naive value."""
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    # pandas.NaT is datetime-like but cannot represent a boundary.
    if value != value:
        raise ValueError(f"{name} must not be missing")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class RunConfig:
    """Fit labels in [start, end), using evidence available at or before cutoff.

    These bounds describe a run; they do not by themselves prove leakage safety.
    Predictors must enforce both delivery membership and dependency availability.
    Horizon and quarter-hour resolution are fixed by the official contract.
    """

    label_start_utc: datetime
    label_end_utc: datetime
    fit_cutoff_utc: datetime

    def __post_init__(self) -> None:
        for name in ("label_start_utc", "label_end_utc", "fit_cutoff_utc"):
            object.__setattr__(self, name, _as_utc(getattr(self, name), name))
        if not (_TRAINING_START <= self.label_start_utc < self.label_end_utc
                <= self.fit_cutoff_utc <= _TRAINING_END):
            raise ValueError("fitting boundaries must be ordered within the permitted training period")
        if any(t.minute or t.second or t.microsecond for t in (
            self.label_start_utc, self.label_end_utc, self.fit_cutoff_utc
        )):
            raise ValueError("run boundaries must fall on full hours")

    @classmethod
    def validation(cls) -> "RunConfig":
        """Hold out 7 September–4 October, as Finnish local dates."""
        cutoff = datetime(2026, 9, 6, 21, tzinfo=timezone.utc)
        return cls(_TRAINING_START, cutoff, cutoff)

    @classmethod
    def test(cls) -> "RunConfig":
        """Fit through 4 October, using only evidence available at the first test origin."""
        return cls(_TRAINING_START, _TRAINING_END, _TRAINING_END)
