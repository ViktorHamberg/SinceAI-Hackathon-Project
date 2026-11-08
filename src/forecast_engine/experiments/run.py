"""Fit once, predict, validate, then score. No work or heavy imports on import.

Uses existing internal evaluation adapters for hashing, safe provenance and official
subprocess reports; numerical metrics are computed exclusively by unchanged score.py.
The existing evaluation.run_workflow and CLI are not modified. Runtime artifacts,
especially generated fold actuals containing restricted spot data, must stay private.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
import time

from .. import evaluation
from ..availability import select_fitting_labels
from ..config import RunConfig
from ..data import load_inputs
from ..engine import forecast
from ..features.training import ChronologicalFold, expanding_window_folds
from ..models import PersistencePredictor
from ..submission import export_forecasts

METRICS = ("mae_p50", "calibration_pinball_mean", "brier_spike_mean", "brier_direction")
COUNTS = ("rows_in_submission", "rows_skipped_price", "rows_scored_price",
          "rows_scored_spike", "rows_scored_direction")


class ExperimentError(RuntimeError):
    """Fixed-format failure; source values and original exception text are suppressed."""


def _validation_origins():
    import pandas as pd

    return tuple(pd.date_range(RunConfig.validation().fit_cutoff_utc,
                               RunConfig.test().fit_cutoff_utc, inclusive="left", freq="h"))


def _read_scores(path):
    """Read only official aggregates; no metric implementations or raw CSV logging."""
    import pandas as pd

    summary = pd.read_csv(path, usecols=[*METRICS, *COUNTS, "coverage_p10_p90"])
    if len(summary) != 1:
        raise ValueError("expected one score summary row")
    row = summary.iloc[0]
    result = {}
    for name in (*METRICS, "coverage_p10_p90"):
        value = float(row[name])
        if math.isinf(value) or value < 0:
            raise ValueError("invalid official metric")
        result[name] = None if math.isnan(value) else value
    for name in COUNTS:
        value = float(row[name])
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            raise ValueError("invalid official count")
        result[name] = int(value)
    return result


def _fold_actuals(data, fold):
    """Scoring-only outcomes in the assessment interval, never handed to a predictor.

    Use rows published by the outer pre-validation cutoff. Assessment tail deliveries
    outside the fold interval are intentionally unlabelled, as in official validation.
    Preserve independent missing price/spot/direction values so score.py decides each
    metric's matched rows. No test or official validation outcomes are included.
    """
    import pandas as pd

    scoring_config = RunConfig(fold.assessment_start_utc, fold.assessment_end_utc,
                               RunConfig.validation().fit_cutoff_utc)
    rows = select_fitting_labels(data.series, scoring_config)
    required = rows.loc[rows.series_id.isin(["fi_imbalance_price", "fi_mfrr_direction"])]
    wide = required.pivot(index="timestamp_utc", columns="series_id", values="value")
    if data.spot is not None:
        spot = select_fitting_labels(data.spot, scoring_config)
        if not (spot.series_id.eq("fi_spot_price") & spot.source.eq("nordpool")).all():
            raise ValueError("invalid fold spot input")
        wide = wide.join(spot.set_index("timestamp_utc")["value"].rename("spot_price"), how="outer")
    wide = wide.reindex(columns=["fi_imbalance_price", "spot_price", "fi_mfrr_direction"])
    direction = wide["fi_mfrr_direction"]
    if not direction.dropna().isin([-1, 0, 1]).all():
        raise ValueError("invalid fold direction")
    actuals = pd.DataFrame({
        "delivery_start_utc": wide.index.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "imbalance_price": wide.fi_imbalance_price.to_numpy(),
        "spot_price": wide.spot_price.to_numpy(),
        "direction": direction.map({1: "up", -1: "down", 0: "none"}).to_numpy(),
    })
    return actuals


def _select_model(name):
    if name == "persistence":
        return PersistencePredictor(), "persistence-v1"
    from ..models.lightgbm import LightGBMPredictor

    mode = {"lightgbm-direct": "direct", "lightgbm-relative": "spot_relative"}[name]
    return LightGBMPredictor(target_mode=mode), f"{name}-v1"


def _model_configuration(predictor, fitted):
    """Allowlisted recipe metadata only; never serialize arbitrary predictor state."""
    from ..models.lightgbm import LightGBMPredictor, FittedLightGBM

    if not isinstance(predictor, LightGBMPredictor) or not isinstance(fitted, FittedLightGBM):
        return {"kind": "persistence" if type(predictor) is PersistencePredictor else "custom"}
    heads = []
    for path, components in (("primary", fitted._heads), ("direct_backup", fitted._direct_heads)):
        for head in components:
            parameters = predictor.recipe.parameters()
            parameters["objective"] = head.objective
            if head.classes:
                parameters["num_class"] = len(head.classes)
            else:
                parameters["alpha"] = {"p10": .1, "p50": .5, "p90": .9}[head.name]
            heads.append({"component_id": f"{path}_{head.name}", "model_sha256": head.fingerprint,
                          "target_mode": "direct" if path == "direct_backup" else
                              predictor.target_mode if not head.classes else "classification",
                          "features": list(head.feature_names), "classes": list(head.classes),
                          "parameters": parameters, "num_boost_round": predictor.recipe.num_boost_round,
                          "native_version": head.native_version})
    return {"kind": "lightgbm", "target_mode": predictor.target_mode,
            "registry_version": fitted._registry_version, "quantile_policy": fitted._quantile_policy,
            "min_training_rows": predictor.min_training_rows,
            "fallback_policy": "fitted_direct_price_when_delivery_spot_unavailable" if
                predictor.target_mode == "spot_relative" else "none",
            "heads": heads}


def _path_counts(data, origins, result, configuration):
    """Availability counts expose no spot values. Path counts come from used evidence."""
    import pandas as pd

    available = 0
    if data.spot is not None:
        spot = data.spot.loc[data.spot.series_id.eq("fi_spot_price") & data.spot.value.notna()]
        for origin in origins:
            available += int((spot.first_usable_origin_utc.le(origin) & spot.timestamp_utc.ge(origin)
                              & spot.timestamp_utc.lt(origin + pd.Timedelta(hours=10))).sum())
    counts = {"delivery_spot_available": available,
              "delivery_spot_unavailable": len(result.forecasts) - available}
    if configuration.get("kind") == "lightgbm":
        relative = sum(e.name.startswith("lightgbm_price_spot_relative_step_")
                       for row in result.provenance.inference for e in row.dependencies)
        backup = sum(e.name.startswith("lightgbm_price_direct_backup_step_")
                     for row in result.provenance.inference for e in row.dependencies)
        is_relative = configuration["target_mode"] == "spot_relative"
        if is_relative and (relative != available or relative + backup != len(result.forecasts)):
            raise ValueError("price path evidence and delivery spot availability disagree")
        counts.update(spot_relative=relative, direct_backup=backup,
                      direct=0 if is_relative else len(result.forecasts))
    return counts


def _spot_mask(data, forecasts):
    """Origin-available exact delivery spot; no outcome information selects rows."""
    import pandas as pd

    if data.spot is None:
        return pd.Series(False, index=forecasts.index)
    spot = data.spot.loc[data.spot.series_id.eq("fi_spot_price") & data.spot.value.notna(),
                         ["timestamp_utc", "first_usable_origin_utc"]]
    joined = forecasts[["forecast_origin_utc", "delivery_start_utc"]].merge(
        spot, how="left", left_on="delivery_start_utc", right_on="timestamp_utc", validate="many_to_one")
    return pd.Series(joined.first_usable_origin_utc.le(joined.forecast_origin_utc).to_numpy(), index=forecasts.index)


def _diagnostics(data, fitted, origins, configuration):
    """Rebuild private features for count-only diagnostics, timed separately."""
    if configuration.get("kind") != "lightgbm":
        return {}
    from ..features import build_features

    features = build_features(fitted._input_view(data), origins=origins, feature_names=fitted._feature_names)
    return {name: {"available": int(features.frame[name].notna().sum()),
                   "missing": int(features.frame[name].isna().sum())} for name in fitted._feature_names}


def run_experiment(*, starter_dir, data_dir, output_dir, fold=None,
                   predictor=None, recipe_id=None, measure_attribution=False):
    """Run validation (fold=None) or a Step 1B ChronologicalFold.

    A custom Predictor needs an explicit safe recipe identifier; it uses the existing
    fit/forecast contract. No model selection, tuning, fitting-label construction or
    feature caching is added here. Prediction inputs are long series/spot only.
    Actuals access/creation follows successful official structural validation.
    """
    import pandas as pd

    if fold is not None and not isinstance(fold, ChronologicalFold):
        raise ExperimentError("experiment requires a chronological fold or validation")
    if not isinstance(measure_attribution, bool):
        raise ExperimentError("measurement option must be boolean")
    if predictor is None:
        predictor = PersistencePredictor()
        recipe_id = recipe_id or "persistence-v1"
    if not isinstance(recipe_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", recipe_id):
        raise ExperimentError("experiment requires a safe explicit recipe identifier")
    starter, data_dir, output = map(lambda p: Path(p).resolve(), (starter_dir, data_dir, output_dir))
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ExperimentError("experiment output must be a new or empty directory")
    inputs, spot = data_dir / "inputs.csv", data_dir / "spot_nordpool.csv"
    actuals = data_dir / "actuals_validation.csv" if fold is None else output / "fold_actuals.csv"
    # Never allow private outputs to overwrite a source or starter file.
    if output == starter or output == data_dir:
        raise ExperimentError("experiment output must be separate from input directories")
    config = RunConfig.validation() if fold is None else fold.config
    origins = _validation_origins() if fold is None else fold.assessment_origins
    manifest = {
        "status": "running", "stage": "preflight", "recipe_id": recipe_id,
        "period": "validation" if fold is None else "prevalidation_fold",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "config": {name: getattr(config, name).isoformat() for name in (
            "label_start_utc", "label_end_utc", "fit_cutoff_utc")},
        "request": {"first_origin_utc": origins[0].isoformat(),
                    "last_origin_utc": origins[-1].isoformat(), "origin_count": len(origins)},
        "consumed_files": {}, "official_commands": [], "artifacts": {}, "timings": {},
    }
    try:
        output.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise ExperimentError("cannot create experiment output directory") from None
    started = time.perf_counter()
    try:
        manifest["environment"] = evaluation._environment()
        from importlib.metadata import PackageNotFoundError, version
        for name in ("lightgbm", "scipy", "narwhals"):
            try:
                manifest["environment"]["dependencies"][name] = version(name)
            except PackageNotFoundError:
                manifest["environment"]["dependencies"][name] = None
        for name, path in (("inputs", inputs), ("spot", spot),
                           ("validator", starter / "validate_submission.py"),
                           ("scorer", starter / "score.py")):
            manifest["consumed_files"][name] = evaluation._file_record(path)
        for name in ("README.md", "requirements.txt", "pyproject.toml", "requirements-dev.in",
                     "requirements-dev.lock", "availability.csv", "baseline.ipynb"):
            path = starter / name
            if path.is_file():
                manifest["consumed_files"][name] = evaluation._file_record(path)
        manifest["stage"] = "load"
        stage_start = time.perf_counter()
        data = load_inputs(inputs, spot_path=spot)
        manifest["input_rows"] = {"series": len(data.series), "spot": len(data.spot)}
        manifest["timings"]["load"] = time.perf_counter() - stage_start
        manifest["stage"] = "fit"
        stage_start = time.perf_counter()
        fitted = predictor.fit(data, config=config)
        if fitted.provenance.config != config:
            raise ValueError("predictor returned a different fitting configuration")
        manifest["timings"]["fit"] = time.perf_counter() - stage_start
        manifest["model_configuration"] = _model_configuration(predictor, fitted)
        manifest["stage"] = "predict"
        stage_start = time.perf_counter()
        if measure_attribution:
            import cProfile
            from ..explainability.drivers import _driver_labels

            profiler = cProfile.Profile()
            result = profiler.runcall(forecast, fitted, data, origins=origins)
            manifest["timings"]["attribution"] = sum(
                item.totaltime for item in profiler.getstats() if item.code is _driver_labels.__code__)
        else:
            result = forecast(fitted, data, origins=origins)
        manifest["timings"]["predict"] = time.perf_counter() - stage_start
        manifest["measurement"] = {"attribution_profiled": measure_attribution,
                                   "attribution_is_part_of_predict": True,
                                   "profiler_overhead_in_predict": measure_attribution}
        manifest["provenance"] = evaluation._safe_provenance(result)
        manifest["forecast_rows"] = len(result.forecasts)
        manifest["price_paths"] = _path_counts(data, origins, result, manifest["model_configuration"])
        if measure_attribution:
            stage_start = time.perf_counter()
            manifest["feature_availability"] = _diagnostics(data, fitted, origins, manifest["model_configuration"])
            manifest["timings"]["feature_diagnostics"] = time.perf_counter() - stage_start
        manifest["stage"] = "export"
        submission = export_forecasts(result.forecasts, output / "forecast_backtest.csv", origins=origins)
        origins_path = output / "forecast_origins.csv"
        pd.DataFrame({"forecast_origin_utc": pd.DatetimeIndex(origins).strftime("%Y-%m-%dT%H:%M:%SZ")}).to_csv(
            origins_path, index=False, lineterminator="\n")
        manifest["artifacts"].update(forecast=str(submission), origins=str(origins_path))
        manifest["stage"] = "validate"
        evaluation._run_tool("validation", starter / "validate_submission.py",
                             ["--backtest", submission, "--origins", origins_path], starter, output, manifest)
        manifest["stage"] = "scoring_actuals"
        if fold is not None:
            _fold_actuals(data, fold).to_csv(actuals, index=False, lineterminator="\n")
            manifest["scoring_label_config"] = {
                "delivery_start_utc": fold.assessment_start_utc.isoformat(),
                "delivery_end_utc": fold.assessment_end_utc.isoformat(),
                "publication_cutoff_utc": RunConfig.validation().fit_cutoff_utc.isoformat(),
            }
            manifest["artifacts"]["private_fold_actuals"] = str(actuals)
        # First actuals-byte access is AFTER validation; never check/hash test actuals.
        manifest["consumed_files"]["scoring_actuals"] = evaluation._file_record(actuals)
        manifest["stage"] = "score"
        score_dir = output / "score"
        evaluation._run_tool("scoring", starter / "score.py", ["--submission", submission,
                             "--actuals", actuals, "--spike-margin", "50", "--output-dir", score_dir],
                             starter, output, manifest)
        manifest["metrics"] = _read_scores(score_dir / "score_summary.csv")
        if manifest["metrics"]["rows_in_submission"] != len(result.forecasts):
            raise ValueError("scorer returned mismatched row count")
        for name in ("score_summary.csv", "score_summary.md", "score_by_horizon.csv"):
            manifest["artifacts"][name] = str(score_dir / name)
        if measure_attribution:
            manifest["stage"] = "shared_spot_scoring"
            mask = _spot_mask(data, result.forecasts)
            keys = result.forecasts.loc[mask, ["forecast_origin_utc", "step"]].to_csv(index=False)
            import hashlib

            manifest["shared_spot"] = {"forecast_rows": int(mask.sum()),
                                       "row_keys_sha256": hashlib.sha256(keys.encode()).hexdigest()}
            if mask.all():
                manifest["shared_spot"].update(metrics=manifest["metrics"], identical_to_complete=True)
            elif not mask.any():
                manifest["shared_spot"].update(metrics={**{k: None for k in (*METRICS, "coverage_p10_p90")},
                                                        **{k: 0 for k in COUNTS}}, identical_to_complete=False)
            else:
                subset = output / "shared_spot_forecasts.csv"
                # Reuse validated CSV spelling/precision, including strict UTC text.
                exported = pd.read_csv(submission, dtype=str, keep_default_na=False)
                exported.loc[mask.to_numpy()].to_csv(subset, index=False, lineterminator="\n")
                subset_dir = output / "shared_spot_score"
                evaluation._run_tool("shared_spot_scoring", starter / "score.py", ["--submission", subset,
                                     "--actuals", actuals, "--spike-margin", "50", "--output-dir", subset_dir],
                                     starter, output, manifest)
                manifest["shared_spot"].update(metrics=_read_scores(subset_dir / "score_summary.csv"),
                                               identical_to_complete=False)
                manifest["artifacts"].update(shared_spot_forecasts=str(subset),
                    shared_spot_score=str(subset_dir / "score_summary.csv"))
        manifest["stage"] = "integrity"
        for record in manifest["consumed_files"].values():
            if evaluation._sha256(record["path"]) != record["sha256"]:
                raise ValueError("experiment source changed during execution")
        if evaluation._package_fingerprints() != manifest["environment"]["package_sources_sha256"]:
            raise ValueError("package sources changed during execution")
        manifest["artifact_sha256"] = {name: evaluation._sha256(path)
                                          for name, path in manifest["artifacts"].items()}
        manifest["status"], manifest["stage"] = "complete", "complete"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["failure"] = {"stage": manifest["stage"], "error_type": type(error).__name__}
        raise ExperimentError(f"experiment failed during {manifest['stage']} ({type(error).__name__}); see run_manifest.json") from None
    finally:
        manifest["elapsed_seconds"] = time.perf_counter() - started
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (output / "run_manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return manifest


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid experiment arguments; use --help.\n")


def main(argv=None):
    parser = _Parser(description="Private chronological experiment using unchanged official tools.")
    parser.add_argument("--period", choices=("validation", "fold-1", "fold-2"), default="validation")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--model", choices=("persistence", "lightgbm-direct", "lightgbm-relative"))
    from .recipes import RECIPES
    selection.add_argument("--recipe", choices=tuple(RECIPES))
    parser.add_argument("--measure-attribution", action="store_true")
    parser.add_argument("--starter-dir", type=Path, default=Path("."))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, required=True)
    options = parser.parse_args(argv)
    fold = None if options.period == "validation" else expanding_window_folds()[int(options.period[-1]) - 1]
    try:
        if options.recipe:
            predictor, recipe_id = RECIPES[options.recipe].predictor(), options.recipe
        else:
            predictor, recipe_id = _select_model(options.model or "persistence")
        manifest = run_experiment(starter_dir=options.starter_dir, data_dir=options.data_dir,
                                  output_dir=options.output_dir, fold=fold,
                                  predictor=predictor, recipe_id=recipe_id,
                                  measure_attribution=options.measure_attribution)
    except Exception as error:
        print(f"Experiment failed ({type(error).__name__}); inspect the safe run manifest if created.", file=sys.stderr)
        return 1
    print(f"Completed experiment: {manifest['forecast_rows']} forecast rows; see run_manifest.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
