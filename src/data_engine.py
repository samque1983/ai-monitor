# src/data_engine.py
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Dict
import pandas as pd
import numpy as np
from src.data_loader import classify_market
from src.market_data import MarketDataProvider

logger = logging.getLogger(__name__)


@dataclass
class TickerData:
    ticker: str
    name: str
    market: str              # "US" | "HK" | "CN"
    last_price: float
    ma200: Optional[float]
    ma50w: Optional[float]
    rsi14: Optional[float]
    iv_rank: Optional[float]
    iv_momentum: Optional[float]  # 新增: 5日IV动量 (%)
    prev_close: float
    earnings_date: Optional[date]
    days_to_earnings: Optional[int]

    # Phase 2: 高股息新增字段
    dividend_yield: Optional[float] = None
    dividend_yield_5y_percentile: Optional[float] = None
    dividend_quality_score: Optional[float] = None
    consecutive_years: Optional[int] = None
    dividend_growth_5y: Optional[float] = None
    payout_ratio: Optional[float] = None
    roe: Optional[float] = None
    debt_to_equity: Optional[float] = None
    industry: Optional[str] = None
    sector: Optional[str] = None
    free_cash_flow: Optional[float] = None
    payout_type: Optional[str] = None   # "FCF" | "GAAP" | None

    # Phase 3: 股息卡片富化字段
    quality_breakdown: Optional[Dict[str, float]] = None
    analysis_text: Optional[str] = None
    forward_dividend_rate: Optional[float] = None
    max_yield_5y: Optional[float] = None
    data_version_date: Optional[str] = None


@dataclass
class EarningsGap:
    """历史财报 Gap 统计"""
    ticker: str
    avg_gap: float       # mean(|gap|) 平均跳空幅度 (%)
    up_ratio: float      # P(gap > 0) 上涨概率 (%)
    max_gap: float       # 最大跳空 (保留符号)
    sample_count: int    # 样本数量


def compute_sma(prices: pd.Series, window: int) -> Optional[float]:
    """Compute Simple Moving Average. Returns None if insufficient data."""
    if len(prices) < window:
        return None
    return float(prices.iloc[-window:].mean())


def compute_rsi(prices: pd.Series, period: int = 14) -> Optional[float]:
    """Compute RSI using Wilder's smoothing method. Returns None if insufficient data."""
    if len(prices) < period + 1:
        return None
    deltas = prices.diff().dropna()
    gains = deltas.clip(lower=0)
    losses = (-deltas.clip(upper=0))

    avg_gain = gains.iloc[:period].mean()
    avg_loss = losses.iloc[:period].mean()

    # Smoothed RSI (Wilder's method)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains.iloc[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses.iloc[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def compute_earnings_gaps(
    ticker: str,
    earnings_dates: list,
    price_df: pd.DataFrame,
    min_samples: int = 2,
) -> Optional[EarningsGap]:
    """
    计算历史财报 Gap 统计

    Gap 定义 (MVP 简化版):
        gap = (财报日 Open - 前一交易日 Close) / 前一交易日 Close * 100

    边界处理:
    - 财报日不在 price_df 中: 跳过该事件
    - 样本数 < min_samples: 返回 None
    - prev_close = 0: 跳过该事件
    """
    if not earnings_dates or price_df.empty:
        return None

    # 数据验证
    if not validate_price_df(price_df, ticker):
        return None

    gaps = []
    for ed in earnings_dates:
        ed_ts = pd.Timestamp(ed)

        # 检查财报日是否在数据中
        if ed_ts not in price_df.index:
            continue

        # 获取前一交易日
        idx = price_df.index.get_loc(ed_ts)
        if idx == 0:
            continue
        prev_ts = price_df.index[idx - 1]

        prev_close = float(price_df.loc[prev_ts, "Close"])
        ed_open = float(price_df.loc[ed_ts, "Open"])

        # 除零保护
        if prev_close == 0 or pd.isna(prev_close):
            continue

        gap = (ed_open - prev_close) / prev_close * 100
        gaps.append(gap)

    # 样本数检查
    if len(gaps) < min_samples:
        return None

    # 统计计算
    abs_gaps = [abs(g) for g in gaps]
    avg_gap = sum(abs_gaps) / len(abs_gaps)
    up_count = sum(1 for g in gaps if g > 0)
    up_ratio = up_count / len(gaps) * 100
    max_gap_val = max(gaps, key=abs)  # 保留符号

    return EarningsGap(
        ticker=ticker,
        avg_gap=round(avg_gap, 1),
        up_ratio=round(up_ratio, 1),
        max_gap=round(max_gap_val, 1),
        sample_count=len(gaps),
    )


def validate_price_df(df: pd.DataFrame, ticker: str) -> bool:
    """
    验证价格 DataFrame 的质量 (data-explorer 思路)

    检查项:
    1. 必须包含 Open, Close 列
    2. 价格值 > 0
    3. 无 NaN (或 NaN 占比 < 5%)

    Returns:
        True: 数据合格
        False: 数据异常,应跳过该 ticker
    """
    if df.empty:
        logger.warning(f"Empty price data for {ticker}")
        return False

    required_cols = ["Open", "Close"]
    if not all(col in df.columns for col in required_cols):
        logger.warning(f"Missing required columns for {ticker}")
        return False

    # 检查价格 > 0
    if (df["Close"] <= 0).any() or (df["Open"] <= 0).any():
        logger.warning(f"Invalid price values for {ticker}")
        return False

    # 检查 NaN 占比
    total_cells = len(df) * len(required_cols)
    nan_count = df[required_cols].isna().sum().sum()
    nan_ratio = nan_count / total_cells if total_cells > 0 else 0

    if nan_ratio > 0.05:
        logger.warning(f"Too many NaN values for {ticker}: {nan_ratio:.1%}")
        return False

    return True


def build_ticker_data(
    ticker: str,
    provider: MarketDataProvider,
    reference_date: Optional[date] = None,
) -> Optional[TickerData]:
    """Build TickerData for a single ticker. Returns None on failure."""
    if reference_date is None:
        reference_date = date.today()

    # Fetch daily price data
    daily_df = provider.get_price_data(ticker, period="1y")
    if daily_df.empty:
        logger.warning(f"No daily data for {ticker}, skipping")
        return None

    close = daily_df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    last_price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) >= 2 else last_price

    # Daily SMA 200
    ma200 = compute_sma(close, 200)

    # RSI-14
    rsi14 = compute_rsi(close, 14)

    # Weekly SMA 50
    weekly_df = provider.get_weekly_price_data(ticker, period="2y")
    ma50w = None
    if not weekly_df.empty:
        weekly_close = weekly_df["Close"]
        if isinstance(weekly_close, pd.DataFrame):
            weekly_close = weekly_close.iloc[:, 0]
        ma50w = compute_sma(weekly_close, 50)

    # IV Rank
    iv_rank = provider.get_iv_rank(ticker)

    # IV Momentum
    iv_momentum = provider.get_iv_momentum(ticker)

    # Earnings date
    earnings_date = provider.get_earnings_date(ticker)
    days_to_earnings = None
    if earnings_date:
        days_to_earnings = (earnings_date - reference_date).days
        if days_to_earnings < 0:
            days_to_earnings = None
            earnings_date = None

    market = classify_market(ticker)

    return TickerData(
        ticker=ticker,
        name=ticker,
        market=market,
        last_price=last_price,
        ma200=ma200,
        ma50w=ma50w,
        rsi14=rsi14,
        iv_rank=iv_rank,
        iv_momentum=iv_momentum,
        prev_close=prev_close,
        earnings_date=earnings_date,
        days_to_earnings=days_to_earnings,
    )
