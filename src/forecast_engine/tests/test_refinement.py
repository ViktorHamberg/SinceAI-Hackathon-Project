"""Focused synthetic checks for bounded refinement and unattended execution."""

from contextlib import redirect_stdout
from dataclasses import fields
from io import StringIO
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from forecast_engine import RunConfig
from forecast_engine import evaluation
from forecast_engine.experiments import compare, run
from forecast_engine.experiments.recipes import ALL_RECIPES, RECIPES, REFINEMENTS
from forecast_engine.features.training import ChronologicalFold

ROOT = Path(__file__).resolve().parents[3]


class RefinementPolicyTests(unittest.TestCase):
    def test_two_slots_each_change_one_tree_setting_only(self):
        self.assertEqual(len(ALL_RECIPES), 6)
        control = RECIPES["relative-control-v1"].predictor()
        for identity, setting in (("relative-rounds60-v1", "num_boost_round"),
                                  ("relative-l2-10-v1", "l2_regularization")):
            candidate = REFINEMENTS[identity].predictor()
            self.assertEqual(candidate.target_mode, control.target_mode)
            self.assertEqual(candidate.feature_names, control.feature_names)
            self.assertEqual(candidate.min_training_rows, control.min_training_rows)
            changed = [f.name for f in fields(control.recipe)
                       if getattr(candidate.recipe, f.name) != getattr(control.recipe, f.name)]
            self.assertEqual(changed, [setting])
            with patch.object(run, "run_experiment", return_value={"forecast_rows": 80}) as execute, redirect_stdout(StringIO()):
                self.assertEqual(run.main(["--recipe", identity, "--period", "fold-1",
                                           "--measure-attribution", "--output-dir", "unused"]), 0)
            self.assertEqual(execute.call_args.kwargs["predictor"], candidate)

    def test_selection_retains_control_unless_refinement_passes_both_references(self):
        def result(value):
            return {"losses": {scope: {m: value for m in run.METRICS}
                               for scope in ("fold-1", "fold-2", "pooled")}}
        results = {"persistence-v1": result(2.), "relative-control-v1": result(1.),
                   **{name: result(1.) for name in REFINEMENTS}}
        self.assertEqual(compare._selection_4b(results)["selected_recipe"], "relative-control-v1")
        results["relative-rounds60-v1"] = result(.98)
        self.assertEqual(compare._selection_4b(results)["selected_recipe"], "relative-rounds60-v1")
        results["relative-rounds60-v1"]["losses"]["fold-2"]["brier_spike_mean"] = 1.02
        selection = compare._selection_4b(results)
        self.assertEqual(selection["selected_recipe"], "relative-control-v1")
        self.assertFalse(selection["automatic_activation"])
        self.assertEqual(selection["decisions"]["relative-rounds60-v1"]["references"],
                         ["persistence-v1", "relative-control-v1"])

    def test_runner_resumes_verified_runs_and_stops_on_failure_without_retry(self):
        plan = {"scope": "Step 4B only", "folds": [{"fold": "fold-1"}, {"fold": "fold-2"}],
                "sources": {"scorer": {"path": str(ROOT / "score.py")},
                            "inputs": {"path": str(ROOT / "data" / "inputs.csv")}}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "fold-1" / "persistence-v1").mkdir(parents=True)
            with patch.object(compare, "_validated_plan", return_value=plan), \
                 patch.object(compare, "_checked_manifest") as check, \
                 patch.object(compare, "build_report", return_value={"complete": True}) as report, \
                 patch.object(compare.subprocess, "run", return_value=Mock(returncode=0)) as process, \
                 redirect_stdout(StringIO()):
                self.assertEqual(compare.execute_study(output_dir=root), {"complete": True})
                self.assertEqual(process.call_count, 7)
                self.assertEqual(check.call_count, 8)
                report.assert_called_once()
                for call in process.call_args_list:
                    command = call.args[0]
                    self.assertIn("--measure-attribution", command)
                    self.assertIn(command[command.index("--period") + 1], ("fold-1", "fold-2"))
            failure = root / "failed"
            failure.mkdir()
            with patch.object(compare, "_validated_plan", return_value=plan), \
                 patch.object(compare, "build_report") as report, \
                 patch.object(compare.subprocess, "run", return_value=Mock(returncode=1)) as process, \
                 redirect_stdout(StringIO()):
                with self.assertRaisesRegex(ValueError, "no automatic retry"):
                    compare.execute_study(output_dir=failure)
                process.assert_called_once()
                report.assert_not_called()
            with patch.object(compare, "_validated_plan", return_value=plan), \
                 patch.object(compare, "_checked_manifest", side_effect=ValueError("incomplete run")), \
                 patch.object(compare.subprocess, "run") as process:
                with self.assertRaisesRegex(ValueError, "incomplete run"):
                    compare.execute_study(output_dir=root)
                process.assert_not_called()


@unittest.skipUnless(importlib.util.find_spec("lightgbm") is not None, "optional LightGBM not installed")
class RefinementWorkflowTests(unittest.TestCase):
    def test_registered_refinements_native_scoring_and_pooled_report(self):
        from forecast_engine.tests.test_lightgbm import ml_fixture

        data, config, _ = ml_fixture()
        folds = tuple(ChronologicalFold(
            RunConfig(config.label_start_utc, config.fit_cutoff_utc + pd.Timedelta(hours=2 * i),
                      config.fit_cutoff_utc + pd.Timedelta(hours=2 * i)),
            config.fit_cutoff_utc + pd.Timedelta(hours=2 * i),
            config.fit_cutoff_utc + pd.Timedelta(hours=2 * i + 2)) for i in range(2))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "data"
            inputs.mkdir()
            data.series.to_csv(inputs / "inputs.csv", index=False)
            data.spot.to_csv(inputs / "spot_nordpool.csv", index=False)
            previous = root / "previous"
            with patch.object(compare, "expanding_window_folds", return_value=folds):
                prior = compare.write_plan(starter_dir=ROOT, data_dir=inputs, output_dir=previous)
            (previous / "comparison.json").write_text("{}")
            lineage = {"plan": evaluation._file_record(previous / "study_plan.json"),
                       "report": evaluation._file_record(previous / "comparison.json")}
            output = root / "refinements"
            with patch.object(compare, "_prior_evidence", return_value=(lineage, prior)), \
                 patch.object(compare, "expanding_window_folds", return_value=folds):
                plan = compare.write_plan(starter_dir=ROOT, data_dir=inputs, output_dir=output,
                                          stage="4b", previous_study=previous)
            self.assertEqual((plan["allocated_4a"], plan["allocated_4b"], plan["reserved_4b"]), (4, 2, 0))
            self.assertEqual(len(plan["recipes"]), 3)
            for number, fold in enumerate(folds, 1):
                for identity in ("persistence-v1", *compare._recipes(plan)):
                    predictor = None if identity == "persistence-v1" else ALL_RECIPES[identity].predictor()
                    manifest = run.run_experiment(starter_dir=ROOT, data_dir=inputs,
                        output_dir=output / f"fold-{number}" / identity, fold=fold,
                        predictor=predictor, recipe_id=identity, measure_attribution=True)
                    self.assertEqual(manifest["status"], "complete")
            with patch.object(compare, "_prior_evidence", return_value=(lineage, prior)):
                report = compare.build_report(output_dir=output)
                self.assertEqual((report["recipes_used"], report["recipes_reserved_4b"]), (6, 0))
                self.assertIn(report["selection"]["selected_recipe"], ("persistence-v1", *compare._recipes(plan)))
                self.assertEqual(report["selected_configuration"]["recipe_id"], report["selection"]["selected_recipe"])
                for result in report["results"].values():
                    self.assertEqual(result["losses"]["pooled"]["rows_scored_price"], 24)
                manifest_path = output / "fold-1" / "relative-rounds60-v1" / "run_manifest.json"
                manifest = json.loads(manifest_path.read_text())
                manifest["model_configuration"]["heads"][0]["num_boost_round"] = 30
                manifest_path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, "parameters mismatch"):
                    compare.build_report(output_dir=output)


if __name__ == "__main__":
    unittest.main()
