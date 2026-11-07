"""Invented calibration examples; never print or use restricted challenge values."""

import ast
from dataclasses import FrozenInstanceError
from datetime import timedelta
import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from forecast_engine import ForecastInputs, FittedPredictor, MissingEvidenceError, Predictor, RunConfig
from forecast_engine.models import PersistencePredictor
from _input_fixtures import long_rows


def calibration_fixture(*, start=None, hours=24, price=lambda i: float(i)):
    start = start or RunConfig.validation().label_start_utc
    dates = pd.date_range(start, periods=hours * 4, freq="15min")
    # Official-style delay: publication is the first full hour after end + 60min.
    available = (dates + pd.Timedelta(minutes=75)).ceil("h")
    series = long_rows(*[
        ("fi_imbalance_price", date, usable, price(i))
        for i, (date, usable) in enumerate(zip(dates, available))
    ], *[
        ("fi_mfrr_direction", dates[i], available[i], direction)
        for i, direction in enumerate([1., 1., -1., 0.])
    ])
    spot = long_rows(*[
        ("fi_spot_price", date, start, price(i)) for i, date in enumerate(dates)
    ])
    config = RunConfig(RunConfig.validation().label_start_utc,
                       start + timedelta(hours=hours), start + timedelta(hours=hours))
    return ForecastInputs(series, spot), config


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.data, self.config = calibration_fixture()

    def fit(self, data=None, config=None):
        return PersistencePredictor().fit(data or self.data, config=config or self.config)

    def test_known_linear_errors_counts_and_direction_frequencies(self):
        fitted = self.fit()
        self.assertEqual(fitted.q10, tuple(float(step + 4) for step in range(1, 41)))
        self.assertEqual(fitted.q90, fitted.q10)
        self.assertEqual(fitted.error_counts, tuple(n for n in range(21, 11, -1) for _ in range(4)))
        self.assertEqual(fitted.provenance.counts["historical_origins"], 21)
        self.assertEqual(fitted.provenance.counts["error_pairs"], 660)
        self.assertEqual((fitted.p_up, fitted.p_down, fitted.p_none), (.5, .25, .25))
        self.assertEqual((fitted.p_spike_high, fitted.p_spike_low), (0., 0.))
        self.assertEqual(fitted.provenance.counts["spike_pairs"], 92)

    def test_known_nonlinear_horizon_quantiles_use_linear_interpolation(self):
        data, config = calibration_fixture(price=lambda i: float(i * i))
        fitted = self.fit(data, config)
        # Step 1 residuals are 40*h-25 for h=2..22. Step 40 residuals are
        # 352*h+1496 for h=2..13. These independent expectations require interpolation.
        self.assertEqual((fitted.q10[0], fitted.q90[0]), (135., 775.))
        self.assertAlmostEqual(fitted.q10[39], 2587.2)
        self.assertAlmostEqual(fitted.q90[39], 5684.8)

    def test_partial_horizons_and_per_step_target_evidence(self):
        fitted = self.fit()
        evidence = {e.name: e for e in fitted.provenance.dependencies}
        start = self.config.label_start_utc
        # The last forecastable origin contributes its first four steps only.
        last_origin = start + timedelta(hours=22)
        self.assertIn(last_origin, {s.timestamp_utc for s in evidence["error_step_01"].sources})
        self.assertNotIn(last_origin + timedelta(minutes=60),
                         {s.timestamp_utc for s in evidence["error_step_05"].sources})
        for step in range(1, 41):
            targets = evidence[f"error_step_{step:02}"].sources
            derived = evidence[f"quantile_offsets_step_{step:02}"]
            self.assertEqual(len(targets), fitted.error_counts[step - 1])
            for target in targets:
                origin = target.timestamp_utc - timedelta(minutes=(step - 1) * 15)
                self.assertTrue(any(s.used_at_utc == origin and s.timestamp_utc <= origin
                                    for s in derived.sources))
                self.assertLess(target.timestamp_utc, self.config.label_end_utc)

    def test_historical_publication_delay_changes_correct_residuals_and_lineage(self):
        data, config = calibration_fixture(hours=14)
        start = config.label_start_utc
        frame = data.series.copy()
        delayed = (frame.series_id == "fi_imbalance_price") & (frame.timestamp_utc == start + timedelta(minutes=105))
        frame.loc[delayed, "first_usable_origin_utc"] = start + timedelta(hours=4)
        fitted = self.fit(ForecastInputs(frame, data.spot), config)
        # Step 40 has two errors: 44 at origin 02:00, 45 at 03:00. The later
        # published observation at 01:45 cannot replace the 01:30 observation at 03:00.
        self.assertAlmostEqual(fitted.q10[39], 44.1)
        self.assertAlmostEqual(fitted.q90[39], 44.9)
        evidence = next(e for e in fitted.provenance.dependencies if e.name == "quantile_offsets_step_40")
        source = [s for s in evidence.sources if s.used_at_utc == start + timedelta(hours=3)]
        self.assertEqual(len(source), 1)
        self.assertEqual(source[0].timestamp_utc, start + timedelta(minutes=90))

    def test_both_standard_cutoffs_and_ineligible_label_value_removal_invariance(self):
        for standard in [RunConfig.validation(), RunConfig.test()]:
            data, _ = calibration_fixture(start=standard.label_end_utc - timedelta(hours=24))
            excluded = long_rows(
                ("fi_imbalance_price", standard.label_end_utc, standard.fit_cutoff_utc, 999999.),
                ("fi_mfrr_direction", standard.label_end_utc, standard.fit_cutoff_utc, -1.),
                ("fi_imbalance_price", standard.label_start_utc - timedelta(minutes=15),
                 standard.label_start_utc, -999999.),
            )
            with self.subTest(cutoff=standard.fit_cutoff_utc):
                expected = self.fit(data, standard)
                changed = pd.concat([data.series, excluded], ignore_index=True)
                bad = ((changed.first_usable_origin_utc > standard.fit_cutoff_utc)
                       | (changed.timestamp_utc < standard.label_start_utc)
                       | (changed.timestamp_utc >= standard.label_end_utc))
                changed.loc[bad, "value"] = 123456789.
                self.assertEqual(self.fit(ForecastInputs(changed, data.spot), standard), expected)
                self.assertEqual(self.fit(ForecastInputs(changed.loc[~bad], data.spot), standard), expected)
                for e in expected.provenance.dependencies:
                    self.assertLessEqual(e.used_at_utc, standard.fit_cutoff_utc)
                    for s in e.sources:
                        self.assertLessEqual(s.first_usable_origin_utc, s.used_at_utc)
                        self.assertLess(s.timestamp_utc, standard.label_end_utc)

    def test_strict_spike_thresholds_and_both_dependencies(self):
        spot = self.data.spot.iloc[:4].copy()
        spot["value"] = [-50., -49.0001, 52., 53.0001]
        # Imbalance values 0,1,2,3: differences +50,+50.0001,-50,-50.0001.
        fitted = self.fit(ForecastInputs(self.data.series, spot))
        self.assertEqual((fitted.p_spike_high, fitted.p_spike_low), (.25, .25))
        self.assertEqual(fitted.provenance.counts["spike_pairs"], 4)
        derived = next(e for e in fitted.provenance.dependencies if e.name == "spike_frequencies")
        self.assertEqual({s.series_id for s in derived.sources}, {"fi_imbalance_price", "fi_spot_price"})
        self.assertEqual(len(derived.sources), 8)
        # A pre-cutoff delivery is still unusable when either source is published late.
        spot.loc[spot.index[1], "first_usable_origin_utc"] = self.config.fit_cutoff_utc + timedelta(hours=1)
        late = self.fit(ForecastInputs(self.data.series, spot))
        self.assertEqual((late.p_spike_high, late.p_spike_low), (0., .333333))
        self.assertEqual(late.provenance.counts["spike_pairs"], 3)
        removed = self.fit(ForecastInputs(self.data.series, spot.drop(index=spot.index[1])))
        self.assertEqual(late, removed)

    def test_imbalance_publication_is_also_required_for_spike_pairs(self):
        frame = self.data.series.copy()
        mask = (frame.series_id == "fi_imbalance_price") & (frame.timestamp_utc == self.config.label_start_utc)
        frame.loc[mask, "first_usable_origin_utc"] = self.config.fit_cutoff_utc + timedelta(hours=1)
        fitted = self.fit(ForecastInputs(frame, self.data.spot))
        self.assertEqual(fitted.provenance.counts["spike_pairs"], 91)
        self.assertNotIn(self.config.label_start_utc, {
            s.timestamp_utc for e in fitted.provenance.dependencies if e.name == "spike_frequencies"
            for s in e.sources
        })

    def test_direction_frequencies_preserve_reference_rounding(self):
        direction = long_rows(*[
            ("fi_mfrr_direction", self.config.label_start_utc + timedelta(minutes=i * 15),
             self.config.fit_cutoff_utc, v) for i, v in enumerate([1., -1., 0.])
        ])
        frame = pd.concat([self.data.series.loc[self.data.series.series_id != "fi_mfrr_direction"], direction], ignore_index=True)
        fitted = self.fit(ForecastInputs(frame, self.data.spot))
        self.assertEqual((fitted.p_up, fitted.p_down, fitted.p_none), (.333333, .333333, .333334))

    def test_calibration_falls_back_beyond_three_days_without_staleness_cap(self):
        start = self.config.label_start_utc
        data, config = calibration_fixture(start=start + timedelta(days=4), hours=14)
        frame = pd.concat([data.series, long_rows(("fi_imbalance_price", start, start, 3.))], ignore_index=True)
        fitted = self.fit(ForecastInputs(frame, data.spot), config)
        self.assertTrue(any(s.timestamp_utc == start and s.used_at_utc > start + timedelta(days=3)
                            for e in fitted.provenance.dependencies for s in e.sources))

    def test_missing_essential_evidence_and_invalid_direction_fail_clearly(self):
        for series in ["fi_imbalance_price", "fi_mfrr_direction"]:
            with self.subTest(series=series), self.assertRaises(MissingEvidenceError):
                self.fit(ForecastInputs(self.data.series.loc[self.data.series.series_id != series], self.data.spot))
        for spot in [None, self.data.spot.iloc[:0], self.data.spot.assign(value=np.nan),
                     self.data.spot.assign(first_usable_origin_utc=self.config.fit_cutoff_utc + timedelta(hours=1))]:
            with self.subTest(spot_missing=spot is None), self.assertRaisesRegex(MissingEvidenceError, "spike"):
                self.fit(ForecastInputs(self.data.series, spot))
        data, config = calibration_fixture(hours=5)
        with self.assertRaisesRegex(MissingEvidenceError, "step"):
            self.fit(data, config)
        delayed = self.data.series.copy()
        delayed.loc[delayed.series_id == "fi_imbalance_price", "first_usable_origin_utc"] = self.config.fit_cutoff_utc
        with self.assertRaisesRegex(MissingEvidenceError, "step 1"):
            self.fit(ForecastInputs(delayed, self.data.spot))
        invalid = self.data.series.copy()
        invalid.loc[invalid.series_id == "fi_mfrr_direction", "value"] = 2.
        with self.assertRaisesRegex(ValueError, "direction") as error:
            self.fit(ForecastInputs(invalid, self.data.spot))
        self.assertNotIn("2.0", str(error.exception))

    def test_repeatability_frozen_state_no_input_mutation_and_no_prediction_yet(self):
        before_series, before_spot = self.data.series.copy(), self.data.spot.copy()
        fitted = self.fit()
        self.assertIsInstance(PersistencePredictor(), Predictor)
        self.assertIsInstance(fitted, FittedPredictor)
        self.assertEqual(fitted, self.fit())
        assert_frame_equal(self.data.series, before_series)
        assert_frame_equal(self.data.spot, before_spot)
        with self.assertRaises(FrozenInstanceError):
            fitted.p_up = .9
        with self.assertRaises(TypeError):
            fitted.q10[0] = 999.
        with self.assertRaises(TypeError):
            fitted.provenance.counts["error_pairs"] = 0
        with self.assertRaises(FrozenInstanceError):
            fitted.provenance.dependencies[0].sources[0].used_at_utc = self.config.fit_cutoff_utc
        saved = (fitted.q10, fitted.q90, dict(fitted.provenance.counts))
        self.data.series["value"] = -999.
        self.data.spot["value"] = 999.
        self.assertEqual(saved, (fitted.q10, fitted.q90, dict(fitted.provenance.counts)))
        with self.assertRaisesRegex(NotImplementedError, "Step 4"):
            fitted.predict(self.data, origins=[self.config.fit_cutoff_utc])

    def test_provenance_has_no_values_and_statistic_repr_does_not_log_numbers(self):
        fitted = self.fit()
        self.assertEqual(repr(fitted), "FittedPersistence()")
        for e in fitted.provenance.dependencies:
            for s in e.sources:
                self.assertFalse(hasattr(s, "value"))
                self.assertLessEqual(s.first_usable_origin_utc, s.used_at_utc)
        self.assertEqual(fitted.provenance.max_first_usable_origin_utc, self.config.fit_cutoff_utc)
        self.assertEqual(fitted.provenance.config, self.config)

    def test_reference_calibration_numerical_agreement_on_eligible_synthetic_history(self):
        # Test-only source extraction; package runtime never reads/executes notebooks.
        notebook = json.loads((Path(__file__).resolve().parents[1] / "baseline.ipynb").read_text())
        names = {"rows_available_at", "to_utc", "series", "persistence_at", "calibrate"}
        functions = []
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                functions.extend(n for n in ast.parse("".join(cell["source"])).body
                                 if isinstance(n, ast.FunctionDef) and n.name in names)
        self.assertEqual({n.name for n in functions}, names)
        namespace = {"pd": pd, "np": np, "IMBALANCE": "fi_imbalance_price", "DIRECTION": "fi_mfrr_direction",
                     "STEP_OFFSETS": pd.to_timedelta(np.arange(40) * 15, unit="min"),
                     "SPIKE_MARGIN": 50., "HORIZON_STEPS": 40}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "<baseline calibration source>", "exec"), namespace)
        data, config = calibration_fixture(price=lambda i: float((i * i) % 71))
        fitted = self.fit(data, config)
        series = data.series.copy()
        spot = data.spot.copy()
        for table in [series, spot]:
            for name in ["timestamp_utc", "first_usable_origin_utc"]:
                table[name] = pd.to_datetime(table[name], utc=True)
        baseline = namespace["calibrate"](series, spot, config.fit_cutoff_utc)
        np.testing.assert_allclose(fitted.q10, baseline["q10"], rtol=0, atol=1e-12)
        np.testing.assert_allclose(fitted.q90, baseline["q90"], rtol=0, atol=1e-12)
        for name in ["p_up", "p_down", "p_none", "p_spike_high", "p_spike_low"]:
            self.assertEqual(getattr(fitted, name), baseline[name])
        self.assertEqual(fitted.provenance.counts["historical_origins"], baseline["n_origins"])
        self.assertEqual(fitted.provenance.counts["error_pairs"], baseline["n_error_pairs"])


if __name__ == "__main__":
    unittest.main()
