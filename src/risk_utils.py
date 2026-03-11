"""Shared utilities for risk modules."""
import os
import re
from dataclasses import dataclass
from typing import List, Set

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


@dataclass
class AccountConfig:
    key: str           # env key prefix (e.g. "ALICE")
    name: str
    code: str
    flex_token: str
    flex_query_id: str


def load_account_configs() -> List[AccountConfig]:
    """Scan os.environ for ACCOUNT_*_FLEX_TOKEN pattern and return configs."""
    configs = []
    seen_keys: Set[str] = set()
    for env_key, val in os.environ.items():
        m = re.match(r"^ACCOUNT_([A-Z0-9_]+)_FLEX_TOKEN$", env_key)
        if not m:
            continue
        key = m.group(1)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        query_id = os.environ.get(f"ACCOUNT_{key}_FLEX_QUERY_ID", "")
        name = os.environ.get(f"ACCOUNT_{key}_NAME", key)
        code = os.environ.get(f"ACCOUNT_{key}_CODE", "")
        configs.append(AccountConfig(
            key=key, name=name, code=code,
            flex_token=val, flex_query_id=query_id,
        ))
    return configs
