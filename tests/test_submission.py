"""CSV export checks use synthetic forecasts and temporary output directories only."""

from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal

from forecast_engine import FORECAST_COLUMNS, export_forecasts
from forecast_engine.models import PersistencePredictor
from forecast_engine.submission import _round_trip
from test_calibration import calibration_fixture


class SubmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data, config = calibration_fixture()
        cls.origin = config.fit_cutoff_utc
        cls.frame = PersistencePredictor().fit(data, config=config).predict(data, origins=[cls.origin]).forecasts

    def test_empty_optional_values_round_trip_with_official_header_and_utc_format(self):
        before = self.frame.copy()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "forecast_backtest.csv"
            self.assertEqual(export_forecasts(self.frame, target, origins=[self.origin]), target)
            payload = target.read_text(encoding="utf-8")
            self.assertEqual(payload.splitlines()[0], ",".join(FORECAST_COLUMNS))
            self.assertEqual(len(payload.splitlines()), 41)
            self.assertIn(self.origin.strftime("%Y-%m-%dT%H:%M:%SZ"), payload)
            self.assertNotIn("+00:00", payload)
            self.assertNotIn("Unnamed", payload)
            self.assertTrue(all(line.endswith(",,") for line in payload.splitlines()[1:]))
            recovered = _round_trip(payload)
            self.assertEqual(tuple(recovered.columns), FORECAST_COLUMNS)
            assert_frame_equal(recovered, self.frame, check_dtype=False)
            self.assertEqual(list(target.parent.iterdir()), [target])
        assert_frame_equal(self.frame, before)

    def test_populated_optional_values_unicode_quotes_and_literal_na_survive(self):
        frame = self.frame.copy()
        frame.loc[:2, "data_cutoff_utc"] = self.origin - timedelta(minutes=5)
        labels = ["tuuli;recent_price", "NA", "nan", 'quoted,"driver"\nline', ""]
        frame.loc[:4, "top_drivers"] = labels
        with tempfile.TemporaryDirectory() as directory:
            path = export_forecasts(frame, Path(directory) / "optional.csv")
            recovered = _round_trip(path.read_text(encoding="utf-8"))
        self.assertEqual(recovered.top_drivers.iloc[:4].tolist(), labels[:4])
        self.assertTrue(pd.isna(recovered.top_drivers.iloc[4]))
        self.assertTrue(recovered.data_cutoff_utc.iloc[:3].eq(self.origin - timedelta(minutes=5)).all())
        self.assertEqual(frame.top_drivers.iloc[4], "")

    def test_invalid_input_and_incomplete_origin_do_not_touch_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "existing.csv"
            target.write_text("existing output")
            bad = self.frame.copy()
            bad.loc[0, "p_up"] = 2.
            for frame, origins in [(bad, [self.origin]), (self.frame, [self.origin, self.origin + timedelta(hours=1)])]:
                with self.assertRaises(ValueError):
                    export_forecasts(frame, target, origins=origins)
                self.assertEqual(target.read_text(), "existing output")
            absent = Path(directory) / "never_created" / "bad.csv"
            with self.assertRaises(ValueError):
                export_forecasts(bad, absent)
            self.assertFalse(absent.parent.exists())

    def test_serialized_probability_rounding_uses_official_tolerance_without_repair(self):
        frame = self.frame.copy()
        frame[["p_up", "p_down", "p_none"]] = [1 / 3, 1 / 3, 1 - 2 / 3]
        with tempfile.TemporaryDirectory() as directory:
            target = export_forecasts(frame, Path(directory) / "rounded.csv")
            recovered = _round_trip(target.read_text())
        self.assertEqual(recovered.loc[0, ["p_up", "p_down", "p_none"]].tolist(), [.333333] * 3)
        self.assertAlmostEqual(frame.p_up.iloc[0], 1 / 3)

    def test_post_serialization_validation_rejects_corruption_before_writing(self):
        original = pd.DataFrame.to_csv

        def corrupt(frame, buffer, **kwargs):
            original(frame, buffer, **kwargs)
            payload = buffer.getvalue().replace(",0.500000,", ",1.500000,", 1)
            buffer.seek(0)
            buffer.truncate()
            buffer.write(payload)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.csv"
            path.write_text("existing output")
            with patch.object(pd.DataFrame, "to_csv", corrupt), self.assertRaises(ValueError):
                export_forecasts(self.frame, path)
            self.assertEqual(path.read_text(), "existing output")

    def test_failed_atomic_replace_cleans_temporary_file_and_preserves_existing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.csv"
            path.write_text("existing output")
            with patch("forecast_engine.submission.os.replace", side_effect=OSError("synthetic failure")):
                with self.assertRaises(OSError):
                    export_forecasts(self.frame, path)
            self.assertEqual(path.read_text(), "existing output")
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
