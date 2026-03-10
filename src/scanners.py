from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple, TYPE_CHECKING
import logging

import pandas as pd

from src.data_engine import TickerData, EarningsGap, compute_earnings_gaps

if TYPE_CHECKING:
    from src.market_data import MarketDataProvider

logger = logging.getLogger(__name__)


def scan_iv_extremes(data: List[TickerData]) -> Tuple[List[TickerData], List[TickerData]]:
    """Module 2: Find tickers with extreme IV Rank. Returns (low_iv_list, high_iv_list)."""
    low = [t for t in data if t.iv_rank is not None and t.iv_rank < 20]
    high = [t for t in data if t.iv_rank is not None and t.iv_rank > 80]
    return low, high


def scan_iv_momentum(
    data: List[TickerData],
    threshold: float = 30.0
) -> List[TickerData]:
    """
    波动率异动雷达: 筛选 IV 快速膨胀的标的

    触发条件:
        iv_momentum > threshold (默认 30%)

    输出:
        符合条件的 TickerData 列表,按 iv_momentum 降序排列
    """
    result = [
        t for t in data
        if t.iv_momentum is not None and t.iv_momentum > threshold
    ]
    # 按动量降序排列
    result.sort(key=lambda x: x.iv_momentum, reverse=True)
    return result


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
    ask: float
    mid: float
    spread_pct: float
    dte: int
    expiration: date
    apy: float           # percentage, based on midpoint
    earnings_risk: bool
    liquidity_warn: bool  # True if spread 20-30%


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
    ask = float(best.get("ask", 0) or 0)
    dte = int(best["dte"])
    expiration = best["expiration"]

    if strike == 0 or dte == 0:
        return None

    # Liquidity: compute spread
    mid = (bid + ask) / 2 if ask > 0 else bid
    spread_pct = ((ask - bid) / mid * 100) if mid > 0 and ask > 0 else 0.0

    # Hard filter: spread > 30% → no signal for standalone sell put
    if spread_pct > 30:
        return None

    liquidity_warn = spread_pct > 20

    apy = (mid / strike) * (365 / dte) * 100

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
        ask=ask,
        mid=mid,
        spread_pct=round(spread_pct, 1),
        dte=dte,
        expiration=expiration if isinstance(expiration, date) else expiration,
        apy=round(apy, 2),
        earnings_risk=earnings_risk,
        liquidity_warn=liquidity_warn,
    )


def scan_earnings_gap(
    data: List[TickerData],
    provider: "MarketDataProvider",
    days_threshold: int = 3,
) -> List[EarningsGap]:
    """
    财报 Gap 黑天鹅预警: 分析即将财报的历史跳空风险

    触发条件:
        days_to_earnings <= days_threshold (默认 3 天)
    """
    results = []

    for t in data:
        # 检查是否临近财报
        if t.days_to_earnings is None or t.days_to_earnings > days_threshold:
            continue

        # 跳过非期权市场
        if provider.should_skip_options(t.ticker):
            continue

        try:
            # 获取历史财报日期 (带 fallback)
            hist_dates = provider.get_historical_earnings_dates(t.ticker)
            if len(hist_dates) < 2:
                logger.debug(f"Insufficient earnings history for {t.ticker}")
                continue

            # 获取历史价格
            price_df = provider.get_price_data(t.ticker, period="3y")
            if price_df.empty:
                logger.warning(f"No price data for {t.ticker}")
                continue

            # 计算 Gap 统计
            gap = compute_earnings_gaps(t.ticker, hist_dates, price_df)
            if gap:
                results.append(gap)

        except Exception as e:
            logger.error(f"Earnings gap scan failed for {t.ticker}: {e}")
            continue

    return results
