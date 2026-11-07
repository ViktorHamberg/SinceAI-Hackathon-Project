"""Synthetic outcome/HTTP checks; real datasets and restricted spot values are unused."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from io import StringIO
import json
from pathlib import Path
import tempfile
import traceback
import unittest
from unittest.mock import Mock, patch

import pandas as pd
from fastapi.testclient import TestClient

from backend.app.actuals import HISTORY_COLUMNS, ActualsStore, HistoryUnavailableError, load_actuals
from backend.app.config import DEFAULT_ORIGIN, ForecastConfig, HistoryConfig
from backend.app.forecast_service import prepare_forecast
from backend.app.main import create_app
from backend.app.schemas import utc_text
from backend.tests.test_forecast_service import PRIVATE_SENTINEL
from backend.tests.test_origin_selection import synthetic_batch
from forecast_engine import ForecastInputs, RunConfig


class HistoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name) / "outcome folder with spaces"
        self.directory.mkdir()
        self.history_config = HistoryConfig.from_data_dir(self.directory)
        self.origins = (DEFAULT_ORIGIN, DEFAULT_ORIGIN + timedelta(hours=1))
        self.config = ForecastConfig(self.directory / "inputs.csv", self.directory / "spot.csv", self.origins)
        result = synthetic_batch(self.origins)
        self.fitted = Mock(provenance=result.provenance.fitting)
        self.fitted.predict.return_value = result
        self.predictor = Mock()
        self.predictor.fit.return_value = self.fitted
        self.data = ForecastInputs(pd.DataFrame({"invented": [1]}))
        with patch("backend.app.forecast_service.load_inputs", return_value=self.data):
            self.service = prepare_forecast(self.config, predictor=self.predictor, model_id="synthetic-v1")

    def write_actuals(self, rows):
        frame = pd.DataFrame(rows, columns=HISTORY_COLUMNS)
        frame["spot_price"] = PRIVATE_SENTINEL
        frame["first_usable_origin_utc"] = "2026-11-07T00:00:00Z"
        frame.to_csv(self.history_config.actuals_path, index=False)

    def app(self):
        return create_app(service_factory=lambda: self.service, history_config=self.history_config)

    def test_three_column_ingestion_precise_join_counts_and_inclusive_metrics(self):
        self.write_actuals([
            [utc_text(DEFAULT_ORIGIN), "-10", " UP "],
            [utc_text(DEFAULT_ORIGIN + timedelta(minutes=15)), "10", "down"],
            [utc_text(DEFAULT_ORIGIN + timedelta(minutes=30)), "30", ""],
            [utc_text(DEFAULT_ORIGIN + timedelta(minutes=45)), "", "none"],
        ])
        read = pd.read_csv
        with patch("pandas.read_csv", wraps=read) as reads:
            store = load_actuals(self.history_config)
        self.assertEqual(reads.call_args.kwargs["usecols"], list(HISTORY_COLUMNS))
        self.assertFalse(reads.call_args.kwargs["keep_default_na"])
        forecast = self.service.response()
        for point in forecast["points"]:
            point.update(p10=-10., p50=0., p90=10.)
        history = json.loads(store.history_for(forecast).to_json())
        self.assertEqual(len(history["points"]), 40)
        self.assertEqual(history["metrics"], {
            "total_quarters": 40, "matched_price_count": 3, "missing_price_count": 37,
            "matched_direction_count": 3, "missing_direction_count": 37,
            "mae_p50": 50 / 3, "coverage_p10_p90": 2 / 3, "covered_price_count": 2,
        })
        self.assertEqual(history["points"][0]["actual_direction"], "up")
        self.assertIsNone(history["points"][3]["actual_imbalance_price"])
        self.assertEqual(history["points"][3]["actual_direction"], "none")
        self.assertEqual(history["comparison_mode"], "retrospective")
        self.assertNotIn(PRIVATE_SENTINEL, json.dumps(history) + repr(store))
        self.assertNotIn("spot_price", json.dumps(history))
        self.assertNotIn("first_usable_origin_utc", json.dumps(history))

    def test_all_missing_and_tail_outcomes_preserve_40_rows_with_null_metrics(self):
        self.write_actuals([])
        store = load_actuals(self.history_config)
        empty = store.history_for(self.service.response())
        self.assertEqual(len(empty.points), 40)
        self.assertEqual(empty.metrics.matched_price_count, 0)
        self.assertIsNone(empty.metrics.mae_p50)
        self.assertIsNone(empty.metrics.coverage_p10_p90)
        self.assertNotIn("NaN", empty.to_json())
        origin = RunConfig.test().fit_cutoff_utc - timedelta(hours=1)
        self.write_actuals([[utc_text(origin), "1.23456789", "none"]])
        store = load_actuals(self.history_config)
        forecast = self.service.response()
        forecast["forecast_origin_utc"] = utc_text(origin)
        for index, point in enumerate(forecast["points"]):
            point["forecast_origin_utc"] = utc_text(origin)
            point["delivery_start_utc"] = utc_text(origin + timedelta(minutes=15 * index))
        tail = store.history_for(forecast)
        self.assertEqual(tail.points[0].actual_imbalance_price, 1.23456789)
        self.assertTrue(all(point.actual_imbalance_price is None for point in tail.points[1:]))
        self.assertEqual(tail.metrics.missing_price_count, 39)
        self.assertEqual([point.step for point in tail.points], list(range(1, 41)))

    def test_bad_source_rejected_atomically_without_private_diagnostics(self):
        valid = [utc_text(DEFAULT_ORIGIN), "-5.123456789", "up"]
        bad_rows = [
            [valid, valid],
            [["2026-09-06T21:01:00Z", "1", "up"]],
            [["2026-09-06T21:00:00", "1", "up"]],
            [["2026-09-06T21:00:00.000Z", "1", "up"]],
            [["2026-10-04T21:00:00Z", "1", "up"]],
            [["2026-09-06T20:45:00Z", "1", "up"]],
            [[valid[0], "nan", "up"]], [[valid[0], "inf", "up"]],
            [[valid[0], PRIVATE_SENTINEL, "up"]], [[valid[0], "1", PRIVATE_SENTINEL]],
        ]
        for rows in bad_rows:
            self.write_actuals(rows)
            with self.subTest(rows=rows), self.assertRaises(HistoryUnavailableError) as error:
                load_actuals(self.history_config)
            self.assertNotIn(PRIVATE_SENTINEL, "".join(traceback.format_exception(error.exception)))
        pd.DataFrame({"delivery_start_utc": [valid[0]], "spot_price": [PRIVATE_SENTINEL]}).to_csv(self.history_config.actuals_path, index=False)
        with self.assertRaises(HistoryUnavailableError):
            load_actuals(self.history_config)
        for name in ("actuals_test.csv", "inputs.csv", "spot_nordpool.csv"):
            with self.assertRaises(ValueError):
                HistoryConfig(self.directory / name)

    def test_forecast_routes_and_rejected_history_queries_do_not_load_outcomes(self):
        with patch("backend.app.main.load_actuals", side_effect=AssertionError) as loader:
            with TestClient(self.app()) as client:
                for path in ("/api/health", "/api/origins", "/api/forecast", "/docs", "/openapi.json"):
                    self.assertEqual(client.get(path).status_code, 200)
                operation = client.get("/openapi.json").json()["paths"]["/api/history"]["get"]
                self.assertEqual(set(operation["responses"]), {"200", "400", "404", "500", "503"})
                parameters = operation["parameters"]
                self.assertEqual(parameters[0]["name"], "origin")
                self.assertTrue(parameters[0]["required"])
                for query in ("", "?origin=", "?origin=bad", "?origin=2026-09-06T21:15:00Z",
                              "?origin=2026-09-06T21:00:00Z&origin=bad", "?path=private",
                              "?origin=2026-09-06T21:00:00Z&model=private"):
                    self.assertEqual(client.get("/api/history" + query).status_code, 400)
                self.assertEqual(client.get("/api/history?origin=2026-09-06T23:00:00Z").status_code, 404)
                self.assertIsNone(client.app.state.actuals_store)
                loader.assert_not_called()

    def test_concurrent_history_requests_load_once_cache_metadata_and_never_refit(self):
        self.write_actuals([[utc_text(self.origins[1]), "10", "down"]])
        app = self.app()
        original = self.service.response_json()
        with patch("backend.app.main.load_actuals", wraps=load_actuals) as loader:
            with TestClient(app) as client:
                def retrieve(origin):
                    return client.get("/api/history", params={"origin": utc_text(origin)})
                with ThreadPoolExecutor(max_workers=4) as executor:
                    responses = list(executor.map(retrieve, self.origins * 4))
                loader.assert_called_once_with(self.history_config)
                for response in responses:
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    self.assertNotIn(PRIVATE_SENTINEL, response.text)
                first, second = responses[0].json(), responses[1].json()
                for key in ("run_id", "model_id", "predictor_id", "engine_revision", "generated_at_utc", "fit_cutoff_utc"):
                    self.assertEqual(first[key], self.service.response()[key])
                    self.assertEqual(second[key], first[key])
                self.assertEqual(first["actuals_snapshot_id"], second["actuals_snapshot_id"])
                self.assertEqual(first["points"][4], {"delivery_start_utc": utc_text(self.origins[1]), "step": 5,
                                                       "actual_imbalance_price": 10., "actual_direction": "down"})
                self.assertEqual(second["points"][0]["actual_imbalance_price"], 10.)
                self.assertNotEqual(first["metrics"]["mae_p50"], second["metrics"]["mae_p50"])
                self.assertEqual(first["metrics"]["coverage_p10_p90"], 0.)
                self.assertEqual(second["metrics"]["coverage_p10_p90"], 1.)
                for index, response in enumerate(responses):
                    self.assertEqual(response.json(), (first, second)[index % 2])
                self.assertEqual(client.get("/api/forecast").json(), json.loads(original))
        self.assertIsNone(app.state.actuals_store)
        self.assertEqual(app.state.history_cache, {})
        self.predictor.fit.assert_called_once_with(self.data, config=RunConfig.validation())
        self.fitted.predict.assert_called_once()

    def test_missing_actuals_does_not_stop_forecasts_and_load_failure_can_be_retried(self):
        app = self.app()
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/forecast").status_code, 200)
            failed = client.get("/api/history", params={"origin": utc_text(DEFAULT_ORIGIN)})
            self.assertEqual(failed.status_code, 503)
            self.assertIsNone(app.state.actuals_store)
            self.assertEqual(client.get("/api/health").status_code, 200)
            self.write_actuals([[utc_text(DEFAULT_ORIGIN), "0", "none"]])
            self.assertEqual(client.get("/api/history", params={"origin": utc_text(DEFAULT_ORIGIN)}).status_code, 200)
        self.assertEqual(client.get("/api/history", params={"origin": utc_text(DEFAULT_ORIGIN)}).status_code, 503)

    def test_new_lifespan_refreshes_actuals_snapshot_without_mutating_forecast(self):
        self.write_actuals([[utc_text(DEFAULT_ORIGIN), "1", "none"]])
        app = self.app()
        with TestClient(app) as client:
            first = client.get("/api/history", params={"origin": utc_text(DEFAULT_ORIGIN)}).json()
            self.write_actuals([[utc_text(DEFAULT_ORIGIN), "2", "up"]])
            self.assertEqual(client.get("/api/history", params={"origin": utc_text(DEFAULT_ORIGIN)}).json(), first)
        with TestClient(app) as client:
            second = client.get("/api/history", params={"origin": utc_text(DEFAULT_ORIGIN)}).json()
        self.assertNotEqual(first["actuals_snapshot_id"], second["actuals_snapshot_id"])
        self.assertEqual(second["points"][0]["actual_imbalance_price"], 2.)
        self.assertEqual(first["run_id"], second["run_id"])

    def test_history_response_allowlist_and_unexpected_errors_are_sanitized(self):
        self.write_actuals([[utc_text(DEFAULT_ORIGIN), "0", "none"]])
        app = self.app()
        with TestClient(app) as client:
            path = "/api/history?origin=" + utc_text(DEFAULT_ORIGIN)
            payload = client.get(path).json()
            self.assertEqual(set(payload["points"][0]), {"delivery_start_utc", "step", "actual_imbalance_price", "actual_direction"})
            payload["spot_price"] = PRIVATE_SENTINEL
            payload["points"][0]["private_source"] = PRIVATE_SENTINEL
            app.state.history_cache[DEFAULT_ORIGIN] = json.dumps(payload)
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(PRIVATE_SENTINEL, response.text)
            payload["points"][0]["actual_direction"] = PRIVATE_SENTINEL
            app.state.history_cache[DEFAULT_ORIGIN] = json.dumps(payload)
            self.assertEqual(client.get(path).status_code, 500)
            app.state.history_cache.clear()
            stdout, stderr = StringIO(), StringIO()
            with patch.object(ActualsStore, "history_for", side_effect=ValueError(PRIVATE_SENTINEL)), redirect_stdout(stdout), redirect_stderr(stderr):
                failed = client.get(path)
            self.assertEqual(failed.status_code, 500)
            self.assertNotIn(PRIVATE_SENTINEL, failed.text + stdout.getvalue() + stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
