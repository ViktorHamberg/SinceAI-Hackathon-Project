"""Export validation or test forecasts from the application's saved fitted model.

Run from the repository's Python environment. This script never fits a model or
reads validation actuals; use the unchanged official tools to validate and score
the generated CSV afterward. Output stays under the ignored baseline_output/ tree.
"""

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path
import shutil

from backend.app.config import ForecastConfig
from backend.app.forecast_service import _engine_revision, _model_identity
from forecast_engine import RunConfig, export_forecasts, forecast, load_inputs
from forecast_engine.models.artifacts import load_fitted_model
from forecast_engine.models.lightgbm import LightGBMPredictor


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", choices=("validation", "test"), default="validation")
    parser.add_argument(
        "--output-dir", type=Path,
        default=None,
        help="New directory for the forecast and origins CSV files.",
    )
    args = parser.parse_args()
    requested_output = args.output_dir or (root / "baseline_output" / "engine" / f"cached-relative-{args.period}-01")
    output_dir = requested_output if requested_output.is_absolute() else root / requested_output
    if output_dir.exists():
        parser.error(f"output directory already exists: {output_dir}; choose a new one")

    config = ForecastConfig.from_data_dir(root / "data")
    predictor = LightGBMPredictor(target_mode="spot_relative")
    fit_config = RunConfig.validation()
    identity = _model_identity(config, predictor, fit_config, _engine_revision(), "relative-control-v1")
    fitted = load_fitted_model(config.model_cache_path, identity=identity)

    if args.period == "test":
        with (root / "forecast_origins.csv").open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != ["forecast_origin_utc"]:
                parser.error("official test origins file has unexpected columns")
            origins = tuple(datetime.fromisoformat(row["forecast_origin_utc"].replace("Z", "+00:00"))
                            for row in reader)
        first = RunConfig.test().fit_cutoff_utc
        if len(origins) != 673 or origins != tuple(first + timedelta(hours=hour) for hour in range(673)):
            parser.error("official test origins file does not contain the expected 673 hourly origins")
    else:
        first = fit_config.fit_cutoff_utc
        end = RunConfig.test().fit_cutoff_utc
        origins = tuple(first + timedelta(hours=hour) for hour in range(int((end - first) / timedelta(hours=1))))

    data = load_inputs(config.inputs_path, spot_path=config.spot_path)
    result = forecast(fitted, data, origins=origins)

    output_dir.mkdir(parents=True)
    export_forecasts(result.forecasts, output_dir / "forecast_backtest.csv", origins=origins)
    if args.period == "test":
        shutil.copyfile(root / "forecast_origins.csv", output_dir / "forecast_origins.csv")
    else:
        with (output_dir / "forecast_origins.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["forecast_origin_utc"])
            writer.writerows([[origin.strftime("%Y-%m-%dT%H:%M:%SZ")] for origin in origins])
    print(f"Exported {len(result.forecasts)} forecast rows for {len(origins)} {args.period} origins to {output_dir}")


if __name__ == "__main__":
    main()
