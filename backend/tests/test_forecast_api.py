"""HTTP/lifespan checks use the real service boundary with invented engine results."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import traceback
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.app.config import ForecastConfig
from backend.app.forecast_service import ForecastPreparationError, ForecastService, prepare_forecast
from backend.app.main import create_app
from backend.tests.test_forecast_service import PRIVATE_SENTINEL, synthetic_result
from forecast_engine import ForecastInputs, RunConfig


class ForecastApiTests(unittest.TestCase):
    def setUp(self):
        self.result = synthetic_result()
        self.fitted = Mock(provenance=self.result.provenance.fitting)
        self.fitted.predict.return_value = self.result
        self.predictor = Mock()
        self.predictor.fit.return_value = self.fitted
        self.config = ForecastConfig(Path("invented inputs.csv"), Path("invented spot.csv"))
        self.services = []
        loader = patch("backend.app.forecast_service.load_inputs", return_value=ForecastInputs(None))
        self.loader = loader.start()
        self.addCleanup(loader.stop)

        def prepare():
            service = prepare_forecast(self.config, predictor=self.predictor, model_id="synthetic-v1")
            self.services.append(service)
            return service

        self.factory = Mock(side_effect=prepare)
        self.app = create_app(service_factory=self.factory)

    def test_lifespan_prepares_once_and_http_preserves_all_fields(self):
        self.factory.assert_not_called()
        with TestClient(self.app) as client:
            expected = self.services[0].response()
            for _ in range(3):
                response = client.get("/api/forecast")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["content-type"], "application/json")
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(response.json(), expected)
                self.assertNotIn(PRIVATE_SENTINEL, response.text)
                self.assertNotIn("spot_price", response.text)
            self.assertEqual(len(expected["points"]), 40)
            self.factory.assert_called_once_with()
            self.predictor.fit.assert_called_once()
            self.fitted.predict.assert_called_once()
            self.assertEqual(self.predictor.fit.call_args.kwargs["config"], RunConfig.validation())
        self.assertIsNone(self.app.state.forecast_service)

    def test_health_reports_readiness_only_and_has_no_forecast_values(self):
        with TestClient(self.app) as client:
            response = client.get("/api/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ready"})
            self.assertEqual(response.headers["cache-control"], "no-store")

    def test_without_lifespan_and_after_shutdown_routes_are_not_ready(self):
        client = TestClient(self.app)
        for path in ("/api/health", "/api/forecast"):
            self.assertEqual(client.get(path).status_code, 503)
        self.factory.assert_not_called()
        with client:
            self.assertEqual(client.get("/api/forecast").status_code, 200)
        self.assertEqual(client.get("/api/forecast").status_code, 503)

    def test_separate_lifespans_and_app_instances_do_not_reuse_stale_snapshots(self):
        with TestClient(self.app) as client:
            first = client.get("/api/forecast").json()
        with TestClient(self.app) as client:
            second = client.get("/api/forecast").json()
        other = create_app(service_factory=self.factory)
        with TestClient(other) as client:
            third = client.get("/api/forecast").json()
        self.assertEqual(len({r["run_id"] for r in (first, second, third)}), 3)
        self.assertEqual(self.factory.call_count, 3)
        self.assertIsNone(self.app.state.forecast_service)
        self.assertIsNone(other.state.forecast_service)

    def test_parallel_retrieval_has_one_run_and_no_engine_work(self):
        with TestClient(self.app) as client:
            with ThreadPoolExecutor(max_workers=4) as executor:
                responses = list(executor.map(lambda _: client.get("/api/forecast"), range(8)))
            self.assertTrue(all(r.status_code == 200 for r in responses))
            self.assertEqual(len({r.json()["run_id"] for r in responses}), 1)
            self.predictor.fit.assert_called_once()
            self.fitted.predict.assert_called_once()
            self.loader.assert_called_once()

    def test_query_parameters_are_rejected_instead_of_ignoring_an_origin(self):
        with TestClient(self.app) as client:
            for path in ("/api/forecast", "/api/health"):
                response = client.get(path, params={"origin": PRIVATE_SENTINEL})
                self.assertEqual(response.status_code, 400)
                self.assertNotIn(PRIVATE_SENTINEL, response.text)
                self.assertEqual(response.headers["cache-control"], "no-store")

    def test_no_file_routes_or_write_routes(self):
        with TestClient(self.app) as client:
            for path in ("/data/spot_nordpool.csv", "/baseline_output/test.json", "/api/files", "/api/origins"):
                self.assertEqual(client.get(path).status_code, 404)
            self.assertEqual(client.post("/api/forecast", json={"path": PRIVATE_SENTINEL}).status_code, 405)

    def test_openapi_reuses_existing_forecast_dataclasses_and_docs_are_available(self):
        with TestClient(self.app) as client:
            schema = client.get("/openapi.json")
            self.assertEqual(schema.status_code, 200)
            spec = schema.json()
            self.assertEqual(set(spec["paths"]), {"/api/forecast", "/api/health"})
            response_schema = spec["paths"]["/api/forecast"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
            self.assertEqual(response_schema["$ref"], "#/components/schemas/ForecastResponse")
            fields = spec["components"]["schemas"]["ForecastPoint"]["properties"]
            self.assertEqual(len(fields), 13)
            self.assertNotIn("spot_price", fields)
            self.assertNotIn(PRIVATE_SENTINEL, schema.text)
            docs = client.get("/docs")
            self.assertEqual(docs.status_code, 200)
            self.assertIn("swagger-ui", docs.text)

    def test_response_allowlist_filters_unexpected_fields(self):
        with TestClient(self.app) as client:
            payload = self.services[0].response()
            payload["spot_price"] = PRIVATE_SENTINEL
            payload["points"][0]["raw_source"] = PRIVATE_SENTINEL
            with patch.object(ForecastService, "response", return_value=payload):
                response = client.get("/api/forecast")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(PRIVATE_SENTINEL, response.text)
            self.assertNotIn("spot_price", response.text)
            self.assertNotIn("raw_source", response.text)

    def test_invalid_response_and_unexpected_retrieval_failures_are_sanitized(self):
        captured = []

        class Capture(logging.Handler):
            def emit(self, record):
                captured.append(self.format(record))

        handler = Capture()
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        stdout, stderr = StringIO(), StringIO()
        with TestClient(self.app) as client, redirect_stdout(stdout), redirect_stderr(stderr):
            payload = self.services[0].response()
            payload["points"][0]["p50"] = PRIVATE_SENTINEL
            with patch.object(ForecastService, "response", return_value=payload):
                invalid = client.get("/api/forecast")
            with patch.object(ForecastService, "response", side_effect=RuntimeError(PRIVATE_SENTINEL)):
                failed = client.get("/api/forecast")
            for response in (invalid, failed):
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertNotIn(PRIVATE_SENTINEL, response.text)
        self.assertNotIn(PRIVATE_SENTINEL, "\n".join(captured) + stdout.getvalue() + stderr.getvalue())

    def test_startup_failure_is_sanitized_and_publishes_no_partial_service(self):
        for failure in (RuntimeError(PRIVATE_SENTINEL), ForecastPreparationError(PRIVATE_SENTINEL)):
            factory = Mock(side_effect=failure)
            app = create_app(service_factory=factory)
            with self.subTest(failure=type(failure).__name__):
                with self.assertRaisesRegex(RuntimeError, "Forecast service could not start") as error:
                    with TestClient(app):
                        self.fail("failed startup must not yield a running app")
                self.assertNotIn(PRIVATE_SENTINEL, "".join(traceback.format_exception(error.exception)))
                self.assertIsNone(app.state.forecast_service)
                factory.assert_called_once()

    def test_default_composition_uses_real_preparation_function_once(self):
        service = self.factory()
        with patch("backend.app.main.prepare_forecast", return_value=service) as prepare:
            app = create_app(self.config)
            prepare.assert_not_called()
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/forecast").json(), service.response())
                client.get("/api/health")
            prepare.assert_called_once_with(self.config)
        with self.assertRaises(ValueError):
            create_app(self.config, service_factory=self.factory)

    def test_import_declares_app_without_engine_initialization_or_numeric_imports(self):
        script = textwrap.dedent('''
            import os,sys
            sys.path.insert(0,sys.argv[1])
            from backend.app import forecast_service
            def forbidden(*args,**kwargs):
                raise AssertionError("import initialized forecast service")
            forecast_service.prepare_forecast=forbidden
            def audit(event,args):
                if event=="open":
                    path,mode,flags=args
                    if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC):
                        raise AssertionError("import wrote a file")
                    if isinstance(path,(str,bytes)) and os.fsdecode(path).endswith((".csv",".parquet")):
                        raise AssertionError("import read a dataset")
                if event in {"subprocess.Popen","os.system","socket.connect","os.mkdir"}:
                    raise AssertionError("import did external work")
            sys.addaudithook(audit)
            from backend.app.main import app
            assert app.state.forecast_service is None
            assert "pandas" not in sys.modules and "numpy" not in sys.modules
            assert not os.listdir(".")
        ''')
        with tempfile.TemporaryDirectory() as directory:
            root = str(Path(__file__).resolve().parents[2])
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", script, root],
                                       cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout + completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
