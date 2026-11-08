"""Native synthetic cache integration; no challenge data or performance studies."""

from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from backend.app.config import DEFAULT_ORIGIN, ForecastConfig
from backend.app.forecast_service import ForecastPreparationError, prepare_forecast
from backend.app.main import create_app
from forecast_engine.models.lightgbm import LightGBMPredictor


@unittest.skipUnless(importlib.util.find_spec("lightgbm") is not None, "LightGBM not installed")
class ModelCacheTests(unittest.TestCase):
    def setUp(self):
        from forecast_engine.tests.test_lightgbm import ml_fixture

        data, config, _ = ml_fixture()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        shift = pd.Timestamp(DEFAULT_ORIGIN) - pd.Timestamp(config.fit_cutoff_utc)
        for name, frame in (("inputs.csv", data.series), ("spot.csv", data.spot)):
            frame = frame.copy()
            for column in ("timestamp_utc", "first_usable_origin_utc"):
                frame[column] += shift
            frame.to_csv(self.root / name, index=False)
        self.path = self.root / "private cache" / "relative.json"
        self.config = ForecastConfig(self.root / "inputs.csv", self.root / "spot.csv",
                                     origins=(DEFAULT_ORIGIN,), model_cache_path=self.path)

    def test_fit_once_across_restarts_and_cached_model_reaches_http_and_catalog(self):
        from forecast_engine.models.artifacts import load_fitted_model

        with patch.object(LightGBMPredictor, "fit", autospec=True, side_effect=LightGBMPredictor.fit) as fit:
            first = prepare_forecast(self.config)
        self.assertEqual(fit.call_count, 1)
        self.assertTrue(self.path.is_file())
        with patch.object(LightGBMPredictor, "fit", side_effect=AssertionError("restart retraining forbidden")), \
             patch("forecast_engine.models.artifacts.load_fitted_model", wraps=load_fitted_model) as load:
            with TestClient(create_app(self.config)) as client:
                response = client.get("/api/forecast")
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["points"], first.response()["points"])
                self.assertEqual(payload["model_id"], "relative-control-v1")
                self.assertEqual(payload["predictor_id"], "lightgbm-relative-v1")
                self.assertEqual(client.get("/api/forecast").json(), payload)
                self.assertEqual(client.get("/api/origins").json()["model_id"], payload["model_id"])
                for forbidden in ('"spot_price":', '"_model_text":', '"dependencies":', '"model_cache_path":'):
                    self.assertNotIn(forbidden, response.text)
            load.assert_called_once()
            later = replace(self.config, origins=(DEFAULT_ORIGIN + pd.Timedelta(hours=1),))
            service = prepare_forecast(later)
            self.assertEqual(len(service.response()["points"]), 40)

    def test_changed_data_or_corrupt_cache_fails_without_retraining(self):
        prepare_forecast(self.config)
        original = self.path.read_bytes()
        with patch.object(LightGBMPredictor, "fit", side_effect=AssertionError("no surprise retrain")) as fit:
            with self.config.spot_path.open("a") as output:
                output.write("\n")
            with self.assertRaises(ForecastPreparationError) as error:
                prepare_forecast(self.config)
            self.assertEqual(error.exception.stage, "loading model cache")
            self.path.write_text('INVENTED_PRIVATE_TEXT')
            with self.assertRaises(ForecastPreparationError) as error:
                prepare_forecast(self.config)
            self.assertNotIn("INVENTED_PRIVATE_TEXT", str(error.exception))
            fit.assert_not_called()
        self.assertNotEqual(self.path.read_bytes(), original)

    def test_changed_runtime_and_engine_identity_reject_cache(self):
        prepare_forecast(self.config)
        document = json.loads(self.path.read_text())
        for field, value in (("engine_revision", "sha256:changed"), ("python", [0, 0, 0]),
                             ("libraries", {"lightgbm": "changed"})):
            edited = {**document, "identity": {**document["identity"], field: value}}
            self.path.write_text(json.dumps(edited))
            with patch.object(LightGBMPredictor, "fit", side_effect=AssertionError("no surprise retrain")) as fit:
                with self.assertRaises(ForecastPreparationError):
                    prepare_forecast(self.config)
                fit.assert_not_called()

    def test_default_cache_is_ignored_local_path_and_source_collision_rejected(self):
        config = ForecastConfig.from_data_dir()
        self.assertIn("baseline_output", config.model_cache_path.parts)
        self.assertNotIn(str(config.model_cache_path), repr(config))
        with self.assertRaises(ValueError):
            replace(self.config, model_cache_path=self.config.inputs_path)
        for name in ("actuals_validation.csv", "actuals_validation.json", "inputs.csv"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                replace(self.config, model_cache_path=self.root / name)


if __name__ == "__main__":
    unittest.main()
