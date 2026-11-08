"""Explicit real-data acceptance check; prints safe metadata/counts, never prices.

Run from the repository root: python -m backend.tests.smoke_forecast --data-dir data
This is a verification command, not a forecast export or application runtime API.
"""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
from unittest.mock import patch

from backend.app.config import ForecastConfig
from backend.app.forecast_service import ForecastPreparationError, prepare_forecast


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        import pandas as pd
        from forecast_engine.models.lightgbm import LightGBMPredictor

        config = ForecastConfig.from_data_dir(args.data_dir)
        source_paths = [config.inputs_path, config.spot_path]
        before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths]
        read_csv = pd.read_csv
        loaded_paths = []

        def guarded_read(path, *args, **kwargs):
            actual = Path(path).resolve()
            if actual not in source_paths:
                raise AssertionError("unexpected dataset access")
            loaded_paths.append(actual)
            return read_csv(path, *args, **kwargs)

        with patch("pandas.read_csv", side_effect=guarded_read):
            service = prepare_forecast(config)
        response = service.response()
        frame = service._result.forecasts  # Verification only; never exposed to app consumers.
        frame = frame.loc[frame["forecast_origin_utc"].eq(service.default_origin_utc)]
        assert len(frame) == len(response["points"]) == 40
        for point, row in zip(response["points"], frame.itertuples(index=False)):
            for name in ("forecast_origin_utc", "delivery_start_utc"):
                assert pd.Timestamp(point[name]) == getattr(row, name)
            assert point["step"] == row.step
            for name in ("p10", "p50", "p90", "p_up", "p_down", "p_none", "p_spike_high", "p_spike_low"):
                assert point[name] == getattr(row, name)
        with patch.object(LightGBMPredictor, "fit", side_effect=AssertionError("refitting forbidden")), \
             patch.object(type(service._fitted), "predict", side_effect=AssertionError("prediction forbidden")):
            assert service.response() == response
            assert json.loads(service.response_json()) == response
        assert loaded_paths == source_paths
        assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths]
        assert '"spot_price":' not in service.response_json()
        print(json.dumps({
            "status": "pass", "forecast_rows": len(frame), "dataset_reads": len(loaded_paths),
            "actuals_reads": 0, "required_values_match_engine": True,
            "retrieval_reuses_snapshot": True, "input_hashes_unchanged": True,
            "run_id": response["run_id"], "model_id": response["model_id"],
            "engine_revision": response["engine_revision"],
            "preparation_seconds": round(service.preparation_seconds, 3),
            "python": sys.version.split()[0],
            "dependencies": {k: importlib.metadata.version(k) for k in ("pandas", "numpy", "forecast-engine")},
        }, indent=2))
        return 0
    except ForecastPreparationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Real-data smoke failed; check local setup and rerun the synthetic tests.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
