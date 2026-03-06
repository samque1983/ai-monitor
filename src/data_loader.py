# src/data_loader.py
import io
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
import logging

logger = logging.getLogger(__name__)


def clean_strike_price(value) -> Optional[float]:
    """Clean strike price value: remove $, Chinese chars, convert to float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        import math
        if math.isnan(value):
            return None
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    # Remove $ and any non-numeric chars except . and -
    cleaned = re.sub(r"[^\d.\-]", "", s)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_ticker(ticker: str) -> str:
    """Normalize ticker symbol for yfinance compatibility.

    - BRK.B → BRK-B (yfinance uses dash for share class)
    - 600900 → 600900.SS (Shanghai)
    - 000001 → 000001.SZ (Shenzhen)
    - 300750 → 300750.SZ (Shenzhen ChiNext)
    """
    t = ticker.strip().upper()
    # Already has exchange suffix like .SS, .SZ, .HK → skip digit logic
    if re.match(r"^\d{6}\.(SS|SZ)$", t):
        return t
    # US share class: BRK.B → BRK-B, BRK.A → BRK-A
    if re.match(r"^[A-Z]+\.[A-Z]$", t):
        return t.replace(".", "-")
    # Bare 6-digit A-share code → add suffix
    if re.match(r"^\d{6}$", t):
        if t.startswith("6"):
            return t + ".SS"
        else:
            return t + ".SZ"
    return t


def classify_market(ticker: str) -> str:
    """Classify ticker into market: 'US', 'HK', or 'CN'."""
    ticker = ticker.upper()
    if ticker.endswith(".HK"):
        return "HK"
    if ticker.endswith(".SS") or ticker.endswith(".SZ"):
        return "CN"
    return "US"


def fetch_universe(csv_url: str) -> Tuple[List[str], Dict[str, float]]:
    """Fetch stock universe from Google Sheets CSV.

    Returns:
        tickers: List of all ticker symbols
        target_buys: Dict of {ticker: strike_price} for Sell Put scanning

    Raises on network/parse failure (no data = no scan).
    """
    resp = requests.get(csv_url, timeout=30, verify=False)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    df = pd.read_csv(io.StringIO(resp.text))

    # Clean ticker column
    df["代码"] = df["代码"].astype(str).str.strip()
    df = df[df["代码"].notna() & (df["代码"] != "") & (df["代码"] != "nan") & (df["代码"] != "None")]

    df["代码"] = df["代码"].apply(normalize_ticker)
    tickers = df["代码"].tolist()

    # Build target buy list
    target_buys = {}
    if "Strike (黄金位)" in df.columns:
        for _, row in df.iterrows():
            ticker = row["代码"]
            strike = clean_strike_price(row.get("Strike (黄金位)"))
            if strike is not None:
                target_buys[ticker] = strike

    logger.info(f"Loaded {len(tickers)} tickers, {len(target_buys)} target buys")
    return tickers, target_buys
