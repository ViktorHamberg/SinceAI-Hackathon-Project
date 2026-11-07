"""Versioned feature definitions. Each feature has exactly one attribution category.

Observation windows are [origin - window, origin); latest observations have delivery
strictly before origin. Delivery features require an exact quarter-hour match.
Calendar components are deterministic functions of delivery time in Europe/Helsinki;
holidays use the supplied calendar rows. No historical forecast vintages are inferred.
"""

from dataclasses import dataclass
from types import MappingProxyType

REGISTRY_VERSION = "asof-v1"
CATEGORIES = (
    "renewable_production", "consumption", "production", "cross_border_flows",
    "neighboring_markets", "balancing_conditions", "historical_prices",
    "spot_price_conditions", "calendar_horizon",
)


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    category: str
    unit: str
    operation: str
    source_series: tuple[str, ...] = ()
    window_minutes: int | None = None
    missing_policy: str = "NaN; no filling; omit dependency evidence when missing"


_definitions = [
    FeatureDefinition("horizon_step", "calendar_horizon", "quarter-hour", "step",
                      missing_policy="Always known from origin and step"),
    FeatureDefinition("lead_minutes", "calendar_horizon", "min", "lead",
                      missing_policy="Always known from origin and step"),
    *[FeatureDefinition(f"delivery_{part}", "calendar_horizon", "index", f"calendar_{part}",
                        missing_policy="Always known from delivery timestamp")
      for part in ("hour_local", "weekday_local", "quarter", "is_dst")],
]


def _observation(series: str, category: str, unit: str) -> None:
    _definitions.extend((
        FeatureDefinition(f"{series}_latest", category, unit, "latest", (series,)),
        FeatureDefinition(f"{series}_age_minutes", category, "min", "age", (series,)),
    ))


_observation("fi_imbalance_price", "historical_prices", "EUR/MWh")
_observation("fi_mfrr_direction", "balancing_conditions", "-1/0/1")
for _window in (60, 180):
    for _op in ("mean", "std"):
        _definitions.append(FeatureDefinition(
            f"fi_imbalance_price_{_op}_{_window}m", "historical_prices", "EUR/MWh",
            _op, ("fi_imbalance_price",), _window,
        ))

for _series, _category, _unit in (
    ("fi_spot_price", "spot_price_conditions", "EUR/MWh"),
    ("cal_is_holiday_fi", "calendar_horizon", "0/1"),
    ("fi_consumption_fc_da", "consumption", "MW"),
    ("fi_wind_fc_da", "renewable_production", "MWh/h"),
    ("fi_solar_fc_da", "renewable_production", "MWh/h"),
    ("fi_ee_capacity_da", "cross_border_flows", "MW"),
    ("ee_fi_capacity_da", "cross_border_flows", "MW"),
    *[(f"{area}_load_fc_da", "neighboring_markets", "MW") for area in ("se1", "se3", "ee")],
):
    _definitions.append(FeatureDefinition(
        f"{_series}_delivery", _category, _unit, "delivery", (_series,),
    ))

for _series, _category, _unit in (
    *[(f"fi_{reserve}_{side}_price", "balancing_conditions", "EUR/MWh")
      for reserve in ("mfrr", "afrr") for side in ("up", "down")],
    *[(f"fi_mfrr_{side}_activated", "balancing_conditions", "MW") for side in ("up", "down")],
    ("fi_consumption", "consumption", "MWh/h"),
    ("fi_production", "production", "MWh/h"),
    *[(f"fi_{area}_flow", "cross_border_flows", "MW") for area in ("se3", "no4", "se1")],
    ("fi_ee_flow", "cross_border_flows", "MWh/h"),
    *[(f"{area}_imbalance_price_{side}", "neighboring_markets", "EUR/MWh")
      for area in ("se1", "se3", "ee") for side in ("long", "short")],
):
    _observation(_series, _category, _unit)

FEATURE_REGISTRY = MappingProxyType({definition.name: definition for definition in _definitions})
DEFAULT_FEATURE_NAMES = tuple(definition.name for definition in _definitions[:14]) + (
    "fi_spot_price_delivery",
)
# First 14 definitions: six calendar/horizon, four latest/age and four rolling features.
del _definitions, _series, _category, _unit, _window, _op
