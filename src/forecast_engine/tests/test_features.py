"""Feature semantics and leakage checks with invented values, never challenge data."""

from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from forecast_engine import ForecastInputs
from forecast_engine.data import LONG_COLUMNS
from forecast_engine.features import (
    DEFAULT_FEATURE_NAMES, FEATURE_REGISTRY, REGISTRY_VERSION, build_features,
)
from forecast_engine.features.registry import CATEGORIES


def long_rows(*records):
    """(series, delivery, publication, invented value), including typed empty inputs."""
    return pd.DataFrame([
        {"series_id": series, "source": "nordpool" if series == "fi_spot_price" else "fingrid",
         "dataset_id": "", "timestamp_utc": delivery, "first_usable_origin_utc": publication,
         "value": value, "unit": "EUR/MWh" if "price" in series else "MW"}
        for series, delivery, publication, value in records
    ], columns=LONG_COLUMNS).astype({"value": "float64"})


ORIGIN = pd.Timestamp("2026-09-07T00:00:00Z")


class FeatureTests(unittest.TestCase):
    def build(self, rows=None, spot=None, **kwargs):
        return build_features(ForecastInputs(long_rows() if rows is None else rows, spot),
                              origins=kwargs.pop("origins", [ORIGIN]), **kwargs)

    def test_registry_is_stable_immutable_and_covers_supplied_market_groups(self):
        self.assertEqual(len(DEFAULT_FEATURE_NAMES), 15)
        self.assertEqual(set(d.category for d in FEATURE_REGISTRY.values()), set(CATEGORIES))
        expected_sources = {
            "fi_imbalance_price", "fi_spot_price", "fi_mfrr_direction", "fi_afrr_up_price",
            "fi_afrr_down_price", "fi_mfrr_up_price", "fi_mfrr_down_price",
            "fi_mfrr_up_activated", "fi_mfrr_down_activated", "fi_consumption", "fi_production",
            "fi_consumption_fc_da", "fi_wind_fc_da", "fi_solar_fc_da", "fi_ee_capacity_da",
            "ee_fi_capacity_da", "cal_is_holiday_fi",
            *[f"fi_{area}_flow" for area in ("ee", "se1", "se3", "no4")],
            *[f"{area}_load_fc_da" for area in ("ee", "se1", "se3")],
            *[f"{area}_imbalance_price_{side}" for area in ("ee", "se1", "se3")
              for side in ("long", "short")],
        }
        self.assertEqual({s for d in FEATURE_REGISTRY.values() for s in d.source_series}, expected_sources)
        self.assertEqual(FEATURE_REGISTRY["fi_ee_flow_latest"].unit, "MWh/h")
        self.assertEqual(FEATURE_REGISTRY["fi_ee_flow_age_minutes"].unit, "min")
        for name, definition in FEATURE_REGISTRY.items():
            self.assertEqual(name, definition.name)
            self.assertTrue(definition.unit and definition.missing_policy)
        with self.assertRaises(TypeError):
            FEATURE_REGISTRY["new"] = FEATURE_REGISTRY["horizon_step"]
        with self.assertRaises(FrozenInstanceError):
            FEATURE_REGISTRY["horizon_step"].unit = "changed"

    def test_complete_sorted_horizons_and_deterministic_feature_order(self):
        origins = [ORIGIN + pd.Timedelta(hours=1), ORIGIN]
        selected = list(reversed(DEFAULT_FEATURE_NAMES))
        result = self.build(origins=origins, feature_names=selected)
        self.assertEqual(result.registry_version, REGISTRY_VERSION)
        self.assertEqual(result.feature_names, DEFAULT_FEATURE_NAMES)
        self.assertEqual(len(result.frame), 80)
        self.assertEqual(tuple(result.frame.columns[3:]), DEFAULT_FEATURE_NAMES)
        self.assertEqual(str(result.frame.forecast_origin_utc.dtype), "datetime64[ns, UTC]")
        for offset in (0, 40):
            part = result.frame.iloc[offset:offset + 40]
            self.assertEqual(list(part.step), list(range(1, 41)))
            self.assertEqual(list(part.horizon_step), list(range(1, 41)))
            self.assertEqual(list(part.lead_minutes), list(range(0, 600, 15)))
            self.assertEqual(part.delivery_start_utc.iloc[-1] - part.forecast_origin_utc.iloc[0],
                             pd.Timedelta(hours=9, minutes=45))
        for row, record in zip(result.frame.itertuples(), result.evidence):
            self.assertEqual((row.forecast_origin_utc, row.delivery_start_utc, row.step),
                             (record.forecast_origin_utc, record.delivery_start_utc, record.step))

    def test_latest_observation_publication_boundary_and_age(self):
        rows = long_rows(
            ("fi_imbalance_price", "2026-09-06T23:00Z", "2026-09-06T23:00Z", -10),
            ("fi_imbalance_price", "2026-09-06T23:45Z", ORIGIN, 30),
            ("fi_imbalance_price", ORIGIN, ORIGIN, 900),  # Not past delivery.
            ("fi_imbalance_price", "2026-09-06T23:30Z", "2026-09-07T01:00Z", 800),
            ("fi_mfrr_direction", "2026-09-06T23:15Z", ORIGIN, -1),
        )
        result = self.build(rows)
        self.assertTrue(result.frame.fi_imbalance_price_latest.eq(30).all())
        self.assertTrue(result.frame.fi_imbalance_price_age_minutes.eq(15).all())
        self.assertTrue(result.frame.fi_mfrr_direction_latest.eq(-1).all())
        self.assertTrue(result.frame.fi_mfrr_direction_age_minutes.eq(45).all())
        dependency = {e.name: e for e in result.evidence[0].dependencies}["fi_imbalance_price_latest"]
        self.assertEqual(len(dependency.sources), 1)
        self.assertEqual(dependency.sources[0].first_usable_origin_utc, ORIGIN)

    def test_rolling_window_boundaries_and_all_contributing_rows(self):
        rows = long_rows(*[
            ("fi_imbalance_price", delivery, ORIGIN, value)
            for delivery, value in [
                ("2026-09-06T20:45Z", 999), ("2026-09-06T21:00Z", 2),
                ("2026-09-06T23:00Z", -2), ("2026-09-06T23:15Z", np.nan),
                ("2026-09-06T23:30Z", 6), ("2026-09-07T00:00Z", 999),
            ]])
        result = self.build(rows)
        row = result.frame.iloc[0]
        self.assertEqual(row.fi_imbalance_price_mean_60m, 2)
        self.assertEqual(row.fi_imbalance_price_std_60m, 4)
        self.assertEqual(row.fi_imbalance_price_mean_180m, 2)
        deps = {d.name: d for d in result.evidence[0].dependencies}
        self.assertEqual(len(deps["fi_imbalance_price_mean_60m"].sources), 2)
        self.assertEqual(len(deps["fi_imbalance_price_mean_180m"].sources), 3)
        self.assertEqual(deps["fi_imbalance_price_mean_180m"].sources[0].timestamp_utc,
                         pd.Timestamp("2026-09-06T21:00Z"))
        for record in result.evidence:
            for dependency in record.dependencies:
                self.assertEqual(dependency.used_at_utc, ORIGIN)
                self.assertTrue(all(s.first_usable_origin_utc <= s.used_at_utc == ORIGIN
                                    for s in dependency.sources))

    def test_delivery_forecasts_and_spot_require_exact_published_quarter(self):
        rows = long_rows(
            ("fi_wind_fc_da", "2026-09-07T01:00Z", ORIGIN, 100),
            ("fi_wind_fc_da", "2026-09-07T01:15Z", "2026-09-07T01:00Z", 200),
        )
        spot = long_rows(
            ("fi_spot_price", "2026-09-07T01:00Z", ORIGIN, -5),
            ("fi_spot_price", "2026-09-07T01:15Z", "2026-09-07T01:00Z", 800),
        )
        result = self.build(rows, spot, feature_names=["fi_wind_fc_da_delivery", "fi_spot_price_delivery"])
        self.assertEqual(result.frame.iloc[4].fi_spot_price_delivery, -5)
        self.assertEqual(result.frame.iloc[4].fi_wind_fc_da_delivery, 100)
        self.assertTrue(result.frame.iloc[5:].fi_spot_price_delivery.isna().all())
        self.assertTrue(result.frame.iloc[:4].fi_spot_price_delivery.isna().all())
        self.assertEqual(len(result.evidence[4].dependencies), 2)
        self.assertEqual(result.evidence[5].dependencies, ())

    def test_missing_inputs_are_nan_without_fabricated_evidence(self):
        result = self.build(feature_names=tuple(FEATURE_REGISTRY))
        source_names = [d.name for d in FEATURE_REGISTRY.values() if d.source_series]
        self.assertTrue(result.frame[source_names].isna().all().all())
        self.assertTrue(all(not row.dependencies for row in result.evidence))
        # One finite observation gives population std zero, without filling gaps.
        one = self.build(long_rows(("fi_imbalance_price", "2026-09-06T23:45Z", ORIGIN, 4)))
        self.assertEqual(one.frame.iloc[0].fi_imbalance_price_std_60m, 0)

    def test_sparse_afrr_and_stale_observation_policy(self):
        rows = long_rows(("fi_afrr_up_price", "2026-09-01T00:00Z", "2026-09-01T01:00Z", -7))
        result = self.build(rows, feature_names=["fi_afrr_up_price_latest", "fi_afrr_up_price_age_minutes",
                                               "fi_afrr_down_price_latest"])
        self.assertTrue(result.frame.fi_afrr_down_price_latest.isna().all())
        self.assertTrue(result.frame.fi_afrr_up_price_latest.eq(-7).all())
        self.assertEqual(result.frame.iloc[0].fi_afrr_up_price_age_minutes, 6 * 24 * 60)

    def test_optional_groups_use_their_declared_source_and_operation(self):
        records = {}
        for definition in FEATURE_REGISTRY.values():
            if not definition.source_series:
                continue
            series = definition.source_series[0]
            delivery = ORIGIN if definition.operation == "delivery" else ORIGIN - pd.Timedelta(minutes=15)
            records[series] = (series, delivery, ORIGIN, 1 if series in {
                "fi_mfrr_direction", "cal_is_holiday_fi"} else 10)
        spot = long_rows(records.pop("fi_spot_price"))
        result = self.build(long_rows(*records.values()), spot, feature_names=tuple(FEATURE_REGISTRY))
        dependencies = {d.name: d for d in result.evidence[0].dependencies}
        for definition in FEATURE_REGISTRY.values():
            if not definition.source_series:
                continue
            self.assertEqual(dependencies[definition.name].sources[0].series_id,
                             definition.source_series[0])
            expected = 15 if definition.operation == "age" else (
                0 if definition.operation == "std" else records.get(
                    definition.source_series[0], (None, None, None, 10))[3])
            self.assertEqual(result.frame.iloc[0][definition.name], expected)
        self.assertTrue(result.frame.iloc[1:].fi_wind_fc_da_delivery.isna().all())

    def test_unavailable_perturbation_removal_and_input_order_invariance(self):
        eligible = long_rows(("fi_imbalance_price", "2026-09-06T23:45Z", ORIGIN, 20))
        unavailable = long_rows(("fi_imbalance_price", "2026-09-06T23:30Z", "2026-09-07T01:00Z", 999))
        base = self.build(eligible)
        combined = pd.concat([unavailable, eligible], ignore_index=True)
        original = combined.copy(deep=True)
        for changed in (combined, combined.assign(value=[-999, 20]), combined.iloc[::-1]):
            result = self.build(changed)
            assert_frame_equal(base.frame, result.frame)
            self.assertEqual(base.evidence, result.evidence)
        assert_frame_equal(original, combined)
        # Apply the same invariance rule to future delivery inputs, including spot.
        future = long_rows(("fi_spot_price", "2026-09-07T01:00Z", "2026-09-07T01:00Z", 777))
        assert_frame_equal(base.frame, self.build(eligible, future).frame)
        self.assertEqual(base.evidence, self.build(eligible, future.assign(value=-777)).evidence)

    def test_single_batch_and_caller_mutation_are_independent(self):
        rows = long_rows(("fi_imbalance_price", "2026-09-06T23:45Z", ORIGIN, 12))
        batch = self.build(rows, origins=[ORIGIN, ORIGIN + pd.Timedelta(hours=1)])
        for offset, origin in enumerate((ORIGIN, ORIGIN + pd.Timedelta(hours=1))):
            single = self.build(rows, origins=[origin])
            assert_frame_equal(single.frame, batch.frame.iloc[offset * 40:(offset + 1) * 40].reset_index(drop=True))
            self.assertEqual(single.evidence, batch.evidence[offset * 40:(offset + 1) * 40])
        rows.loc[:, "value"] = 99
        self.assertTrue(batch.frame.fi_imbalance_price_latest.eq(12).all())

    def test_dst_repeated_hour_and_midnight_use_delivery_in_helsinki(self):
        result = self.build(origins=[pd.Timestamp("2026-10-25T00:00Z")])
        first, second = result.frame.iloc[0], result.frame.iloc[4]
        self.assertEqual((first.delivery_hour_local, second.delivery_hour_local), (3, 3))
        self.assertEqual((first.delivery_is_dst, second.delivery_is_dst), (1, 0))
        self.assertNotEqual(first.delivery_start_utc, second.delivery_start_utc)
        self.assertEqual(result.frame.iloc[1].delivery_quarter, 1)
        crossing = self.build(origins=[pd.Timestamp("2026-09-06T20:00Z")])
        self.assertEqual((crossing.frame.iloc[0].delivery_weekday_local,
                          crossing.frame.iloc[4].delivery_weekday_local), (6, 0))
        self.assertEqual((crossing.frame.iloc[0].delivery_hour_local,
                          crossing.frame.iloc[4].delivery_hour_local), (23, 0))

    def test_origins_and_feature_selection_fail_safely(self):
        for origins in ([], [ORIGIN, ORIGIN], [datetime(2026, 9, 7)], [pd.NaT],
                        [ORIGIN + pd.Timedelta(minutes=15)], [ORIGIN + pd.Timedelta(nanoseconds=1)]):
            with self.subTest(origins=origins), self.assertRaises(ValueError):
                self.build(origins=origins)
        for names in ([], ["unknown"], ["lead_minutes", "lead_minutes"]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                self.build(feature_names=names)
        normalized = self.build(origins=[pd.Timestamp("2026-09-07T03:00+03:00")])
        self.assertEqual(normalized.frame.forecast_origin_utc.iloc[0], ORIGIN)

    def test_no_values_in_evidence_repr_or_error_messages(self):
        marker = 876543.21
        result = self.build(spot=long_rows(("fi_spot_price", ORIGIN, ORIGIN, marker)))
        self.assertNotIn(str(marker), repr(result))
        self.assertNotIn(str(marker), repr(result.evidence))
        self.assertTrue(all(not hasattr(s, "value") for r in result.evidence
                            for e in r.dependencies for s in e.sources))
        with self.assertRaisesRegex(ValueError, "spot inputs must be supplied separately") as caught:
            self.build(long_rows(("fi_spot_price", ORIGIN, ORIGIN, marker)))
        self.assertNotIn(str(marker), str(caught.exception))

    def test_import_has_no_data_access_writes_or_heavy_imports(self):
        script = '''
import sys, os
def audit(event, args):
    if event == "open":
        path, mode, flags = args
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            raise AssertionError("import writes")
        if isinstance(path, (str, bytes)) and not os.fsdecode(path).endswith((".py", ".pyc")):
            raise AssertionError("non-code read")
    if event in {"subprocess.Popen", "socket.connect", "os.mkdir"}:
        raise AssertionError("external work")
sys.addaudithook(audit)
import forecast_engine.features
assert not {"pandas", "numpy", "lightgbm"}.intersection(sys.modules)
'''
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", script],
                                       cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout + completed.stderr, "")
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
