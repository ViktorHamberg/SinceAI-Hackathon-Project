"""Private fitted-state round trips use invented data and never run a study."""

from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from forecast_engine import forecast
from forecast_engine.models.artifacts import load_fitted_model, save_fitted_model
from forecast_engine.models.lightgbm import LightGBMPredictor


@unittest.skipUnless(importlib.util.find_spec("lightgbm") is not None, "LightGBM not installed")
class ModelArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from forecast_engine.tests.test_lightgbm import ml_fixture

        cls.data, cls.config, recipe = ml_fixture()
        cls.fitted = LightGBMPredictor(recipe=recipe, min_training_rows=10, target_mode="spot_relative").fit(
            cls.data, config=cls.config)

    def test_exact_round_trip_including_lineage_backup_predictions_and_drivers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.json"
            save_fitted_model(path, self.fitted, identity={"source": "synthetic"})
            loaded = load_fitted_model(path, identity={"source": "synthetic"})
            self.assertEqual(loaded, self.fitted)
            with self.assertRaises(TypeError):
                loaded.provenance.counts["changed"] = 1
            data = self.data.spot.copy()
            data.loc[data.timestamp_utc.ge(self.config.fit_cutoff_utc), "first_usable_origin_utc"] = (
                self.config.fit_cutoff_utc + pd.Timedelta(hours=1))
            for inputs in (self.data, replace(self.data, spot=data)):
                before = forecast(self.fitted, inputs, origins=[self.config.fit_cutoff_utc])
                with patch.object(LightGBMPredictor, "fit", side_effect=AssertionError("refit forbidden")):
                    after = forecast(loaded, inputs, origins=[self.config.fit_cutoff_utc])
                pd.testing.assert_frame_equal(before.forecasts, after.forecasts)
                self.assertEqual(before.provenance, after.provenance)

    def test_stale_identity_corruption_and_unknown_state_fail(self):
        from forecast_engine.models.artifacts import _canonical
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            save_fitted_model(path, self.fitted, identity={"version": 1})
            with self.assertRaises(ValueError):
                load_fitted_model(path, identity={"version": 2})
            document = json.loads(path.read_text())
            document["model"]["value"]["_target_mode"] = "direct"
            path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):
                load_fitted_model(path, identity={"version": 1})
            document["model"] = {"type": "arbitrary.import", "value": {}}
            document["model_sha256"] = hashlib.sha256(_canonical(document["model"])).hexdigest()
            path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):
                load_fitted_model(path, identity={"version": 1})

    def test_failed_atomic_write_preserves_previous_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            save_fitted_model(path, self.fitted, identity={"version": 1})
            before = path.read_bytes()
            with patch("forecast_engine.models.artifacts.os.replace", side_effect=OSError("invented failure")):
                with self.assertRaises(OSError):
                    save_fitted_model(path, self.fitted, identity={"version": 2})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
