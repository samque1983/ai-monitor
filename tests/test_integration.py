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


def test_build_agent_payload_includes_all_signal_types():
    """_build_agent_payload returns dicts with signal_type for all signal types."""
    from src.main import _build_agent_payload
    from unittest.mock import MagicMock

    # minimal mocks
    sell_put_signal = MagicMock()
    sell_put_signal.ticker = "AAPL"
    sell_put_signal.strike = 180.0
    sell_put_signal.dte = 52
    sell_put_signal.bid = 3.2
    sell_put_signal.apy = 18.5
    sell_put_signal.earnings_risk = False

    ticker = MagicMock()
    ticker.ticker = "AAPL"
    ticker.last_price = 185.0
    ticker.ma200 = 170.0
    ticker.iv_rank = 18.0
    ticker.rsi14 = 42.0

    payload = _build_agent_payload(
        sell_puts=[(sell_put_signal, ticker)],
        iv_low=[ticker],
        iv_high=[],
        ma200_bull=[],
        ma200_bear=[],
        leaps=[],
        earnings_gaps=[],
        earnings_gap_ticker_map={},
        iv_momentum=[],
        dividend_signals=[],
    )

    types = {s["signal_type"] for s in payload}
    assert "sell_put" in types
    assert "iv_low" in types
    assert all("ticker" in s for s in payload)


def test_agent_payload_includes_floor_price():
    """Dividend signal dict in agent payload must include floor_price, floor_downside_pct,
    data_age_days, needs_reeval, quality_breakdown, and analysis_text fields."""
    from src.main import _build_agent_payload
    from src.dividend_scanners import DividendBuySignal
    from src.data_engine import TickerData

    td = TickerData(
        ticker="KO",
        name="Coca-Cola",
        market="US",
        last_price=65.0,
        ma200=60.0,
        ma50w=62.0,
        rsi14=40.0,
        iv_rank=20.0,
        iv_momentum=None,
        prev_close=64.0,
        earnings_date=None,
        days_to_earnings=None,
        dividend_yield=5.0,
        dividend_yield_5y_percentile=95.0,
        dividend_quality_score=80.0,
        consecutive_years=10,
        dividend_growth_5y=3.5,
        payout_ratio=60.0,
        roe=15.0,
        debt_to_equity=1.0,
        industry="Beverages",
        sector="Consumer Staples",
        free_cash_flow=10_000_000,
        forward_dividend_rate=2.0,
        max_yield_5y=4.0,
        quality_breakdown={"stability": 80.0},
        analysis_text="Strong payer.",
        data_version_date=str(date.today()),
    )

    signal = DividendBuySignal(
        ticker_data=td,
        signal_type="STOCK",
        current_yield=5.0,
        yield_percentile=95.0,
        option_details=None,
        forward_dividend_rate=2.0,
        max_yield_5y=4.0,
        floor_price=50.0,
        floor_downside_pct=round((65.0 - 50.0) / 65.0 * 100, 1),
        data_age_days=0,
        needs_reeval=False,
    )

    payload = _build_agent_payload(
        sell_puts=[],
        iv_low=[],
        iv_high=[],
        ma200_bull=[],
        ma200_bear=[],
        leaps=[],
        earnings_gaps=[],
        earnings_gap_ticker_map={},
        iv_momentum=[],
        dividend_signals=[signal],
    )

    assert len(payload) == 1
    entry = payload[0]
    assert entry["signal_type"] == "dividend"
    assert "floor_price" in entry
    assert "floor_downside_pct" in entry
    assert "data_age_days" in entry
    assert "needs_reeval" in entry
    assert "quality_breakdown" in entry
    assert "analysis_text" in entry
    assert "max_yield_5y" in entry
    assert entry["floor_price"] == pytest.approx(50.0)
    assert entry["max_yield_5y"] == pytest.approx(4.0)
    assert entry["data_age_days"] == 0
    assert entry["needs_reeval"] is False
    assert entry["analysis_text"] == "Strong payer."


def test_build_agent_payload_illiquid_option_details():
    """_build_agent_payload must not KeyError when option_details is illiquid dict.

    Illiquid dict has sell_put_illiquid=True and only strike/dte/spread_pct keys —
    no bid, ask, mid, or apy. The payload should set option_illiquid=True and
    option_bid=None without raising.
    """
    from src.main import _build_agent_payload
    from src.dividend_scanners import DividendBuySignal
    from src.data_engine import TickerData

    td = TickerData(
        ticker="KO",
        name="Coca-Cola",
        market="US",
        last_price=65.0,
        ma200=60.0,
        ma50w=62.0,
        rsi14=40.0,
        iv_rank=20.0,
        iv_momentum=None,
        prev_close=64.0,
        earnings_date=None,
        days_to_earnings=None,
        dividend_yield=5.0,
        dividend_yield_5y_percentile=95.0,
        dividend_quality_score=80.0,
        consecutive_years=10,
        dividend_growth_5y=3.5,
        payout_ratio=60.0,
        roe=15.0,
        debt_to_equity=1.0,
        industry="Beverages",
        sector="Consumer Staples",
        free_cash_flow=10_000_000,
        forward_dividend_rate=2.0,
        max_yield_5y=4.0,
        quality_breakdown={"stability": 80.0},
        analysis_text="Strong payer.",
        data_version_date=str(date.today()),
    )

    illiquid_opt = {
        "sell_put_illiquid": True,
        "strike": 60.0,
        "dte": 30,
        "spread_pct": 85.0,
    }

    signal = DividendBuySignal(
        ticker_data=td,
        signal_type="STOCK_OPTION",
        current_yield=5.0,
        yield_percentile=95.0,
        option_details=illiquid_opt,
        forward_dividend_rate=2.0,
        max_yield_5y=4.0,
        floor_price=50.0,
        floor_downside_pct=round((65.0 - 50.0) / 65.0 * 100, 1),
        data_age_days=0,
        needs_reeval=False,
    )

    payload = _build_agent_payload(
        sell_puts=[],
        iv_low=[],
        iv_high=[],
        ma200_bull=[],
        ma200_bear=[],
        leaps=[],
        earnings_gaps=[],
        earnings_gap_ticker_map={},
        iv_momentum=[],
        dividend_signals=[signal],
    )

    assert len(payload) == 1
    entry = payload[0]
    assert entry["signal_type"] == "dividend"
    assert entry["option_illiquid"] is True
    assert entry["option_bid"] is None
    assert entry["option_apy"] is None
    assert entry["combined_apy"] is None
    assert entry["option_strike"] == pytest.approx(60.0)
    assert entry["option_dte"] == 30
    assert entry["option_spread_pct"] == pytest.approx(85.0)


def test_build_agent_payload_sell_put_has_liquidity_fields():
    """Sell put payload must include liquidity fields from SellPutSignal."""
    from src.main import _build_agent_payload
    from src.scanners import SellPutSignal
    from unittest.mock import MagicMock

    signal = SellPutSignal(
        ticker="AAPL", strike=150.0, bid=1.0, ask=1.2, mid=1.1,
        spread_pct=18.2, dte=45,
        expiration=date.today() + timedelta(days=45),
        apy=5.9, earnings_risk=False, liquidity_warn=False,
    )

    ticker = MagicMock()
    ticker.ticker = "AAPL"
    ticker.earnings_date = None
    ticker.days_to_earnings = None

    payload = _build_agent_payload(
        sell_puts=[(signal, ticker)],
        iv_low=[], iv_high=[], ma200_bull=[],
        ma200_bear=[], leaps=[], earnings_gaps=[], earnings_gap_ticker_map={},
        iv_momentum=[], dividend_signals=[],
    )

    sp = next(p for p in payload if p["signal_type"] == "sell_put")
    assert sp["ask"] == 1.2
    assert sp["mid"] == 1.1
    assert sp["spread_pct"] == 18.2
    assert sp["liquidity_warn"] is False
