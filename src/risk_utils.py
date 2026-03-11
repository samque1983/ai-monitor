"""Shared utilities for risk modules."""
import os
from typing import Set

CASH_LIKE_TICKERS: Set[str] = {
    "SGOV", "BIL", "SHV", "SHY", "VGSH", "JPST", "ICSH",
    "VMFXX", "SPAXX", "FDRXX", "SPRXX",
}

_FX_DEFAULTS = {
    "HKD": 0.1280, "CNH": 0.1378, "CNY": 0.1378,
    "EUR": 1.08, "GBP": 1.27, "CAD": 0.73, "JPY": 0.0066,
}


def get_fx_rate(currency: str) -> float:
    """Return USD per 1 unit of given currency. Reads FX_<CCY>USD env var first."""
    if currency == "USD":
        return 1.0
    env_key = f"FX_{currency}USD"
    env_val = os.environ.get(env_key)
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    return _FX_DEFAULTS.get(currency, 1.0)


def normalize_ticker(symbol: str) -> str:
    """Normalize ticker for yfinance: numeric HK codes → 0883.HK, spaces → dash."""
    if symbol.isdigit():
        return symbol.zfill(4) + ".HK"
    if " " in symbol:
        return symbol.replace(" ", "-")
    return symbol
