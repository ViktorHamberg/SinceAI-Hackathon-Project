"""Explicit local input paths; historical fitting boundaries belong to the engine."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from forecast_engine import RunConfig

DEFAULT_ORIGIN = datetime(2026, 9, 6, 21, tzinfo=timezone.utc)
DEFAULT_ORIGINS = tuple(DEFAULT_ORIGIN + timedelta(hours=hours) for hours in (0, 1, 6, 24, 168, 648))
MAX_CACHED_ORIGINS = 6


@dataclass(frozen=True, slots=True)
class ForecastConfig:
    """Paths resolve at configuration time, never during module import.

    Explicit relative paths resolve from the caller's directory. Default data paths
    derive from this checkout, so changing the working directory cannot select data.
    Paths are private and deliberately omitted from repr and forecast responses.
    """

    inputs_path: Path = field(repr=False)
    spot_path: Path = field(repr=False)
    origins: tuple[datetime, ...] = DEFAULT_ORIGINS
    model_cache_path: Path | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for name in ("inputs_path", "spot_path"):
            path = Path(getattr(self, name)).expanduser().resolve()
            if path.stem.lower().startswith("actuals"):
                raise ValueError("Scoring actuals cannot be configured as forecast inputs.")
            object.__setattr__(self, name, path)
        if self.inputs_path == self.spot_path:
            raise ValueError("Input series and spot data require separate files.")
        if self.model_cache_path is not None:
            cache = Path(self.model_cache_path).expanduser().resolve()
            if (cache in (self.inputs_path, self.spot_path) or cache.suffix.lower() != ".json"
                    or cache.stem.lower().startswith("actuals")):
                raise ValueError("Model cache requires a separate JSON file, never source data.")
            object.__setattr__(self, "model_cache_path", cache)
        if not isinstance(self.origins, tuple) or not 1 <= len(self.origins) <= MAX_CACHED_ORIGINS:
            raise ValueError("Configure between one and six forecast origins.")
        normalized = []
        for origin in self.origins:
            if not isinstance(origin, datetime) or origin != origin or origin.utcoffset() is None:
                raise ValueError("Forecast origins require aware datetimes.")
            origin = origin.astimezone(timezone.utc)
            if (origin.minute or origin.second or origin.microsecond or getattr(origin, "nanosecond", 0)
                    or not RunConfig.validation().fit_cutoff_utc <= origin < RunConfig.test().fit_cutoff_utc):
                raise ValueError("Forecast origins must be full hours within the validation period.")
            normalized.append(origin)
        if len(set(normalized)) != len(normalized):
            raise ValueError("Forecast origins must be unique.")
        object.__setattr__(self, "origins", tuple(sorted(normalized)))

    @classmethod
    def from_data_dir(cls, data_dir: str | Path | None = None) -> "ForecastConfig":
        directory = (Path(data_dir) if data_dir is not None
                     else Path(__file__).resolve().parents[2] / "data")
        cache = Path(__file__).resolve().parents[2] / "baseline_output" / "application" / "models" / "relative-control-v1.json"
        return cls(directory / "inputs.csv", directory / "spot_nordpool.csv", model_cache_path=cache)


@dataclass(frozen=True, slots=True)
class HistoryConfig:
    """Validation outcomes are a separate source, never a forecast input."""

    actuals_path: Path = field(repr=False)

    def __post_init__(self) -> None:
        path = Path(self.actuals_path).expanduser().resolve()
        if path.name.lower() != "actuals_validation.csv":
            raise ValueError("History requires the validation actuals file.")
        object.__setattr__(self, "actuals_path", path)

    @classmethod
    def from_data_dir(cls, data_dir: str | Path | None = None) -> "HistoryConfig":
        directory = (Path(data_dir) if data_dir is not None
                     else Path(__file__).resolve().parents[2] / "data")
        return cls(directory / "actuals_validation.csv")
