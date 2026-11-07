"""Synthetic contract/configuration checks; no challenge data is read."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from forecast_engine import (
    FORECAST_COLUMNS, HORIZON_STEPS, STEP_MINUTES, FitProvenance,
    FittedPredictor, ForecastInputs, ForecastProvenance, ForecastResult,
    OriginProvenance, Predictor, RunConfig, check_forecast_schema, empty_forecast_frame,
)


class RunConfigTests(unittest.TestCase):
    def test_official_boundaries_and_local_midnight(self):
        validation, test = RunConfig.validation(), RunConfig.test()
        self.assertEqual(validation.label_start_utc.isoformat(), "2026-05-31T21:00:00+00:00")
        self.assertEqual(validation.label_end_utc.isoformat(), "2026-09-06T21:00:00+00:00")
        self.assertEqual(validation.label_end_utc, validation.fit_cutoff_utc)
        self.assertEqual(test.label_start_utc, validation.label_start_utc)
        self.assertEqual(test.label_end_utc.isoformat(), "2026-10-04T21:00:00+00:00")
        self.assertEqual(test.label_end_utc, test.fit_cutoff_utc)
        helsinki_summer = timezone(timedelta(hours=3))
        self.assertEqual(validation.fit_cutoff_utc.astimezone(helsinki_summer).hour, 0)
        self.assertEqual(test.fit_cutoff_utc.astimezone(helsinki_summer).day, 5)
        self.assertEqual((HORIZON_STEPS, STEP_MINUTES), (40, 15))

    def test_normalizes_explicit_timezone_and_is_immutable(self):
        c = RunConfig.validation()
        offset = timezone(timedelta(hours=3))
        normalized = RunConfig(*(v.astimezone(offset) for v in (
            c.label_start_utc, c.label_end_utc, c.fit_cutoff_utc)))
        self.assertEqual(normalized, c)
        self.assertIs(normalized.fit_cutoff_utc.tzinfo, timezone.utc)
        with self.assertRaises(FrozenInstanceError):
            c.fit_cutoff_utc = RunConfig.test().fit_cutoff_utc

    def test_rejects_ambiguous_or_unsafe_boundaries(self):
        c = RunConfig.validation()
        cases = [
            (c.label_start_utc.replace(tzinfo=None), c.label_end_utc, c.fit_cutoff_utc),
            (c.label_start_utc, c.label_end_utc, "2026-09-06T21:00:00Z"),
            (c.label_start_utc - timedelta(hours=1), c.label_end_utc, c.fit_cutoff_utc),
            (c.label_end_utc, c.label_start_utc, c.fit_cutoff_utc),
            (c.label_start_utc, c.label_end_utc, c.fit_cutoff_utc - timedelta(hours=1)),
            (c.label_start_utc, c.label_end_utc, RunConfig.test().fit_cutoff_utc + timedelta(hours=1)),
            (c.label_start_utc, c.label_end_utc, c.fit_cutoff_utc + timedelta(minutes=15)),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                RunConfig(*args)


def synthetic_table(origins):
    """A schema fixture, not a predictor or evidence of forecast quality."""
    count = len(origins) * 40
    frame = empty_forecast_frame().reindex(range(count))
    frame["forecast_origin_utc"] = pd.Series(pd.to_datetime(origins, utc=True).repeat(40))
    frame["step"] = pd.Series(list(range(1, 41)) * len(origins), dtype="int64")
    frame["delivery_start_utc"] = (
        frame["forecast_origin_utc"] + pd.to_timedelta((frame["step"] - 1) * 15, unit="min")
    )
    for name, value in zip(FORECAST_COLUMNS[3:11], (-10., 0., 10., .2, .3, .5, .1, .1)):
        frame[name] = value
    return frame


class ForecastContractTests(unittest.TestCase):
    def test_empty_schema_matches_unchanged_official_template_header(self):
        # Only the public header is read; no actual or spot data is accessed.
        template = Path(__file__).resolve().parents[1] / "sample_submission.csv"
        with template.open(encoding="utf-8-sig") as stream:
            self.assertEqual(tuple(stream.readline().strip().split(",")), FORECAST_COLUMNS)
        frame = empty_forecast_frame()
        check_forecast_schema(frame)
        self.assertTrue(frame.empty)
        self.assertEqual(str(frame["step"].dtype), "int64")
        self.assertEqual(str(frame["top_drivers"].dtype), "string")
        for name in ("forecast_origin_utc", "delivery_start_utc", "data_cutoff_utc"):
            self.assertEqual(str(frame[name].dtype), "datetime64[ns, UTC]")

    def test_optional_fields_can_be_missing_then_populated_without_schema_change(self):
        origin = datetime(2026, 10, 25, 0, tzinfo=timezone.utc)
        frame = synthetic_table([origin])
        check_forecast_schema(frame)
        dtypes = frame.dtypes.copy()
        self.assertTrue(frame[["data_cutoff_utc", "top_drivers"]].isna().all().all())
        frame.loc[0, "data_cutoff_utc"] = origin - timedelta(hours=1)
        frame.loc[0, "top_drivers"] = "wind_forecast;recent_imbalance"
        check_forecast_schema(frame)
        self.assertTrue(frame.dtypes.equals(dtypes))
        self.assertEqual(frame.loc[0, "top_drivers"], "wind_forecast;recent_imbalance")

    def test_schema_check_rejects_invalid_shapes_and_types_without_repair(self):
        good = synthetic_table([datetime(2026, 9, 7, tzinfo=timezone.utc)])
        bad_tables = [
            good.drop(columns="top_drivers"), good[list(reversed(FORECAST_COLUMNS))],
            good.assign(extra="metadata"), good.assign(step=good.step.astype(float)),
            good.assign(p50="not numeric"), good.assign(p_up=True),
            good.assign(p10=1 + 2j),
            good.assign(forecast_origin_utc=good.forecast_origin_utc.dt.tz_localize(None)),
            good.assign(delivery_start_utc=good.delivery_start_utc.dt.tz_convert("Europe/Helsinki")),
            good.assign(data_cutoff_utc=pd.Series([None] * len(good), dtype=object)),
            good.assign(top_drivers=pd.Series([None] * len(good), dtype=object)),
        ]
        for bad in bad_tables:
            before = bad.copy(deep=True)
            with self.subTest(dtypes=str(bad.dtypes)), self.assertRaises(ValueError):
                check_forecast_schema(bad)
            assert_frame_equal(bad, before)
        with self.assertRaises(TypeError):
            check_forecast_schema([])

    def test_result_exposes_provenance_separately_from_table(self):
        config = RunConfig.validation()
        fitting = FitProvenance(config=config, predictor_id="synthetic-test", counts={"labels": 3})
        origin = OriginProvenance(config.fit_cutoff_utc)
        result = ForecastResult(synthetic_table([config.fit_cutoff_utc]),
                                ForecastProvenance(fitting, (origin,)))
        self.assertIs(result.provenance.fitting, fitting)
        self.assertEqual(result.provenance.inference, (origin,))
        self.assertEqual(tuple(result.forecasts.columns), FORECAST_COLUMNS)
        self.assertEqual(result.forecasts.attrs, {})

    def test_model_independent_fit_then_single_or_batch_call_shape(self):
        # Two unrelated test doubles need no inheritance or baseline-specific state.
        class FittedDouble:
            def __init__(self, provenance):
                self.provenance = provenance

            def predict(self, data, *, origins):
                return ForecastResult(synthetic_table(origins), ForecastProvenance(self.provenance))

        class PredictorDouble:
            def fit(self, data, *, config):
                return FittedDouble(FitProvenance(config, "test-double"))

        class AlternativeDouble:
            def fit(self, data, *, config):
                return FittedDouble(FitProvenance(config, "alternative-test-double"))

        config = RunConfig.validation()
        origins = [config.fit_cutoff_utc, config.fit_cutoff_utc + timedelta(hours=1)]
        data = ForecastInputs(pd.DataFrame())
        for predictor in (PredictorDouble(), AlternativeDouble()):
            self.assertIsInstance(predictor, Predictor)
            fitted = predictor.fit(data, config=config)
            self.assertIsInstance(fitted, FittedPredictor)
            batch = fitted.predict(data, origins=origins)
            single = fitted.predict(data, origins=origins[:1])
            check_forecast_schema(batch.forecasts)
            self.assertEqual(len(batch.forecasts), 80)
            assert_frame_equal(batch.forecasts.iloc[:40], single.forecasts)


if __name__ == "__main__":
    unittest.main()
