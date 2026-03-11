"""Option strategy recognition — groups raw Flex positions into named strategies."""
from dataclasses import dataclass, field
from typing import List, Optional
from src.flex_client import PositionRecord


@dataclass
class StrategyGroup:
    underlying: str
    strategy_type: str   # "Iron Condor", "Bull Put Spread", "Naked Put", ...
    intent: str          # "income" | "hedge" | "directional" | "speculation" | "mixed"
    legs: List[PositionRecord] = field(default_factory=list)
    stock_leg: Optional[PositionRecord] = None
    modifiers: List[PositionRecord] = field(default_factory=list)
    net_delta: float = 0.0
    net_theta: float = 0.0
    net_vega: float = 0.0
    net_gamma: float = 0.0
    max_profit: Optional[float] = None   # None = unlimited
    max_loss: Optional[float] = None     # None = unlimited (naked)
    breakevens: List[float] = field(default_factory=list)
    expiry: str = ""     # primary leg expiry "YYYYMMDD"
    dte: int = 0
    net_pnl: float = 0.0
    net_credit: float = 0.0   # >0 = received premium, <0 = paid premium
    currency: str = "USD"
