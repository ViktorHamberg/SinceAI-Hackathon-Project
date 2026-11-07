"""Synthetic in-memory prediction and result-contract checks; no challenge data."""

from dataclasses import replace
from datetime import timedelta
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from forecast_engine import (
    FORECAST_COLUMNS, ForecastInputs, MissingEvidenceError,
    forecast, validate_forecasts,
)
from forecast_engine.models import PersistencePredictor
from _input_fixtures import long_rows
from test_calibration import calibration_fixture


class PredictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.config = calibration_fixture()
        cls.fitted = PersistencePredictor().fit(cls.data, config=cls.config)
        cls.origin = cls.config.fit_cutoff_utc

    def test_single_origin_has_known_baseline_values_complete_schema_and_provenance(self):
        result = self.fitted.predict(self.data, origins=[self.origin])
        frame = result.forecasts
        self.assertEqual(len(frame), 40)
        self.assertEqual(tuple(frame.columns), FORECAST_COLUMNS)
        self.assertEqual(frame.step.tolist(), list(range(1, 41)))
        self.assertEqual(frame.p50.tolist(), [91.] * 40)
        self.assertEqual(frame.p10.tolist(), [91.] * 40)  # Positive lower offsets clip to zero.
        self.assertEqual(frame.p90.tolist(), list(np.arange(96., 136.)))
        self.assertTrue(frame[["data_cutoff_utc", "top_drivers"]].isna().all().all())
        self.assertEqual(str(frame.data_cutoff_utc.dtype), "datetime64[ns, UTC]")
        self.assertEqual(str(frame.top_drivers.dtype), "string")
        self.assertIs(result.provenance.fitting, self.fitted.provenance)
        record = result.provenance.inference[0]
        self.assertEqual(record.source_ages["fi_imbalance_price"], timedelta(minutes=75))
        self.assertEqual(record.max_first_usable_origin_utc, self.origin)
        self.assertEqual(len(record.dependencies[0].sources), 1)
        source = record.dependencies[0].sources[0]
        self.assertEqual(source.used_at_utc, self.origin)
        self.assertEqual(source.timestamp_utc, self.origin - timedelta(minutes=75))
        self.assertFalse(hasattr(source, "value"))
        self.assertEqual(frame.attrs, {})
        validate_forecasts(frame, origins=[self.origin])

    def test_batch_matches_single_calls_and_fitted_state_does_not_refit_or_change(self):
        origins = [self.origin, self.origin + timedelta(hours=1)]
        counts = dict(self.fitted.provenance.counts)
        offsets = (self.fitted.q10, self.fitted.q90)
        before_series, before_spot = self.data.series.copy(), self.data.spot.copy()
        with patch.object(PersistencePredictor, "fit", side_effect=AssertionError("must not fit")):
            batch = forecast(self.fitted, self.data, origins=list(reversed(origins)))
            single = [self.fitted.predict(self.data, origins=[o]) for o in origins]
            repeat = self.fitted.predict(self.data, origins=origins)
        assert_frame_equal(batch.forecasts, pd.concat([r.forecasts for r in single], ignore_index=True))
        assert_frame_equal(batch.forecasts, repeat.forecasts)
        self.assertEqual(batch.provenance.inference, tuple(r.provenance.inference[0] for r in single))
        self.assertEqual(counts, dict(self.fitted.provenance.counts))
        self.assertEqual(offsets, (self.fitted.q10, self.fitted.q90))
        assert_frame_equal(self.data.series, before_series)
        assert_frame_equal(self.data.spot, before_spot)

    def test_unavailable_or_future_observations_cannot_change_predictions(self):
        extra = long_rows(
            ("fi_imbalance_price", self.origin - timedelta(minutes=15), self.origin + timedelta(hours=1), 10000.),
        )
        # Replace this existing delayed row, rather than introducing a duplicate key.
        keep = self.data.series.timestamp_utc != self.origin - timedelta(minutes=15)
        frame = pd.concat([self.data.series.loc[keep], extra, long_rows(
            ("fi_imbalance_price", self.origin + timedelta(minutes=15), self.origin, 20000.),
        )], ignore_index=True)
        expected = self.fitted.predict(ForecastInputs(frame), origins=[self.origin])
        unavailable = ((frame.first_usable_origin_utc > self.origin) | (frame.timestamp_utc > self.origin))
        changed = frame.copy()
        changed.loc[unavailable, "value"] = -999999.
        for rows in [changed, changed.loc[~unavailable]]:
            result = self.fitted.predict(ForecastInputs(rows), origins=[self.origin])
            assert_frame_equal(result.forecasts, expected.forecasts)
            self.assertEqual(result.provenance, expected.provenance)

    def test_recent_search_and_all_earlier_fallback_without_staleness_limit(self):
        origin = self.origin + timedelta(days=5)
        old = origin - timedelta(days=4)
        rows = long_rows(
            ("fi_imbalance_price", old, old + timedelta(hours=2), -30.),
            ("fi_imbalance_price", origin - timedelta(hours=1), origin + timedelta(hours=1), 900.),
            ("fi_imbalance_price", origin - timedelta(minutes=30), origin, None),
        )
        fallback = self.fitted.predict(ForecastInputs(rows), origins=[origin])
        self.assertEqual(fallback.forecasts.p50.iloc[0], -30.)
        self.assertEqual(fallback.provenance.inference[0].source_ages["fi_imbalance_price"], timedelta(days=4))
        recent = long_rows(("fi_imbalance_price", origin - timedelta(hours=2), origin, -5.))
        latest = self.fitted.predict(ForecastInputs(pd.concat([rows, recent], ignore_index=True)), origins=[origin])
        self.assertEqual(latest.forecasts.p50.iloc[0], -5.)

    def test_negative_prices_rounding_and_deliberate_quantile_clipping(self):
        rows = long_rows(("fi_imbalance_price", self.origin - timedelta(hours=2), self.origin, -50.123456))
        fitted = replace(self.fitted, q10=(-10.,) * 40, q90=(-5.,) * 40)
        result = fitted.predict(ForecastInputs(rows), origins=[self.origin])
        self.assertEqual(result.forecasts.p50.iloc[0], -50.1235)
        self.assertEqual(result.forecasts.p10.iloc[0], -60.1235)
        self.assertEqual(result.forecasts.p90.iloc[0], -50.1235)  # Negative upper offset clips to zero.
        validate_forecasts(result.forecasts)

    def test_missing_observation_and_pre_fit_requests_fail_with_origin_and_component(self):
        for rows in [self.data.series.iloc[:0], self.data.series.assign(value=np.nan)]:
            with self.assertRaisesRegex(MissingEvidenceError, "persistence observation.*origin.*steps"):
                self.fitted.predict(ForecastInputs(rows), origins=[self.origin])
        with self.assertRaisesRegex(ValueError, "fitted statistics unavailable.*origin"):
            self.fitted.predict(self.data, origins=[self.origin - timedelta(hours=1)])

    def test_request_origins_must_be_unique_aware_full_hours_and_nonempty(self):
        for origins in [[], [self.origin, self.origin], [self.origin.replace(tzinfo=None)],
                        [self.origin + timedelta(minutes=15)], [pd.NaT]]:
            with self.subTest(origins=origins), self.assertRaises(ValueError):
                self.fitted.predict(self.data, origins=origins)

    def test_fitted_dependencies_are_checked_independently_of_summary_timestamp(self):
        first = self.fitted.provenance.dependencies[0]
        future_evidence = replace(first, used_at_utc=self.origin + timedelta(hours=1))
        bad_provenance = replace(self.fitted.provenance, dependencies=(future_evidence,))
        bad_fit = replace(self.fitted, provenance=bad_provenance)
        with self.assertRaisesRegex(ValueError, "fitted dependency.*origin"):
            bad_fit.predict(self.data, origins=[self.origin + timedelta(hours=2)])
        missing = replace(self.fitted, provenance=replace(self.fitted.provenance, dependencies=()))
        with self.assertRaisesRegex(MissingEvidenceError, "complete dependency evidence"):
            missing.predict(self.data, origins=[self.origin])

    def test_finnish_repeated_dst_hour_remains_two_distinct_utc_origins(self):
        first = pd.Timestamp("2026-10-25T03:00:00+03:00")
        second = pd.Timestamp("2026-10-25T03:00:00+02:00")
        data = ForecastInputs(long_rows(("fi_imbalance_price", first - timedelta(hours=2), first, 10.)))
        result = self.fitted.predict(data, origins=[second, first])
        for index, origin in enumerate([first.tz_convert("UTC"), second.tz_convert("UTC")]):
            block = result.forecasts.iloc[index * 40:(index + 1) * 40]
            self.assertEqual(block.delivery_start_utc.tolist(), list(pd.date_range(origin, periods=40, freq="15min")))
        self.assertEqual(result.forecasts.forecast_origin_utc.nunique(), 2)

    def test_model_independent_dispatch_checks_alternative_result(self):
        result = self.fitted.predict(self.data, origins=[self.origin])

        class Alternative:
            provenance = self.fitted.provenance

            def predict(model, data, *, origins):
                return result

        actual = forecast(Alternative(), self.data, origins=[self.origin])
        assert_frame_equal(actual.forecasts, result.forecasts)
        bad = replace(result, forecasts=result.forecasts.iloc[1:])
        with patch.object(Alternative, "predict", return_value=bad), self.assertRaisesRegex(ValueError, "missing forecast"):
            forecast(Alternative(), self.data, origins=[self.origin])
        with patch.object(Alternative, "predict", return_value=replace(result, provenance=replace(result.provenance, inference=()))):
            with self.assertRaisesRegex(ValueError, "inference provenance"):
                forecast(Alternative(), self.data, origins=[self.origin])


class ForecastValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data, config = calibration_fixture()
        cls.origin = config.fit_cutoff_utc
        cls.frame = PersistencePredictor().fit(data, config=config).predict(data, origins=[cls.origin]).forecasts

    def test_invalid_values_fail_without_mutation_or_repair(self):
        cases = [
            ("p50", np.nan), ("p10", -np.inf), ("p90", np.inf),
            ("p10", 9999.), ("p90", -9999.), ("p_up", -.1),
            ("p_down", 1.1), ("p_none", .4), ("p_spike_high", 1.),
            ("data_cutoff_utc", self.origin + timedelta(seconds=1)),
            ("data_cutoff_utc", pd.Timestamp(self.origin) - pd.Timedelta(nanoseconds=1)),
        ]
        for name, value in cases:
            frame = self.frame.copy()
            frame.loc[0, name] = value
            if name == "p_spike_high":
                frame.loc[0, "p_spike_low"] = .1
            before = frame.copy()
            with self.subTest(column=name, value=value), self.assertRaisesRegex(ValueError, "origin.*step"):
                validate_forecasts(frame, origins=[self.origin])
            assert_frame_equal(frame, before)

    def test_missing_duplicate_unexpected_unsorted_keys_and_wrong_delivery_fail(self):
        wrong_delivery = self.frame.copy()
        wrong_delivery.loc[0, "delivery_start_utc"] += timedelta(minutes=15)
        wrong_step = self.frame.copy()
        wrong_step.loc[0, "step"] = 0
        cases = [self.frame.iloc[1:], pd.concat([self.frame, self.frame.iloc[:1]]),
                 self.frame.iloc[::-1], wrong_delivery, wrong_step]
        for frame in cases:
            with self.subTest(rows=len(frame)), self.assertRaises(ValueError):
                validate_forecasts(frame, origins=[self.origin])
        with self.assertRaisesRegex(ValueError, "missing forecast"):
            validate_forecasts(self.frame, origins=[self.origin, self.origin + timedelta(hours=1)])
        with self.assertRaises(ValueError):
            validate_forecasts(self.frame, origins=[self.origin + timedelta(hours=1)])

    def test_schema_and_required_timestamp_failures_are_not_coerced(self):
        cases = [self.frame.drop(columns="top_drivers"), self.frame[list(reversed(FORECAST_COLUMNS))],
                 self.frame.assign(p50="invalid"), self.frame.assign(step=self.frame.step.astype(float)),
                 self.frame.assign(forecast_origin_utc=self.frame.forecast_origin_utc.dt.tz_localize(None)),
                 self.frame.assign(delivery_start_utc=pd.NaT)]
        for frame in cases:
            with self.subTest(columns=list(frame.columns)), self.assertRaises(ValueError):
                validate_forecasts(frame)

    def test_nullable_integer_keys_and_negative_quantiles_are_valid(self):
        frame = self.frame.copy()
        frame["step"] = frame.step.astype("Int64")
        frame[["p10", "p50", "p90"]] = [-30., -20., -10.]
        validate_forecasts(frame)


if __name__ == "__main__":
    unittest.main()
