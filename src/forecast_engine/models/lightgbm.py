"""Pooled direct/spot-relative price predictor behind existing engine protocols.

No public core exports or CLI defaults change. Optional LightGBM is loaded on fit or
prediction only. P50 driver labels use verified private contributions; calibration
remains a later step.
Evidence gaps fail explicitly; persistence is an explicitly selected separate model,
never a silent catch-all fallback. Fit state retains no mutable training DataFrames.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
from collections.abc import Sequence
from types import MappingProxyType

from ..availability import MissingEvidenceError, select_fitting_labels
from ..config import RunConfig
from ..contracts import FitProvenance, ForecastInputs, ForecastProvenance, ForecastResult, empty_forecast_frame
from ..features import DEFAULT_FEATURE_NAMES, REGISTRY_VERSION, build_features
from ..features.registry import FEATURE_REGISTRY
from ..features.training import build_training_examples
from ..provenance import derive_evidence, fitting_provenance, origin_provenance
from .heads import DIRECTION_CLASSES, SPIKE_CLASSES, TreeRecipe, fit_head, load_lightgbm
from .targets import build_price_targets, reconstruct_prices


@dataclass(frozen=True, repr=False)
class FittedLightGBM:
    _heads: tuple = field(repr=False)
    _feature_names: tuple[str, ...]
    _recipe: TreeRecipe
    provenance: FitProvenance = field(repr=False)
    _registry_version: str = REGISTRY_VERSION
    _target_mode: str = "direct"
    _quantile_policy: str = "preserve_p50_clamp_outer_bounds"
    _direct_heads: tuple = field(default=(), repr=False)

    def _input_view(self, data):
        return _input_view(data, self._feature_names, include_spot=self._target_mode == "spot_relative")

    def predict(self, data: ForecastInputs, *, origins: Sequence[datetime]) -> ForecastResult:
        import numpy as np
        import pandas as pd
        from ..engine import _check_fitting_availability, _prepare_origins, _validate_result

        requested = _prepare_origins(origins)
        _check_fitting_availability(self.provenance, requested[0])
        if self._registry_version != REGISTRY_VERSION:
            raise ValueError("fitted feature registry differs from the current registry")
        names = self._feature_names
        if self._target_mode == "spot_relative" and "fi_spot_price_delivery" not in names:
            names = (*names, "fi_spot_price_delivery")
        features = build_features(self._input_view(data), origins=requested, feature_names=names)
        matrix = features.frame[list(self._feature_names)]
        raw = {head.name: head.predict(matrix) for head in self._heads}
        quantiles = pd.DataFrame({name: raw[name] for name in ("p10", "p50", "p90")}, index=matrix.index)
        reconstruction = reconstruct_prices(quantiles, features=features, mode=self._target_mode)
        prices = reconstruction.prices.copy()
        backup = reconstruction.requires_direct_backup
        if backup.any():
            if len(self._direct_heads) != 3:
                raise MissingEvidenceError("relative prediction requires the fitted direct-price backup")
            for head in self._direct_heads:
                prices.loc[backup, head.name] = head.predict(matrix.loc[backup])
        frame = empty_forecast_frame().reindex(range(len(matrix)))
        for name in ("forecast_origin_utc", "delivery_start_utc", "step"):
            frame[name] = features.frame[name].copy()
        frame["p50"] = prices.p50
        frame["p10"] = np.minimum(prices.p10, prices.p50)
        frame["p90"] = np.maximum(prices.p90, prices.p50)
        for index, label in enumerate(DIRECTION_CLASSES):
            frame[f"p_{label}"] = raw["direction"][:, index]
        frame["p_spike_high"], frame["p_spike_low"] = raw["spike"][:, 0], raw["spike"][:, 1]
        from ..explainability.drivers import _driver_labels

        frame["top_drivers"] = pd.array(_driver_labels(
            self, features, reconstruction=reconstruction, prices=prices, forecast_p50=frame.p50,
        ), dtype="string")
        records = []
        rows_by_origin = {origin: [] for origin in requested}
        for position, row in enumerate(features.evidence):
            rows_by_origin[row.forecast_origin_utc].append((position, row))
        for origin in requested:
            origin_rows = rows_by_origin[origin]
            # Declare only feature rows actually used by this origin's predictions.
            dependencies = tuple(dict.fromkeys(e for _, row in origin_rows for e in row.dependencies
                                               if e.name in self._feature_names))
            if dependencies:
                evidence = derive_evidence("lightgbm_features", *dependencies, used_at_utc=origin)
            else:
                # With only deterministic/missing inputs, the frozen model itself
                # supplies the source evidence. Keep full lineage, not a digest.
                evidence = derive_evidence("lightgbm_fitted_state", *self.provenance.dependencies,
                                           used_at_utc=origin)
            components = [evidence]
            if self._target_mode == "spot_relative":
                for position, row in origin_rows:
                    path = "direct_backup" if backup.iloc[position] else "spot_relative"
                    inputs = [e for e in row.dependencies if e.name in self._feature_names]
                    if path == "spot_relative":
                        inputs.append(reconstruction.spot_evidence[position])
                    # Calendar-only paths still depend on a fully evidenced frozen model.
                    components.append(derive_evidence(
                        f"lightgbm_price_{path}_step_{row.step:02}",
                        *(inputs or [evidence]), used_at_utc=origin,
                    ))
            records.append(origin_provenance(origin, components))
        result = ForecastResult(frame, ForecastProvenance(self.provenance, tuple(records)))
        _validate_result(result, requested)
        return result


@dataclass(frozen=True)
class LightGBMPredictor:
    """V1 recipe; all five primary learned heads must fit successfully.

    Minimum rows apply independently to price/direction/spike tasks; classifiers need
    all three classes. Insufficient evidence raises MissingEvidenceError. Select
    PersistencePredictor explicitly if that policy is unsuitable for a run.
    """

    recipe: TreeRecipe = field(default_factory=TreeRecipe)
    feature_names: tuple[str, ...] = DEFAULT_FEATURE_NAMES
    min_training_rows: int = 40
    target_mode: str = "direct"

    def __post_init__(self):
        names = tuple(self.feature_names)
        if (not names or len(set(names)) != len(names) or "horizon_step" not in names
                or any(name not in FEATURE_REGISTRY for name in names)):
            raise ValueError("model features require unique registered names including horizon_step")
        if not isinstance(self.recipe, TreeRecipe):
            raise TypeError("model recipe must be TreeRecipe")
        if isinstance(self.min_training_rows, bool) or not isinstance(self.min_training_rows, int) or self.min_training_rows < 1:
            raise ValueError("minimum training rows must be a positive integer")
        if self.target_mode not in ("direct", "spot_relative"):
            raise ValueError("model target mode must be direct or spot_relative")
        object.__setattr__(self, "feature_names", tuple(name for name in FEATURE_REGISTRY if name in names))

    def fit(self, data: ForecastInputs, *, config: RunConfig) -> FittedLightGBM:
        import numpy as np
        import pandas as pd

        load_lightgbm()  # Fail before expensive feature construction if setup is absent.
        data = _input_view(data, self.feature_names, include_labels=True, include_spot=True)
        # Every historical origin precedes this cutoff. Removing rows not even
        # published by fit time cannot remove a usable historical feature.
        from ..availability import select_available
        data = ForecastInputs(select_available(data.series, config.fit_cutoff_utc),
                              None if data.spot is None else select_available(data.spot, config.fit_cutoff_utc))
        selected = select_fitting_labels(data.series, config)
        selected = selected.loc[selected.series_id.isin(["fi_imbalance_price", "fi_mfrr_direction"])].dropna(subset=["value"])
        if selected.empty:
            raise MissingEvidenceError("LightGBM fitting requires eligible labels")
        # Derive the origin range ONLY from eligible labels, never held-out rows.
        first = max(pd.Timestamp(config.label_start_utc), selected.timestamp_utc.min().floor("h"))
        last = min(pd.Timestamp(config.label_end_utc) - pd.Timedelta(hours=1), selected.timestamp_utc.max().floor("h"))
        origins = tuple(pd.date_range(first, last, freq="h"))
        examples = build_training_examples(data, config=config, origins=origins, feature_names=self.feature_names)
        targets = build_price_targets(examples, mode=self.target_mode)
        direct_targets = build_price_targets(examples, mode="direct") if self.target_mode == "spot_relative" else targets
        matrix = examples.features.frame[list(self.feature_names)]
        masks = {"price": targets.eligible, "direction": examples.eligible.direction,
                 "spike": examples.eligible.spike}
        if self.target_mode == "spot_relative":
            masks["direct_backup"] = direct_targets.eligible
        direction = examples.labels.direction.map({1: 0, -1: 1, 0: 2})
        spike = examples.labels.spike_class.map({"high": 0, "low": 1, "neither": 2})
        for name, mask in masks.items():
            if int(mask.sum()) < self.min_training_rows:
                raise MissingEvidenceError(f"insufficient eligible LightGBM {name} training rows")
        for name, labels in (("direction", direction), ("spike", spike)):
            if set(labels.loc[masks[name]]) != {0, 1, 2}:
                raise MissingEvidenceError(f"LightGBM {name} training requires all three classes")
        heads = []
        for name, quantile in (("p10", .1), ("p50", .5), ("p90", .9)):
            heads.append(fit_head(name, matrix.loc[masks["price"]], targets.values.loc[masks["price"]],
                                  recipe=self.recipe, quantile=quantile))
        for name, labels, classes in (("direction", direction, DIRECTION_CLASSES), ("spike", spike, SPIKE_CLASSES)):
            heads.append(fit_head(name, matrix.loc[masks[name]], labels.loc[masks[name]],
                                  recipe=self.recipe, classes=classes))
        direct_heads = []
        if self.target_mode == "spot_relative":
            for name, quantile in (("p10", .1), ("p50", .5), ("p90", .9)):
                direct_heads.append(fit_head(name, matrix.loc[direct_targets.eligible],
                                            direct_targets.values.loc[direct_targets.eligible],
                                            recipe=self.recipe, quantile=quantile))
        label_components = []
        for name, mask in masks.items():
            dependencies = []
            for position in np.flatnonzero(mask.to_numpy()):
                row = examples.label_evidence[position]
                dependencies.append(targets.label_evidence[position] if name == "price" else
                                    row.direction if name == "direction" else
                                    direct_targets.label_evidence[position] if name == "direct_backup" else row.spike)
            label_components.append(derive_evidence(f"lightgbm_{name}_labels", *dict.fromkeys(dependencies),
                                                    used_at_utc=config.fit_cutoff_utc))
        used = pd.concat(list(masks.values()), axis=1).any(axis=1)
        historical = tuple(dict.fromkeys(e for position in np.flatnonzero(used.to_numpy())
                                         for e in examples.features.evidence[position].dependencies))
        historical_inputs = ([derive_evidence("lightgbm_historical_features", *historical,
                                              used_at_utc=config.fit_cutoff_utc)] if historical else [])
        model_id = "lightgbm-direct-v1" if self.target_mode == "direct" else "lightgbm-relative-v1"
        provenance = fitting_provenance(config, predictor_id=model_id,
                                       labels=label_components, historical_inputs=historical_inputs)
        provenance = replace(provenance, counts=MappingProxyType({
            **provenance.counts, "historical_origins": len(origins),
            **{f"training_rows_{name}": int(mask.sum()) for name, mask in masks.items()},
            "heads": len(heads) + len(direct_heads), "num_boost_round": self.recipe.num_boost_round, "seed": self.recipe.seed,
        }))
        return FittedLightGBM(tuple(heads), self.feature_names, self.recipe, provenance,
                              _target_mode=self.target_mode, _direct_heads=tuple(direct_heads))


def _input_view(data, names, *, include_labels=False, include_spot=False):
    """Copy only declared sources before repeated historical normalization.

    Availability checks remain in the unchanged feature builder. This is a source
    projection, not an origin-dependent cache, label imputation or evidence shortcut.
    """
    sources = {source for name in names for source in FEATURE_REGISTRY[name].source_series}
    if include_labels:
        sources.update(("fi_imbalance_price", "fi_mfrr_direction"))
    return ForecastInputs(
        data.series.loc[data.series.series_id.isin(sources)].copy(),
        data.spot if include_spot or "fi_spot_price" in sources else None,
    )
