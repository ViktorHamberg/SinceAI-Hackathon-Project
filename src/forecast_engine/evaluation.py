"""Local workflow, official-tool adapters and value-free reproducibility records.

No model algorithm, metric formula, notebook execution or prediction I/O lives here.
Scoring actuals are passed only to the external scorer after forecasts are exported.
"""

from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from .config import RunConfig
from .contracts import FORECAST_COLUMNS
from .data import load_inputs
from .engine import forecast
from .models import PersistencePredictor
from .submission import export_forecasts


class WorkflowError(RuntimeError):
    """A safe workflow diagnostic, with no raw input or subprocess error values."""


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_record(path):
    return {"path": str(path), "sha256": _sha256(path)}


def _git_state(package_dir):
    try:
        revision = subprocess.run(["git", "-C", str(package_dir), "rev-parse", "HEAD"], capture_output=True, text=True)
        status = subprocess.run(["git", "-C", str(package_dir), "status", "--porcelain"], capture_output=True, text=True)
        if revision.returncode or status.returncode:
            return {"available": False}
        return {"available": True, "commit": revision.stdout.strip(), "dirty": bool(status.stdout),
                "status_sha256": hashlib.sha256(status.stdout.encode()).hexdigest()}
    except OSError:
        return {"available": False}


def _environment():
    versions = {}
    for name in ("forecast-engine", "pandas", "numpy", "pyarrow", "requests", "tzdata", "setuptools", "wheel"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    package = Path(__file__).resolve().parent
    return {"python": sys.version, "executable": sys.executable, "dependencies": versions,
            "git": _git_state(package),
            "package_sources_sha256": _package_fingerprints()}


def _package_fingerprints():
    package = Path(__file__).resolve().parent
    return {str(p.relative_to(package)): _sha256(p) for p in sorted(package.rglob("*.py"))}


def _expected_origins(mode):
    import pandas as pd

    first = RunConfig.validation().fit_cutoff_utc if mode == "validation" else RunConfig.test().fit_cutoff_utc
    last = (pd.Timestamp(RunConfig.test().fit_cutoff_utc) - pd.Timedelta(hours=1)
            if mode == "validation" else pd.Timestamp("2026-11-01T21:00:00Z"))
    return pd.date_range(first, last, freq="h")


def _read_request(origins_path, template_path, mode):
    import numpy as np
    import pandas as pd

    origins = pd.read_csv(origins_path, dtype="string", keep_default_na=False)
    template = pd.read_csv(template_path, dtype="string", keep_default_na=False)
    if list(origins.columns) != ["forecast_origin_utc"] or tuple(template.columns) != FORECAST_COLUMNS:
        raise WorkflowError("origins/template schema does not match the official files")

    def timestamps(series):
        if not series.str.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|\+00:00)").all():
            raise WorkflowError("origins/template requires nonmissing whole-second UTC timestamps")
        return pd.to_datetime(series, utc=True, format="mixed")

    requested = pd.DatetimeIndex(timestamps(origins.forecast_origin_utc)).as_unit("ns")
    expected = _expected_origins(mode).as_unit("ns")
    if not requested.equals(expected):
        raise WorkflowError("origins do not match the complete official period")
    if len(template) != len(expected) * 40 or not template[list(FORECAST_COLUMNS[3:])].eq("").all().all():
        raise WorkflowError("template must contain complete empty forecast horizons")
    steps = pd.to_numeric(template.step, errors="raise")
    if not pd.api.types.is_integer_dtype(steps.dtype):
        raise WorkflowError("template steps must be integers")
    repeated = pd.Series(expected.repeat(40))
    expected_steps = np.tile(np.arange(1, 41), len(expected))
    deliveries = repeated + pd.to_timedelta((expected_steps - 1) * 15, unit="min")
    if not (timestamps(template.forecast_origin_utc).eq(repeated).all()
            and np.array_equal(steps.to_numpy(), expected_steps)
            and timestamps(template.delivery_start_utc).eq(deliveries).all()):
        raise WorkflowError("template identifiers do not match the official origin/step grid")
    return list(requested)


def _run_tool(label, script, arguments, starter, output, manifest):
    command = [sys.executable, str(script), *map(str, arguments)]
    record = {"tool": label, "command": command, "cwd": str(starter), "exit_code": None}
    manifest["official_commands"].append(record)
    started = time.perf_counter()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "SINCEAI_ORGANIZER": "0"}
    try:
        completed = subprocess.run(command, cwd=starter, env=env, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace")
        record["exit_code"] = completed.returncode
        # Error output may contain individual values or parser excerpts. Store only
        # fixed-format statuses/counts/finding codes, never raw stdout or stderr.
        record["summary"] = [line for line in completed.stdout.splitlines() if re.fullmatch(
            r"(?:VALIDATION (?:PASSED|FAILED)|(?:Rows|Forecast origins): \d+(?: / \d+)?|"
            r"(?:Errors|Warnings|Template rows): \d+|(?:ERROR|WARNING) \[[A-Z_]+\])", line)]
        record["stderr_present"] = bool(completed.stderr)
    except OSError:
        record["launch_failed"] = True
    record["elapsed_seconds"] = time.perf_counter() - started
    report = output / f"official_{label}.json"
    report.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    record["report"] = str(report)
    manifest["artifacts"][f"official_{label}_report"] = str(report)
    if record["exit_code"] != 0:
        raise WorkflowError(f"official {label} failed (exit code {record['exit_code']}); see its safe JSON report")


def _safe_provenance(result):
    fitted = result.provenance.fitting
    lineage = hashlib.sha256()
    source_count = 0
    for evidence in fitted.dependencies:
        lineage.update((evidence.name + "\0" + evidence.used_at_utc.isoformat() + "\0").encode())
        for source in evidence.sources:
            record = (source.series_id, source.timestamp_utc.isoformat(),
                      source.first_usable_origin_utc.isoformat(), source.used_at_utc.isoformat())
            lineage.update(("\0".join(record) + "\n").encode())
            source_count += 1
    return {"predictor": fitted.predictor_id, "counts": dict(fitted.counts),
            "max_fitting_availability_utc": fitted.max_first_usable_origin_utc.isoformat(),
            "latest_fitting_label_delivery_utc": fitted.latest_label_delivery_utc.isoformat(),
            "fitting_source_uses": source_count, "fitting_lineage_sha256": lineage.hexdigest(),
            "inference": [{"origin_utc": p.forecast_origin_utc.isoformat(),
                           "max_availability_utc": p.max_first_usable_origin_utc.isoformat(),
                           "source_timestamps_utc": {k: v.isoformat() for k, v in p.source_timestamps_utc.items()},
                           "source_ages_seconds": {k: v.total_seconds() for k, v in p.source_ages.items()}}
                          for p in result.provenance.inference]}


def run_workflow(mode, *, starter_dir, data_dir=None, output_dir=None,
                 inputs_file=None, spot_file=None, actuals_file=None, argv=()):
    """Fit/predict with the shared API, then run official scripts outside the core.

    Require a fresh output directory to prevent stale results or starter overwrites.
    Error manifests use only safe phase/type diagnostics; raw exceptions are not logged.
    """
    if mode not in {"validation", "test"} or (mode == "test" and actuals_file is not None):
        raise WorkflowError("choose validation or test; test mode cannot receive actuals")
    starter = Path(starter_dir).resolve()
    data_dir = Path(data_dir).resolve() if data_dir is not None else starter / "data"
    output = Path(output_dir).resolve() if output_dir is not None else starter / "baseline_output" / "engine" / mode
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise WorkflowError("output directory must be new or empty; existing runs are not overwritten")
    try:
        output.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise WorkflowError("cannot create output directory") from None
    config = RunConfig.validation() if mode == "validation" else RunConfig.test()
    manifest = {"mode": mode, "status": "running", "stage": "preflight",
                "started_utc": datetime.now(timezone.utc).isoformat(),
                "command": [sys.executable, "-m", "forecast_engine", *argv],
                "arguments": {"starter_dir": str(starter), "data_dir": str(data_dir), "output_dir": str(output)},
                "config": {key: getattr(config, key).isoformat() for key in ("label_start_utc", "label_end_utc", "fit_cutoff_utc")},
                "consumed_files": {}, "starter_files": {}, "official_commands": [],
                "artifacts": {"manifest": str(output / "run_manifest.json")}}
    started = time.perf_counter()
    try:
        inputs = Path(inputs_file).resolve() if inputs_file else data_dir / "inputs.csv"
        spot = Path(spot_file).resolve() if spot_file else data_dir / "spot_nordpool.csv"
        actuals = (Path(actuals_file).resolve() if actuals_file else data_dir / "actuals_validation.csv") if mode == "validation" else None
        if any(path.stem.lower().startswith("actuals") for path in (inputs, spot)):
            raise WorkflowError("scoring actuals cannot be supplied as forecasting inputs")
        if actuals is not None and actuals.stem.lower().startswith("actuals_test"):
            raise WorkflowError("test actuals cannot be supplied to validation scoring")
        required = {"inputs": inputs, "spot": spot, "validator": starter / "validate_submission.py"}
        if mode == "validation":
            required.update(generator=starter / "make_templates.py", scorer=starter / "score.py", validation_actuals=actuals)
        else:
            required.update(origins=starter / "forecast_origins.csv", template=starter / "sample_submission.csv")
        for label, path in required.items():
            if not path.is_file():
                raise WorkflowError(f"missing required {label} file")
        manifest["environment"] = _environment()
        for name in ("README.md", "requirements.txt", "pyproject.toml", "availability.csv", "baseline.ipynb", ".gitignore", ".gitattributes",
                     "make_templates.py", "validate_submission.py", "score.py", "forecast_origins.csv", "sample_submission.csv"):
            path = starter / name
            if path.is_file():
                manifest["starter_files"][name] = _file_record(path)
        for label, path in (("inputs", inputs), ("spot", spot)):
            manifest["consumed_files"][label] = _file_record(path)
            manifest["arguments"][f"{label}_file"] = str(path)
        origins_path, template_path = output / "forecast_origins.csv", output / "sample_submission.csv"
        manifest["stage"] = "templates"
        if mode == "validation":
            _run_tool("templates", required["generator"], ["--test-start", "2026-09-07", "--test-end", "2026-10-04",
                      "--timezone", "Europe/Helsinki", "--output-dir", output], starter, output, manifest)
        else:
            shutil.copyfile(required["origins"], origins_path)
            shutil.copyfile(required["template"], template_path)
        requested = _read_request(origins_path, template_path, mode)
        manifest["consumed_files"].update(origins=_file_record(origins_path), template=_file_record(template_path))
        manifest["origin_count"] = len(requested)
        manifest["stage"] = "load"
        loaded = load_inputs(inputs, spot_path=spot)
        manifest["input_row_counts"] = {"series": len(loaded.series), "spot": len(loaded.spot)}
        manifest["stage"] = "fit"
        fitted = PersistencePredictor().fit(loaded, config=config)
        manifest["stage"] = "predict"
        result = forecast(fitted, loaded, origins=requested)
        manifest["provenance"] = _safe_provenance(result)
        manifest["forecast_rows"] = len(result.forecasts)
        manifest["stage"] = "export"
        submission = export_forecasts(result.forecasts, output / "forecast_backtest.csv", origins=requested)
        manifest["artifacts"].update(submission=str(submission), origins=str(origins_path), template=str(template_path))
        manifest["stage"] = "validate"
        _run_tool("validation", required["validator"], ["--backtest", submission, "--origins", origins_path], starter, output, manifest)
        if mode == "validation":
            manifest["stage"] = "score"
            # First actuals-byte access is here, after prediction/export/validation.
            manifest["consumed_files"]["validation_actuals"] = _file_record(actuals)
            manifest["arguments"]["actuals_file"] = str(actuals)
            score_dir = output / "score"
            _run_tool("scoring", required["scorer"], ["--submission", submission, "--actuals", actuals,
                      "--spike-margin", "50", "--output-dir", score_dir], starter, output, manifest)
            for name in ("score_summary.csv", "score_summary.md", "score_by_horizon.csv"):
                path = score_dir / name
                if not path.is_file():
                    raise WorkflowError("official scorer did not create the expected score artifacts")
                manifest["artifacts"][name] = str(path)
        manifest["stage"] = "integrity"
        for record in [*manifest["starter_files"].values(), *manifest["consumed_files"].values()]:
            if _sha256(record["path"]) != record["sha256"]:
                raise WorkflowError("a source input or original starter file changed during the run")
        if _package_fingerprints() != manifest["environment"]["package_sources_sha256"]:
            raise WorkflowError("package source files changed during the run")
        manifest["artifact_sha256"] = {name: _sha256(path) for name, path in manifest["artifacts"].items() if name != "manifest"}
        manifest["status"] = "complete"
        manifest["stage"] = "complete"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["failure"] = {"stage": manifest["stage"], "error_type": type(error).__name__}
        if isinstance(error, WorkflowError):
            raise
        raise WorkflowError(f"workflow failed during {manifest['stage']} ({type(error).__name__}); see run_manifest.json") from None
    finally:
        manifest["elapsed_seconds"] = time.perf_counter() - started
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (output / "run_manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return manifest
