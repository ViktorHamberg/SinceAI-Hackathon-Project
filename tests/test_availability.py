"""Synthetic boundary and noninterference checks for historical selection."""

from datetime import timedelta
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from forecast_engine import (
    MissingEvidenceError, RunConfig, rows_available_at, select_available, select_fitting_labels,
)
from _input_fixtures import long_rows


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.origin = RunConfig.validation().fit_cutoff_utc
        self.rows = long_rows(
            ("fi_imbalance_price", self.origin - timedelta(hours=2), self.origin, -8.),
            ("fi_wind_fc_da", self.origin + timedelta(hours=5), self.origin - timedelta(hours=1), 100.),
            ("fi_spot_price", self.origin + timedelta(hours=6), self.origin, 20.),
            ("late_optional", self.origin - timedelta(hours=1), self.origin + timedelta(hours=1), 33.),
        )

    def test_inclusive_publication_and_future_deliveries(self):
        selected = select_available(self.rows, self.origin)
        self.assertEqual(set(selected.series_id), {"fi_imbalance_price", "fi_wind_fc_da", "fi_spot_price"})
        self.assertTrue((selected.first_usable_origin_utc <= self.origin).all())
        self.assertEqual(sum(selected.timestamp_utc > self.origin), 2)
        # Once published, the delayed optional observation can be used at a later origin.
        later = select_available(self.rows, self.origin + timedelta(hours=1))
        self.assertIn("late_optional", set(later.series_id))

    def test_unavailable_value_changes_or_removal_cannot_change_selection(self):
        expected = select_available(self.rows, self.origin)
        changed = self.rows.copy()
        changed.loc[changed.series_id == "late_optional", "value"] = -999999.
        assert_frame_equal(select_available(changed, self.origin), expected)
        removed = changed.loc[changed.series_id != "late_optional"]
        assert_frame_equal(select_available(removed, self.origin), expected)
        assert_frame_equal(self.rows, long_rows(
            ("fi_imbalance_price", self.origin - timedelta(hours=2), self.origin, -8.),
            ("fi_wind_fc_da", self.origin + timedelta(hours=5), self.origin - timedelta(hours=1), 100.),
            ("fi_spot_price", self.origin + timedelta(hours=6), self.origin, 20.),
            ("late_optional", self.origin - timedelta(hours=1), self.origin + timedelta(hours=1), 33.),
        ))

    def test_fitting_requires_delivery_and_publication_for_both_run_cutoffs(self):
        for config in (RunConfig.validation(), RunConfig.test()):
            c = config.fit_cutoff_utc
            frame = long_rows(
                ("at_start", config.label_start_utc, c, 1.),
                ("last_eligible", config.label_end_utc - timedelta(minutes=15), c, 2.),
                ("at_end", config.label_end_utc, c - timedelta(hours=1), 3.),
                ("too_early", config.label_start_utc - timedelta(minutes=15), c, 4.),
                ("delayed_label", config.label_end_utc - timedelta(minutes=30), c + timedelta(hours=1), 5.),
            )
            with self.subTest(cutoff=c):
                expected = select_fitting_labels(frame, config)
                self.assertEqual(set(expected.series_id), {"at_start", "last_eligible"})
                frame.loc[frame.series_id == "delayed_label", "value"] = -10000.
                assert_frame_equal(select_fitting_labels(frame, config), expected)
                frame = frame.loc[~frame.series_id.isin(["delayed_label", "at_end", "too_early"])]
                assert_frame_equal(select_fitting_labels(frame, config), expected)

    def test_optional_gaps_stay_missing_essential_gaps_fail_explicitly(self):
        frame = pd.concat([self.rows, long_rows(
            ("missing_optional", self.origin, self.origin, None),
        )], ignore_index=True)
        selected = select_available(frame, self.origin, required_series=["fi_imbalance_price"])
        self.assertTrue(pd.isna(selected.loc[selected.series_id == "missing_optional", "value"]).all())
        wide = rows_available_at(frame, self.origin)
        self.assertNotIn("late_optional", wide.columns)
        self.assertTrue(wide["missing_optional"].isna().all())
        self.assertTrue(wide["fi_wind_fc_da"].isna().any())
        for name in ("late_optional", "missing_optional", "absent"):
            with self.subTest(series=name), self.assertRaises(MissingEvidenceError):
                select_available(frame, self.origin, required_series=[name])
        with self.assertRaises(MissingEvidenceError):
            select_fitting_labels(frame, RunConfig.validation(), required_series=["fi_spot_price"])

    def test_naive_and_nonhour_origins_fail_without_guessing_timezone(self):
        for origin in [self.origin.replace(tzinfo=None), self.origin + timedelta(minutes=15), pd.NaT]:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                select_available(self.rows, origin)

    def test_offset_origins_are_normalized_and_dst_remains_unambiguous(self):
        a = pd.Timestamp("2026-10-25T03:00:00+03:00")
        b = pd.Timestamp("2026-10-25T03:00:00+02:00")
        frame = long_rows(("published_between", a, b, 5.))
        self.assertTrue(select_available(frame, a).empty)
        self.assertEqual(len(select_available(frame, b)), 1)


if __name__ == "__main__":
    unittest.main()
