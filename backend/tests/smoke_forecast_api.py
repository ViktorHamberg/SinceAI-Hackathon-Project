"""Explicit real-data HTTP acceptance on an ephemeral loopback port; never prints prices.

Run from the repository root: python -m backend.tests.smoke_forecast_api --data-dir data
Starts one temporary Uvicorn server, verifies it and shuts it down before returning.
"""

import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import socket
import sys
import threading
import time
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

from backend.app.config import ForecastConfig, HistoryConfig
from backend.app.actuals import HISTORY_COLUMNS
from backend.app.forecast_service import prepare_forecast
from backend.app.main import create_app
from backend.app.schemas import utc_text
from urllib.parse import urlencode


def _require(condition: bool) -> None:
    # Verification must also run if Python is invoked with -O.
    if not condition:
        raise RuntimeError("HTTP acceptance check failed.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--include-history", action="store_true",
                        help="Also verify retrospective validation outcomes using only the three approved columns.")
    args = parser.parse_args(argv)
    server, thread, listener = None, None, None
    stage = "configuration"
    report = None
    try:
        import pandas as pd
        import uvicorn
        from forecast_engine.models import FittedPersistence, PersistencePredictor

        config = ForecastConfig.from_data_dir(args.data_dir)
        history_config = HistoryConfig.from_data_dir(args.data_dir) if args.include_history else None
        source_paths = [config.inputs_path, config.spot_path]
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths]
        read_csv = pd.read_csv
        fit, predict = PersistencePredictor.fit, FittedPersistence.predict
        reads, services = [], []

        def guarded_read(path, *args, **kwargs):
            actual = Path(path).resolve()
            _require(actual in source_paths or history_config is not None and actual == history_config.actuals_path)
            if actual not in source_paths:
                _require(kwargs.get("usecols") == list(HISTORY_COLUMNS))
            reads.append(actual)
            return read_csv(path, *args, **kwargs)

        def factory():
            service = prepare_forecast(config)
            services.append(service)
            return service

        stage = "binding loopback"
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        application = create_app(service_factory=factory, history_config=history_config)
        server = uvicorn.Server(uvicorn.Config(
            application, host="127.0.0.1", port=port,
            access_log=False, log_level="warning", lifespan="on",
        ))
        stage = "server startup"
        started = time.perf_counter()
        with patch("pandas.read_csv", side_effect=guarded_read), \
             patch.object(PersistencePredictor, "fit", autospec=True, side_effect=fit) as fit_calls, \
             patch.object(FittedPersistence, "predict", autospec=True, side_effect=predict) as predict_calls:
            thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            thread.start()
            deadline = started + 180
            while not server.started:
                _require(thread.is_alive() and time.perf_counter() < deadline)
                time.sleep(.05)
            startup_seconds = time.perf_counter() - started
            _require(len(services) == 1)
            service = services[0]
            opener = build_opener(ProxyHandler({}))

            def get(path, expected=200):
                try:
                    response = opener.open(f"http://127.0.0.1:{port}{path}", timeout=10)
                except HTTPError as error:
                    response = error
                with response:
                    _require(response.status == expected)
                    _require(response.headers.get("Cache-Control") == "no-store")
                    return response.read().decode("utf-8")

            stage = "HTTP response checks"
            _require(json.loads(get("/api/health")) == {"status": "ready"})
            raw = get("/api/forecast")
            payload = json.loads(raw)
            _require(payload == service.response())
            frame = service._result.forecasts  # Verification only, never an HTTP field.
            catalog = json.loads(get("/api/origins"))
            _require(catalog == service.origins_response())
            _require(catalog["origins"] == [utc_text(origin) for origin in config.origins])
            _require(catalog["default_origin_utc"] == payload["forecast_origin_utc"])
            _require(len(frame) == len(config.origins) * 40)
            request_seconds = []
            for origin in config.origins:
                path = "/api/forecast?" + urlencode({"origin": utc_text(origin)})
                requested = time.perf_counter()
                body = get(path)
                request_seconds.append(time.perf_counter() - requested)
                selected = json.loads(body)
                _require(selected == service.response(origin))
                for key in ("schema_version", "run_id", "model_id", "predictor_id", "engine_revision",
                            "generated_at_utc", "fit_cutoff_utc"):
                    _require(selected[key] == catalog[key])
                rows = frame.loc[frame["forecast_origin_utc"].eq(origin)]
                _require(len(selected["points"]) == len(rows) == 40)
                for point, row in zip(selected["points"], rows.itertuples(index=False)):
                    for name in ("forecast_origin_utc", "delivery_start_utc"):
                        _require(pd.Timestamp(point[name]) == getattr(row, name))
                    _require(point["step"] == row.step)
                    for name in ("p10", "p50", "p90", "p_up", "p_down", "p_none", "p_spike_high", "p_spike_low"):
                        _require(point[name] == getattr(row, name))
                _require("spot_price" not in body and "dependencies" not in body)
                _require(get(path) == body)
            _require("spot_price" not in raw and "dependencies" not in raw)
            for _ in range(3):
                _require(json.loads(get("/api/forecast")) == payload)
            _require(fit_calls.call_count == predict_calls.call_count == 1)
            _require(reads == source_paths)
            _require("swagger-ui" in get("/docs"))
            schema = json.loads(get("/openapi.json"))
            _require(set(schema["paths"]) == {"/api/forecast", "/api/health", "/api/origins", "/api/history"})
            get("/api/forecast?origin=2026-09-07T00:00:00Z", 404)
            get("/api/forecast?origin=invalid", 400)
            get("/data/spot_nordpool.csv", 404)
            history_report = {}
            if args.include_history:
                stage = "retrospective comparison"
                _require(application.state.actuals_store is None)
                default_before = service.response_json()
                snapshots = []
                for origin in config.origins:
                    path = "/api/history?" + urlencode({"origin": utc_text(origin)})
                    body = get(path)
                    history = json.loads(body)
                    forecast = service.response(origin)
                    _require(history["comparison_mode"] == "retrospective")
                    _require(len(history["points"]) == 40)
                    for key in ("run_id", "model_id", "predictor_id", "engine_revision", "generated_at_utc",
                                "forecast_origin_utc", "fit_cutoff_utc"):
                        _require(history[key] == forecast[key])
                    _require(get(path) == body)
                    _require("spot_price" not in body and "first_usable_origin_utc" not in body)
                    snapshots.append((history, forecast))
                _require(reads == source_paths + [history_config.actuals_path])
                # Independent reference read also excludes spot at ingestion.
                reference = guarded_read(history_config.actuals_path, usecols=list(HISTORY_COLUMNS),
                                         dtype=str, keep_default_na=False)
                reference["delivery_start_utc"] = pd.to_datetime(reference["delivery_start_utc"], utc=True)
                reference = reference.set_index("delivery_start_utc")
                for history, forecast in snapshots:
                    errors, covered, directions = [], 0, 0
                    for point, predicted in zip(history["points"], forecast["points"]):
                        _require(point["delivery_start_utc"] == predicted["delivery_start_utc"] and point["step"] == predicted["step"])
                        delivery = pd.Timestamp(point["delivery_start_utc"])
                        actual = reference.loc[delivery] if delivery in reference.index else None
                        price = float(actual["imbalance_price"]) if actual is not None and actual["imbalance_price"].strip() else None
                        direction = actual["direction"].strip().lower() or None if actual is not None else None
                        _require(point["actual_imbalance_price"] == price and point["actual_direction"] == direction)
                        if price is not None:
                            errors.append(abs(price - predicted["p50"]))
                            covered += int(predicted["p10"] <= price <= predicted["p90"])
                        directions += int(direction is not None)
                    n = len(errors)
                    _require(history["metrics"] == {
                        "total_quarters": 40, "matched_price_count": n, "missing_price_count": 40 - n,
                        "matched_direction_count": directions, "missing_direction_count": 40 - directions,
                        "mae_p50": math.fsum(errors) / n if n else None,
                        "coverage_p10_p90": covered / n if n else None, "covered_price_count": covered,
                    })
                _require(len({history["actuals_snapshot_id"] for history, _ in snapshots}) == 1)
                _require(service.response_json() == default_before)
                _require(fit_calls.call_count == predict_calls.call_count == 1)
                history_report = {
                    "history_origins": len(snapshots), "history_rows": len(snapshots) * 40,
                    "history_values_and_metrics_match": True, "history_uses_three_columns_only": True,
                    "application_actuals_reads": 1, "independent_reference_actuals_reads": 1,
                    "shared_actuals_snapshot": True, "forecast_unchanged_after_history": True,
                }
        stage = "input integrity"
        _require(before == [hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths])
        report = {
            "status": "pass", "transport": "HTTP over ephemeral 127.0.0.1 port",
            "forecast_rows": len(frame), "fit_calls": 1, "predict_calls": 1,
            "forecast_origins": len(config.origins), "cached_json_bytes": service.cached_json_bytes,
            "forecast_table_bytes": int(frame.memory_usage(index=True, deep=True).sum()),
            "memory_scope": "Serialized cache and forecast table only; excludes fitted state and provenance.",
            "selection_HTTP_max_seconds": round(max(request_seconds), 4),
            "source_csv_reads": sum(path in source_paths for path in reads),
            "actuals_reads": sum(path not in source_paths for path in reads),
            "required_values_match_engine": True, "repeated_HTTP_response_equal": True,
            "input_hashes_unchanged": True, "docs_and_openapi": "pass",
            "unsupported_origin_rejected": True, "data_route_absent": True,
            "run_id": payload["run_id"], "model_id": payload["model_id"],
            "engine_revision": payload["engine_revision"],
            "preparation_seconds": round(service.preparation_seconds, 3),
            "server_startup_seconds": round(startup_seconds, 3),
            "python": sys.version.split()[0],
            "dependencies": {name: importlib.metadata.version(name) for name in (
                "forecast-engine", "pandas", "numpy", "fastapi", "uvicorn", "httpx2", "starlette", "pydantic",
            )},
            **history_report,
        }
    except Exception as error:
        print(f"HTTP smoke failed during {stage} ({type(error).__name__}).", file=sys.stderr)
        return 1
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=15)
        if listener is not None:
            listener.close()
    if thread is not None and thread.is_alive():
        print("HTTP smoke failed to stop its temporary server.", file=sys.stderr)
        return 1
    _require(application.state.forecast_service is None)
    report["server_shutdown"] = "pass"
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
