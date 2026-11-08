"""Preregister, execute and compare controlled folds without test outcomes.

All CSVs written here are private diagnostics, not complete submission artifacts.
Losses come from unchanged score.py; only deltas/retention rules are computed here.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from .. import evaluation
from ..config import RunConfig
from ..features.training import expanding_window_folds
from .recipes import RECIPES, REFINEMENTS, RETENTION, UNTESTED
from .run import COUNTS, METRICS, _read_scores


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _recipes(plan):
    if plan.get("scope") == "Step 4B only":
        return {"relative-control-v1": RECIPES["relative-control-v1"], **REFINEMENTS}
    if plan.get("scope") != "Step 4A only":
        raise ValueError("unknown study scope")
    return RECIPES


def _prior_evidence(root):
    root = Path(root).resolve()
    plan_path = root / "study_plan.json"
    plan = json.loads(plan_path.read_text())
    report_path = root / "comparison" / "comparison.json"
    report = json.loads(report_path.read_text())
    expected = [{"recipe_id": r.recipe_id, "target_mode": r.target_mode,
                 "features": list(r.features), "hypothesis": r.hypothesis} for r in RECIPES.values()]
    if (plan["scope"] != "Step 4A only"
            or evaluation._sha256(plan_path) != (root / "study_plan.sha256").read_text().strip()
            or report["plan_sha256"] != evaluation._sha256(plan_path)
            or plan["allocated_4a"] != 4 or plan["reserved_4b"] != 2
            or report["recipes_used"] != 4 or report["recipes_reserved_4b"] != 2
            or plan["recipes"] != expected or plan["retention"] != dict(RETENTION)
            or report["selection"] != _selection(report["results"])
            or report["selection"]["selected_recipe"] != "relative-control-v1"):
        raise ValueError("4B requires verified 4A relative-control evidence")
    for identity in ("persistence-v1", *RECIPES):
        result = report["results"][identity]
        for fold in plan["folds"]:
            manifest = _checked_manifest(root, fold, identity, plan)
            if result["losses"][fold["fold"]] != manifest["metrics"]:
                raise ValueError("4A recorded fold evidence changed")
        for evidence in result["pooled_evidence"].values():
            for name in ("forecasts", "actuals", "score"):
                record = evidence[name]
                if evaluation._sha256(record["path"]) != record["sha256"]:
                    raise ValueError("4A pooled artifact changed")
            if any(command["exit_code"] != 0 for command in evidence["commands"]):
                raise ValueError("4A pooled scoring failed")
        if result["losses"]["pooled"] != _read_scores(result["pooled_evidence"]["pooled"]["score"]["path"]):
            raise ValueError("4A pooled losses changed")
    return {"plan": evaluation._file_record(plan_path), "report": evaluation._file_record(report_path)}, plan


def write_plan(*, starter_dir, data_dir, output_dir, stage="4a", previous_study=None):
    from ..models.heads import TreeRecipe

    starter, data, output = (Path(p).resolve() for p in (starter_dir, data_dir, output_dir))
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("plan requires a fresh directory")
    if stage not in ("4a", "4b"):
        raise ValueError("unknown study stage")
    plan = {
        "scope": "Step 4A only", "planned_utc": datetime.now(timezone.utc).isoformat(),
        "learned_recipe_budget": 6, "allocated_4a": 4, "reserved_4b": 2,
        "counting": "Distinct real-data configurations count once across folds; synthetic verification is not model selection.",
        "retention": dict(RETENTION), "untested_hypotheses": UNTESTED,
        "prior_validation_reuse": "Step 2C validation was inspected and motivated relative-only feature ablations. No official validation outcomes are read in this study; selection uses earlier folds.",
        "parameters": TreeRecipe().parameters(), "num_boost_round": TreeRecipe().num_boost_round,
        "recipes": [{"recipe_id": r.recipe_id, "target_mode": r.target_mode,
                     "features": r.features, "hypothesis": r.hypothesis} for r in RECIPES.values()],
        "folds": [{"fold": f"fold-{i}", "config": {k: getattr(f.config, k).isoformat() for k in
                   ("label_start_utc", "label_end_utc", "fit_cutoff_utc")},
                   "assessment_start_utc": f.assessment_start_utc.isoformat(),
                   "assessment_end_utc": f.assessment_end_utc.isoformat(),
                   "origin_count": len(f.assessment_origins)} for i, f in enumerate(expanding_window_folds(), 1)],
        "sources": {name: evaluation._file_record(path) for name, path in
                    (("inputs", data / "inputs.csv"), ("spot", data / "spot_nordpool.csv"),
                     ("validator", starter / "validate_submission.py"), ("scorer", starter / "score.py"))},
        "package_sources_sha256": evaluation._package_fingerprints(),
        "cost_policy": "Predict includes attribution and cProfile overhead. Feature-count diagnostics are separately timed. Overlapping local jobs are not controlled runtime benchmarks.",
        "pooled_policy": "Exclude each fold's out-of-assessment delivery tail before pooling, so later-fold labels cannot relabel an earlier fold's unscored tail. Original complete horizons remain unchanged.",
    }
    if stage == "4b":
        if previous_study is None:
            raise ValueError("4B requires the completed 4A study")
        lineage, prior = _prior_evidence(previous_study)
        if plan["folds"] != prior["folds"] or plan["sources"] != prior["sources"]:
            raise ValueError("4B must retain 4A data, tools and folds")
        core = lambda sources: {name: digest for name, digest in sources.items()
                                if not name.startswith(("experiments/", "tests/"))}
        if core(prior["package_sources_sha256"]) != core(plan["package_sources_sha256"]):
            raise ValueError("4B requires unchanged model, feature and attribution sources")
        plan.update(scope="Step 4B only", allocated_4b=2, reserved_4b=0,
                    previous_study=lineage, retention_reference="relative-control-v1",
                    comparison_policy="Refinements must pass the same gate versus the relative control and persistence; rank eligible recipes including the retained control by pooled losses. No automatic activation.",
                    runner_policy="Sequential subprocesses; resume only verified complete runs. No retries or overwrites of incomplete runs.")
        plan["recipes"] = [{"recipe_id": r.recipe_id, "target_mode": r.target_mode,
                            "features": r.features, "hypothesis": r.hypothesis,
                            "parameters": r.tree.parameters(), "num_boost_round": r.tree.num_boost_round}
                           for r in _recipes(plan).values()]
        plan["untested_hypotheses"] = [*UNTESTED[:2],
            "Head-specific subsets, horizon grouping, other tree settings, ensembles and regimes.", UNTESTED[-1]]
    output.mkdir(parents=True, exist_ok=True)
    _write(output / "study_plan.json", plan)
    (output / "study_plan.sha256").write_text(evaluation._sha256(output / "study_plan.json") + "\n")
    return plan


def _checked_manifest(root, fold, identity, plan):
    directory = root / fold["fold"] / identity
    manifest = json.loads((directory / "run_manifest.json").read_text())
    if (manifest["status"] != "complete" or manifest["period"] != "prevalidation_fold"
            or manifest["recipe_id"] != identity or manifest["config"] != fold["config"]
            or manifest["request"]["origin_count"] != fold["origin_count"]
            or datetime.fromisoformat(manifest["started_utc"]) < datetime.fromisoformat(plan["planned_utc"])
            or manifest["environment"]["package_sources_sha256"] != plan["package_sources_sha256"]
            or not manifest["measurement"]["attribution_profiled"]
            or any(c["exit_code"] != 0 for c in manifest["official_commands"])):
        raise ValueError("run does not match preregistered study")
    for name, source in plan["sources"].items():
        if manifest["consumed_files"][name] != source:
            raise ValueError("study source mismatch")
    actuals = manifest["consumed_files"]["scoring_actuals"]
    expected_labels = {"delivery_start_utc": fold["assessment_start_utc"],
                       "delivery_end_utc": fold["assessment_end_utc"],
                       "publication_cutoff_utc": RunConfig.validation().fit_cutoff_utc.isoformat()}
    if manifest.get("scoring_label_config") != expected_labels:
        raise ValueError("assessment label boundaries mismatch")
    if Path(actuals["path"]).resolve() != directory / "fold_actuals.csv":
        raise ValueError("unexpected scoring actuals")
    if evaluation._sha256(actuals["path"]) != actuals["sha256"]:
        raise ValueError("scoring actuals changed")
    for name, path in manifest["artifacts"].items():
        if not Path(path).resolve().is_relative_to(directory):
            raise ValueError("artifact outside run")
        if evaluation._sha256(path) != manifest["artifact_sha256"][name]:
            raise ValueError("artifact changed")
    if manifest["metrics"] != _read_scores(manifest["artifacts"]["score_summary.csv"]):
        raise ValueError("manifest losses differ from official score artifact")
    shared = manifest["shared_spot"]
    if shared["identical_to_complete"]:
        if shared["metrics"] != manifest["metrics"]:
            raise ValueError("shared complete losses mismatch")
    elif shared["forecast_rows"]:
        if shared["metrics"] != _read_scores(manifest["artifacts"]["shared_spot_score"]):
            raise ValueError("shared losses mismatch")
    configuration = manifest["model_configuration"]
    if identity == "persistence-v1":
        if configuration["kind"] != "persistence":
            raise ValueError("baseline kind mismatch")
    else:
        recipe = _recipes(plan)[identity]
        if (configuration["kind"] != "lightgbm" or configuration["target_mode"] != recipe.target_mode
                or len(configuration["heads"]) != (5 if recipe.target_mode == "direct" else 8)
                or configuration["min_training_rows"] != 40):
            raise ValueError("recipe mismatch")
        for head in configuration["heads"]:
            if (head["features"] != list(recipe.features) or head["num_boost_round"] != recipe.tree.num_boost_round
                    or any(head["parameters"].get(k) != v for k, v in recipe.tree.parameters().items())):
                raise ValueError("recipe parameters mismatch")
    return manifest


def _horizons(path):
    import pandas as pd

    names = ["horizon_hour", "step_first", "step_last", "rows_scored_price", "rows_scored_spike",
             "rows_scored_direction", *METRICS, "coverage_p10_p90"]
    frame = pd.read_csv(path, usecols=names).astype(object)
    return frame.where(pd.notna(frame), None).to_dict("records")


def _passes(candidate, reference):
    """Predeclared loss-only gate; coverage and costs remain visible diagnostics."""
    tolerance = RETENTION["absolute_tolerance"]
    for scope in ("fold-1", "fold-2", "pooled"):
        for metric in METRICS:
            a, b = candidate[scope][metric], reference[scope][metric]
            if a is None or b is None or a - b > max(tolerance, abs(b) * RETENTION["maximum_relative_regression"]):
                return False
    return any(reference["pooled"][metric] - candidate["pooled"][metric] >=
               max(tolerance, abs(reference["pooled"][metric]) * RETENTION["minimum_relative_improvement"])
               for metric in METRICS)


def _selection(results):
    baseline = results["persistence-v1"]["losses"]
    controls = [name for name in ("direct-control-v1", "relative-control-v1")
                if _passes(results[name]["losses"], baseline)]
    key = lambda name: (*[results[name]["losses"]["pooled"][m] for m in METRICS], name)
    control = min(controls, key=key) if controls else None
    decisions = {}
    eligible = list(controls)
    for name in RECIPES:
        references = ["persistence-v1"]
        if name not in ("direct-control-v1", "relative-control-v1"):
            references.append("relative-control-v1")
            if control and control not in references:
                references.append(control)
        passed = all(_passes(results[name]["losses"], results[ref]["losses"]) for ref in references)
        decisions[name] = {"passes": passed, "references": references}
        if passed and name not in eligible:
            eligible.append(name)
    return {"selected_recipe": min(eligible, key=key) if eligible else "persistence-v1",
            "selected_control": control, "decisions": decisions, "automatic_activation": False}


def _selection_4b(results):
    baseline, control = "persistence-v1", "relative-control-v1"
    eligible = [control] if _passes(results[control]["losses"], results[baseline]["losses"]) else []
    decisions = {}
    for name in REFINEMENTS:
        references = [baseline, control]
        passed = all(_passes(results[name]["losses"], results[ref]["losses"]) for ref in references)
        decisions[name] = {"passes": passed, "references": references}
        if passed:
            eligible.append(name)
    key = lambda name: (*[results[name]["losses"]["pooled"][m] for m in METRICS], name)
    return {"selected_recipe": min(eligible, key=key) if eligible else baseline,
            "selected_control": control, "decisions": decisions, "automatic_activation": False}


def _validated_plan(root):
    plan_path = root / "study_plan.json"
    plan = json.loads(plan_path.read_text())
    if evaluation._sha256(plan_path) != (root / "study_plan.sha256").read_text().strip():
        raise ValueError("study plan changed")
    if plan["package_sources_sha256"] != evaluation._package_fingerprints():
        raise ValueError("study sources changed")
    for source in plan["sources"].values():
        if evaluation._sha256(source["path"]) != source["sha256"]:
            raise ValueError("study inputs/tools changed")
    expected = [{"recipe_id": r.recipe_id, "target_mode": r.target_mode,
                 "features": list(r.features), "hypothesis": r.hypothesis} for r in _recipes(plan).values()]
    if plan["scope"] == "Step 4B only":
        for record, recipe in zip(expected, _recipes(plan).values()):
            record.update(parameters=recipe.tree.parameters(), num_boost_round=recipe.tree.num_boost_round)
        if plan.get("allocated_4b") != 2 or plan.get("retention_reference") != "relative-control-v1":
            raise ValueError("4B registration mismatch")
        for record in plan["previous_study"].values():
            if evaluation._sha256(record["path"]) != record["sha256"]:
                raise ValueError("4A lineage changed")
        lineage, _ = _prior_evidence(Path(plan["previous_study"]["plan"]["path"]).parent)
        if lineage != plan["previous_study"]:
            raise ValueError("4A lineage mismatch")
    reserved = 0 if plan["scope"] == "Step 4B only" else 2
    if (plan["recipes"] != expected or plan["retention"] != dict(RETENTION)
            or (plan["learned_recipe_budget"], plan["allocated_4a"], plan["reserved_4b"]) != (6, 4, reserved)):
        raise ValueError("study registration mismatch")
    return plan


def build_report(*, output_dir):
    import pandas as pd

    root = Path(output_dir).resolve()
    plan = _validated_plan(root)
    plan_path = root / "study_plan.json"
    identities = ["persistence-v1", *_recipes(plan)]
    manifests = {name: [_checked_manifest(root, fold, name, plan) for fold in plan["folds"]] for name in identities}
    for index, fold in enumerate(plan["folds"]):
        baseline = manifests["persistence-v1"][index]
        base_grid = None
        for name in identities:
            manifest = manifests[name][index]
            if (manifest["consumed_files"]["scoring_actuals"]["sha256"] != baseline["consumed_files"]["scoring_actuals"]["sha256"]
                    or manifest["request"] != baseline["request"]
                    or manifest["shared_spot"]["row_keys_sha256"] != baseline["shared_spot"]["row_keys_sha256"]
                    or any(manifest["metrics"][k] != baseline["metrics"][k] for k in COUNTS)
                    or any(manifest["shared_spot"]["metrics"][k] != baseline["shared_spot"]["metrics"][k] for k in COUNTS)):
                raise ValueError("unmatched study rows/outcomes")
            grid = pd.read_csv(manifest["artifacts"]["forecast"], usecols=["forecast_origin_utc", "delivery_start_utc", "step"])
            if base_grid is None:
                base_grid = grid
            elif not grid.equals(base_grid):
                raise ValueError("unmatched forecast grid")
    analysis = root / "comparison"
    if analysis.exists() and any(analysis.iterdir()):
        raise ValueError("comparison output already exists")
    analysis.mkdir(exist_ok=True)
    actual_frames = [pd.read_csv(m["consumed_files"]["scoring_actuals"]["path"], dtype=str, keep_default_na=False)
                     for m in manifests["persistence-v1"]]
    actuals = pd.concat(actual_frames, ignore_index=True)
    if actuals.delivery_start_utc.duplicated().any():
        raise ValueError("overlapping fold outcomes")
    actuals_path = analysis / "private_pooled_actuals.csv"
    actuals.to_csv(actuals_path, index=False, lineterminator="\n")
    results = {}
    for name in identities:
        runs = manifests[name]
        result = {"folds": [], "losses": {}, "costs_seconds": [], "shared_spot": {}, "pooled_evidence": {}}
        frames, shared_frames = [], []
        for fold, manifest in zip(plan["folds"], runs):
            frame = pd.read_csv(manifest["artifacts"]["forecast"], dtype=str, keep_default_na=False)
            frame = frame.loc[pd.to_datetime(frame.delivery_start_utc, utc=True) < pd.Timestamp(fold["assessment_end_utc"])]
            if manifest["shared_spot"]["identical_to_complete"]:
                shared = frame
            elif manifest["shared_spot"]["forecast_rows"] == 0:
                shared = frame.iloc[:0]
            else:
                shared = pd.read_csv(manifest["artifacts"]["shared_spot_forecasts"], dtype=str, keep_default_na=False)
                shared = shared.loc[pd.to_datetime(shared.delivery_start_utc, utc=True) < pd.Timestamp(fold["assessment_end_utc"])]
            frames.append(frame)
            shared_frames.append(shared)
            result["losses"][fold["fold"]] = manifest["metrics"]
            result["shared_spot"][fold["fold"]] = manifest["shared_spot"]
            result["costs_seconds"].append(manifest["timings"])
            result["folds"].append({"fold": fold["fold"], "metrics": manifest["metrics"],
                "feature_availability": manifest.get("feature_availability", {}), "price_paths": manifest["price_paths"],
                "training_counts": manifest["provenance"]["counts"],
                "horizons": _horizons(manifest["artifacts"]["score_by_horizon.csv"])})
        pooled = pd.concat(frames, ignore_index=True)
        pooled_shared = pd.concat(shared_frames, ignore_index=True)
        for scope, frame in (("pooled", pooled), ("pooled_shared_spot", pooled_shared)):
            if frame.empty:
                result["shared_spot"][scope] = {"metrics": {**{k: None for k in (*METRICS, "coverage_p10_p90")}, **{k: 0 for k in COUNTS}}}
                continue
            directory = analysis / name / scope
            directory.mkdir(parents=True)
            path = directory / "private_assessment_forecasts.csv"
            frame.to_csv(path, index=False, lineterminator="\n")
            tool = {"official_commands": [], "artifacts": {}}
            evaluation._run_tool("scoring", plan["sources"]["scorer"]["path"],
                ["--submission", path, "--actuals", actuals_path, "--spike-margin", "50", "--output-dir", directory / "score"],
                Path(plan["sources"]["scorer"]["path"]).parent, directory, tool)
            metrics = _read_scores(directory / "score" / "score_summary.csv")
            result["pooled_evidence"][scope] = {"commands": tool["official_commands"],
                "forecasts": evaluation._file_record(path), "actuals": evaluation._file_record(actuals_path),
                "score": evaluation._file_record(directory / "score" / "score_summary.csv")}
            if scope == "pooled":
                if any(metrics[k] != sum(m["metrics"][k] for m in runs)
                       for k in ("rows_scored_price", "rows_scored_spike", "rows_scored_direction")):
                    raise ValueError("pooling changed matched outcomes")
                result["losses"][scope] = metrics
                result["pooled_horizons"] = _horizons(directory / "score" / "score_by_horizon.csv")
            else:
                if any(metrics[k] != sum(m["shared_spot"]["metrics"][k] for m in runs)
                       for k in ("rows_scored_price", "rows_scored_spike", "rows_scored_direction")):
                    raise ValueError("shared pooling changed matched outcomes")
                result["shared_spot"][scope] = {"metrics": metrics}
        results[name] = result
    refinement = plan["scope"] == "Step 4B only"
    report = {"scope": "Step 4B pre-validation comparison" if refinement else "Step 4A pre-validation comparison", "plan_sha256": evaluation._sha256(plan_path),
              "recipes_used": 6 if refinement else 4, "recipes_reserved_4b": 0 if refinement else 2, "results": results,
              "selection": _selection_4b(results) if refinement else _selection(results), "untested_hypotheses": plan["untested_hypotheses"],
              "prior_validation_reuse": plan["prior_validation_reuse"], "cost_policy": plan["cost_policy"],
              "pooled_policy": plan["pooled_policy"]}
    if refinement:
        report["previous_study"] = plan["previous_study"]
        report["selected_configuration"] = next((r for r in plan["recipes"]
            if r["recipe_id"] == report["selection"]["selected_recipe"]), {"recipe_id": "persistence-v1"})
    _write(analysis / "comparison.json", report)
    lines = ["# " + report["scope"], "", "| Recipe | Pooled MAE | Pinball | Spike Brier | Direction Brier | Coverage |", "|---|---:|---:|---:|---:|---:|"]
    for name, result in results.items():
        metrics = result["losses"]["pooled"]
        lines.append("| " + name + " | " + " | ".join("unavailable" if metrics[k] is None else f"{metrics[k]:.6f}"
                     for k in (*METRICS, "coverage_p10_p90")) + " |")
    lines += ["", "Provisional choice: `" + report["selection"]["selected_recipe"] + "`. No application activation.",
              "", ("Six of six learned recipe slots used; no slots remain." if refinement else "Four of six learned recipe slots used; two reserved for 4B.") + " All fold losses, matched counts, source availability, backup usage, horizon diagnostics and costs are in comparison.json.",
              "", plan["pooled_policy"], "", plan["cost_policy"], "", plan["prior_validation_reuse"],
              "", "No calibration, official-validation selection, test-outcome access or final submission generation. Windows and full-data deployment performance remain unverified."]
    (analysis / "comparison.md").write_text("\n".join(lines) + "\n")
    return report


def execute_study(*, output_dir):
    root = Path(output_dir).resolve()
    plan = _validated_plan(root)
    if (root / "comparison" / "comparison.json").exists():
        raise ValueError("study already reported; inspect existing results")
    for fold in plan["folds"]:
        for identity in ("persistence-v1", *_recipes(plan)):
            _validated_plan(root)
            directory = root / fold["fold"] / identity
            if directory.exists():
                _checked_manifest(root, fold, identity, plan)
                print(f"Verified completed run: {fold['fold']} / {identity}", flush=True)
                continue
            command = [sys.executable, "-W", "error::FutureWarning", "-m", "forecast_engine.experiments.run",
                       "--starter-dir", str(Path(plan["sources"]["scorer"]["path"]).parent),
                       "--data-dir", str(Path(plan["sources"]["inputs"]["path"]).parent),
                       "--period", fold["fold"], "--measure-attribution", "--output-dir", str(directory)]
            command += ["--model", "persistence"] if identity == "persistence-v1" else ["--recipe", identity]
            print(f"Starting: {fold['fold']} / {identity}", flush=True)
            with (root / f"{fold['fold']}-{identity}.log").open("x") as log:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
            if completed.returncode:
                raise ValueError("study run failed; inspect private log; no automatic retry")
            _checked_manifest(root, fold, identity, plan)
            print(f"Completed: {fold['fold']} / {identity}", flush=True)
    return build_report(output_dir=root)


def main(argv=None):
    from .run import _Parser

    parser = _Parser(description="Private Step 4A/4B preregistration, terminal execution and matched fold comparison.")
    parser.add_argument("action", choices=("plan", "report", "execute"))
    parser.add_argument("--stage", choices=("4a", "4b"), default="4a")
    parser.add_argument("--previous-study", type=Path)
    parser.add_argument("--starter-dir", type=Path, default=Path("."))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, required=True)
    options = parser.parse_args(argv)
    try:
        if options.action == "plan":
            write_plan(starter_dir=options.starter_dir, data_dir=options.data_dir, output_dir=options.output_dir,
                       stage=options.stage, previous_study=options.previous_study)
        elif options.action == "execute":
            execute_study(output_dir=options.output_dir)
        else:
            build_report(output_dir=options.output_dir)
    except Exception as error:
        print(f"Comparison failed ({type(error).__name__}); no source diagnostics printed.")
        return 1
    print("Completed study action; inspect private study plan/comparison artifacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
