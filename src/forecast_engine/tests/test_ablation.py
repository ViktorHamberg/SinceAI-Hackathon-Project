"""Synthetic verification of preregistration, measured cohorts and matched scoring."""

import importlib.util
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from forecast_engine import ForecastInputs, RunConfig, forecast
from forecast_engine.experiments import compare, run
from forecast_engine.experiments.recipes import RECIPES
from forecast_engine.features import build_features
from forecast_engine.features.training import ChronologicalFold
from forecast_engine.tests.test_features import long_rows

ROOT = Path(__file__).resolve().parents[3]


class AblationPolicyTests(unittest.TestCase):
    def test_recipe_cli_passes_registered_configuration_and_explicit_measurement(self):
        with patch.object(run, "run_experiment", return_value={"forecast_rows": 80}) as execute, redirect_stdout(StringIO()):
            self.assertEqual(run.main(["--recipe", "relative-wind-load-v1", "--period", "fold-1",
                                       "--measure-attribution", "--output-dir", "unused"]), 0)
        arguments = execute.call_args.kwargs
        self.assertEqual(arguments["recipe_id"], "relative-wind-load-v1")
        self.assertEqual(arguments["predictor"].feature_names, RECIPES["relative-wind-load-v1"].features)
        self.assertTrue(arguments["measure_attribution"])

    def test_four_fixed_recipes_share_tree_settings_and_registered_features(self):
        self.assertEqual(len(RECIPES), 4)
        predictors = [r.predictor() for r in RECIPES.values()]
        self.assertTrue(all(p.recipe == predictors[0].recipe for p in predictors))
        self.assertEqual(predictors[0].feature_names, predictors[1].feature_names)
        self.assertEqual(len(predictors[2].feature_names) - len(predictors[1].feature_names), 2)
        self.assertEqual(len(predictors[3].feature_names) - len(predictors[1].feature_names), 8)
        with self.assertRaises(TypeError):
            RECIPES["extra"] = None

    def test_retention_requires_practical_loss_gain_and_fold_consistency_not_coverage(self):
        reference = {scope: {m: 1. for m in run.METRICS} for scope in ("fold-1", "fold-2", "pooled")}
        candidate = {scope: dict(values) for scope, values in reference.items()}
        self.assertFalse(compare._passes(candidate, reference))
        candidate["pooled"]["mae_p50"] = .98
        self.assertTrue(compare._passes(candidate, reference))
        candidate["fold-1"]["brier_spike_mean"] = 1.02
        self.assertFalse(compare._passes(candidate, reference))
        candidate["fold-1"]["brier_spike_mean"] = 1.
        candidate["pooled"]["mae_p50"] = .999
        self.assertFalse(compare._passes(candidate, reference))
        candidate["pooled"]["mae_p50"] = None
        self.assertFalse(compare._passes(candidate, reference))

    def test_spot_subset_uses_exact_delivery_and_publication_inclusively(self):
        origin = pd.Timestamp("2026-08-24T00:00Z")
        delivery = origin + pd.Timedelta(hours=1)
        data = ForecastInputs(long_rows(), long_rows(("fi_spot_price", delivery, delivery, 9876543.21)))
        frame = pd.DataFrame({"forecast_origin_utc": [origin, delivery, delivery],
                              "delivery_start_utc": [delivery, delivery, delivery + pd.Timedelta(minutes=15)]})
        self.assertEqual(list(run._spot_mask(data, frame)), [False, True, False])
        self.assertFalse(run._spot_mask(ForecastInputs(data.series), frame).any())

    def test_optional_features_obey_availability_and_preserve_exact_evidence(self):
        origin = pd.Timestamp("2026-08-24T00:00Z")
        future = origin + pd.Timedelta(hours=1)
        data = ForecastInputs(long_rows(
            ("fi_wind_fc_da", origin, origin, 100.),
            ("fi_consumption_fc_da", origin, future, 200.),
            ("fi_mfrr_up_price", origin - pd.Timedelta(minutes=15), origin, 300.),
        ))
        names = tuple(dict.fromkeys(n for r in RECIPES.values() for n in r.features))
        before = build_features(data, origins=[origin], feature_names=names)
        frame = data.series.copy()
        frame.loc[frame.first_usable_origin_utc.gt(origin), "value"] = 9876543.21
        after = build_features(ForecastInputs(frame), origins=[origin], feature_names=names)
        pd.testing.assert_frame_equal(before.frame, after.frame)
        self.assertEqual(before.evidence, after.evidence)
        self.assertTrue(before.frame.fi_consumption_fc_da_delivery.isna().all())
        self.assertEqual(before.frame.fi_wind_fc_da_delivery.iloc[0], 100.)
        for record in before.evidence:
            for evidence in record.dependencies:
                self.assertTrue(all(s.first_usable_origin_utc <= origin for s in evidence.sources))


@unittest.skipUnless(importlib.util.find_spec("lightgbm") is not None, "optional LightGBM not installed")
class AblationWorkflowTests(unittest.TestCase):
    def test_preregistered_native_fold_study_and_pooled_tail_protection(self):
        from forecast_engine.tests.test_lightgbm import ml_fixture

        data, config, _ = ml_fixture()
        series = data.series.copy()
        spot = data.spot.copy()
        late = spot.timestamp_utc.ge(config.fit_cutoff_utc) & spot.timestamp_utc.dt.minute.eq(15)
        spot.loc[late, "first_usable_origin_utc"] = config.fit_cutoff_utc + pd.Timedelta(hours=1)
        folds = (ChronologicalFold(config, config.fit_cutoff_utc, config.fit_cutoff_utc + pd.Timedelta(hours=2)),
                 ChronologicalFold(RunConfig(config.label_start_utc, config.fit_cutoff_utc + pd.Timedelta(hours=2),
                                            config.fit_cutoff_utc + pd.Timedelta(hours=2)),
                                   config.fit_cutoff_utc + pd.Timedelta(hours=2),
                                   config.fit_cutoff_utc + pd.Timedelta(hours=4)))
        with tempfile.TemporaryDirectory() as workdir:
            directory = Path(workdir)
            inputs, output = directory / "data", directory / "study"
            inputs.mkdir()
            series.to_csv(inputs / "inputs.csv", index=False)
            spot.to_csv(inputs / "spot_nordpool.csv", index=False)
            with patch.object(compare, "expanding_window_folds", return_value=folds):
                plan = compare.write_plan(starter_dir=ROOT, data_dir=inputs, output_dir=output)
            self.assertEqual((plan["allocated_4a"], plan["reserved_4b"]), (4, 2))
            with self.assertRaises(ValueError):
                compare.write_plan(starter_dir=ROOT, data_dir=inputs, output_dir=output)
            for number, fold in enumerate(folds, 1):
                for identity in ("persistence-v1", *RECIPES):
                    predictor = None if identity == "persistence-v1" else RECIPES[identity].predictor()
                    manifest = run.run_experiment(starter_dir=ROOT, data_dir=inputs,
                        output_dir=output / f"fold-{number}" / identity, fold=fold,
                        predictor=predictor, recipe_id=identity, measure_attribution=True)
                    self.assertEqual(manifest["status"], "complete")
                    self.assertGreaterEqual(manifest["timings"]["attribution"], 0.)
                    self.assertLessEqual(manifest["timings"]["attribution"], manifest["timings"]["predict"])
                    self.assertLess(manifest["shared_spot"]["forecast_rows"], manifest["forecast_rows"])
                    if identity != "persistence-v1":
                        self.assertGreater(manifest["timings"]["attribution"], 0.)
                    self.assertNotIn("_model_text", json.dumps(manifest))
            report = compare.build_report(output_dir=output)
            self.assertIn(report["selection"]["selected_recipe"], ("persistence-v1", *RECIPES))
            for result in report["results"].values():
                self.assertEqual(result["losses"]["pooled"]["rows_scored_price"], 24)
                self.assertEqual(result["losses"]["pooled"]["rows_scored_price"],
                                 sum(f["metrics"]["rows_scored_price"] for f in result["folds"]))
                self.assertTrue(result["pooled_horizons"])
            self.assertTrue((output / "comparison" / "comparison.md").is_file())
            with self.assertRaises(ValueError):
                compare.build_report(output_dir=output)
            manifest_path = output / "fold-1" / "relative-control-v1" / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["metrics"]["mae_p50"] = 0.
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "official score"):
                compare.build_report(output_dir=output)


if __name__ == "__main__":
    unittest.main()
