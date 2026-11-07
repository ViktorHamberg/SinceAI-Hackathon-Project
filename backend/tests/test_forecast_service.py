"""Synthetic application boundary tests; no challenge datasets are read."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import timedelta
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import traceback
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

import pandas as pd

from forecast_engine import (
    FORECAST_COLUMNS, DependencyEvidence, FitProvenance, ForecastInputs,
    ForecastProvenance, ForecastResult, OriginProvenance, RunConfig,
    SourceDependency, empty_forecast_frame,
)
from backend.app.config import ForecastConfig
from backend.app.forecast_service import ForecastPreparationError, prepare_forecast

ROOT = Path(__file__).resolve().parents[2]
PRIVATE_SENTINEL = "INVENTED_PRIVATE_SOURCE_987654321"


def synthetic_result():
    config = RunConfig.validation()
    origin = config.fit_cutoff_utc
    source = SourceDependency("fi_imbalance_price", origin - timedelta(hours=2),
                              origin - timedelta(hours=1), origin)
    evidence = DependencyEvidence("synthetic_observation", origin, (source,))
    fitting = FitProvenance(config, "synthetic", counts={PRIVATE_SENTINEL: 1},
                            dependencies=(evidence,))
    frame = empty_forecast_frame().reindex(range(40))
    frame["forecast_origin_utc"] = pd.Series([origin] * 40, dtype="datetime64[ns, UTC]")
    frame["delivery_start_utc"] = pd.date_range(origin, periods=40, freq="15min")
    frame["step"] = pd.Series(range(1, 41), dtype="int64")
    for name, value in zip(FORECAST_COLUMNS[3:11],
                           [-31.123456789, -11.987654321, 9.123456789, .2, .3, .5, .1, .25]):
        frame[name] = value
    frame.attrs["spot_price"] = PRIVATE_SENTINEL
    record = OriginProvenance(origin, dependencies=(evidence,))
    return ForecastResult(frame, ForecastProvenance(fitting, (record,)))


class ForecastServiceTests(unittest.TestCase):
    def setUp(self):
        self.result = synthetic_result()
        self.data = ForecastInputs(pd.DataFrame({"private_source": [PRIVATE_SENTINEL]}))
        self.config = ForecastConfig(Path("unused inputs.csv"), Path("unused spot.csv"))
        self.fitted = Mock(provenance=self.result.provenance.fitting)
        self.fitted.predict.return_value = self.result
        self.predictor = Mock()
        self.predictor.fit.return_value = self.fitted
        loader = patch("backend.app.forecast_service.load_inputs", return_value=self.data)
        self.loader = loader.start()
        self.addCleanup(loader.stop)

    def prepare(self, **kwargs):
        return prepare_forecast(self.config, predictor=self.predictor,
                                model_id="synthetic-v1", **kwargs)

    def test_complete_response_preserves_values_and_time_arithmetic(self):
        service = self.prepare()
        response = service.response()
        self.assertEqual(set(response), {
            "schema_version", "run_id", "model_id", "predictor_id", "engine_revision",
            "generated_at_utc", "forecast_origin_utc", "fit_cutoff_utc", "points",
        })
        self.assertEqual(response["forecast_origin_utc"], "2026-09-06T21:00:00Z")
        self.assertEqual(response["fit_cutoff_utc"], response["forecast_origin_utc"])
        self.assertEqual(len(response["points"]), 40)
        for point, row in zip(response["points"], self.result.forecasts.itertuples(index=False)):
            self.assertEqual(tuple(point), FORECAST_COLUMNS)
            self.assertIsInstance(point["step"], int)
            for name in FORECAST_COLUMNS[3:11]:
                self.assertEqual(point[name], getattr(row, name))
            delivery = pd.Timestamp(response["forecast_origin_utc"]) + pd.Timedelta(minutes=15 * (point["step"] - 1))
            self.assertEqual(pd.Timestamp(point["delivery_start_utc"]), delivery)
            self.assertTrue(point["delivery_start_utc"].endswith("Z"))
            self.assertIsNone(point["data_cutoff_utc"])
            self.assertIsNone(point["top_drivers"])
        self.assertEqual(response["points"][-1]["delivery_start_utc"], "2026-09-07T06:45:00Z")
        self.assertEqual(json.loads(service.response_json()), response)

    def test_explicit_initialization_once_and_no_work_on_retrieval(self):
        service = self.prepare()
        self.loader.assert_called_once_with(self.config.inputs_path, spot_path=self.config.spot_path)
        self.predictor.fit.assert_called_once_with(self.data, config=RunConfig.validation())
        self.fitted.predict.assert_called_once_with(self.data, origins=(RunConfig.validation().fit_cutoff_utc,))
        before = service.response_json()
        with patch("backend.app.forecast_service.load_inputs", side_effect=AssertionError), \
             patch.object(self.predictor, "fit", side_effect=AssertionError), \
             patch.object(self.fitted, "predict", side_effect=AssertionError):
            for _ in range(3):
                self.assertEqual(service.response_json(), before)
                self.assertEqual(service.response(), json.loads(before))
        self.assertGreaterEqual(service.preparation_seconds, 0)

    def test_callers_cannot_mutate_the_cached_response(self):
        service = self.prepare()
        original = service.response_json()
        copy = service.response()
        copy["run_id"] = "replaced"
        copy["points"][0]["p50"] = 99999
        copy["points"].clear()
        self.result.forecasts.loc[0, "p50"] = 55555
        self.assertEqual(service.response_json(), original)
        self.assertEqual(len(service.response()["points"]), 40)

    def test_run_identity_stays_fixed_and_distinguishes_preparations(self):
        first, second = self.prepare().response(), self.prepare().response()
        self.assertNotEqual(first["run_id"], second["run_id"])
        for response in (first, second):
            self.assertEqual(str(UUID(response["run_id"])), response["run_id"])
            self.assertEqual(response["model_id"], "synthetic-v1")
            self.assertEqual(response["predictor_id"], "synthetic")
            self.assertEqual(response["schema_version"], "1.0")
            self.assertRegex(response["engine_revision"], r"^sha256:[0-9a-f]{64}$")
            self.assertTrue(response["generated_at_utc"].endswith("Z"))
        self.assertEqual(first["engine_revision"], second["engine_revision"])

    def test_source_values_provenance_and_paths_are_absent(self):
        service = self.prepare()
        combined = service.response_json() + repr(service)
        for forbidden in (PRIVATE_SENTINEL, "spot_price", "private_source", "dependencies",
                          "provenance", "unused inputs", "unused spot"):
            self.assertNotIn(forbidden, combined)

    def test_optional_cutoff_and_approved_driver_survive_unknown_text_is_dropped(self):
        origin = RunConfig.validation().fit_cutoff_utc
        self.result.forecasts.loc[0, "data_cutoff_utc"] = origin - timedelta(minutes=5)
        self.result.forecasts.loc[0, "top_drivers"] = "last_imbalance_price"
        self.result.forecasts.loc[1, "top_drivers"] = PRIVATE_SENTINEL
        self.result.forecasts.loc[2, "top_drivers"] = "last_imbalance_price;" + PRIVATE_SENTINEL
        self.result.forecasts.loc[3, "top_drivers"] = ""
        response = self.prepare().response()
        self.assertEqual(response["points"][0]["data_cutoff_utc"], "2026-09-06T20:55:00Z")
        self.assertEqual(response["points"][0]["top_drivers"], "last_imbalance_price")
        self.assertTrue(all(p["top_drivers"] is None for p in response["points"][1:]))
        self.assertNotIn(PRIVATE_SENTINEL, json.dumps(response))

    def test_invalid_engine_outputs_fail_without_repair_or_partial_response(self):
        for column, value in [("p50", float("nan")), ("p90", float("inf")),
                              ("p10", 1000.), ("p_up", -1.), ("p_none", .9),
                              ("p_spike_high", 1.)]:
            bad = self.result.forecasts.copy()
            bad.loc[0, column] = value
            self.fitted.predict.return_value = replace(self.result, forecasts=bad)
            with self.subTest(column=column), self.assertRaises(ForecastPreparationError) as error:
                self.prepare()
            self.assertEqual(error.exception.stage, "prediction")
        for frame in (self.result.forecasts.iloc[1:], self.result.forecasts.iloc[::-1],
                      self.result.forecasts.assign(spot_price=123456789.)):
            self.fitted.predict.return_value = replace(self.result, forecasts=frame)
            with self.assertRaises(ForecastPreparationError):
                self.prepare()

    def test_failures_at_each_stage_have_no_sensitive_output_or_chained_traceback(self):
        for target in ["load_inputs", "build_response", "_engine_revision"]:
            stdout, stderr = StringIO(), StringIO()
            with self.subTest(target=target), \
                 patch("backend.app.forecast_service." + target, side_effect=ValueError(PRIVATE_SENTINEL)), \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                with self.assertRaises(ForecastPreparationError) as error:
                    self.prepare()
            diagnostic = "".join(traceback.format_exception(error.exception))
            self.assertNotIn(PRIVATE_SENTINEL, diagnostic + stdout.getvalue() + stderr.getvalue())
            self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")
        for method in (self.predictor.fit, self.fitted.predict):
            method.side_effect = ValueError(PRIVATE_SENTINEL)
            with self.assertRaises(ForecastPreparationError) as error:
                self.prepare()
            self.assertNotIn(PRIVATE_SENTINEL, "".join(traceback.format_exception(error.exception)))
            method.side_effect = None

    def test_engine_source_change_during_preparation_rejects_snapshot(self):
        revisions = ["sha256:" + "a" * 64, "sha256:" + "b" * 64]
        with patch("backend.app.forecast_service._engine_revision", side_effect=revisions):
            with self.assertRaises(ForecastPreparationError) as error:
                self.prepare()
        self.assertEqual(error.exception.stage, "engine integrity")

    def test_another_predictor_works_without_service_changes_and_needs_recipe_label(self):
        with self.assertRaises(ForecastPreparationError) as error:
            prepare_forecast(self.config, predictor=self.predictor)
        self.assertEqual(error.exception.stage, "configuration")
        self.loader.assert_not_called()
        other = Mock()
        other.fit.return_value = self.fitted
        response = prepare_forecast(self.config, predictor=other, model_id="another-recipe-v2").response()
        self.assertEqual(response["model_id"], "another-recipe-v2")
        other.fit.assert_called_once()

    def test_invalid_identity_and_mismatched_fit_config_are_rejected_safely(self):
        with self.assertRaises(ForecastPreparationError):
            prepare_forecast(self.config, predictor=self.predictor, model_id="private text/" + PRIVATE_SENTINEL)
        later = replace(self.result.provenance.fitting, config=RunConfig.test())
        self.fitted.provenance = later
        self.fitted.predict.return_value = replace(self.result, provenance=replace(self.result.provenance, fitting=later))
        with self.assertRaises(ForecastPreparationError):
            self.prepare()


class ConfigurationAndImportTests(unittest.TestCase):
    def test_default_paths_are_checkout_relative_and_actuals_are_rejected(self):
        config = ForecastConfig.from_data_dir()
        self.assertEqual(config.inputs_path, ROOT / "data" / "inputs.csv")
        self.assertEqual(config.spot_path, ROOT / "data" / "spot_nordpool.csv")
        self.assertNotIn(str(ROOT), repr(config))
        for filename in ("actuals_validation.csv", "ACTUALS_TEST.csv"):
            with self.assertRaises(ValueError):
                ForecastConfig(Path(filename), Path("spot.csv"))
        with self.assertRaises(ValueError):
            ForecastConfig(Path("same.csv"), Path("same.csv"))

    def test_import_has_no_data_loading_heavy_imports_writes_or_external_work(self):
        script = textwrap.dedent('''
            import os,sys
            sys.path.insert(0,sys.argv[1])
            def audit(event,args):
                if event == "open":
                    path,mode,flags=args
                    if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                        raise AssertionError("import wrote a file")
                    if isinstance(path,(str,bytes)) and not os.fsdecode(path).endswith((".py",".pyc")):
                        raise AssertionError("import read non-code data")
                if event in {"subprocess.Popen","os.system","socket.connect","os.mkdir"}:
                    raise AssertionError("import did external work")
            sys.addaudithook(audit)
            import backend.app.config
            import backend.app.schemas
            import backend.app.forecast_service
            assert "pandas" not in sys.modules and "numpy" not in sys.modules
            assert not os.listdir(".")
        ''')
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(ROOT)],
                                       cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout + completed.stderr, "")

    def test_real_engine_with_synthetic_csv_paths_with_spaces_and_unrelated_directory(self):
        start = RunConfig.validation().label_start_utc
        dates = pd.date_range(start, periods=96, freq="15min")
        records, spots = [], []
        columns = ["series_id", "source", "dataset_id", "timestamp_utc", "value", "unit", "first_usable_origin_utc"]
        for index, delivery in enumerate(dates):
            usable = (delivery + pd.Timedelta(minutes=75)).ceil("h")
            records.append(["fi_imbalance_price", "fingrid", "319", delivery, float(index), "EUR/MWh", usable])
            records.append(["fi_mfrr_direction", "fingrid", "369", delivery, [-1., 0., 1.][index % 3], "-1/0/1", usable])
            spots.append(["fi_spot_price", "nordpool", "", delivery, float(index), "EUR/MWh", start])
        script = textwrap.dedent('''
            import sys
            sys.path.insert(0,sys.argv[1])
            from backend.app.config import ForecastConfig
            from backend.app.forecast_service import prepare_forecast
            service=prepare_forecast(ForecastConfig.from_data_dir(sys.argv[2]))
            response=service.response()
            assert len(response["points"])==40
            assert response["points"][0]["p50"]==95.
            assert response["model_id"]=="persistence-v1"
            assert response["predictor_id"]=="persistence"
            assert response["forecast_origin_utc"]=="2026-09-06T21:00:00Z"
        ''')
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "input folder with spaces"
            data_dir.mkdir()
            pd.DataFrame(records, columns=columns).to_csv(data_dir / "inputs.csv", index=False)
            pd.DataFrame(spots, columns=columns).to_csv(data_dir / "spot_nordpool.csv", index=False)
            (data_dir / "actuals_validation.csv").write_text("not a readable dataset")
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(ROOT), str(data_dir)],
                                       cwd=directory, capture_output=True, text=True, timeout=45)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout + completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
