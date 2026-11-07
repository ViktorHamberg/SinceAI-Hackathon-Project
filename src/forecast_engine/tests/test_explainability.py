"""Synthetic native attribution checks; numerical records never enter public results."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import FrozenInstanceError, fields, replace
from io import StringIO
import importlib.util
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from forecast_engine import ForecastInputs, ForecastResult, forecast
from forecast_engine.explainability.contributions import (
    AttributionUnavailable, _compare_contributions, _explain, _group_contributions,
    _native_contributions,
)
from forecast_engine.explainability.records import SignedContribution
from forecast_engine.explainability.records import ContributionRecord, ExplanationBatch, Transformation, UnavailableContribution
from forecast_engine.explainability.drivers import _top_drivers
from forecast_engine.features import build_features
from forecast_engine.features.registry import CATEGORIES, REGISTRY_VERSION
from forecast_engine.models import PersistencePredictor
from forecast_engine.models.heads import fit_head, load_lightgbm
from forecast_engine.models.lightgbm import LightGBMPredictor
from forecast_engine.tests.test_lightgbm import ml_fixture


class AttributionUtilityTests(unittest.TestCase):
    def test_signed_grouping_preserves_cancellation_and_zero_categories(self):
        terms = (SignedContribution("fi_imbalance_price_latest", 4.),
                 SignedContribution("fi_imbalance_price_mean_60m", -4.),
                 SignedContribution("horizon_step", -2.))
        grouped = {t.name: t.value for t in _group_contributions(terms)}
        self.assertEqual(grouped, {"historical_prices": 0., "calendar_horizon": -2.})
        self.assertEqual(sum(t.value for t in terms), sum(grouped.values()))
        with self.assertRaises(AttributionUnavailable):
            _group_contributions((SignedContribution("unknown", 1.),))
        with self.assertRaises(AttributionUnavailable):
            _group_contributions((SignedContribution("horizon_step", np.inf),))

    def test_import_is_lazy_and_performs_no_external_work(self):
        script = '''
import sys, os, importlib.abc
class NoOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'lightgbm', 'scipy', 'pandas', 'numpy'}:
            raise ImportError('heavy dependency blocked')
sys.meta_path.insert(0, NoOptional())
def audit(event, args):
    if event == 'open':
        path, mode, flags = args
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            raise AssertionError('write')
        if isinstance(path, (str, bytes)) and not os.fsdecode(path).endswith(('.py', '.pyc')):
            raise AssertionError('noncode read')
    if event in {'subprocess.Popen', 'socket.connect', 'os.mkdir'}:
        raise AssertionError('external work')
sys.addaudithook(audit)
import forecast_engine.explainability.contributions
assert not {'lightgbm', 'scipy', 'numpy', 'pandas'}.intersection(sys.modules)
'''
        with tempfile.TemporaryDirectory() as workdir:
            result = subprocess.run([sys.executable, '-I', '-B', '-c', script], cwd=workdir,
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, '')


def driver_record(terms=(), *, offset=None, base=0.):
    """Invented complete P50 decomposition for deterministic selector tests."""
    raw = base + sum(t.value for t in terms)
    output = raw + (offset or 0.)
    ledger = [Transformation("price_path_primary", raw, raw, "EUR/MWh", "EUR/MWh")]
    if offset is not None:
        ledger.append(Transformation("spot_reconstruction", raw, output, "EUR/MWh", "EUR/MWh",
                                     offset=offset, category="spot_price_conditions"))
    ledger += [Transformation("calibration_identity", output, output, "EUR/MWh", "EUR/MWh"),
               Transformation("preserve_p50_clamp_outer_bounds", output, output, "EUR/MWh", "EUR/MWh",
                              context=(SignedContribution("p50", output),))]
    origin = pd.Timestamp("2026-08-24T00:00Z")
    return ContributionRecord(origin, origin, 1, "p50", None, "primary_p50", "synthetic", "0" * 64,
                              "synthetic", (), 1, REGISTRY_VERSION, "direct" if offset is None else "spot_relative",
                              "raw_price" if offset is None else "raw_spread", "EUR/MWh", "EUR/MWh",
                              base, raw, output, tuple(terms), _group_contributions(terms), tuple(ledger))


class DriverSelectionTests(unittest.TestCase):
    def test_ranks_signed_category_sums_with_stable_ties_and_three_category_limit(self):
        terms = (SignedContribution("fi_imbalance_price_latest", 4.),
                 SignedContribution("fi_imbalance_price_mean_60m", -4.),
                 SignedContribution("fi_consumption_latest", -9.),
                 SignedContribution("fi_wind_fc_da_delivery", 9.),
                 SignedContribution("fi_mfrr_direction_latest", -7.),
                 SignedContribution("horizon_step", 3.))
        expected = "consumption;renewable_production;balancing_conditions"
        self.assertEqual(_top_drivers(driver_record(terms)), expected)
        self.assertEqual(_top_drivers(driver_record(tuple(reversed(terms)))), expected)

    def test_spot_offset_joins_its_learned_category_once_with_signed_cancellation(self):
        terms = (SignedContribution("fi_spot_price_delivery", 8.),
                 SignedContribution("fi_imbalance_price_latest", 4.))
        self.assertEqual(_top_drivers(driver_record(terms, offset=-8.)), "historical_prices")
        terms = (SignedContribution("fi_spot_price_delivery", 2.),
                 SignedContribution("fi_imbalance_price_latest", 9.))
        self.assertEqual(_top_drivers(driver_record(terms, offset=8.)), "spot_price_conditions;historical_prices")

    def test_zero_effects_and_bias_only_predictions_have_no_drivers(self):
        self.assertIsNone(_top_drivers(driver_record(base=42.)))
        self.assertIsNone(_top_drivers(driver_record((SignedContribution("horizon_step", 0.),))))
        self.assertIsNone(_top_drivers(driver_record((SignedContribution("fi_spot_price_delivery", 8.),), offset=-8.)))

    def test_incomplete_foreign_or_unsupported_explanations_are_blank_without_logging(self):
        record = driver_record((SignedContribution("horizon_step", 1.),), offset=9876543.21)
        self.assertEqual(_top_drivers(record), "spot_price_conditions;calendar_horizon")
        variants = [None, replace(record, head="p10"), replace(record, class_name="up"),
                    replace(record, scope="raw_class_margin", unit="raw_margin"),
                    replace(record, scope=None, target_mode="unknown", component_id="unknown"),
                    replace(record, registry_version="unknown"), replace(record, output_value=record.output_value+1),
                    replace(record, base_value=np.nan), replace(record, features=(*record.features, *record.features)),
                    replace(record, categories=(SignedContribution("PRIVATE_9876543.21", 1.),)),
                    replace(record, transformations=record.transformations[:-1]),
                    replace(record, transformations=(*record.transformations[:2], *record.transformations[1:])),
                    replace(record, transformations=(record.transformations[0],
                            replace(record.transformations[1], offset=0.), *record.transformations[2:])),
                    replace(record, transformations=(*record.transformations[:-2],
                            replace(record.transformations[-2], kind="calibration_unknown"), record.transformations[-1]))]
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            for invalid in variants:
                self.assertIsNone(_top_drivers(invalid))
        self.assertEqual(out.getvalue() + err.getvalue(), "")


@unittest.skipUnless(importlib.util.find_spec("lightgbm") is not None, "optional LightGBM not installed")
class NativeAttributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.config, cls.recipe = ml_fixture()
        cls.direct = LightGBMPredictor(recipe=cls.recipe, min_training_rows=10).fit(cls.data, config=cls.config)
        cls.relative = LightGBMPredictor(recipe=cls.recipe, min_training_rows=10,
                                       target_mode="spot_relative").fit(cls.data, config=cls.config)
        cls.origin = cls.config.fit_cutoff_utc

    def records(self, fitted=None, data=None, origins=None):
        return _explain(fitted or self.direct, data or self.data, origins=origins or [self.origin])

    def assert_reconstructs(self, record):
        self.assertAlmostEqual(record.base_value + sum(t.value for t in record.features), record.raw_output, places=9)
        self.assertAlmostEqual(sum(t.value for t in record.features),
                               sum(t.value for t in record.categories), places=9)
        current, unit = record.raw_output, record.unit
        for transform in record.transformations:
            self.assertAlmostEqual(transform.input_value, current, places=9)
            self.assertEqual(transform.input_unit, unit)
            if transform.kind == "spot_reconstruction":
                self.assertAlmostEqual(transform.input_value + transform.offset, transform.output_value, places=9)
                self.assertEqual(transform.category, "spot_price_conditions")
            if transform.kind == "softmax":
                margins = np.array([t.value for t in transform.context])
                probabilities = np.exp(margins - margins.max())
                probabilities /= probabilities.sum()
                labels = [t.name for t in transform.context]
                self.assertAlmostEqual(probabilities[labels.index(record.class_name)], transform.output_value, places=12)
            current, unit = transform.output_value, transform.output_unit
        self.assertAlmostEqual(current, record.output_value, places=9)
        self.assertEqual(unit, record.output_unit)

    def test_all_heads_and_classes_reconstruct_public_predictions_on_correct_scales(self):
        for fitted in (self.direct, self.relative):
            batch = self.records(fitted)
            self.assertFalse(batch.unavailable)
            self.assertEqual(len(batch.records), 360)
            public = forecast(fitted, self.data, origins=[self.origin]).forecasts
            for record in batch.records:
                self.assert_reconstructs(record)
                self.assertEqual(len(record.model_sha256), 64)
                self.assertGreater(record.iterations, 0)
                self.assertLessEqual(record.iterations, self.recipe.num_boost_round)
                self.assertEqual(dict(record.recipe)["seed"], self.recipe.seed)
                self.assertEqual(tuple(t.name for t in record.features), fitted._feature_names)
                row = public.iloc[record.step - 1]
                if record.class_name is None:
                    self.assertEqual(record.unit, "EUR/MWh")
                    self.assertAlmostEqual(record.output_value, row[record.head], places=9)
                else:
                    self.assertEqual(record.scope, "raw_class_margin")
                    self.assertEqual(record.unit, "raw_margin")
                    self.assertEqual(record.output_unit, "probability")
                    if record.head == "direction":
                        expected = row[f"p_{record.class_name}"]
                    elif record.class_name == "neither":
                        expected = 1 - row.p_spike_high - row.p_spike_low
                    else:
                        expected = row[f"p_spike_{record.class_name}"]
                    self.assertAlmostEqual(record.output_value, expected, places=12)

    def test_contributions_vary_with_predictions_for_a_nonconstant_native_head(self):
        matrix = build_features(self.data, origins=[self.origin]).frame[list(self.direct._feature_names)]
        head = fit_head("p50", matrix, matrix.horizon_step * 5 - 100,
                        recipe=self.recipe, quantile=.5)
        fitted = replace(self.direct, _heads=(self.direct._heads[0], head, *self.direct._heads[2:]))
        batch = self.records(fitted)
        self.assertFalse(batch.unavailable)
        rows = [r for r in batch.records if r.head == "p50"]
        self.assertGreater(len({r.raw_output for r in rows}), 1)
        self.assertGreater(len({r.features for r in rows}), 1)
        self.assertEqual(len({r.base_value for r in rows}), 1)
        for r in rows:
            self.assert_reconstructs(r)

    def test_nonconstant_multiclass_heads_preserve_class_blocks_and_raw_margin_scales(self):
        matrix = build_features(self.data, origins=[self.origin]).frame[list(self.direct._feature_names)]
        labels = (matrix.horizon_step // 14).clip(upper=2)
        classifier_heads = tuple(fit_head(head.name, matrix, labels, recipe=self.recipe, classes=head.classes)
                                 for head in self.direct._heads[3:])
        fitted = replace(self.direct, _heads=(*self.direct._heads[:3], *classifier_heads))
        batch = self.records(fitted)
        self.assertFalse(batch.unavailable)
        native = load_lightgbm()
        for head in classifier_heads:
            model = native.Booster(model_str=head._model_text)
            raw = model.predict(matrix, raw_score=True, num_threads=1)
            probabilities = head.predict(matrix)
            self.assertFalse(np.allclose(raw[:, 0], raw[:, 1]))
            rows = [r for r in batch.records if r.head == head.name]
            self.assertTrue(any(t.value != 0 for r in rows for t in r.features))
            for r in rows:
                column = head.classes.index(r.class_name)
                self.assertAlmostEqual(r.raw_output, raw[r.step - 1, column], places=12)
                self.assertAlmostEqual(r.output_value, probabilities[r.step - 1, column], places=12)
                self.assert_reconstructs(r)

    def test_mixed_spot_paths_use_active_heads_and_ignore_unpublished_inputs(self):
        spot = self.data.spot.copy()
        future = spot.timestamp_utc.ge(self.origin)
        late = future & spot.timestamp_utc.dt.minute.eq(15)
        missing = future & spot.timestamp_utc.dt.minute.eq(0)
        spot.loc[late, "first_usable_origin_utc"] = self.origin + pd.Timedelta(hours=1)
        spot.loc[missing, "value"] = np.nan
        spot.loc[future & spot.timestamp_utc.dt.minute.eq(30), "first_usable_origin_utc"] = self.origin
        data = ForecastInputs(self.data.series, spot)
        batch = self.records(self.relative, data)
        self.assertFalse(batch.unavailable)
        prices = [r for r in batch.records if r.class_name is None]
        self.assertEqual(sum(r.component_id.startswith("direct_backup_") for r in prices), 60)
        self.assertEqual(sum(r.scope == "raw_spread" for r in prices), 60)
        direct_backup = self.records(self.direct, data)
        direct = {(r.step, r.head): r for r in direct_backup.records if r.class_name is None}
        for record in prices:
            self.assert_reconstructs(record)
            if record.component_id.startswith("direct_backup_"):
                self.assertEqual(record.model_sha256, direct[record.step, record.head].model_sha256)
                self.assertEqual(record.features, direct[record.step, record.head].features)
                self.assertEqual(record.output_value, direct[record.step, record.head].output_value)
                self.assertFalse(any(t.offset is not None for t in record.transformations))
        series = self.data.series.copy()
        hidden = series.first_usable_origin_utc.gt(self.origin)
        series.loc[hidden, "value"] = 999999.
        spot.loc[late, "value"] = -999999.
        self.assertEqual(batch, self.records(self.relative, ForecastInputs(series, spot)))
        removed = ForecastInputs(series.loc[~hidden], spot.loc[~late])
        self.assertEqual(batch, self.records(self.relative, removed))

    def test_prediction_and_input_state_stay_unchanged_with_single_batch_agreement(self):
        for fitted in (self.direct, self.relative):
            state = [h.fingerprint for h in (*fitted._heads, *fitted._direct_heads)]
            origins = [self.origin, self.origin + pd.Timedelta(hours=1)]
            before = forecast(fitted, self.data, origins=origins)
            series, spot = self.data.series.copy(deep=True), self.data.spot.copy(deep=True)
            with patch("forecast_engine.models.lightgbm.fit_head", side_effect=AssertionError("refit")):
                batch = self.records(fitted, origins=origins)
                single = tuple(r for origin in origins for r in self.records(fitted, origins=[origin]).records)
                self.assertEqual(batch.records, single)
            after = forecast(fitted, self.data, origins=origins)
            assert_frame_equal(before.forecasts, after.forecasts)
            self.assertEqual(before.provenance, after.provenance)
            self.assertTrue(all(set(text.split(";")).issubset(CATEGORIES)
                                for text in after.forecasts.top_drivers.dropna()))
            self.assertEqual([f.name for f in fields(ForecastResult)], ["forecasts", "provenance"])
            self.assertEqual(state, [h.fingerprint for h in (*fitted._heads, *fitted._direct_heads)])
            assert_frame_equal(series, self.data.series)
            assert_frame_equal(spot, self.data.spot)

    def test_completely_missing_spot_uses_only_direct_price_backup_records(self):
        batch = self.records(self.relative, ForecastInputs(self.data.series, None))
        self.assertFalse(batch.unavailable)
        prices = [r for r in batch.records if r.class_name is None]
        self.assertEqual(len(prices), 120)
        self.assertTrue(all(r.component_id.startswith("direct_backup_") and r.scope == "raw_price" for r in prices))
        self.assertTrue(all(not any(t.kind == "spot_reconstruction" for t in r.transformations) for r in prices))
        with self.assertRaisesRegex(AttributionUnavailable, "missing_direct_backup"):
            self.records(replace(self.relative, _direct_heads=()), ForecastInputs(self.data.series, None))

    def test_real_native_crossing_quantiles_record_clamp_without_moving_negative_median(self):
        matrix = build_features(self.data, origins=[self.origin]).frame[list(self.direct._feature_names)]
        heads = tuple(fit_head(q, matrix, np.full(len(matrix), value), recipe=self.recipe, quantile=alpha)
                      for q, value, alpha in (("p10", 10., .1), ("p50", -20., .5), ("p90", -50., .9)))
        fitted = replace(self.direct, _heads=(*heads, *self.direct._heads[3:]))
        batch = self.records(fitted)
        self.assertFalse(batch.unavailable)
        for r in batch.records:
            if r.class_name is None:
                self.assert_reconstructs(r)
                self.assertEqual(r.output_value, -20.)
                self.assertEqual(r.raw_output, {"p10": 10., "p50": -20., "p90": -50.}[r.head])
                self.assertEqual(r.transformations[-1].kind, "preserve_p50_clamp_outer_bounds")

    def test_relative_reconstruction_is_separate_when_spot_is_not_a_learned_feature(self):
        fitted = LightGBMPredictor(recipe=self.recipe, min_training_rows=10, target_mode="spot_relative",
                                   feature_names=("horizon_step",)).fit(self.data, config=self.config)
        batch = self.records(fitted)
        self.assertFalse(batch.unavailable)
        for r in batch.records:
            if r.class_name is None:
                self.assertEqual([t.name for t in r.features], ["horizon_step"])
                self.assertEqual([t.name for t in r.categories], ["calendar_horizon"])
                offset = next(t for t in r.transformations if t.kind == "spot_reconstruction")
                self.assertEqual(offset.category, "spot_price_conditions")
                self.assert_reconstructs(r)

    def test_same_delivery_comparison_requires_matching_frozen_head_and_scope(self):
        for fitted in (self.direct, self.relative):
            batch = self.records(fitted, origins=[self.origin, self.origin + pd.Timedelta(hours=1)])
            for head, label in (("p50", None), ("direction", "up")):
                a = next(r for r in batch.records if r.forecast_origin_utc == self.origin and r.step == 5
                         and r.head == head and r.class_name == label)
                b = next(r for r in batch.records if r.forecast_origin_utc > self.origin and r.step == 1
                         and r.head == head and r.class_name == label)
                delta = _compare_contributions(a, b)
                self.assertAlmostEqual(delta.base_delta + sum(t.value for t in delta.features), delta.raw_output_delta)
                self.assertAlmostEqual(sum(t.value for t in delta.categories), sum(t.value for t in delta.features))
                self.assertEqual(delta.output_delta, b.output_value - a.output_value)
                for other in (replace(b, model_sha256="different"), replace(b, component_id="different"),
                              replace(b, registry_version="different"), replace(b, class_name="different"),
                              replace(b, delivery_start_utc=b.delivery_start_utc + pd.Timedelta(minutes=15))):
                    with self.assertRaises(AttributionUnavailable):
                        _compare_contributions(a, other)

    def test_unsupported_policies_and_components_report_unavailable_without_fabrication(self):
        for fitted in (replace(self.direct, _quantile_policy="unknown"),
                       replace(self.direct, _registry_version="unknown"),
                       PersistencePredictor().fit(self.data, config=self.config)):
            with self.assertRaises(AttributionUnavailable):
                self.records(fitted)
        original = _native_contributions

        def unavailable(head, matrix):
            if head.name == "p50":
                raise AttributionUnavailable("unsupported_tree_type")
            return original(head, matrix)

        with patch("forecast_engine.explainability.contributions._native_contributions", unavailable):
            batch = self.records()
        self.assertEqual(len(batch.unavailable), 40)
        self.assertTrue(all(r.component_id == "primary_p50" for r in batch.unavailable))
        self.assertFalse(any(r.head == "p50" for r in batch.records))
        malformed = replace(self.relative._heads[3], classes=())
        fitted = replace(self.relative, _heads=(*self.relative._heads[:3], malformed, self.relative._heads[4]))
        batch = self.records(fitted, ForecastInputs(self.data.series, None))
        self.assertEqual(len(batch.unavailable), 40)
        self.assertTrue(all(r.component_id == "primary_direction" for r in batch.unavailable))
        self.assertFalse(any(r.head == "direction" for r in batch.records))

    def test_native_bad_layout_additivity_class_order_and_linear_trees_are_rejected_safely(self):
        head = self.direct._heads[3]
        matrix = build_features(self.data, origins=[self.origin]).frame[list(head.feature_names)]
        with self.assertRaisesRegex(AttributionUnavailable, "unsupported_head"):
            _native_contributions(replace(head, classes=tuple(reversed(head.classes))), matrix)
        native = load_lightgbm()
        for fault in ("shape", "nonfinite", "sum", "linear", "failure"):
            booster = native.Booster(model_str=head._model_text)
            proxy = Mock(wraps=booster)
            proxy.params = {**booster.params, "linear_tree": fault == "linear"}

            def predict(features, **options):
                if options.get("pred_contrib"):
                    if fault == "failure":
                        raise RuntimeError("PRIVATE_9876543.21")
                    values = booster.predict(features, **options)
                    if fault == "shape": return values[:, :-1]
                    if fault == "nonfinite": values[0, 0] = np.nan
                    if fault == "sum": values[0, 0] += 50
                    return values
                return booster.predict(features, **options)

            proxy.predict.side_effect = predict
            fake = SimpleNamespace(__version__=native.__version__, Booster=lambda **kwargs: proxy)
            with patch("forecast_engine.explainability.contributions.load_lightgbm", return_value=fake):
                with self.assertRaises(AttributionUnavailable) as caught:
                    _native_contributions(head, matrix)
            self.assertNotIn("9876543.21", str(caught.exception))
            if fault == "linear": proxy.predict.assert_not_called()

    def test_records_are_immutable_private_and_produce_no_logs(self):
        spot = self.data.spot.copy()
        spot.loc[spot.timestamp_utc.ge(self.origin), "value"] = 9876543.21
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            batch = self.records(self.relative, ForecastInputs(self.data.series, spot))
        self.assertEqual(out.getvalue() + err.getvalue(), "")
        r = next(r for r in batch.records if r.head == "p50")
        for item in (batch, r, r.features[0], r.categories[0], r.transformations[1]):
            self.assertNotIn("9876543.21", repr(item))
        with self.assertRaises(FrozenInstanceError): r.base_value = 1
        with self.assertRaises(FrozenInstanceError): r.features[0].value = 1
        with self.assertRaises(FrozenInstanceError): r.transformations[1].offset = 1
        self.assertIsInstance(batch.records, tuple)
        self.assertIsInstance(r.features, tuple)
        self.assertIsInstance(r.transformations, tuple)

    def test_integrated_drivers_preserve_numbers_state_and_reuse_prediction_features(self):
        from forecast_engine.explainability import contributions
        for fitted in (self.direct, self.relative):
            state = [h.fingerprint for h in (*fitted._heads, *fitted._direct_heads)]
            with patch("forecast_engine.explainability.drivers._driver_labels", return_value=(None,) * 40):
                baseline = forecast(fitted, self.data, origins=[self.origin])
            with patch("forecast_engine.models.lightgbm.build_features", wraps=build_features) as build, \
                 patch.object(contributions, "_native_contributions", wraps=_native_contributions) as native, \
                 patch("forecast_engine.models.lightgbm.fit_head", side_effect=AssertionError("refit")):
                result = forecast(fitted, self.data, origins=[self.origin])
            self.assertEqual(build.call_count, 1)
            self.assertTrue(all(call.args[0].name == "p50" for call in native.call_args_list))
            assert_frame_equal(baseline.forecasts.drop(columns="top_drivers"), result.forecasts.drop(columns="top_drivers"))
            self.assertEqual(baseline.provenance, result.provenance)
            self.assertEqual(state, [h.fingerprint for h in (*fitted._heads, *fitted._direct_heads)])
            if fitted._target_mode == "spot_relative":
                self.assertTrue(result.forecasts.top_drivers.notna().any())
            for text in result.forecasts.top_drivers.dropna():
                self.assertLessEqual(len(text.split(";")), 3)
                self.assertTrue(set(text.split(";")).issubset(CATEGORIES))

    def test_integrated_mixed_horizons_use_backup_drivers_and_ignore_unpublished_values(self):
        matrix = build_features(self.data, origins=[self.origin]).frame[list(self.direct._feature_names)]
        head = fit_head("p50", matrix, matrix.horizon_step * 5 - 100, recipe=self.recipe, quantile=.5)
        fitted = replace(self.relative, _direct_heads=(self.relative._direct_heads[0], head, self.relative._direct_heads[2]))
        spot = self.data.spot.copy()
        late = spot.timestamp_utc.ge(self.origin) & spot.timestamp_utc.dt.minute.eq(15)
        missing = spot.timestamp_utc.ge(self.origin) & spot.timestamp_utc.dt.minute.eq(0)
        spot.loc[late, "first_usable_origin_utc"] = self.origin + pd.Timedelta(hours=1)
        spot.loc[missing, "value"] = np.nan
        data = ForecastInputs(self.data.series, spot)
        result = forecast(fitted, data, origins=[self.origin])
        private = self.records(fitted, data)
        for record in private.records:
            if record.head != "p50": continue
            actual = result.forecasts.top_drivers.iloc[record.step - 1]
            expected = _top_drivers(record)
            self.assertTrue(pd.isna(actual) if expected is None else actual == expected)
            if record.component_id == "direct_backup_p50":
                self.assertEqual(actual, "calendar_horizon")
        spot.loc[late, "value"] = 9876543.21
        changed = forecast(fitted, ForecastInputs(self.data.series, spot), origins=[self.origin])
        assert_frame_equal(result.forecasts, changed.forecasts)
        without_spot = forecast(fitted, ForecastInputs(self.data.series, None), origins=[self.origin])
        self.assertTrue(without_spot.forecasts.top_drivers.eq("calendar_horizon").all())

    def test_integrated_unavailable_p50_and_unknown_transforms_leave_text_blank(self):
        def unavailable(head, matrix):
            raise AttributionUnavailable("native_attribution_unavailable")
        with patch("forecast_engine.explainability.contributions._native_contributions", unavailable):
            result = forecast(self.relative, self.data, origins=[self.origin])
        self.assertTrue(result.forecasts.top_drivers.isna().all())
        result = forecast(replace(self.relative, _quantile_policy="unknown"), self.data, origins=[self.origin])
        self.assertTrue(result.forecasts.top_drivers.isna().all())

    def test_driver_binding_rejects_duplicate_foreign_missing_and_blocked_records(self):
        batch = self.records(self.relative)
        record = next(r for r in batch.records if r.head == "p50" and _top_drivers(r) is not None)
        others = tuple(r for r in batch.records if r is not record)
        variants = [ExplanationBatch((*batch.records, record), ()), ExplanationBatch(others, ()),
                    ExplanationBatch((*others, replace(record, model_sha256="foreign")), ()),
                    ExplanationBatch(batch.records, (UnavailableContribution(record.forecast_origin_utc,
                        record.delivery_start_utc, record.step, record.component_id, "native_attribution_unavailable"),))]
        for invalid in variants:
            with patch("forecast_engine.explainability.drivers._explain_prepared", return_value=invalid):
                result = forecast(self.relative, self.data, origins=[self.origin])
            self.assertTrue(pd.isna(result.forecasts.top_drivers.iloc[record.step - 1]))


if __name__ == "__main__":
    unittest.main()
