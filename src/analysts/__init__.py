from .base import BaseAnalyst
from .buffett import BuffettAnalyst
from .munger import MungerAnalyst
from .soros import SorosAnalyst
from .lynch import LynchAnalyst
from .dalio import DalioAnalyst
from .icahn import IcahnAnalyst
from .graham import GrahamAnalyst

ALL_ANALYSTS = [
    BuffettAnalyst,
    MungerAnalyst,
    SorosAnalyst,
    LynchAnalyst,
    DalioAnalyst,
    IcahnAnalyst,
    GrahamAnalyst,
]

__all__ = [
    "BaseAnalyst",
    "BuffettAnalyst",
    "MungerAnalyst",
    "SorosAnalyst",
    "LynchAnalyst",
    "DalioAnalyst",
    "IcahnAnalyst",
    "GrahamAnalyst",
    "ALL_ANALYSTS",
]
