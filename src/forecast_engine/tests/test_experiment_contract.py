"""Synthetic orchestration and real official-tool checks; no restricted fixtures."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from forecast_engine import ForecastInputs, RunConfig, forecast, load_inputs
from forecast_engine.experiments import run
from forecast_engine.features.training import ChronologicalFold
from forecast_engine.models import PersistencePredictor
from forecast_engine.tests.test_features import long_rows

ROOT = Path(__file__).resolve().parents[3]


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data_dir, self.starter, self.output = [self.root / x for x in ("data with spaces", "starter", "run")]
        self.data_dir.mkdir()
        self.starter.mkdir()
        # Tests execute the real, unchanged tools from the repository.
        for name in ("validate_submission.py", "score.py"):
            shutil.copyfile(ROOT / name, self.starter / name)
        self.cutoff = pd.Timestamp("2026-08-23T21:00Z")
        self.fold = ChronologicalFold(RunConfig(RunConfig.validation().label_start_utc,
                                              self.cutoff, self.cutoff),
                                      self.cutoff, self.cutoff + pd.Timedelta(hours=2))
        self.write_data(self.cutoff)

    def write_data(self, cutoff):
        records, spot = [], []
        for i, delivery in enumerate(pd.date_range(cutoff - pd.Timedelta(days=1), periods=144, freq="15min")):
            publication = (delivery + pd.Timedelta(minutes=15)).ceil("h")
            records.extend([("fi_imbalance_price", delivery, publication, float(i % 17 - 8)),
                            ("fi_mfrr_direction", delivery, publication, i % 3 - 1)])
            spot.append(("fi_spot_price", delivery, cutoff - pd.Timedelta(days=2), 9876543.21))
        long_rows(*records).to_csv(self.data_dir / "inputs.csv", index=False)
        long_rows(*spot).to_csv(self.data_dir / "spot_nordpool.csv", index=False)

    def invoke(self, **kwargs):
        return run.run_experiment(starter_dir=self.starter, data_dir=self.data_dir,
                                  output_dir=self.output, fold=kwargs.pop("fold", self.fold), **kwargs)

    def test_fold_end_to_end_all_metrics_and_safe_manifests(self):
        manifest = self.invoke()
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["forecast_rows"], 80)
        self.assertEqual(manifest["metrics"]["rows_scored_price"], 12)
        for name in run.METRICS:
            self.assertIsInstance(manifest["metrics"][name], float)
        self.assertEqual([x["exit_code"] for x in manifest["official_commands"]], [0, 0])
        self.assertIn("Errors: 0", manifest["official_commands"][0]["summary"])
        self.assertEqual(len(pd.read_csv(self.output / "fold_actuals.csv")), 8)
        self.assertEqual(manifest["scoring_label_config"]["publication_cutoff_utc"],
                         RunConfig.validation().fit_cutoff_utc.isoformat())
        for path in self.output.glob("*.json"):
            self.assertNotIn("9876543.21", path.read_text())

    def test_validation_actuals_access_follows_validation_and_fit_once(self):
        cutoff = RunConfig.validation().fit_cutoff_utc
        self.write_data(cutoff)
        origins = tuple(pd.date_range(cutoff, periods=2, freq="h"))
        pd.DataFrame({"delivery_start_utc": [cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")],
                      "imbalance_price": [3], "spot_price": [9876543.21], "direction": ["up"]}).to_csv(
                          self.data_dir / "actuals_validation.csv", index=False)
        calls, events = [], []
        original_record = run.evaluation._file_record
        original_tool = run.evaluation._run_tool

        def record(path):
            if Path(path).name == "actuals_validation.csv":
                self.assertIn("validated", events)
                self.assertEqual(calls, ["fit"])
            self.assertNotIn("actuals_test", str(path))
            return original_record(path)

        def tool(label, *args):
            original_tool(label, *args)
            if label == "validation":
                events.append("validated")

        class CountingPredictor:
            def fit(self, data, *, config):
                self_case.assertIsInstance(data, ForecastInputs)
                self_case.assertEqual(set(data.series.columns), set(long_rows().columns))
                calls.append("fit")
                return PersistencePredictor().fit(data, config=config)

        self_case = self
        with patch.object(run, "_validation_origins", return_value=origins), \
             patch.object(run.evaluation, "_file_record", side_effect=record), \
             patch.object(run.evaluation, "_run_tool", side_effect=tool):
            manifest = self.invoke(fold=None, predictor=CountingPredictor(), recipe_id="counted-v1")
        self.assertEqual(manifest["metrics"]["rows_scored_price"], 1)
        self.assertFalse((self.output / "fold_actuals.csv").exists())
        data = load_inputs(self.data_dir / "inputs.csv", spot_path=self.data_dir / "spot_nordpool.csv")
        expected = forecast(PersistencePredictor().fit(data, config=RunConfig.validation()), data, origins=origins)
        actual = pd.read_csv(self.output / "forecast_backtest.csv")
        self.assertEqual(len(actual), len(expected.forecasts))
        for name in ("p10", "p50", "p90", "p_up", "p_down", "p_none", "p_spike_high", "p_spike_low"):
            self.assertTrue((actual[name] - expected.forecasts[name]).abs().le(0.000001).all())

    def test_validation_failure_never_creates_scoring_actuals_and_hides_raw_output(self):
        (self.starter / "validate_submission.py").write_text(
            "import sys\nprint('SENSITIVE_9876543.21')\nprint('SENSITIVE_9876543.21', file=sys.stderr)\nsys.exit(1)\n")
        with self.assertRaises(run.ExperimentError) as caught:
            self.invoke()
        self.assertNotIn("9876543.21", str(caught.exception))
        self.assertFalse((self.output / "fold_actuals.csv").exists())
        manifest = json.loads((self.output / "run_manifest.json").read_text())
        self.assertEqual(manifest["failure"]["stage"], "validate")
        self.assertNotIn("scoring_actuals", manifest["consumed_files"])
        for path in self.output.glob("*.json"):
            self.assertNotIn("9876543.21", path.read_text())

    def test_model_error_is_sanitized_and_requires_explicit_recipe(self):
        class BrokenPredictor:
            def fit(self, *args, **kwargs):
                raise RuntimeError("SENSITIVE_9876543.21")

        with self.assertRaises(run.ExperimentError):
            self.invoke(predictor=BrokenPredictor())
        self.assertFalse(self.output.exists())
        with self.assertRaises(run.ExperimentError) as caught:
            self.invoke(predictor=BrokenPredictor(), recipe_id="broken")
        self.assertNotIn("SENSITIVE", str(caught.exception))
        manifest = json.loads((self.output / "run_manifest.json").read_text())
        self.assertEqual(manifest["failure"], {"stage": "fit", "error_type": "RuntimeError"})

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir()
        marker = self.output / "existing.txt"
        marker.write_text("keep")
        with self.assertRaises(run.ExperimentError):
            self.invoke()
        self.assertEqual(marker.read_text(), "keep")
        self.assertEqual(list(self.output.iterdir()), [marker])

    def test_fold_actuals_preserve_missing_components_and_publication_cutoff(self):
        start, end = self.fold.assessment_start_utc, self.fold.assessment_end_utc
        late = RunConfig.validation().fit_cutoff_utc + pd.Timedelta(hours=1)
        data = ForecastInputs(long_rows(
            ("fi_imbalance_price", start, start + pd.Timedelta(hours=1), 10),
            ("fi_mfrr_direction", start + pd.Timedelta(minutes=15), start, 0),
            ("fi_imbalance_price", start + pd.Timedelta(minutes=30), late, 99),
            ("fi_imbalance_price", end, end, 99),
        ), long_rows(("fi_spot_price", start + pd.Timedelta(minutes=15), start, -2)))
        actuals = run._fold_actuals(data, self.fold)
        self.assertEqual(len(actuals), 2)
        self.assertTrue(pd.isna(actuals.spot_price.iloc[0]))
        self.assertTrue(pd.isna(actuals.imbalance_price.iloc[1]))
        self.assertEqual(actuals.direction.iloc[1], "none")
        self.assertNotIn(99, list(actuals.imbalance_price))

    def test_default_origins_and_cli_failures_are_safe(self):
        self.assertEqual(len(run._validation_origins()), 672)
        self.assertEqual(run._validation_origins()[0], RunConfig.validation().fit_cutoff_utc)
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = run.main(["--data-dir", str(self.root / "missing"), "--output-dir", str(self.output)])
        self.assertEqual(code, 1)
        self.assertNotIn("missing", stderr.getvalue())
        with redirect_stderr(StringIO()) as error, self.assertRaises(SystemExit) as caught:
            run.main(["--period", "SENSITIVE_9876543.21"])
        self.assertEqual(caught.exception.code, 2)
        self.assertNotIn("SENSITIVE", error.getvalue())

    def test_cli_selection_is_explicit_and_default_remains_persistence(self):
        for name in (None, "persistence", "lightgbm-direct", "lightgbm-relative"):
            arguments = ["--output-dir", str(self.output)]
            if name is not None:
                arguments.extend(["--model", name])
            with patch.object(run, "run_experiment", return_value={"forecast_rows": 80}) as execute, \
                 redirect_stdout(StringIO()):
                self.assertEqual(run.main(arguments), 0)
            selected = name or "persistence"
            self.assertEqual(execute.call_args.kwargs["recipe_id"], f"{selected}-v1")
            predictor = execute.call_args.kwargs["predictor"]
            if selected == "persistence":
                self.assertIsInstance(predictor, PersistencePredictor)
            else:
                self.assertEqual(predictor.target_mode, "direct" if selected.endswith("direct") else "spot_relative")
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            run.main(["--model", "unknown", "--output-dir", str(self.output)])

    @unittest.skipUnless(importlib.util.find_spec("lightgbm") is not None, "optional LightGBM not installed")
    def test_both_models_run_official_tools_and_record_safe_reproducible_configuration(self):
        from forecast_engine.tests.test_lightgbm import ml_fixture

        data, config, _ = ml_fixture()
        data.series.to_csv(self.data_dir / "inputs.csv", index=False)
        data.spot.to_csv(self.data_dir / "spot_nordpool.csv", index=False)
        self.fold = ChronologicalFold(config, config.fit_cutoff_utc,
                                      config.fit_cutoff_utc + pd.Timedelta(hours=2))
        for name in ("lightgbm-direct", "lightgbm-relative"):
            predictor, identity = run._select_model(name)
            self.output = self.root / name
            manifest = self.invoke(predictor=predictor, recipe_id=identity)
            self.assertEqual(manifest["status"], "complete")
            self.assertTrue(all(isinstance(manifest["metrics"][metric], float) for metric in run.METRICS))
            model = manifest["model_configuration"]
            relative = name.endswith("relative")
            self.assertEqual(len(model["heads"]), 8 if relative else 5)
            for head in model["heads"]:
                self.assertEqual(head["num_boost_round"], 30)
                self.assertEqual(head["parameters"]["seed"], 2026)
                self.assertEqual(head["parameters"]["num_threads"], 1)
                self.assertEqual(len(head["model_sha256"]), 64)
                self.assertIn("horizon_step", head["features"])
                self.assertTrue(head["native_version"])
            paths = manifest["price_paths"]
            self.assertEqual(paths["delivery_spot_available"], 76)
            self.assertEqual(paths["delivery_spot_unavailable"], 4)
            self.assertEqual(paths["spot_relative"], 76 if relative else 0)
            self.assertEqual(paths["direct_backup"], 4 if relative else 0)
            self.assertEqual(paths["direct"], 0 if relative else 80)
            serialized = json.dumps(manifest)
            self.assertNotIn("_model_text", serialized)
            self.assertNotIn('"spot_price":', serialized)

    def test_import_has_no_heavy_imports_or_io(self):
        script = '''
import sys, os
def audit(event, args):
    if event == "open":
        path, mode, flags = args
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            raise AssertionError("write")
        if isinstance(path, (str, bytes)) and not os.fsdecode(path).endswith((".py", ".pyc")):
            raise AssertionError("noncode read")
    if event in {"subprocess.Popen", "socket.connect", "os.mkdir"}:
        raise AssertionError("external work")
sys.addaudithook(audit)
import forecast_engine.experiments.run
assert not {"pandas", "numpy", "lightgbm"}.intersection(sys.modules)
'''
        with tempfile.TemporaryDirectory() as workdir:
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", script], cwd=workdir,
                                       capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout + completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
