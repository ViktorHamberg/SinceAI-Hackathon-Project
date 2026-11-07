"""Declared dependency lineage is checked through derived inputs, without values."""

from datetime import timedelta
import unittest

from forecast_engine import (
    DependencyEvidence, MissingEvidenceError, RunConfig, SourceDependency,
    derive_evidence, evidence_from_rows, fitting_provenance, origin_provenance,
    select_fitting_labels,
)
from _input_fixtures import long_rows


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.config = RunConfig.validation()
        self.origin = self.config.fit_cutoff_utc

    def evidence(self, series, delivery, published, *, use=None):
        return evidence_from_rows(long_rows((series, delivery, published, 123456.75)),
                                  name=series, used_at_utc=use or self.origin)

    def test_derived_and_nested_evidence_retains_every_source_and_actual_use(self):
        historical = self.origin - timedelta(hours=2)
        a = self.evidence("wind", self.origin + timedelta(hours=5), historical, use=historical)
        b = self.evidence("load", self.origin + timedelta(hours=5), self.origin)
        derived = derive_evidence("net_load", a, b, used_at_utc=self.origin)
        nested = derive_evidence("nested_feature", derived, a, used_at_utc=self.origin)
        self.assertEqual(len(nested.sources), 2)
        self.assertEqual(nested.max_first_usable_origin_utc, self.origin)
        self.assertEqual(nested.sources[0].used_at_utc, historical)
        record = origin_provenance(self.origin, [nested])
        self.assertEqual(record.dependencies, (nested,))
        self.assertEqual(record.max_first_usable_origin_utc, self.origin)
        self.assertGreater(record.source_timestamps_utc["wind"], self.origin)
        self.assertNotIn("123456.75", repr(record))

    def test_unavailable_raw_dependency_cannot_hide_in_derived_evidence(self):
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.evidence("late", self.origin, self.origin + timedelta(hours=1))
        later = self.evidence("late", self.origin, self.origin + timedelta(hours=1),
                              use=self.origin + timedelta(hours=1))
        with self.assertRaisesRegex(ValueError, "later origin"):
            derive_evidence("backdated", later, used_at_utc=self.origin)
        with self.assertRaises(ValueError):
            origin_provenance(self.origin, [later])
        with self.assertRaises(ValueError):
            DependencyEvidence("backdated", self.origin, later.sources)

    def test_a_row_used_at_two_historical_origins_retains_both_uses(self):
        delivery, publication = self.origin - timedelta(hours=5), self.origin - timedelta(hours=3)
        a = self.evidence("recent_price", delivery, publication, use=publication)
        b = self.evidence("recent_price", delivery, publication, use=self.origin)
        aggregate = derive_evidence("historical_errors", a, b, used_at_utc=self.origin)
        self.assertEqual(len(aggregate.sources), 2)
        self.assertEqual({s.used_at_utc for s in aggregate.sources}, {publication, self.origin})

    def test_empty_or_missing_dependencies_are_not_successful_essential_evidence(self):
        for rows in [long_rows(), long_rows(("missing", self.origin, self.origin, None))]:
            with self.assertRaises(MissingEvidenceError):
                evidence_from_rows(rows, name="essential", used_at_utc=self.origin)
        with self.assertRaises(MissingEvidenceError):
            derive_evidence("missing", used_at_utc=self.origin)
        empty = DependencyEvidence("optional", self.origin, ())
        with self.assertRaises(MissingEvidenceError):
            derive_evidence("cannot_invent", empty, used_at_utc=self.origin)

    def test_fitting_records_labels_and_historical_inputs_without_fitting(self):
        origin = self.origin - timedelta(hours=3)
        inputs = self.evidence("historical_input", origin - timedelta(hours=1), origin, use=origin)
        target = self.evidence("target", self.origin - timedelta(minutes=15), self.origin)
        record = fitting_provenance(self.config, predictor_id="future-model",
                                    labels=[target], historical_inputs=[inputs])
        self.assertEqual(record.counts, {"target": 1})
        self.assertEqual(record.max_first_usable_origin_utc, self.origin)
        self.assertEqual(record.latest_label_delivery_utc, self.origin - timedelta(minutes=15))
        self.assertEqual(record.dependencies, (target, inputs))
        self.assertEqual(record.dependencies[1].sources[0].used_at_utc, origin)

    def test_fitting_rechecks_all_label_dependencies_not_only_delivery_or_summary(self):
        before = self.origin - timedelta(minutes=15)
        eligible = self.evidence("target", before, self.origin)
        at_end = self.evidence("at_end", self.origin, self.origin)
        too_early = self.evidence("too_early", self.config.label_start_utc - timedelta(minutes=15), self.origin)
        delayed = self.evidence("delayed", before, self.origin + timedelta(hours=1),
                                use=self.origin + timedelta(hours=1))
        for bad in (at_end, too_early, delayed):
            with self.subTest(component=bad.name), self.assertRaises(ValueError):
                fitting_provenance(self.config, predictor_id="test", labels=[eligible, bad])
        # A derived label with one eligible and one excluded source is still excluded.
        mixed = derive_evidence("mixed", eligible, at_end, used_at_utc=self.origin)
        with self.assertRaises(ValueError):
            fitting_provenance(self.config, predictor_id="test", labels=[mixed])
        with self.assertRaises(MissingEvidenceError):
            fitting_provenance(self.config, predictor_id="test", labels=[])

    def test_raw_evidence_requires_availability_at_historical_origin_not_just_cutoff(self):
        historical = self.origin - timedelta(hours=2)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.evidence("leaking_input", historical - timedelta(hours=1), self.origin, use=historical)
        rows = long_rows(("target", self.origin - timedelta(minutes=15), self.origin, 7.))
        labels = select_fitting_labels(rows, self.config, required_series=["target"])
        evidence = evidence_from_rows(labels, name="target", used_at_utc=self.origin)
        self.assertEqual(evidence.max_first_usable_origin_utc, self.origin)


if __name__ == "__main__":
    unittest.main()
