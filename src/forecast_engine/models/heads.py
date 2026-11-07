"""Small native LightGBM heads; optional imports happen only during fit/predict.

Fitted heads retain an immutable private model string rather than a mutable Booster.
Prediction reconstructs a temporary native Booster; it never refits or persists models.
Model strings contain learned numeric information and must not be logged/published.
"""

from dataclasses import dataclass, field
import hashlib
import importlib
import math

DIRECTION_CLASSES = ("up", "down", "none")
SPIKE_CLASSES = ("high", "low", "neither")


def load_lightgbm():
    try:
        return importlib.import_module("lightgbm")
    except (ImportError, OSError):
        raise ImportError("LightGBM/native runtime unavailable; follow the engine experiment setup guide") from None


@dataclass(frozen=True)
class TreeRecipe:
    """Fixed-budget, CPU-only v1 recipe. No random split, tuning or early stopping."""

    num_boost_round: int = 30
    num_leaves: int = 15
    min_data_in_leaf: int = 20
    learning_rate: float = 0.05
    l2_regularization: float = 1.0
    seed: int = 2026

    def __post_init__(self):
        for name in ("num_boost_round", "num_leaves", "min_data_in_leaf", "seed"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < (0 if name == "seed" else 1):
                raise ValueError("tree recipe requires positive integer sizes and a nonnegative seed")
        if self.num_leaves < 2:
            raise ValueError("tree recipe requires at least two leaves")
        if not math.isfinite(self.learning_rate) or not 0 < self.learning_rate <= 1:
            raise ValueError("learning_rate must be finite and in (0,1]")
        if not math.isfinite(self.l2_regularization) or self.l2_regularization < 0:
            raise ValueError("regularization must be finite and nonnegative")

    def parameters(self):
        return {
            "boosting_type": "gbdt", "device_type": "cpu", "num_threads": 1,
            "deterministic": True, "force_col_wise": True, "verbosity": -1,
            "num_leaves": self.num_leaves, "min_data_in_leaf": self.min_data_in_leaf,
            "learning_rate": self.learning_rate, "lambda_l2": self.l2_regularization,
            "seed": self.seed, "data_random_seed": self.seed,
            "feature_fraction_seed": self.seed, "bagging_seed": self.seed,
            "feature_fraction": 1.0, "bagging_fraction": 1.0, "bagging_freq": 0,
            "feature_pre_filter": False, "min_data_in_bin": 1, "metric": "None",
        }


@dataclass(frozen=True, repr=False)
class FittedHead:
    name: str
    feature_names: tuple[str, ...]
    objective: str
    classes: tuple[str, ...]
    native_version: str
    _model_text: str = field(repr=False)

    @property
    def fingerprint(self):
        return hashlib.sha256(self._model_text.encode()).hexdigest()

    def predict(self, features):
        import numpy as np

        if tuple(features.columns) != self.feature_names:
            raise ValueError("prediction features differ from fitted head schema")
        try:
            native = load_lightgbm()
            model = native.Booster(model_str=self._model_text)
            values = np.asarray(model.predict(features, validate_features=True, num_threads=1), dtype=float)
        except ImportError:
            raise
        except Exception:
            raise RuntimeError("native LightGBM head prediction failed") from None
        shape = (len(features), len(self.classes)) if self.classes else (len(features),)
        if values.shape != shape or not np.isfinite(values).all():
            raise ValueError("native head returned invalid shape or nonfinite predictions")
        if self.classes and (np.any(values < 0) or np.any(values > 1)
                             or not np.allclose(values.sum(axis=1), 1, rtol=0, atol=1e-12)):
            raise ValueError("native classifier returned invalid probabilities")
        return values


def fit_head(name, features, labels, *, recipe, quantile=None, classes=()):
    """Fit one approved native objective with fixed parameters; no implicit fallback."""
    import numpy as np

    values = np.asarray(labels, dtype=float)
    if values.shape != (len(features),) or not np.isfinite(values).all():
        raise ValueError("head labels must be finite and aligned")
    if np.isinf(features.to_numpy(dtype=float)).any():
        raise ValueError("head features cannot contain infinity")
    if bool(classes) == (quantile is not None):
        raise ValueError("head needs exactly one quantile or classification objective")
    parameters = recipe.parameters()
    objective = "multiclass" if classes else "quantile"
    parameters["objective"] = objective
    if classes:
        if set(values) != set(range(len(classes))):
            raise ValueError("classification training requires every declared class")
        parameters["num_class"] = len(classes)
    else:
        if quantile not in (0.1, 0.5, 0.9):
            raise ValueError("unsupported price quantile")
        parameters["alpha"] = quantile
    native = load_lightgbm()
    try:
        dataset = native.Dataset(features, label=values, feature_name=list(features.columns), free_raw_data=True)
        model = native.train(parameters, dataset, num_boost_round=recipe.num_boost_round)
        model_text = model.model_to_string()
    except Exception:
        raise RuntimeError("native LightGBM head fitting failed") from None
    return FittedHead(name, tuple(features.columns), objective, tuple(classes), native.__version__, model_text)
