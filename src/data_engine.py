# src/data_engine.py
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional
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
    prev_close: float
    earnings_date: Optional[date]
    days_to_earnings: Optional[int]


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
        prev_close=prev_close,
        earnings_date=earnings_date,
        days_to_earnings=days_to_earnings,
    )
