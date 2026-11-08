"""Synthetic multi-origin service/API checks; no challenge datasets are loaded."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import traceback
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import pandas as pd
from fastapi.testclient import TestClient

from backend.app.config import DEFAULT_ORIGIN, DEFAULT_ORIGINS, ForecastConfig
from backend.app.forecast_service import ForecastPreparationError, prepare_forecast
from backend.app.main import create_app
from backend.app.schemas import utc_text
from backend.tests.test_forecast_service import PRIVATE_SENTINEL, synthetic_result
from forecast_engine import ForecastInputs, ForecastProvenance, ForecastResult, OriginProvenance, RunConfig


def synthetic_batch(origins):
    single = synthetic_result()
    frames, records = [], []
    for index, origin in enumerate(origins):
        frame = single.forecasts.copy()
        frame["forecast_origin_utc"] = pd.Series([origin] * 40, dtype="datetime64[ns, UTC]")
        frame["delivery_start_utc"] = pd.date_range(origin, periods=40, freq="15min")
        frame[["p10", "p50", "p90"]] += index
        frames.append(frame)
        records.append(OriginProvenance(origin, dependencies=single.provenance.inference[0].dependencies))
    return ForecastResult(pd.concat(frames, ignore_index=True),
                          ForecastProvenance(single.provenance.fitting, tuple(records)))


class OriginSelectionTests(unittest.TestCase):
    def test_default_replay_has_one_origin_per_day_across_validation(self):
        self.assertEqual(len(DEFAULT_ORIGINS), 28)
        self.assertEqual(DEFAULT_ORIGINS[0], RunConfig.validation().fit_cutoff_utc)
        self.assertEqual(DEFAULT_ORIGINS[-1], RunConfig.test().fit_cutoff_utc - timedelta(days=1))
        self.assertTrue(all(later - earlier == timedelta(days=1)
                            for earlier, later in zip(DEFAULT_ORIGINS, DEFAULT_ORIGINS[1:])))

    def setUp(self):
        self.config = ForecastConfig(Path("unused inputs.csv"), Path("unused spot.csv"))
        self.result = synthetic_batch(self.config.origins)
        self.data = ForecastInputs(pd.DataFrame({"spot_price": [PRIVATE_SENTINEL]}))
        self.fitted = Mock(provenance=self.result.provenance.fitting)
        self.fitted.predict.return_value = self.result
        self.predictor = Mock()
        self.predictor.fit.return_value = self.fitted
        loader = patch("backend.app.forecast_service.load_inputs", return_value=self.data)
        self.loader = loader.start()
        self.addCleanup(loader.stop)

    def prepare(self):
        return prepare_forecast(self.config, predictor=self.predictor, model_id="synthetic-v1")

    def test_one_fit_and_batch_prediction_preserve_each_origin_and_shared_identity(self):
        service = self.prepare()
        self.loader.assert_called_once_with(self.config.inputs_path, spot_path=self.config.spot_path)
        self.predictor.fit.assert_called_once_with(self.data, config=RunConfig.validation())
        self.fitted.predict.assert_called_once_with(self.data, origins=DEFAULT_ORIGINS)
        catalog = service.origins_response()
        self.assertEqual(set(catalog), {"schema_version", "run_id", "model_id", "predictor_id", "engine_revision",
                                        "generated_at_utc", "fit_cutoff_utc", "default_origin_utc", "origins"})
        self.assertEqual(catalog["origins"], [utc_text(origin) for origin in DEFAULT_ORIGINS])
        self.assertEqual(catalog["default_origin_utc"], utc_text(DEFAULT_ORIGIN))
        for index, origin in enumerate(DEFAULT_ORIGINS):
            response = service.response(origin)
            self.assertEqual(response["forecast_origin_utc"], utc_text(origin))
            self.assertEqual(len(response["points"]), 40)
            for key in ("schema_version", "run_id", "model_id", "predictor_id", "engine_revision",
                        "generated_at_utc", "fit_cutoff_utc"):
                self.assertEqual(response[key], catalog[key])
            for step, point in enumerate(response["points"], 1):
                self.assertEqual(point["step"], step)
                self.assertEqual(point["forecast_origin_utc"], utc_text(origin))
                self.assertEqual(point["delivery_start_utc"], utc_text(origin + timedelta(minutes=15 * (step - 1))))
                self.assertEqual(point["p50"], -11.987654321 + index)
        self.assertEqual(service.response(), service.response(DEFAULT_ORIGINS[0]))
        expected_bytes = sum(len(service.response_json(origin).encode()) for origin in DEFAULT_ORIGINS)
        self.assertGreater(service.cached_json_bytes, expected_bytes)

    def test_explicit_nearby_origins_preserve_distinct_forecasts_for_the_same_delivery(self):
        self.config = replace(self.config, origins=(DEFAULT_ORIGIN, DEFAULT_ORIGIN + timedelta(hours=1)))
        self.fitted.predict.return_value = synthetic_batch(self.config.origins)
        service = self.prepare()
        earlier, later = (service.response(origin) for origin in self.config.origins)
        self.assertEqual(earlier["points"][4]["delivery_start_utc"], later["points"][0]["delivery_start_utc"])
        self.assertNotEqual(earlier["points"][4]["p50"], later["points"][0]["p50"])

    def test_cache_and_catalog_are_detached_and_selection_never_runs_engine_work(self):
        service = self.prepare()
        originals = [service.response_json(origin) for origin in DEFAULT_ORIGINS]
        service.response()["points"].clear()
        service.origins_response()["origins"].clear()
        self.result.forecasts.loc[:, "p50"] = -22.
        with patch("backend.app.forecast_service.load_inputs", side_effect=AssertionError), \
             patch.object(self.predictor, "fit", side_effect=AssertionError), \
             patch.object(self.fitted, "predict", side_effect=AssertionError):
            with TestClient(create_app(service_factory=lambda: service)) as client:
                def retrieve(origin):
                    return client.get("/api/forecast", params={"origin": utc_text(origin)})
                with ThreadPoolExecutor(max_workers=4) as executor:
                    responses = list(executor.map(retrieve, DEFAULT_ORIGINS * 2))
                for index, response in enumerate(responses):
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), json.loads(originals[index % len(DEFAULT_ORIGINS)]))
                    self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(len(client.get("/api/origins").json()["origins"]), len(DEFAULT_ORIGINS))

    def test_query_validation_is_bounded_and_sanitized(self):
        service = self.prepare()
        with TestClient(create_app(service_factory=lambda: service)) as client:
            self.assertEqual(client.get("/api/forecast").json(), service.response())
            for origin in DEFAULT_ORIGINS:
                for text in (utc_text(origin), utc_text(origin).replace("Z", "+00:00")):
                    response = client.get("/api/forecast", params={"origin": text})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), service.response(origin))
            invalid = ["", PRIVATE_SENTINEL, "2026-09-06T21:00:00", "2026-09-07T00:00:00+03:00",
                       "2026-09-06T21:15:00Z", "2026-09-06T21:00:01Z", "2026-09-06T21:00:00.000Z",
                       "2026-09-31T21:00:00Z", "x" * 10000]
            for text in invalid:
                with self.subTest(origin=text[:30]):
                    response = client.get("/api/forecast", params={"origin": text})
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json(), {"detail": "Origin must be a full-hour UTC timestamp."})
            for text in ("2026-09-06T20:00:00Z", "2026-09-08T00:00:00Z", "2026-10-04T21:00:00Z"):
                response = client.get("/api/forecast", params={"origin": text})
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(text, response.text)
            duplicate = urlencode([("origin", utc_text(DEFAULT_ORIGIN)), ("origin", PRIVATE_SENTINEL)])
            for query in (duplicate, urlencode({"path": PRIVATE_SENTINEL}), "origin=&model=secret"):
                response = client.get("/api/forecast?" + query)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn(PRIVATE_SENTINEL, response.text)
            for path in ("/api/origins", "/api/health"):
                self.assertEqual(client.get(path, params={"origin": PRIVATE_SENTINEL}).status_code, 400)

    def test_catalog_has_only_safe_identity_and_origin_fields_with_readiness_and_schema(self):
        app = create_app(service_factory=self.prepare)
        client = TestClient(app)
        self.assertEqual(client.get("/api/origins").status_code, 503)
        with client:
            response = client.get("/api/origins")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertNotIn(PRIVATE_SENTINEL, response.text + repr(app.state.forecast_service))
            self.assertNotIn("spot_price", response.text)
            spec = client.get("/openapi.json").json()
            parameters = spec["paths"]["/api/forecast"]["get"]["parameters"]
            self.assertEqual(parameters[0]["name"], "origin")
            self.assertFalse(parameters[0]["required"])
            service = app.state.forecast_service
            bad = service.origins_response()
            bad["spot_price"] = PRIVATE_SENTINEL
            with patch.object(type(service), "origins_response", return_value=bad):
                self.assertNotIn(PRIVATE_SENTINEL, client.get("/api/origins").text)
            bad["origins"] = None
            with patch.object(type(service), "origins_response", return_value=bad):
                failed = client.get("/api/origins")
                self.assertEqual(failed.status_code, 500)
                self.assertNotIn(PRIVATE_SENTINEL, failed.text)
        self.assertEqual(client.get("/api/origins").status_code, 503)

    def test_incomplete_or_extra_batch_origin_prevents_startup_without_partial_cache(self):
        for frame in (self.result.forecasts.iloc[:-1], self.result.forecasts.iloc[40:],
                      pd.concat([self.result.forecasts, self.result.forecasts.iloc[:40]])):
            self.fitted.predict.return_value = replace(self.result, forecasts=frame)
            with self.subTest(rows=len(frame)), self.assertRaises(ForecastPreparationError):
                self.prepare()
        with patch("backend.app.forecast_service.build_response", side_effect=ValueError(PRIVATE_SENTINEL)):
            self.fitted.predict.return_value = self.result
            with self.assertRaises(ForecastPreparationError) as error:
                self.prepare()
            self.assertEqual(error.exception.stage, "response serialization")
            self.assertNotIn(PRIVATE_SENTINEL, "".join(traceback.format_exception(error.exception)))


class OriginConfigurationTests(unittest.TestCase):
    def test_normalizes_sorts_and_bounds_local_configuration(self):
        local = DEFAULT_ORIGIN.astimezone(timezone(timedelta(hours=3)))
        config = ForecastConfig(Path("inputs"), Path("spot"), (DEFAULT_ORIGINS[1], local))
        self.assertEqual(config.origins, DEFAULT_ORIGINS[:2])
        self.assertEqual(config.origins[0].tzinfo, timezone.utc)
        for origins in ((), DEFAULT_ORIGINS + (DEFAULT_ORIGIN + timedelta(hours=2),),
                        (DEFAULT_ORIGIN, local), (DEFAULT_ORIGIN.replace(tzinfo=None),),
                        (DEFAULT_ORIGIN + timedelta(minutes=15),), (RunConfig.test().fit_cutoff_utc,),
                        (DEFAULT_ORIGIN - timedelta(hours=1),), (pd.NaT,), ("2026-09-06T21:00:00Z",)):
            with self.subTest(origins=origins), self.assertRaises(ValueError):
                ForecastConfig(Path("inputs"), Path("spot"), origins)


if __name__ == "__main__":
    unittest.main()
