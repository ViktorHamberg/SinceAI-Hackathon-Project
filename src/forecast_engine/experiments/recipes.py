"""Four predeclared Step 4A recipes; two of six learned slots remain for 4B."""

from dataclasses import dataclass
from types import MappingProxyType

from ..features.registry import DEFAULT_FEATURE_NAMES, FEATURE_REGISTRY


@dataclass(frozen=True)
class CandidateRecipe:
    recipe_id: str
    target_mode: str
    features: tuple[str, ...]
    hypothesis: str

    def predictor(self):
        from ..models.lightgbm import LightGBMPredictor

        return LightGBMPredictor(target_mode=self.target_mode, feature_names=self.features)


def _features(*extra):
    wanted = {*DEFAULT_FEATURE_NAMES, *extra}
    if not wanted.issubset(FEATURE_REGISTRY):
        raise ValueError("unregistered experiment feature")
    return tuple(name for name in FEATURE_REGISTRY if name in wanted)


RECIPES = MappingProxyType({r.recipe_id: r for r in (
    CandidateRecipe("direct-control-v1", "direct", _features(),
                    "Direct-price control with the original minimal feature set."),
    CandidateRecipe("relative-control-v1", "spot_relative", _features(),
                    "Relative-price control; compare target choice with identical features/settings."),
    CandidateRecipe("relative-wind-load-v1", "spot_relative",
                    _features("fi_wind_fc_da_delivery", "fi_consumption_fc_da_delivery"),
                    "Published delivery wind/load forecasts improve the relative control."),
    CandidateRecipe("relative-mfrr-v1", "spot_relative",
                    _features(*(f"fi_mfrr_{side}_{kind}_{suffix}" for side in ("up", "down")
                                for kind in ("price", "activated") for suffix in ("latest", "age_minutes"))),
                    "Available mFRR price/activation observations and age improve the relative control."),
)})

RETENTION = MappingProxyType({
    "minimum_relative_improvement": .01,
    "maximum_relative_regression": .01,
    "absolute_tolerance": .000001,
    "fold_consistency": "No loss regresses beyond tolerance on either fold or pooled rows.",
    "ranking": "Pooled MAE, then pinball, spike Brier, direction Brier, then recipe ID.",
    "references": "Controls versus persistence; feature variants versus persistence, relative control and the selected control.",
})

UNTESTED = (
    "Solar forecasts and derived delivery ramps; no derived features introduced in 4A.",
    "Sparse aFRR, production/consumption observations, cross-border and neighboring markets.",
    "Head-specific subsets, horizon grouping, tree/regularization refinements, ensembles and regimes.",
    "Calibration remains Step 5; final test generation remains Step 6.",
)
