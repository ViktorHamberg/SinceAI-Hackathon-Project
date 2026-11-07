"""Loading adapters use only invented files and mocked Parquet reads."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal

from forecast_engine import load_input_data, load_inputs, load_spot_prices, normalize_long
from _input_fixtures import long_rows


class DataLoadingTests(unittest.TestCase):
    def setUp(self):
        self.rows = long_rows(
            ("fi_imbalance_price", "2026-06-01T00:00:00+03:00", "2026-05-31T23:00:00Z", -5.),
            ("fi_wind_fc_da", "2026-06-01T03:00:00Z", "2026-05-31T21:00:00Z", None),
        )

    def test_csv_loads_utc_negative_values_and_preserves_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inputs.csv"
            self.rows.to_csv(path, index=False)
            result = load_input_data(path)
        self.assertEqual(str(result.timestamp_utc.dtype), "datetime64[ns, UTC]")
        self.assertEqual(str(result.first_usable_origin_utc.dtype), "datetime64[ns, UTC]")
        self.assertEqual(result.timestamp_utc.iloc[0], pd.Timestamp("2026-05-31T21:00:00Z"))
        self.assertEqual(result.value.iloc[0], -5.)
        self.assertTrue(pd.isna(result.value.iloc[1]))
        self.assertEqual(result.dataset_id.iloc[0], "319")

    def test_explicit_input_and_spot_paths_and_no_directory_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            inputs, spot = directory / "inputs.csv", directory / "spot_nordpool.csv"
            self.rows.to_csv(inputs, index=False)
            long_rows(("fi_spot_price", "2026-06-01T04:00:00Z", "2026-05-31T21:00:00Z", 12.)).to_csv(spot, index=False)
            (directory / "actuals_validation.csv").write_text("must never be read")
            result = load_inputs(inputs, spot_path=spot)
            self.assertEqual(len(result.series), 2)
            self.assertEqual(len(result.spot), 1)
            self.assertIsNone(load_inputs(inputs).spot)
            with self.assertRaises(FileNotFoundError):
                load_inputs(inputs, spot_path=directory / "missing.csv")

    def test_parquet_dispatch_and_actionable_missing_engine_error(self):
        with patch("pandas.read_parquet", return_value=self.rows) as reader:
            result = load_input_data(Path("synthetic.parquet"))
            reader.assert_called_once_with(Path("synthetic.parquet"))
            assert_frame_equal(result, normalize_long(self.rows))
        with patch("pandas.read_parquet", side_effect=ImportError("backend internals")):
            with self.assertRaisesRegex(ImportError, "pyarrow"):
                load_input_data("synthetic.parquet")

    def test_scoring_files_are_blocked_and_renamed_scoring_schema_is_rejected(self):
        with patch("pandas.read_csv") as reader:
            with self.assertRaisesRegex(ValueError, "scoring actuals"):
                load_input_data("actuals_validation.csv")
            reader.assert_not_called()
        actuals_shape = pd.DataFrame(columns=[
            "delivery_start_utc", "imbalance_price", "spot_price", "direction", "first_usable_origin_utc"
        ])
        with patch("pandas.read_csv", return_value=actuals_shape):
            with self.assertRaisesRegex(ValueError, "schema"):
                load_input_data("renamed.csv")

    def test_role_mismatch_and_unsupported_files_fail(self):
        with patch("pandas.read_csv", return_value=self.rows):
            with self.assertRaisesRegex(ValueError, "only nordpool"):
                load_spot_prices("synthetic.csv")
        spot = long_rows(("fi_spot_price", "2026-06-01T00:00:00Z", "2026-05-31T21:00:00Z", 2.))
        with patch("pandas.read_csv", return_value=spot):
            with self.assertRaisesRegex(ValueError, "separately"):
                load_input_data("synthetic.csv")
        with self.assertRaisesRegex(ValueError, "CSV or Parquet"):
            load_input_data("inputs.xlsx")

    def test_rejects_ambiguous_timestamps_duplicates_and_malformed_values(self):
        cases = [
            self.rows.assign(timestamp_utc="2026-06-01 00:00:00"),
            self.rows.assign(first_usable_origin_utc=None),
            self.rows.assign(timestamp_utc=1234),
            self.rows.assign(timestamp_utc="2026-06-01T00:01:00Z"),
            self.rows.assign(first_usable_origin_utc="2026-06-01T00:15:00Z"),
            pd.concat([self.rows, self.rows.iloc[:1]], ignore_index=True),
            self.rows.assign(value=float("inf")),
            self.rows.assign(value="INVENTED_PRIVATE_VALUE"),
            self.rows.assign(value=True),
            self.rows.assign(series_id=None),
        ]
        for frame in cases:
            before = frame.copy(deep=True)
            with self.subTest(columns=list(frame.columns)), self.assertRaises(ValueError) as context:
                normalize_long(frame)
            self.assertNotIn("INVENTED_PRIVATE_VALUE", str(context.exception))
            assert_frame_equal(frame, before)

    def test_empty_optional_table_has_typed_columns(self):
        empty = normalize_long(long_rows())
        self.assertTrue(empty.empty)
        self.assertEqual(str(empty.value.dtype), "float64")
        self.assertEqual(str(empty.timestamp_utc.dtype), "datetime64[ns, UTC]")

    def test_blank_dataset_ids_are_nullable_without_changing_nonblank_metadata(self):
        frame = long_rows(*[
            (f"metadata_case_{i}", "2026-06-01T00:00:00Z", "2026-06-01T01:00:00Z", 1.)
            for i in range(6)
        ])
        frame["dataset_id"] = ["", None, " \t ", "319", "17.1.g:SE1", pd.NA]
        before = frame.copy(deep=True)
        result = normalize_long(frame)
        self.assertEqual(str(result.dataset_id.dtype), "string")
        self.assertEqual(result.dataset_id.isna().tolist(), [True, True, True, False, False, True])
        self.assertEqual(result.dataset_id.iloc[3:5].tolist(), ["319", "17.1.g:SE1"])
        assert_frame_equal(frame, before)

    def test_csv_and_parquet_normalize_blank_dataset_ids_identically(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "inputs.csv"
            parquet_path = Path(directory) / "inputs.parquet"
            self.rows.to_csv(csv_path, index=False)
            csv_rows = load_input_data(csv_path)
            if importlib.util.find_spec("pyarrow") is not None:
                self.rows.to_parquet(parquet_path, index=False, engine="pyarrow")
                parquet_rows = load_input_data(parquet_path)
            else:
                # Exercise the same normalizer with the blank text retained by Parquet.
                with patch("pandas.read_parquet", return_value=self.rows):
                    parquet_rows = load_input_data(parquet_path)
        assert_frame_equal(csv_rows, parquet_rows)
        self.assertTrue(pd.isna(csv_rows.dataset_id.iloc[1]))


if __name__ == "__main__":
    unittest.main()
