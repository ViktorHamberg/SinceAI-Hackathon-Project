"""Target transformations use synthetic values only; no LightGBM training needed."""

from dataclasses import replace
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_series_equal

from forecast_engine import ForecastInputs, RunConfig
from forecast_engine.features import build_features
from forecast_engine.features.training import build_training_examples
from forecast_engine.models.targets import build_price_targets, reconstruct_prices
from forecast_engine.tests.test_features import long_rows


class PriceTargetTests(unittest.TestCase):
    origin = pd.Timestamp("2026-08-23T23:00Z")
    cutoff = pd.Timestamp("2026-08-24T00:00Z")

    def data(self):
        deliveries = pd.date_range(self.origin, periods=4, freq="15min")
        return ForecastInputs(long_rows(
            ("fi_imbalance_price", deliveries[0], self.cutoff, -70),
            ("fi_imbalance_price", deliveries[1], self.cutoff, -20),
            ("fi_imbalance_price", deliveries[2], self.cutoff + pd.Timedelta(hours=1), 900),
            ("fi_imbalance_price", deliveries[3], self.cutoff, 3),
            ("fi_imbalance_price", self.cutoff, self.cutoff, 900),
        ), long_rows(
            ("fi_spot_price", deliveries[0], self.origin, -100),
            ("fi_spot_price", deliveries[1], self.cutoff, 10),
            ("fi_spot_price", deliveries[2], self.origin, 20),
        ))

    def examples(self, data=None):
        return build_training_examples(
            data or self.data(), config=RunConfig(RunConfig.validation().label_start_utc,
                                                self.cutoff, self.cutoff), origins=[self.origin],
        )

    def raw(self, features):
        return pd.DataFrame(np.tile([-30., -20., -10.], (len(features.frame), 1)),
                            columns=["p10", "p50", "p90"], index=features.frame.index)

    def test_direct_targets_ignore_other_head_masks_and_missing_spot(self):
        examples = self.examples()
        before = examples.labels.copy(deep=True)
        examples = replace(examples, eligible=examples.eligible.assign(direction=False, spike=False))
        targets = build_price_targets(examples)
        self.assertEqual(targets.mode, "direct")
        self.assertEqual(targets.unit, "EUR/MWh")
        self.assertEqual(list(targets.values.iloc[[0, 1, 3]]), [-70, -20, 3])
        self.assertEqual(targets.eligible.sum(), 3)
        self.assertTrue(targets.values.iloc[4:].isna().all())
        self.assertEqual(targets.label_evidence[3], examples.label_evidence[3].price)
        assert_frame_equal(before, examples.labels)
        targets.values.iloc[0] = 123
        self.assertEqual(examples.labels.imbalance_price.iloc[0], -70)

    def test_relative_targets_require_both_cutoff_eligible_labels_and_exact_lineage(self):
        examples = self.examples()
        targets = build_price_targets(examples, mode="spot_relative")
        self.assertEqual(list(targets.values.iloc[:2]), [30, -30])
        self.assertEqual(targets.eligible.sum(), 2)
        self.assertTrue(targets.values.iloc[2:].isna().all())
        for position, dependency in enumerate(targets.label_evidence[:2]):
            self.assertEqual(dependency.used_at_utc, self.cutoff)
            self.assertEqual({s.series_id for s in dependency.sources},
                             {"fi_imbalance_price", "fi_spot_price"})
            self.assertEqual({s.timestamp_utc for s in dependency.sources},
                             {examples.label_evidence[position].delivery_start_utc})
        self.assertTrue(all(e is None for e in targets.label_evidence[2:]))

    def test_label_spot_does_not_become_a_historical_reconstruction_offset(self):
        examples = self.examples()
        targets = build_price_targets(examples, mode="spot_relative")
        result = reconstruct_prices(self.raw(examples.features), features=examples.features,
                                    mode="spot_relative")
        self.assertTrue(targets.eligible.iloc[1])  # Spot published by fitting time.
        self.assertTrue(result.requires_direct_backup.iloc[1])  # Not at the origin.
        self.assertTrue(result.prices.iloc[1].isna().all())
        self.assertIsNone(result.spot_evidence[1])

    def test_relative_reconstruction_uses_exact_published_future_delivery_spot(self):
        features = build_features(self.data(), origins=[self.origin])
        raw = self.raw(features)
        before = raw.copy(deep=True)
        result = reconstruct_prices(raw, features=features, mode="spot_relative")
        self.assertEqual(list(result.prices.iloc[0]), [-130, -120, -110])
        self.assertEqual(list(result.prices.iloc[2]), [-10, 0, 10])
        self.assertFalse(result.requires_direct_backup.iloc[2])
        source = result.spot_evidence[2].sources[0]
        self.assertGreater(source.timestamp_utc, self.origin)
        self.assertEqual(source.first_usable_origin_utc, self.origin)
        assert_frame_equal(raw, before)
        raw.iloc[0, 0] = 99
        self.assertEqual(result.prices.iloc[0].p10, -130)

    def test_direct_reconstruction_needs_no_spot_and_does_not_repair_crossings(self):
        features = build_features(self.data(), origins=[self.origin], feature_names=["horizon_step"])
        raw = self.raw(features)
        raw.iloc[0] = [3, -5, -10]
        direct = reconstruct_prices(raw, features=features)
        assert_frame_equal(direct.prices, raw)
        self.assertFalse(direct.requires_direct_backup.any())
        self.assertTrue(all(e is None for e in direct.spot_evidence))
        with self.assertRaisesRegex(ValueError, "delivery spot feature"):
            reconstruct_prices(raw, features=features, mode="spot_relative")

    def test_no_spot_yields_missing_relative_targets_and_explicit_backup_requests(self):
        data = replace(self.data(), spot=None)
        examples = self.examples(data)
        targets = build_price_targets(examples, mode="spot_relative")
        self.assertFalse(targets.eligible.any())
        self.assertTrue(targets.values.isna().all())
        result = reconstruct_prices(self.raw(examples.features), features=examples.features,
                                    mode="spot_relative")
        self.assertTrue(result.requires_direct_backup.all())
        self.assertTrue(result.prices.isna().all().all())

    def test_unavailable_value_perturbation_and_removal_leave_earlier_results_unchanged(self):
        data = self.data()
        base = self.examples(data)
        series = data.series.copy()
        series.loc[series.first_usable_origin_utc > self.cutoff, "value"] = -999
        changed = self.examples(replace(data, series=series))
        for mode in ("direct", "spot_relative"):
            expected, actual = build_price_targets(base, mode=mode), build_price_targets(changed, mode=mode)
            assert_series_equal(expected.values, actual.values)
            self.assertEqual(expected.label_evidence, actual.label_evidence)
        # A fitting label may legitimately change when eligible; here only origin-time
        # reconstruction is compared after changing/removing unpublished spot inputs.
        spots = data.spot.copy()
        spots.loc[spots.first_usable_origin_utc > self.origin, "value"] = 888
        for table in (spots, spots.loc[spots.first_usable_origin_utc <= self.origin]):
            features = build_features(replace(data, spot=table), origins=[self.origin])
            actual = reconstruct_prices(self.raw(features), features=features, mode="spot_relative")
            expected = reconstruct_prices(self.raw(base.features), features=base.features, mode="spot_relative")
            assert_frame_equal(actual.prices, expected.prices)
            assert_series_equal(actual.requires_direct_backup, expected.requires_direct_backup)
            self.assertEqual(actual.spot_evidence, expected.spot_evidence)

    def test_misaligned_rows_masks_and_raw_quantiles_are_rejected(self):
        examples = self.examples()
        with self.assertRaises(ValueError):
            build_price_targets(replace(examples, labels=examples.labels.iloc[::-1]))
        with self.assertRaises(ValueError):
            build_price_targets(replace(examples, eligible=examples.eligible.assign(price=True)))
        with self.assertRaises(ValueError):
            build_price_targets(replace(examples, label_evidence=examples.label_evidence[::-1]))
        features = examples.features
        for raw in (self.raw(features).iloc[::-1], self.raw(features).drop(columns="p90"),
                    self.raw(features).assign(p10=np.inf), self.raw(features).assign(p10=np.nan),
                    self.raw(features).assign(p10="private")):
            with self.subTest(), self.assertRaises(ValueError):
                reconstruct_prices(raw, features=features)

    def test_forged_late_or_wrong_delivery_reconstruction_evidence_is_rejected(self):
        features = self.examples().features
        record = features.evidence[0]
        dependency = next(e for e in record.dependencies if e.name == "fi_spot_price_delivery")
        source = dependency.sources[0]
        late = self.origin + pd.Timedelta(hours=1)
        variants = [
            replace(dependency, used_at_utc=late, sources=(replace(source,
                first_usable_origin_utc=late, used_at_utc=late),)),
            replace(dependency, sources=(replace(source, timestamp_utc=self.origin + pd.Timedelta(minutes=15)),)),
        ]
        for invalid in variants:
            row = replace(record, dependencies=tuple(invalid if e.name == dependency.name else e
                                                     for e in record.dependencies))
            changed = replace(features, evidence=(row, *features.evidence[1:]))
            with self.assertRaises(ValueError):
                reconstruct_prices(self.raw(changed), features=changed, mode="spot_relative")

    def test_forged_label_evidence_and_mode_are_rejected_without_printing_values(self):
        examples = self.examples()
        record = examples.label_evidence[0]
        late = self.cutoff + pd.Timedelta(hours=1)
        invalid = replace(record.price, used_at_utc=late, sources=(replace(record.price.sources[0],
                            first_usable_origin_utc=late, used_at_utc=late),))
        changed = replace(examples, label_evidence=(replace(record, price=invalid), *examples.label_evidence[1:]))
        with self.assertRaises(ValueError):
            build_price_targets(changed)
        for mode in ("unknown", None):
            with self.assertRaises(ValueError):
                build_price_targets(examples, mode=mode)
            with self.assertRaises(ValueError):
                reconstruct_prices(self.raw(examples.features), features=examples.features, mode=mode)
        marker = "-100"
        result = reconstruct_prices(self.raw(examples.features), features=examples.features, mode="spot_relative")
        self.assertNotIn(marker, repr(result))
        self.assertNotIn(marker, repr(build_price_targets(examples, mode="spot_relative")))

    def test_nonfinite_arithmetic_fails_safely(self):
        data = ForecastInputs(long_rows(("fi_imbalance_price", self.origin, self.cutoff, -1e308)),
                              long_rows(("fi_spot_price", self.origin, self.origin, 1e308)))
        examples = self.examples(data)
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            build_price_targets(examples, mode="spot_relative")
        raw = self.raw(examples.features).assign(p10=1e308, p50=1e308, p90=1e308)
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            reconstruct_prices(raw, features=examples.features, mode="spot_relative")

    def test_import_does_not_load_data_numeric_libraries_or_lightgbm(self):
        script = '''
import sys, os
def audit(event, args):
    if event == "open":
        path, mode, flags = args
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            raise AssertionError("write")
        if isinstance(path, (str, bytes)) and not os.fsdecode(path).endswith((".py", ".pyc")):
            raise AssertionError("noncode read")
    if event in {"subprocess.Popen", "socket.connect", "os.mkdir"}:
        raise AssertionError("external work")
sys.addaudithook(audit)
import forecast_engine.models.targets
assert not {"pandas", "numpy", "lightgbm"}.intersection(sys.modules)
'''
        with tempfile.TemporaryDirectory() as workdir:
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", script], cwd=workdir,
                                       capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout + completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
