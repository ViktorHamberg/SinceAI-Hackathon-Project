"""P50-only category identifiers. Numeric explanation data stays private."""

import math

from ..features.registry import REGISTRY_VERSION
from .contributions import AttributionUnavailable, _explain_prepared, _group_contributions
from .records import ContributionRecord


def _close(a, b):
    return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def _top_drivers(record):
    """Rank signed category totals only after verifying the complete P50 ledger.

    The reconstruction offset joins its category once; the base is never ranked.
    Unknown transforms or invalid private records yield no optional text.
    """
    if not isinstance(record, ContributionRecord):
        return None
    try:
        if (record.head != "p50" or record.class_name is not None or record.unit != "EUR/MWh"
                or record.output_unit != "EUR/MWh" or record.registry_version != REGISTRY_VERSION):
            return None
        paths = {("direct", "primary_p50"): "raw_price",
                 ("spot_relative", "primary_p50"): "raw_spread",
                 ("spot_relative", "direct_backup_p50"): "raw_price"}
        scope = paths.get((record.target_mode, record.component_id))
        if scope is None or scope != record.scope:
            return None
        if len({term.name for term in record.features}) != len(record.features):
            return None
        groups = {term.name: term.value for term in _group_contributions(record.features)}
        declared = {term.name: term.value for term in record.categories}
        if (len(declared) != len(record.categories) or groups.keys() != declared.keys()
                or any(not _close(value, declared[name]) for name, value in groups.items())
                or not _close(record.base_value + math.fsum(groups.values()), record.raw_output)):
            return None
        kinds = ["price_path_" + record.component_id.removesuffix("_p50")]
        if record.scope == "raw_spread":
            kinds.append("spot_reconstruction")
        kinds += ["calibration_identity", "preserve_p50_clamp_outer_bounds"]
        if [t.kind for t in record.transformations] != kinds:
            return None
        current = record.raw_output
        for transform in record.transformations:
            if (transform.input_unit != "EUR/MWh" or transform.output_unit != "EUR/MWh"
                    or not _close(transform.input_value, current)):
                return None
            if transform.kind == "spot_reconstruction":
                if (transform.category != "spot_price_conditions" or transform.offset is None
                        or transform.context or not _close(current + transform.offset, transform.output_value)):
                    return None
                groups[transform.category] = math.fsum((groups.get(transform.category, 0.), transform.offset))
            else:
                if (transform.offset is not None or transform.category is not None
                        or not _close(current, transform.output_value)):
                    return None
                if transform.kind == "preserve_p50_clamp_outer_bounds":
                    if (len(transform.context) != 1 or transform.context[0].name != "p50"
                            or not _close(transform.context[0].value, current)):
                        return None
                elif transform.context:
                    return None
            current = transform.output_value
        if (not _close(current, record.output_value)
                or not _close(record.base_value + math.fsum(groups.values()), record.output_value)):
            return None
        ranked = sorted((name for name, value in groups.items() if value != 0.),
                        key=lambda name: (-abs(groups[name]), name))
        return ";".join(ranked[:3]) or None
    except (AttributionUnavailable, AttributeError, TypeError, ValueError, OverflowError):
        return None


def _driver_labels(fitted, features, *, reconstruction, prices, forecast_p50):
    """Bind verified P50 records to prediction rows and the active frozen head."""
    empty = (None,) * len(features.frame)
    try:
        batch = _explain_prepared(fitted, features, price_state=(reconstruction, prices), p50_only=True)
    except AttributionUnavailable:
        return empty
    candidates = {}
    for record in batch.records:
        if record.head == "p50" and record.class_name is None:
            key = (record.forecast_origin_utc, record.delivery_start_utc, record.step)
            candidates.setdefault(key, []).append(record)
    blocked = {(r.forecast_origin_utc, r.delivery_start_utc, r.step)
               for r in batch.unavailable if r.component_id in ("primary_p50", "direct_backup_p50")}
    heads = {h.name: h for h in fitted._heads}
    backup_heads = {h.name: h for h in fitted._direct_heads}
    recipe = tuple(sorted({**fitted._recipe.parameters(), "num_boost_round": fitted._recipe.num_boost_round}.items()))
    labels = []
    for position, row in enumerate(features.evidence):
        key = (row.forecast_origin_utc, row.delivery_start_utc, row.step)
        records = candidates.get(key, ())
        if key in blocked or len(records) != 1:
            labels.append(None)
            continue
        record = records[0]
        backup = bool(reconstruction.requires_direct_backup.iloc[position])
        head = (backup_heads if backup else heads).get("p50")
        if (head is None or record.component_id != ("direct_backup_p50" if backup else "primary_p50")
                or record.model_sha256 != head.fingerprint or record.model_id != fitted.provenance.predictor_id
                or record.native_version != head.native_version or record.recipe != recipe
                or not 0 < record.iterations <= fitted._recipe.num_boost_round
                or record.target_mode != fitted._target_mode
                or tuple(t.name for t in record.features) != fitted._feature_names
                or not _close(record.output_value, float(forecast_p50.iloc[position]))):
            labels.append(None)
            continue
        labels.append(_top_drivers(record))
    return tuple(labels)
