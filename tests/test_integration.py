# tests/test_integration.py
"""Integration test: full scan pipeline with mocked data sources."""
import pytest
import pandas as pd
import numpy as np
from datetime import date, datetime
from unittest.mock import MagicMock
from src.data_engine import build_ticker_data
from src.market_data import MarketDataProvider
from src.scanners import scan_iv_extremes, scan_ma200_crossover, scan_leaps_setup, scan_sell_put
from src.report import format_report


@pytest.fixture
def mock_provider():
    provider = MagicMock(spec=MarketDataProvider)
    provider.ibkr = None

    # Generate realistic daily data (250 trading days)
    dates = pd.date_range("2025-03-01", periods=250, freq="B")
    close = np.concatenate([
        np.linspace(100, 180, 200),  # uptrend
        np.linspace(180, 170, 50),   # pullback
    ])
    daily_df = pd.DataFrame({"Close": close}, index=dates)
    provider.get_price_data.return_value = daily_df

    # Weekly data
    weekly_dates = pd.date_range("2025-01-01", periods=60, freq="W")
    weekly_close = np.linspace(95, 172, 60)
    weekly_df = pd.DataFrame({"Close": weekly_close}, index=weekly_dates)
    provider.get_weekly_price_data.return_value = weekly_df

    provider.get_earnings_date.return_value = date(2026, 4, 25)
    provider.get_iv_rank.return_value = 18.0
    provider.should_skip_options.return_value = False

    return provider


def test_full_pipeline(mock_provider):
    """Test complete scan pipeline from data to report."""
    # Build ticker data
    td = build_ticker_data("AAPL", mock_provider, reference_date=date(2026, 2, 20))
    assert td is not None
    assert td.ticker == "AAPL"

    # Run scanners
    all_data = [td]
    iv_low, iv_high = scan_iv_extremes(all_data)
    ma200_bull, ma200_bear = scan_ma200_crossover(all_data)
    leaps = scan_leaps_setup(all_data)

    # Generate report (should not crash)
    report = format_report(
        scan_date=date(2026, 2, 20),
        data_source="mock",
        universe_count=1,
        iv_low=iv_low, iv_high=iv_high,
        ma200_bullish=ma200_bull, ma200_bearish=ma200_bear,
        leaps=leaps, sell_puts=[],
        elapsed_seconds=1.0,
    )
    assert "量化扫描雷达" in report
    assert "AAPL" in report or "无符合条件的标的" in report
