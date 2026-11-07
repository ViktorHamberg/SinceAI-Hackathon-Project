"""Same engine/application caller and unchanged official tools for both predictors."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

from forecast_engine import forecast
from forecast_engine.experiments.run import run_experiment
from forecast_engine.features.training import ChronologicalFold
from forecast_engine.models import PersistencePredictor
from forecast_engine.models.lightgbm import LightGBMPredictor
from forecast_engine.tests.test_lightgbm import ml_fixture

ROOT = Path(__file__).resolve().parents[3]


class OptionalDependencyCompatibilityTests(unittest.TestCase):
    def test_persistence_and_model_module_import_without_optional_library(self):
        script = '''
import sys, importlib.abc
class NoOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'lightgbm', 'scipy'}:
            raise ImportError('optional dependency deliberately unavailable')
sys.meta_path.insert(0, NoOptional())
from forecast_engine.models import PersistencePredictor
from forecast_engine.models.lightgbm import LightGBMPredictor
assert PersistencePredictor() is not None
assert LightGBMPredictor() is not None
assert not {'lightgbm', 'numpy', 'pandas'}.intersection(sys.modules)
'''
        with tempfile.TemporaryDirectory() as workdir:
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", script], cwd=workdir,
                                       capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout + completed.stderr, "")


@unittest.skipUnless(importlib.util.find_spec("lightgbm") is not None, "approved optional LightGBM is not installed")
class ModelCompatibilityTests(unittest.TestCase):
    def test_same_public_caller_and_backend_serializer(self):
        from backend.app.schemas import build_response

        data, config, recipe = ml_fixture()
        for model in (PersistencePredictor(), LightGBMPredictor(recipe=recipe, min_training_rows=10),
                      LightGBMPredictor(recipe=recipe, min_training_rows=10, target_mode="spot_relative")):
            fitted = model.fit(data, config=config)
            result = forecast(fitted, data, origins=[config.fit_cutoff_utc])
            response = build_response(result, origin=config.fit_cutoff_utc, config=config,
                                      model_id="compatibility-fixture", engine_revision="sha256:" + "0" * 64,
                                      run_id="00000000-0000-0000-0000-000000000001", generated_at_utc=config.fit_cutoff_utc)
            self.assertEqual(len(response.points), 40)
            self.assertEqual(response.predictor_id, fitted.provenance.predictor_id)

    def test_direct_model_exports_and_passes_real_official_validation_and_scoring(self):
        data, config, recipe = ml_fixture()
        fold = ChronologicalFold(config, config.fit_cutoff_utc, config.fit_cutoff_utc + pd.Timedelta(hours=2))
        with tempfile.TemporaryDirectory() as workdir:
            directory = Path(workdir)
            data_dir = directory / "data with spaces"
            data_dir.mkdir()
            data.series.to_csv(data_dir / "inputs.csv", index=False)
            data.spot.to_csv(data_dir / "spot_nordpool.csv", index=False)
            manifest = run_experiment(starter_dir=ROOT, data_dir=data_dir, output_dir=directory / "output",
                                      fold=fold, predictor=LightGBMPredictor(recipe=recipe, min_training_rows=10),
                                      recipe_id="lightgbm-direct-synthetic-v1")
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["forecast_rows"], 80)
            self.assertTrue(all(c["exit_code"] == 0 for c in manifest["official_commands"]))
            self.assertTrue(all(manifest["metrics"][name] is not None for name in (
                "mae_p50", "calibration_pinball_mean", "brier_spike_mean", "brier_direction")))


if __name__ == "__main__":
    unittest.main()
