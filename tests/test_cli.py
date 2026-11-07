"""Synthetic workflow checks; official tools remain byte-for-byte unchanged."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from forecast_engine import RunConfig, forecast, load_inputs
from forecast_engine.cli import main
from forecast_engine import evaluation
from forecast_engine.models import PersistencePredictor
from forecast_engine.submission import _round_trip
from test_calibration import calibration_fixture

ROOT = Path(__file__).resolve().parents[1]


def write_request(directory, origins):
    directory.mkdir(parents=True, exist_ok=True)
    identifiers = pd.DataFrame({
        "forecast_origin_utc": pd.DatetimeIndex(origins).repeat(40),
        "step": np.tile(np.arange(1, 41), len(origins)),
    })
    identifiers["delivery_start_utc"] = identifiers.forecast_origin_utc + pd.to_timedelta((identifiers.step - 1) * 15, unit="min")
    template = identifiers.copy()
    for name in evaluation.FORECAST_COLUMNS[3:]:
        template[name] = ""
    template = template[list(evaluation.FORECAST_COLUMNS)]
    for name in ["forecast_origin_utc", "delivery_start_utc"]:
        template[name] = template[name].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    template.to_csv(directory / "sample_submission.csv", index=False)
    pd.DataFrame({"forecast_origin_utc": pd.DatetimeIndex(origins).strftime("%Y-%m-%dT%H:%M:%SZ")}).to_csv(
        directory / "forecast_origins.csv", index=False)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.starter = self.root / "starter with spaces"
        self.data_dir = self.root / "data with spaces"
        self.starter.mkdir()
        self.data_dir.mkdir()
        for name in ["make_templates.py", "validate_submission.py", "score.py"]:
            shutil.copyfile(ROOT / name, self.starter / name)
        self.output = self.root / "output"

    def data(self, mode):
        config = RunConfig.validation() if mode == "validation" else RunConfig.test()
        data, _ = calibration_fixture(start=config.fit_cutoff_utc - pd.Timedelta(hours=24))
        data.series.to_csv(self.data_dir / "inputs.csv", index=False)
        data.spot.to_csv(self.data_dir / "spot_nordpool.csv", index=False)
        origins = pd.date_range(config.fit_cutoff_utc, periods=2, freq="h")
        # Only a synthetic validation actuals file; no test actuals are created.
        if mode == "validation":
            pd.DataFrame({"delivery_start_utc": origins.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "imbalance_price": [12., 13.], "spot_price": [987654321.234567] * 2,
                          "direction": ["up", "none"]}).to_csv(self.data_dir / "actuals_validation.csv", index=False)
        return origins

    def args(self, mode):
        return [mode, "--starter-dir", str(self.starter), "--data-dir", str(self.data_dir), "--output-dir", str(self.output)]

    def invoke(self, mode):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(self.args(mode))
        return code, stdout.getvalue(), stderr.getvalue()

    def small_validation_templates(self, origins):
        original = evaluation._run_tool

        def run(label, script, arguments, starter, output, manifest):
            if label == "templates":
                # A two-origin fixture instead of a full month. Validator/scorer
                # still execute as real subprocesses using their unchanged files.
                write_request(output, origins)
                manifest["official_commands"].append({"tool": label, "exit_code": 0,
                    "command": [sys.executable, str(script), *map(str, arguments)]})
            else:
                original(label, script, arguments, starter, output, manifest)
        return run

    def test_small_validation_cli_matches_api_and_real_official_tools(self):
        origins = self.data("validation")
        original_hashes = {p.name: evaluation._sha256(p) for p in self.starter.iterdir()}
        with patch.object(evaluation, "_expected_origins", return_value=origins), \
             patch.object(evaluation, "_run_tool", side_effect=self.small_validation_templates(origins)):
            code, stdout, stderr = self.invoke("validation")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stderr, "")
        manifest = json.loads((self.output / "run_manifest.json").read_text())
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual((manifest["origin_count"], manifest["forecast_rows"]), (2, 80))
        self.assertEqual([x["exit_code"] for x in manifest["official_commands"]], [0, 0, 0])
        self.assertEqual(manifest["config"]["fit_cutoff_utc"], RunConfig.validation().fit_cutoff_utc.isoformat())
        self.assertIn("validation_actuals", manifest["consumed_files"])
        self.assertTrue((self.output / "score/score_summary.csv").is_file())
        self.assertTrue((self.output / "official_validation.json").is_file())
        loaded = load_inputs(self.data_dir / "inputs.csv", spot_path=self.data_dir / "spot_nordpool.csv")
        fitted = PersistencePredictor().fit(loaded, config=RunConfig.validation())
        expected = forecast(fitted, loaded, origins=list(origins)).forecasts
        actual = _round_trip((self.output / "forecast_backtest.csv").read_text())
        assert_frame_equal(actual, expected, check_dtype=False)
        self.assertEqual(original_hashes, {p.name: evaluation._sha256(p) for p in self.starter.iterdir()})
        for path in self.output.glob("*.json"):
            self.assertNotIn("987654321.234567", path.read_text())
        self.assertNotIn("987654321.234567", stdout)

    def test_small_test_mode_uses_test_cutoff_and_never_checks_actuals(self):
        origins = self.data("test")
        write_request(self.starter, origins)
        original = evaluation._file_record

        def guard(path):
            self.assertNotIn("actuals", Path(path).name)
            return original(path)

        with patch.object(evaluation, "_expected_origins", return_value=origins), \
             patch.object(evaluation, "_file_record", side_effect=guard):
            code, stdout, stderr = self.invoke("test")
        self.assertEqual(code, 0, stderr)
        manifest = json.loads((self.output / "run_manifest.json").read_text())
        self.assertEqual(manifest["config"]["fit_cutoff_utc"], RunConfig.test().fit_cutoff_utc.isoformat())
        self.assertEqual([r["tool"] for r in manifest["official_commands"]], ["validation"])
        self.assertNotIn("validation_actuals", manifest["consumed_files"])
        self.assertFalse((self.output / "score").exists())

    def test_real_template_generator_produces_canonical_validation_grid(self):
        result = subprocess.run([sys.executable, str(self.starter / "make_templates.py"),
            "--test-start", "2026-09-07", "--test-end", "2026-10-04", "--output-dir", str(self.output)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        origins = evaluation._read_request(self.output / "forecast_origins.csv", self.output / "sample_submission.csv", "validation")
        self.assertEqual(len(origins), 672)
        self.assertEqual(origins[0], pd.Timestamp(RunConfig.validation().fit_cutoff_utc))

    def test_module_test_command_from_unrelated_directory_with_synthetic_data(self):
        self.data("test")
        write_request(self.starter, evaluation._expected_origins("test"))
        # A full-format 673-origin grid with only one synthetic day of fitting data;
        # this is a command/path integration check, not full-data acceptance.
        completed = subprocess.run([sys.executable, "-m", "forecast_engine", *self.args("test")],
                                   cwd=self.root, capture_output=True, text=True, timeout=90)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        manifest = json.loads((self.output / "run_manifest.json").read_text())
        self.assertEqual((manifest["origin_count"], manifest["forecast_rows"]), (673, 26920))
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["official_commands"][0]["exit_code"], 0)
        self.assertTrue(all(Path(p).is_absolute() for p in manifest["artifacts"].values()))

    def test_missing_input_returns_nonzero_with_failure_manifest(self):
        code, stdout, stderr = self.invoke("test")
        self.assertEqual(code, 1)
        self.assertIn("missing required inputs", stderr)
        manifest = json.loads((self.output / "run_manifest.json").read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["failure"]["stage"], "preflight")
        self.assertEqual(stdout, "")

    def test_validator_and_scorer_failures_are_nonzero_and_raw_output_is_not_logged(self):
        origins = self.data("validation")
        actual_run = evaluation._run_tool
        for failure in ["validation", "scoring"]:
            self.output = self.root / failure
            fixture_runner = self.small_validation_templates(origins)

            def run(label, script, arguments, starter, output, manifest):
                if label == failure:
                    completed = subprocess.CompletedProcess([], 1,
                        "ERROR [INVALID_NUMBER]\nPRIVATE_SPOT_VALUE=987654321.234567\n",
                        "SECRET_TOKEN_SHOULD_NOT_APPEAR")
                    with patch("forecast_engine.evaluation.subprocess.run", return_value=completed):
                        actual_run(label, script, arguments, starter, output, manifest)
                else:
                    fixture_runner(label, script, arguments, starter, output, manifest)

            with self.subTest(failure=failure), patch.object(evaluation, "_expected_origins", return_value=origins), \
                 patch.object(evaluation, "_run_tool", side_effect=run):
                code, stdout, stderr = self.invoke("validation")
            self.assertEqual(code, 1)
            manifest = json.loads((self.output / "run_manifest.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["official_commands"][-1]["exit_code"], 1)
            combined = stdout + stderr + "".join(p.read_text() for p in self.output.glob("*.json"))
            self.assertNotIn("987654321.234567", combined)
            self.assertNotIn("SECRET_TOKEN_SHOULD_NOT_APPEAR", combined)
            if failure == "validation":
                self.assertNotIn("validation_actuals", manifest["consumed_files"])

    def test_unexpected_model_error_and_environment_secret_are_not_logged(self):
        origins = self.data("test")
        write_request(self.starter, origins)
        with patch.object(evaluation, "_expected_origins", return_value=origins), \
             patch.object(PersistencePredictor, "fit", side_effect=ValueError("PRIVATE_SPOT_AND_SECRET")), \
             patch.dict(os.environ, {"FINGRID_API_KEY": "PRIVATE_SPOT_AND_SECRET"}):
            code, stdout, stderr = self.invoke("test")
        self.assertEqual(code, 1)
        manifest = (self.output / "run_manifest.json").read_text()
        self.assertNotIn("PRIVATE_SPOT_AND_SECRET", manifest + stdout + stderr)
        self.assertEqual(json.loads(manifest)["failure"]["stage"], "fit")

    def test_nonempty_output_is_refused_and_defaults_are_under_starter(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("keep")
        code, _, stderr = self.invoke("test")
        self.assertEqual(code, 1)
        self.assertIn("new or empty", stderr)
        self.assertEqual(sentinel.read_text(), "keep")
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(["test", "--starter-dir", str(self.starter)])
        self.assertEqual(result, 1)
        self.assertTrue((self.starter / "baseline_output/engine/test/run_manifest.json").is_file())

    def test_invalid_test_actuals_option_does_not_echo_unknown_secret(self):
        stderr = StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            main(["test", "--actuals-file", "SECRET_UNSUPPORTED_VALUE"])
        self.assertEqual(error.exception.code, 2)
        self.assertNotIn("SECRET_UNSUPPORTED_VALUE", stderr.getvalue())

    def test_actuals_paths_are_rejected_before_source_fingerprinting(self):
        for mode, option in [("test", "--inputs-file"), ("test", "--spot-file"), ("validation", "--actuals-file")]:
            self.output = self.root / (mode + option)
            with self.subTest(mode=mode, option=option), patch.object(evaluation, "_file_record") as record:
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    code = main([*self.args(mode), option, str(self.data_dir / "actuals_test.csv")])
                self.assertEqual(code, 1)
                record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
