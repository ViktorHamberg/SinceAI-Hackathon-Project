"""Explicit local input paths; historical fitting boundaries belong to the engine."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ForecastConfig:
    """Paths resolve at configuration time, never during module import.

    Explicit relative paths resolve from the caller's directory. Default data paths
    derive from this checkout, so changing the working directory cannot select data.
    Paths are private and deliberately omitted from repr and forecast responses.
    """

    inputs_path: Path = field(repr=False)
    spot_path: Path = field(repr=False)

    def __post_init__(self) -> None:
        for name in ("inputs_path", "spot_path"):
            path = Path(getattr(self, name)).expanduser().resolve()
            if path.stem.lower().startswith("actuals"):
                raise ValueError("Scoring actuals cannot be configured as forecast inputs.")
            object.__setattr__(self, name, path)
        if self.inputs_path == self.spot_path:
            raise ValueError("Input series and spot data require separate files.")

    @classmethod
    def from_data_dir(cls, data_dir: str | Path | None = None) -> "ForecastConfig":
        directory = (Path(data_dir) if data_dir is not None
                     else Path(__file__).resolve().parents[2] / "data")
        return cls(directory / "inputs.csv", directory / "spot_nordpool.csv")
