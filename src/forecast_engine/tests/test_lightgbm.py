"""Synthetic learned-head tests. Native tests require the approved optional ml setup."""

from dataclasses import FrozenInstanceError, replace
import importlib.util
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from forecast_engine import ForecastInputs, RunConfig, forecast, validate_forecasts
from forecast_engine.availability import MissingEvidenceError
from forecast_engine.features import build_features
from forecast_engine.models.heads import TreeRecipe, load_lightgbm
from forecast_engine.models.lightgbm import LightGBMPredictor
from forecast_engine.tests.test_features import long_rows


def ml_fixture():
    """Invented labels include each direction and strict high/low/neither spikes."""
    cutoff = pd.Timestamp("2026-08-24T00:00Z")
    records, spot = [], []
    for index, delivery in enumerate(pd.date_range(cutoff - pd.Timedelta(hours=12), periods=88, freq="15min")):
        publication = (delivery + pd.Timedelta(minutes=15)).ceil("h")
        reference = float(index % 5 - 2)
        price = reference + (-80., 0., 80.)[index % 3]
        records.extend([("fi_imbalance_price", delivery, publication, price),
                        ("fi_mfrr_direction", delivery, publication, (1, -1, 0)[index % 3])])
        spot.append(("fi_spot_price", delivery, cutoff - pd.Timedelta(days=1), reference))
    data = ForecastInputs(long_rows(*records), long_rows(*spot))
    config = RunConfig(RunConfig.validation().label_start_utc, cutoff, cutoff)
    recipe = TreeRecipe(num_boost_round=5, num_leaves=4, min_data_in_leaf=3)
    return data, config, recipe


class RecipeTests(unittest.TestCase):
    def test_invalid_recipes_and_feature_selections_are_rejected(self):
        for options in ({"num_boost_round": 0}, {"num_leaves": 1}, {"seed": -1},
                        {"learning_rate": np.nan}, {"l2_regularization": -1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                TreeRecipe(**options)
        with self.assertRaises(ValueError):
            LightGBMPredictor(feature_names=("delivery_hour_local",))
        with self.assertRaises(ValueError):
            LightGBMPredictor(min_training_rows=0)
        with self.assertRaises(ValueError):
            LightGBMPredictor(target_mode="unknown")
        with self.assertRaises(FrozenInstanceError):
            TreeRecipe().seed = 4

    def test_missing_native_dependency_has_safe_diagnostic(self):
        with patch("forecast_engine.models.heads.importlib.import_module", side_effect=OSError("PRIVATE_VALUE")):
            with self.assertRaises(ImportError) as caught:
                load_lightgbm()
        self.assertNotIn("PRIVATE_VALUE", str(caught.exception))


@unittest.skipUnless(importlib.util.find_spec("lightgbm") is not None, "approved optional LightGBM is not installed")
class LightGBMTests(unittest.TestCase):
    def setUp(self):
        self.data, self.config, self.recipe = ml_fixture()

    def model(self, **options):
        return LightGBMPredictor(recipe=self.recipe, min_training_rows=10, **options)

    def fit(self):
        return self.model().fit(self.data, config=self.config)

    def test_all_five_heads_complete_valid_forecasts_and_class_mapping(self):
        fitted = self.fit()
        self.assertEqual([h.name for h in fitted._heads], ["p10", "p50", "p90", "direction", "spike"])
        result = forecast(fitted, self.data, origins=[self.config.fit_cutoff_utc])
        validate_forecasts(result.forecasts, origins=[self.config.fit_cutoff_utc])
        self.assertEqual(len(result.forecasts), 40)
        self.assertTrue(result.forecasts.top_drivers.isna().all())
        self.assertTrue(result.forecasts.data_cutoff_utc.isna().all())
        features = build_features(self.data, origins=[self.config.fit_cutoff_utc], feature_names=fitted._feature_names)
        matrix = features.frame[list(fitted._feature_names)]
        direction = fitted._heads[3].predict(matrix)
        spike = fitted._heads[4].predict(matrix)
        np.testing.assert_array_equal(result.forecasts[["p_up", "p_down", "p_none"]], direction)
        np.testing.assert_array_equal(result.forecasts[["p_spike_high", "p_spike_low"]], spike[:, :2])

    def test_repeated_single_batch_predictions_do_not_refit_or_change_learned_state(self):
        fitted = self.fit()
        state = tuple(head.fingerprint for head in fitted._heads)
        with patch("forecast_engine.models.lightgbm.fit_head", side_effect=AssertionError("refit")):
            origins = [self.config.fit_cutoff_utc, self.config.fit_cutoff_utc + pd.Timedelta(hours=1)]
            batch = forecast(fitted, self.data, origins=origins)
            for offset, origin in enumerate(origins):
                single = forecast(fitted, self.data, origins=[origin])
                assert_frame_equal(single.forecasts, batch.forecasts.iloc[offset * 40:(offset + 1) * 40].reset_index(drop=True))
        self.assertEqual(tuple(head.fingerprint for head in fitted._heads), state)
        with self.assertRaises(TypeError):
            fitted.provenance.counts["heads"] = 99
        with self.assertRaises(FrozenInstanceError):
            fitted._target_mode = "spot_relative"

    def test_ineligible_outcome_changes_do_not_change_fit_or_predictions(self):
        first = self.fit()
        series, spot = self.data.series.copy(), self.data.spot.copy()
        series.loc[series.timestamp_utc >= self.config.label_end_utc, "value"] = 99999
        spot.loc[spot.timestamp_utc >= self.config.label_end_utc, "value"] = -99999
        changed = ForecastInputs(series, spot)
        second = self.model().fit(changed, config=self.config)
        self.assertEqual(tuple(h.fingerprint for h in first._heads), tuple(h.fingerprint for h in second._heads))
        self.assertEqual(first.provenance, second.provenance)
        # Compare prediction using identical origin-time inputs: future published
        # observations may legitimately update inference later, never the fitted state.
        a = forecast(first, self.data, origins=[self.config.fit_cutoff_utc])
        b = forecast(second, self.data, origins=[self.config.fit_cutoff_utc])
        assert_frame_equal(a.forecasts, b.forecasts)

    def test_input_detachment_and_provenance_availability(self):
        before = self.data.series.copy(deep=True)
        spot_before = self.data.spot.copy(deep=True)
        fitted = self.fit()
        forecast(fitted, self.data, origins=[self.config.fit_cutoff_utc])
        assert_frame_equal(self.data.series, before)
        assert_frame_equal(self.data.spot, spot_before)
        for dependency in fitted.provenance.dependencies:
            self.assertLessEqual(dependency.used_at_utc, self.config.fit_cutoff_utc)
            for source in dependency.sources:
                self.assertLessEqual(source.first_usable_origin_utc, source.used_at_utc)
                self.assertLessEqual(source.used_at_utc, dependency.used_at_utc)
                if dependency.name.endswith("_labels"):
                    self.assertTrue(self.config.label_start_utc <= source.timestamp_utc < self.config.label_end_utc)
        self.assertNotIn("-80", repr(fitted))

    def test_unpublished_inference_observations_cannot_change_any_head(self):
        fitted = self.fit()
        origin = self.config.fit_cutoff_utc
        baseline = forecast(fitted, self.data, origins=[origin])
        altered = self.data.series.copy()
        unpublished = altered.first_usable_origin_utc > origin
        altered.loc[unpublished, "value"] = 99999
        for series in (altered, altered.loc[~unpublished]):
            result = forecast(fitted, ForecastInputs(series, self.data.spot), origins=[origin])
            assert_frame_equal(result.forecasts, baseline.forecasts)
            self.assertEqual(result.provenance, baseline.provenance)

    def test_missing_classes_and_insufficient_rows_fail_without_fallback(self):
        no_direction = self.data.series.copy()
        no_direction.loc[no_direction.series_id.eq("fi_mfrr_direction"), "value"] = 0
        with self.assertRaisesRegex(MissingEvidenceError, "direction.*all three classes"):
            self.model().fit(ForecastInputs(no_direction, self.data.spot), config=self.config)
        with self.assertRaisesRegex(MissingEvidenceError, "spike"):
            self.model().fit(ForecastInputs(self.data.series, None), config=self.config)
        with self.assertRaises(MissingEvidenceError):
            LightGBMPredictor(recipe=self.recipe, min_training_rows=99999).fit(self.data, config=self.config)
        with patch("forecast_engine.models.heads.load_lightgbm") as native:
            native.return_value.train.side_effect = RuntimeError("PRIVATE_VALUE")
            native.return_value.Dataset.return_value = object()
            with self.assertRaisesRegex(RuntimeError, "head fitting failed") as caught:
                self.fit()
            self.assertNotIn("PRIVATE_VALUE", str(caught.exception))

    def test_partial_labels_do_not_intersect_other_tasks(self):
        series = self.data.series.copy()
        missing = series.series_id.eq("fi_mfrr_direction") & series.timestamp_utc.dt.minute.eq(0)
        series = series.loc[~missing]
        fitted = self.model().fit(ForecastInputs(series, self.data.spot), config=self.config)
        self.assertGreater(fitted.provenance.counts["training_rows_price"],
                           fitted.provenance.counts["training_rows_direction"])
        self.assertEqual(fitted.provenance.counts["training_rows_price"], fitted.provenance.counts["training_rows_spike"])

    def test_quantile_policy_preserves_median_for_crossing_negative_outputs(self):
        fitted = self.fit()
        original = type(fitted._heads[0]).predict

        def outputs(head, features):
            if head.name in {"p10", "p50", "p90"}:
                return np.full(len(features), {"p10": 10., "p50": -20., "p90": -50.}[head.name])
            return original(head, features)

        with patch.object(type(fitted._heads[0]), "predict", outputs):
            frame = forecast(fitted, self.data, origins=[self.config.fit_cutoff_utc]).forecasts
        self.assertTrue(frame[["p10", "p50", "p90"]].eq(-20).all().all())

    def test_calendar_only_features_still_have_frozen_model_evidence(self):
        fitted = self.model(feature_names=("horizon_step",)).fit(self.data, config=self.config)
        result = forecast(fitted, ForecastInputs(long_rows()), origins=[self.config.fit_cutoff_utc])
        self.assertEqual(len(result.forecasts), 40)
        self.assertEqual(result.provenance.inference[0].dependencies[0].name, "lightgbm_fitted_state")

    def test_classification_probability_errors_are_not_repaired(self):
        fitted = self.fit()
        head = fitted._heads[3]
        features = build_features(self.data, origins=[self.config.fit_cutoff_utc], feature_names=fitted._feature_names)
        with patch("forecast_engine.models.heads.load_lightgbm") as native:
            native.return_value.Booster.return_value.predict.return_value = np.ones((40, 3))
            with self.assertRaisesRegex(ValueError, "invalid probabilities"):
                head.predict(features.frame[list(fitted._feature_names)])

    def test_relative_mixed_paths_match_native_heads_and_retain_exact_evidence(self):
        fitted = self.model(target_mode="spot_relative").fit(self.data, config=self.config)
        self.assertEqual(fitted.provenance.counts["heads"], 8)
        origin = self.config.fit_cutoff_utc
        spot = self.data.spot.copy()
        future = spot.timestamp_utc.ge(origin)
        late = future & spot.timestamp_utc.dt.minute.eq(15)
        missing = future & spot.timestamp_utc.dt.minute.eq(0)
        spot.loc[late, "first_usable_origin_utc"] = origin + pd.Timedelta(hours=1)
        spot.loc[missing, "value"] = np.nan
        data = ForecastInputs(self.data.series, spot)
        features = build_features(data, origins=[origin], feature_names=fitted._feature_names)
        matrix = features.frame[list(fitted._feature_names)]
        offsets = matrix.fi_spot_price_delivery
        result = forecast(fitted, data, origins=[origin])
        for head, backup in zip(fitted._heads[:3], fitted._direct_heads):
            expected = np.where(offsets.notna(), head.predict(matrix) + offsets,
                                backup.predict(matrix))
            if head.name == "p50":
                np.testing.assert_array_equal(result.forecasts.p50, expected)
            elif head.name == "p10":
                np.testing.assert_array_equal(result.forecasts.p10, np.minimum(expected, result.forecasts.p50))
            else:
                np.testing.assert_array_equal(result.forecasts.p90, np.maximum(expected, result.forecasts.p50))
        paths = result.provenance.inference[0].dependencies[1:]
        self.assertEqual(len(paths), 40)
        self.assertEqual(sum("direct_backup" in e.name for e in paths), 20)
        for position, evidence in enumerate(paths):
            uses_spot = [s for s in evidence.sources if s.series_id == "fi_spot_price"]
            self.assertEqual(bool(uses_spot), bool(offsets.notna().iloc[position]))
            for source in uses_spot:
                self.assertEqual(source.timestamp_utc, features.frame.delivery_start_utc.iloc[position])
                self.assertLessEqual(source.first_usable_origin_utc, origin)
        components = {e.name: e for e in fitted.provenance.dependencies}
        self.assertEqual({s.series_id for s in components["lightgbm_price_labels"].sources},
                         {"fi_imbalance_price", "fi_spot_price"})
        self.assertEqual({s.series_id for s in components["lightgbm_direct_backup_labels"].sources},
                         {"fi_imbalance_price"})
        spot.loc[late, "value"] = 99999
        changed = forecast(fitted, ForecastInputs(self.data.series, spot), origins=[origin])
        assert_frame_equal(result.forecasts, changed.forecasts)
        self.assertEqual(result.provenance, changed.provenance)

    def test_relative_backup_matches_direct_model_without_changing_classifier_meanings(self):
        relative = self.model(target_mode="spot_relative").fit(self.data, config=self.config)
        direct = self.fit()
        self.assertEqual([h.fingerprint for h in relative._heads[3:]],
                         [h.fingerprint for h in direct._heads[3:]])
        self.assertEqual([h.fingerprint for h in relative._direct_heads],
                         [h.fingerprint for h in direct._heads[:3]])
        data = ForecastInputs(self.data.series, None)
        origins = [self.config.fit_cutoff_utc, self.config.fit_cutoff_utc + pd.Timedelta(hours=1)]
        state = [h.fingerprint for h in (*relative._heads, *relative._direct_heads)]
        with patch("forecast_engine.models.lightgbm.fit_head", side_effect=AssertionError("refit")):
            batch = forecast(relative, data, origins=origins)
            assert_frame_equal(batch.forecasts, forecast(direct, data, origins=origins).forecasts)
            for index, origin in enumerate(origins):
                single = forecast(relative, data, origins=[origin])
                assert_frame_equal(single.forecasts, batch.forecasts.iloc[index*40:(index+1)*40].reset_index(drop=True))
        self.assertEqual(state, [h.fingerprint for h in (*relative._heads, *relative._direct_heads)])
        with self.assertRaisesRegex(MissingEvidenceError, "direct-price backup"):
            forecast(replace(relative, _direct_heads=()), data, origins=origins)

    def test_relative_offset_remains_available_when_omitted_from_learned_features(self):
        fitted = self.model(target_mode="spot_relative", feature_names=("horizon_step",)).fit(
            self.data, config=self.config)
        original = type(fitted._heads[0]).predict

        def crossing(head, matrix):
            if not head.classes:
                return np.full(len(matrix), {"p10": 10., "p50": -20., "p90": -50.}[head.name])
            return original(head, matrix)

        with patch.object(type(fitted._heads[0]), "predict", crossing):
            result = forecast(fitted, self.data, origins=[self.config.fit_cutoff_utc])
        offsets = build_features(self.data, origins=[self.config.fit_cutoff_utc],
                                 feature_names=("fi_spot_price_delivery",)).frame.fi_spot_price_delivery
        np.testing.assert_array_equal(result.forecasts.p50, offsets - 20)
        np.testing.assert_array_equal(result.forecasts.p10, result.forecasts.p50)
        np.testing.assert_array_equal(result.forecasts.p90, result.forecasts.p50)
        self.assertTrue(result.forecasts.p50.lt(0).all())
        self.assertTrue(all("spot_relative" in e.name for e in result.provenance.inference[0].dependencies[1:]))

    def test_unreferenced_sources_do_not_change_fit_or_inference(self):
        original = self.fit()
        extra = long_rows(("fi_wind_fc_da", self.config.fit_cutoff_utc,
                           self.config.fit_cutoff_utc - pd.Timedelta(days=1), 123456.))
        expanded = ForecastInputs(pd.concat([self.data.series, extra], ignore_index=True), self.data.spot)
        fitted = self.model().fit(expanded, config=self.config)
        self.assertEqual(original.provenance, fitted.provenance)
        self.assertEqual([h.fingerprint for h in original._heads], [h.fingerprint for h in fitted._heads])
        origins = [self.config.fit_cutoff_utc]
        a, b = forecast(original, self.data, origins=origins), forecast(fitted, expanded, origins=origins)
        assert_frame_equal(a.forecasts, b.forecasts)
        self.assertEqual(a.provenance, b.provenance)


if __name__ == "__main__":
    unittest.main()
