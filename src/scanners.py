from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

import pandas as pd

from src.data_engine import TickerData


def scan_iv_extremes(data: List[TickerData]) -> Tuple[List[TickerData], List[TickerData]]:
    """Module 2: Find tickers with extreme IV Rank. Returns (low_iv_list, high_iv_list)."""
    low = [t for t in data if t.iv_rank is not None and t.iv_rank < 20]
    high = [t for t in data if t.iv_rank is not None and t.iv_rank > 80]
    return low, high


def scan_ma200_crossover(data: List[TickerData]) -> Tuple[List[TickerData], List[TickerData]]:
    """Module 3: Detect MA200 crossover signals. Returns (bullish_list, bearish_list)."""
    bullish = []
    bearish = []
    for t in data:
        if t.ma200 is None:
            continue
        pct_above = (t.last_price - t.ma200) / t.ma200

        # Bullish cross: was below, now above
        if t.prev_close < t.ma200 and t.last_price > t.ma200:
            bullish.append(t)
        # Just crossed above (within 1% above and prev at or below)
        elif 0 < pct_above <= 0.01 and t.prev_close <= t.ma200:
            bullish.append(t)
        # Bearish cross: was above, now below
        elif t.prev_close > t.ma200 and t.last_price < t.ma200:
            bearish.append(t)
        # Just crossed below (within 1% below and prev at or above)
        elif -0.01 <= pct_above < 0 and t.prev_close >= t.ma200:
            bearish.append(t)

    return bullish, bearish


def scan_leaps_setup(data: List[TickerData]) -> List[TickerData]:
    """Module 4: V1.9 LEAPS Setup — all 4 conditions must be met.

    1. last_price > MA200
    2. last_price within ±3% of weekly MA50
    3. RSI-14 <= 45
    4. IV Rank < 30%
    """
    results = []
    for t in data:
        if t.ma200 is None or t.ma50w is None or t.rsi14 is None or t.iv_rank is None:
            continue
        if t.last_price <= t.ma200:
            continue
        if abs(t.last_price - t.ma50w) / t.ma50w > 0.03:
            continue
        if t.rsi14 > 45:
            continue
        if t.iv_rank >= 30:
            continue
        results.append(t)
    return results


@dataclass
class SellPutSignal:
    ticker: str
    strike: float
    bid: float
    dte: int
    expiration: date
    apy: float           # percentage, e.g. 9.6
    earnings_risk: bool   # True if earnings falls within DTE


def scan_sell_put(
    ticker_data: TickerData,
    target_strike: float,
    options_df: pd.DataFrame,
    min_apy: float = 4.0,
) -> Optional[SellPutSignal]:
    """Module 5: Sell Put scanner for a single ticker.

    Finds the put option with strike closest to (and <=) target_strike.
    Returns SellPutSignal if APY >= min_apy, else None.
    """
    if options_df.empty:
        return None

    eligible = options_df[options_df["strike"] <= target_strike].copy()
    if eligible.empty:
        return None

    eligible = eligible.sort_values("strike", ascending=False)
    best = eligible.iloc[0]

    strike = float(best["strike"])
    bid = float(best["bid"])
    dte = int(best["dte"])
    expiration = best["expiration"]

    if strike == 0 or dte == 0:
        return None

    apy = (bid / strike) * (365 / dte) * 100

    if apy < min_apy:
        return None

    earnings_risk = False
    if ticker_data.earnings_date and ticker_data.days_to_earnings is not None:
        if ticker_data.days_to_earnings <= dte:
            earnings_risk = True

    return SellPutSignal(
        ticker=ticker_data.ticker,
        strike=strike,
        bid=bid,
        dte=dte,
        expiration=expiration if isinstance(expiration, date) else expiration,
        apy=round(apy, 2),
        earnings_risk=earnings_risk,
    )
