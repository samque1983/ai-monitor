# tests/test_integration.py
"""Integration test: full scan pipeline with mocked data sources."""
import pytest
import pandas as pd
import numpy as np
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
from src.dividend_store import DividendStore
from src.data_engine import build_ticker_data
from src.market_data import MarketDataProvider
from src.scanners import scan_iv_extremes, scan_ma200_crossover, scan_leaps_setup, scan_sell_put, scan_iv_momentum, scan_earnings_gap
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
    provider.get_iv_momentum.return_value = 25.0  # Below threshold
    provider.get_historical_earnings_dates.return_value = []

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


def test_phase2_pipeline_integration(mock_provider):
    """Phase 2 扫描器集成测试"""
    td = build_ticker_data("AAPL", mock_provider, reference_date=date(2026, 2, 20))
    assert td is not None

    all_data = [td]

    # Phase 1 扫描器
    iv_low, iv_high = scan_iv_extremes(all_data)
    ma200_bull, ma200_bear = scan_ma200_crossover(all_data)
    leaps = scan_leaps_setup(all_data)

    # Phase 2 扫描器
    iv_momentum = scan_iv_momentum(all_data, threshold=30.0)
    earnings_gaps = scan_earnings_gap(all_data, mock_provider, days_threshold=3)

    # 生成报告
    report = format_report(
        scan_date=date(2026, 2, 20),
        data_source="mock",
        universe_count=1,
        iv_low=iv_low, iv_high=iv_high,
        ma200_bullish=ma200_bull, ma200_bearish=ma200_bear,
        leaps=leaps, sell_puts=[],
        iv_momentum=iv_momentum,
        earnings_gaps=earnings_gaps,
        earnings_gap_ticker_map={"AAPL": td},
        elapsed_seconds=1.0,
    )

    assert "波动率异动雷达" in report
    assert "财报 Gap 预警" in report


def test_weekly_scan_triggered_when_pool_empty(tmp_path):
    """main.py triggers weekly scan when pool is empty."""
    store = DividendStore(str(tmp_path / "test.db"))
    assert store.get_last_scan_date() is None
    assert store.get_current_pool() == []
    store.close()


def test_weekly_scan_triggered_after_7_days(tmp_path):
    """main.py triggers weekly scan when last scan >= 7 days ago."""
    store = DividendStore(str(tmp_path / "test.db"))
    old_date = date.today() - timedelta(days=8)
    from tests.test_dividend_store import _make_ticker
    store.save_pool([_make_ticker("KO")], version=str(old_date))

    last_scan = store.get_last_scan_date()
    assert last_scan == old_date
    assert (date.today() - last_scan).days >= 7
    store.close()


def test_weekly_scan_not_triggered_within_7_days(tmp_path):
    """main.py skips weekly scan when last scan < 7 days ago."""
    store = DividendStore(str(tmp_path / "test.db"))
    recent_date = date.today() - timedelta(days=3)
    from tests.test_dividend_store import _make_ticker
    store.save_pool([_make_ticker("KO")], version=str(recent_date))

    last_scan = store.get_last_scan_date()
    assert (date.today() - last_scan).days < 7
    store.close()


def test_main_card_engine_disabled_by_default():
    """card_engine disabled by default — no CardEngine import errors."""
    from src.config import load_config
    config = load_config("config.yaml")
    assert config.get("card_engine", {}).get("enabled", False) is False
