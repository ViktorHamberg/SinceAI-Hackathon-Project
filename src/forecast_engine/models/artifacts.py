"""Private, versioned JSON persistence for native fitted models and full lineage."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from types import MappingProxyType

from ..config import RunConfig
from ..contracts import FitProvenance
from ..engine import _check_fitting_availability
from ..provenance import DependencyEvidence, SourceDependency
from .heads import DIRECTION_CLASSES, SPIKE_CLASSES, FittedHead, TreeRecipe
from .lightgbm import FittedLightGBM

_TYPES = {kind.__name__: kind for kind in (
    FittedLightGBM, FittedHead, TreeRecipe, FitProvenance, RunConfig,
    DependencyEvidence, SourceDependency,
)}


def _encode(value):
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("artifact datetime must be timezone-aware")
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, tuple):
        return {"type": "tuple", "value": [_encode(item) for item in value]}
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("artifact mapping requires string keys")
        return {"type": "mapping", "value": {key: _encode(item) for key, item in value.items()}}
    if is_dataclass(value) and type(value).__name__ in _TYPES and _TYPES[type(value).__name__] is type(value):
        return {"type": type(value).__name__,
                "value": {field.name: _encode(getattr(value, field.name)) for field in fields(value)}}
    raise ValueError("unsupported artifact state")


def _decode(value):
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if not isinstance(value, dict) or set(value) != {"type", "value"}:
        raise ValueError("invalid artifact state")
    kind, data = value["type"], value["value"]
    if kind == "datetime":
        result = datetime.fromisoformat(data)
        if result.utcoffset() is None:
            raise ValueError("artifact datetime must be timezone-aware")
        return result
    if kind == "tuple" and isinstance(data, list):
        return tuple(_decode(item) for item in data)
    if kind == "mapping" and isinstance(data, dict):
        return MappingProxyType({key: _decode(item) for key, item in data.items()})
    if kind in _TYPES and isinstance(data, dict) and set(data) == {f.name for f in fields(_TYPES[kind])}:
        return _TYPES[kind](**{key: _decode(item) for key, item in data.items()})
    raise ValueError("unknown artifact state type")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _validate(fitted):
    from ..features.registry import FEATURE_REGISTRY, REGISTRY_VERSION

    if type(fitted) is not FittedLightGBM or fitted._registry_version != REGISTRY_VERSION:
        raise ValueError("artifact requires a compatible native fitted model")
    if fitted._target_mode not in ("direct", "spot_relative") or fitted._quantile_policy != "preserve_p50_clamp_outer_bounds":
        raise ValueError("unsupported artifact prediction policy")
    if (not fitted._feature_names or "horizon_step" not in fitted._feature_names
            or len(set(fitted._feature_names)) != len(fitted._feature_names)
            or any(name not in FEATURE_REGISTRY for name in fitted._feature_names)
            or type(fitted._recipe) is not TreeRecipe or type(fitted.provenance) is not FitProvenance):
        raise ValueError("invalid artifact recipe")
    expected_id = "lightgbm-relative-v1" if fitted._target_mode == "spot_relative" else "lightgbm-direct-v1"
    if fitted.provenance.predictor_id != expected_id:
        raise ValueError("artifact predictor identity mismatch")
    _check_fitting_availability(fitted.provenance, fitted.provenance.config.fit_cutoff_utc)
    if tuple(head.name for head in fitted._heads) != ("p10", "p50", "p90", "direction", "spike"):
        raise ValueError("artifact primary heads mismatch")
    backup_names = ("p10", "p50", "p90") if fitted._target_mode == "spot_relative" else ()
    if tuple(head.name for head in fitted._direct_heads) != backup_names:
        raise ValueError("artifact backup heads mismatch")
    for head in (*fitted._heads, *fitted._direct_heads):
        classes = DIRECTION_CLASSES if head.name == "direction" else SPIKE_CLASSES if head.name == "spike" else ()
        if (type(head) is not FittedHead or head.feature_names != fitted._feature_names
                or head.classes != classes or head.objective != ("multiclass" if classes else "quantile")
                or not isinstance(head._model_text, str) or not head._model_text or not head.native_version):
            raise ValueError("invalid artifact head")


def save_fitted_model(path, fitted, *, identity):
    """Atomically save private state; identity must describe sources and runtime."""
    _validate(fitted)
    model = _encode(fitted)
    document = {"format_version": 1, "identity": identity, "model": model,
                "model_sha256": hashlib.sha256(_canonical(model)).hexdigest()}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".model-", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump(document, output, separators=(",", ":"), allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_fitted_model(path, *, identity):
    """Load locally generated JSON only; never unpickle or dynamically import types."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if (set(document) != {"format_version", "identity", "model", "model_sha256"}
            or document["format_version"] != 1 or document["identity"] != identity
            or hashlib.sha256(_canonical(document["model"])).hexdigest() != document["model_sha256"]):
        raise ValueError("model cache is incompatible or damaged; rebuild explicitly")
    fitted = _decode(document["model"])
    _validate(fitted)
    return fitted
