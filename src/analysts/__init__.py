from .base import BaseAnalyst
from .buffett import BuffettAnalyst
from .munger import MungerAnalyst
from .soros import SorosAnalyst
from .lynch import LynchAnalyst
from .dalio import DalioAnalyst
from .icahn import IcahnAnalyst
from .graham import GrahamAnalyst
from .taleb import TalebAnalyst

ALL_ANALYSTS = [
    BuffettAnalyst,
    MungerAnalyst,
    SorosAnalyst,
    LynchAnalyst,
    DalioAnalyst,
    IcahnAnalyst,
    GrahamAnalyst,
    TalebAnalyst,
]

# Mapping from config key to analyst class
ANALYST_REGISTRY = {
    "warren_buffett": BuffettAnalyst,
    "charlie_munger": MungerAnalyst,
    "george_soros": SorosAnalyst,
    "peter_lynch": LynchAnalyst,
    "ray_dalio": DalioAnalyst,
    "carl_icahn": IcahnAnalyst,
    "benjamin_graham": GrahamAnalyst,
    "nassim_taleb": TalebAnalyst,
}


def get_enabled_analysts(config: dict) -> list:
    """Return analyst classes based on config.

    If analysts.enabled is set in config, only return those analysts.
    Otherwise return all analysts.
    """
    enabled = config.get("analysts", {}).get("enabled")
    if enabled is None:
        return list(ALL_ANALYSTS)

    selected = []
    for key in enabled:
        cls = ANALYST_REGISTRY.get(key)
        if cls:
            selected.append(cls)
    return selected


__all__ = [
    "BaseAnalyst",
    "BuffettAnalyst",
    "MungerAnalyst",
    "SorosAnalyst",
    "LynchAnalyst",
    "DalioAnalyst",
    "IcahnAnalyst",
    "GrahamAnalyst",
    "TalebAnalyst",
    "ALL_ANALYSTS",
    "ANALYST_REGISTRY",
    "get_enabled_analysts",
]
