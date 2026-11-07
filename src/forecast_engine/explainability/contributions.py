"""Explicit, private attribution for frozen ordinary-tree LightGBM candidates.

No forecast-result wiring, fitting, file I/O or public driver selection. Native
contributions must reconstruct the exact saved head's raw output before use.
"""

from datetime import timedelta
import math

from ..features.registry import CATEGORIES, FEATURE_REGISTRY, REGISTRY_VERSION
from ..models.heads import DIRECTION_CLASSES, SPIKE_CLASSES, load_lightgbm
from .records import (
    ContributionComparison, ContributionRecord, ExplanationBatch, SignedContribution,
    Transformation, UnavailableContribution,
)


class AttributionUnavailable(ValueError):
    """Fixed reason code only; native exceptions may contain private values."""


def _group_contributions(terms):
    grouped = {name: [] for name in CATEGORIES}
    for term in terms:
        if term.name not in FEATURE_REGISTRY or not math.isfinite(term.value):
            raise AttributionUnavailable("unsupported_feature_contributions")
        grouped[FEATURE_REGISTRY[term.name].category].append(term.value)
    return tuple(SignedContribution(name, math.fsum(values))
                 for name, values in grouped.items() if values)


def _native_contributions(head, matrix):
    """Return dense [row, class, feature+bias] blocks and verified native outputs."""
    import numpy as np

    if tuple(matrix.columns) != head.feature_names:
        raise AttributionUnavailable("feature_schema_mismatch")
    classes = {"direction": DIRECTION_CLASSES, "spike": SPIKE_CLASSES}.get(head.name, ())
    if (head.classes != classes or head.objective != ("multiclass" if classes else "quantile")
            or head.name not in ("p10", "p50", "p90", "direction", "spike")):
        raise AttributionUnavailable("unsupported_head")
    try:
        native = load_lightgbm()
        if native.__version__ != head.native_version:
            raise AttributionUnavailable("native_version_mismatch")
        model = native.Booster(model_str=head._model_text)
        parameters = model.params
        if parameters.get("linear_tree") or parameters.get("boosting") != "gbdt":
            raise AttributionUnavailable("unsupported_tree_type")
        if (parameters.get("objective") != head.objective
                or tuple(model.feature_name()) != head.feature_names
                or (classes and parameters.get("num_class") != len(classes))):
            raise AttributionUnavailable("head_metadata_mismatch")
        if not classes and parameters.get("alpha") != {"p10": .1, "p50": .5, "p90": .9}[head.name]:
            raise AttributionUnavailable("head_metadata_mismatch")
        iterations = model.current_iteration()
        options = dict(start_iteration=0, num_iteration=iterations, validate_features=True, num_threads=1)
        values = model.predict(matrix, pred_contrib=True, **options)
        raw = np.asarray(model.predict(matrix, raw_score=True, **options), dtype=float)
        prediction = head.predict(matrix)
        count = len(classes) or 1
        if not isinstance(values, np.ndarray) or values.shape != (len(matrix), count * (len(matrix.columns) + 1)):
            raise AttributionUnavailable("unsupported_contribution_layout")
        if raw.shape != ((len(matrix), count) if classes else (len(matrix),)):
            raise AttributionUnavailable("unsupported_raw_layout")
        blocks = np.asarray(values, dtype=float).reshape(len(matrix), count, len(matrix.columns) + 1)
        raw = raw.reshape(len(matrix), count)
        if (not np.isfinite(blocks).all() or not np.isfinite(raw).all()
                or not np.allclose(blocks.sum(axis=2), raw, rtol=1e-9, atol=1e-9)):
            raise AttributionUnavailable("additivity_not_verified")
        if classes:
            probabilities = np.exp(raw - raw.max(axis=1, keepdims=True))
            probabilities /= probabilities.sum(axis=1, keepdims=True)
            expected = probabilities
        else:
            expected = raw[:, 0]
        if not np.allclose(expected, prediction, rtol=1e-9, atol=1e-9):
            raise AttributionUnavailable("prediction_link_not_verified")
        return blocks, raw, prediction, iterations
    except AttributionUnavailable:
        raise
    except Exception:
        raise AttributionUnavailable("native_attribution_unavailable") from None


def _check_model(fitted):
    from ..models.lightgbm import FittedLightGBM

    if type(fitted) is not FittedLightGBM:
        raise AttributionUnavailable("unsupported_predictor")
    if (fitted._registry_version != REGISTRY_VERSION or fitted._target_mode not in ("direct", "spot_relative")
            or fitted._quantile_policy != "preserve_p50_clamp_outer_bounds"):
        raise AttributionUnavailable("unsupported_transformation_policy")


def _explain(fitted, data, *, origins):
    """Explain active heads with the same origin-time inputs and price path as predict.

    Return component-specific unavailability rather than fabricated explanations.
    Invalid requests/availability still fail through the existing engine checks.
    """
    from ..engine import _check_fitting_availability, _prepare_origins
    from ..features import build_features

    _check_model(fitted)
    requested = _prepare_origins(origins)
    _check_fitting_availability(fitted.provenance, requested[0])
    names = fitted._feature_names
    if fitted._target_mode == "spot_relative" and "fi_spot_price_delivery" not in names:
        names = (*names, "fi_spot_price_delivery")
    features = build_features(fitted._input_view(data), origins=requested, feature_names=names)
    return _explain_prepared(fitted, features)


def _explain_prepared(fitted, features, *, price_state=None, p50_only=False):
    """Reuse prediction's private inputs/state without attaching records to results."""
    import numpy as np
    import pandas as pd
    from ..models.targets import _check_features, reconstruct_prices

    _check_model(fitted)
    _check_features(features)
    matrix = features.frame[list(fitted._feature_names)]
    primary = {head.name: head for head in fitted._heads}
    backup_heads = {head.name: head for head in fitted._direct_heads}
    if set(primary) != {"p10", "p50", "p90", "direction", "spike"} or len(primary) != len(fitted._heads):
        raise AttributionUnavailable("unsupported_component_set")
    try:
        if price_state is None:
            raw_quantiles = pd.DataFrame({q: primary[q].predict(matrix) for q in ("p10", "p50", "p90")})
            reconstruction = reconstruct_prices(raw_quantiles, features=features, mode=fitted._target_mode)
        else:
            reconstruction, _ = price_state
        backup = reconstruction.requires_direct_backup.to_numpy()
        prices = (reconstruction.prices if price_state is None else price_state[1]).copy()
        if backup.any() and price_state is None:
            if set(backup_heads) != {"p10", "p50", "p90"} or len(backup_heads) != len(fitted._direct_heads):
                raise AttributionUnavailable("missing_direct_backup")
            for q, head in backup_heads.items():
                prices.loc[backup, q] = head.predict(matrix.loc[backup])
    except AttributionUnavailable:
        raise
    except Exception:
        raise AttributionUnavailable("price_reconstruction_unavailable") from None
    final_prices = prices.copy()
    final_prices.p10 = np.minimum(prices.p10, prices.p50)
    final_prices.p90 = np.maximum(prices.p90, prices.p50)
    recipe = tuple(sorted({**fitted._recipe.parameters(), "num_boost_round": fitted._recipe.num_boost_round}.items()))
    records, unavailable = [], []
    all_rows = np.arange(len(matrix))
    components = [("primary", head, all_rows if head.name in ("direction", "spike") else all_rows[~backup])
                  for head in fitted._heads]
    if backup.any():
        components += [("direct_backup", head, all_rows[backup]) for head in fitted._direct_heads]
    for path, head, positions in components:
        if len(positions) == 0 or (p50_only and head.name != "p50"):
            continue
        component = f"{path}_{head.name}"
        try:
            blocks, raw, prediction, iterations = _native_contributions(head, matrix.iloc[positions])
        except AttributionUnavailable as error:
            for position in positions:
                row = features.evidence[position]
                unavailable.append(UnavailableContribution(row.forecast_origin_utc, row.delivery_start_utc,
                                                           row.step, component, str(error)))
            continue
        for local, position in enumerate(positions):
            row = features.evidence[position]
            for index, label in enumerate(head.classes or (None,)):
                value = float(raw[local, index])
                unit = "raw_margin" if head.classes else "EUR/MWh"
                scope = ("raw_class_margin" if head.classes else "raw_spread" if
                         path == "primary" and fitted._target_mode == "spot_relative" else "raw_price")
                terms = tuple(SignedContribution(name, float(amount))
                              for name, amount in zip(head.feature_names, blocks[local, index, :-1]))
                if head.classes:
                    context = tuple(SignedContribution(name, float(amount))
                                    for name, amount in zip(head.classes, raw[local]))
                    output = float(prediction[local, index])
                    ledger = (Transformation("softmax", value, output, unit, "probability", context=context),
                              Transformation("calibration_identity", output, output, "probability", "probability"))
                    output_unit = "probability"
                else:
                    reconstructed = float(prices[head.name].iloc[position])
                    output = float(final_prices[head.name].iloc[position])
                    ledger = [Transformation("price_path_" + path, value, value, unit, unit)]
                    if scope == "raw_spread":
                        offset = float(features.frame.fi_spot_price_delivery.iloc[position])
                        ledger.append(Transformation("spot_reconstruction", value, reconstructed, unit, unit,
                                                     offset=offset, category="spot_price_conditions"))
                    ledger += [Transformation("calibration_identity", reconstructed, reconstructed, unit, unit),
                               Transformation("preserve_p50_clamp_outer_bounds", reconstructed, output, unit, unit,
                                              context=(SignedContribution("p50", float(prices.p50.iloc[position])),))]
                    ledger = tuple(ledger)
                    output_unit = unit
                records.append(ContributionRecord(
                    row.forecast_origin_utc, row.delivery_start_utc, row.step, head.name, label, component,
                    fitted.provenance.predictor_id, head.fingerprint, head.native_version, recipe, iterations,
                    fitted._registry_version, fitted._target_mode, scope, unit, output_unit,
                    float(blocks[local, index, -1]), value, output, terms, _group_contributions(terms), ledger,
                ))
    records.sort(key=lambda r: (r.forecast_origin_utc, r.step, r.head, r.class_name or ""))
    unavailable.sort(key=lambda r: (r.forecast_origin_utc, r.step, r.component_id))
    return ExplanationBatch(tuple(records), tuple(unavailable))


def _compare_contributions(earlier, later):
    """Compare the same delivery/head at consecutive origins under one frozen model.

    Raw deltas retain raw units; output_delta has the later record's output_unit.
    Original ledgers retain offset/nonlinear context. No weather-vintage claim.
    """
    if (not isinstance(earlier, ContributionRecord) or not isinstance(later, ContributionRecord)
            or later.forecast_origin_utc - earlier.forecast_origin_utc != timedelta(hours=1)
            or earlier.delivery_start_utc != later.delivery_start_utc):
        raise AttributionUnavailable("incomparable_records")
    identity = ("head", "class_name", "component_id", "model_id", "model_sha256", "native_version",
                "recipe", "iterations", "registry_version", "target_mode", "scope", "unit", "output_unit")
    if (any(getattr(earlier, name) != getattr(later, name) for name in identity)
            or tuple(t.name for t in earlier.features) != tuple(t.name for t in later.features)):
        raise AttributionUnavailable("incomparable_models_or_scopes")
    terms = tuple(SignedContribution(a.name, b.value - a.value)
                  for a, b in zip(earlier.features, later.features))
    offsets = [math.fsum(t.offset for t in r.transformations if t.kind == "spot_reconstruction")
               for r in (earlier, later)]
    return ContributionComparison(earlier, later, later.base_value - earlier.base_value,
                                  later.raw_output - earlier.raw_output,
                                  later.output_value - earlier.output_value,
                                  terms, _group_contributions(terms), offsets[1] - offsets[0])
