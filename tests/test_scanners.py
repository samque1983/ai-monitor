# tests/test_scanners.py
import pytest
import pandas as pd
from datetime import date
from src.data_engine import TickerData
from src.scanners import scan_iv_extremes, scan_ma200_crossover, scan_leaps_setup
from src.scanners import scan_sell_put, SellPutSignal


def make_ticker(**kwargs) -> TickerData:
    """Helper to create TickerData with sensible defaults."""
    defaults = dict(
        ticker="TEST", name="Test", market="US",
        last_price=100.0, ma200=95.0, ma50w=98.0,
        rsi14=40.0, iv_rank=25.0, prev_close=99.0,
        earnings_date=date(2026, 4, 25), days_to_earnings=64,
    )
    defaults.update(kwargs)
    return TickerData(**defaults)


class TestIVExtremes:
    def test_low_iv_detected(self):
        data = [make_ticker(ticker="LOW", iv_rank=15.0)]
        low, high = scan_iv_extremes(data)
        assert len(low) == 1
        assert low[0].ticker == "LOW"
        assert len(high) == 0

    def test_high_iv_detected(self):
        data = [make_ticker(ticker="HIGH", iv_rank=85.0)]
        low, high = scan_iv_extremes(data)
        assert len(low) == 0
        assert len(high) == 1

    def test_normal_iv_not_included(self):
        data = [make_ticker(ticker="NORMAL", iv_rank=50.0)]
        low, high = scan_iv_extremes(data)
        assert len(low) == 0
        assert len(high) == 0

    def test_none_iv_skipped(self):
        data = [make_ticker(ticker="NOIV", iv_rank=None)]
        low, high = scan_iv_extremes(data)
        assert len(low) == 0
        assert len(high) == 0

    def test_boundary_values(self):
        data = [
            make_ticker(ticker="EXACT20", iv_rank=20.0),  # NOT < 20
            make_ticker(ticker="EXACT80", iv_rank=80.0),  # NOT > 80
        ]
        low, high = scan_iv_extremes(data)
        assert len(low) == 0
        assert len(high) == 0


class TestMA200Crossover:
    def test_bullish_cross(self):
        data = [make_ticker(ticker="BULL", last_price=101.0, ma200=100.0, prev_close=99.0)]
        bullish, bearish = scan_ma200_crossover(data)
        assert len(bullish) == 1
        assert bullish[0].ticker == "BULL"

    def test_bearish_cross(self):
        data = [make_ticker(ticker="BEAR", last_price=99.0, ma200=100.0, prev_close=101.0)]
        bullish, bearish = scan_ma200_crossover(data)
        assert len(bearish) == 1

    def test_just_above_within_1pct(self):
        # Price just crossed above MA200 (within 1%) — prev_close at or below MA200
        data = [make_ticker(ticker="NEAR", last_price=100.5, ma200=100.0, prev_close=100.0)]
        bullish, bearish = scan_ma200_crossover(data)
        assert len(bullish) == 1

    def test_no_cross(self):
        # Both above MA200, not near it
        data = [make_ticker(ticker="ABOVE", last_price=110.0, ma200=100.0, prev_close=109.0)]
        bullish, bearish = scan_ma200_crossover(data)
        assert len(bullish) == 0
        assert len(bearish) == 0

    def test_none_ma200_skipped(self):
        data = [make_ticker(ticker="NOMA", ma200=None)]
        bullish, bearish = scan_ma200_crossover(data)
        assert len(bullish) == 0
        assert len(bearish) == 0


class TestLEAPSSetup:
    def test_all_conditions_met(self):
        data = [make_ticker(
            ticker="LEAPS",
            last_price=100.0,
            ma200=95.0,
            ma50w=98.0,
            rsi14=40.0,
            iv_rank=25.0,
        )]
        result = scan_leaps_setup(data)
        assert len(result) == 1

    def test_price_below_ma200_fails(self):
        data = [make_ticker(last_price=90.0, ma200=95.0)]
        assert len(scan_leaps_setup(data)) == 0

    def test_too_far_from_ma50w_fails(self):
        data = [make_ticker(last_price=100.0, ma50w=90.0)]  # 11% away
        assert len(scan_leaps_setup(data)) == 0

    def test_rsi_too_high_fails(self):
        data = [make_ticker(rsi14=50.0)]
        assert len(scan_leaps_setup(data)) == 0

    def test_iv_rank_too_high_fails(self):
        data = [make_ticker(iv_rank=35.0)]
        assert len(scan_leaps_setup(data)) == 0

    def test_none_iv_rank_skipped(self):
        data = [make_ticker(iv_rank=None)]
        assert len(scan_leaps_setup(data)) == 0

    def test_none_ma200_skipped(self):
        data = [make_ticker(ma200=None)]
        assert len(scan_leaps_setup(data)) == 0

    def test_none_ma50w_skipped(self):
        data = [make_ticker(ma50w=None)]
        assert len(scan_leaps_setup(data)) == 0

    def test_none_rsi_skipped(self):
        data = [make_ticker(rsi14=None)]
        assert len(scan_leaps_setup(data)) == 0


class TestSellPutScanner:
    def test_basic_signal(self):
        ticker_data = make_ticker(
            ticker="AAPL",
            earnings_date=date(2026, 6, 1),
            days_to_earnings=101,
        )
        options_df = pd.DataFrame({
            "strike": [145.0, 150.0, 155.0],
            "bid": [1.5, 2.0, 3.0],
            "dte": [50, 50, 50],
            "expiration": [date(2026, 4, 11)] * 3,
            "impliedVolatility": [0.3, 0.3, 0.3],
        })
        result = scan_sell_put(
            ticker_data=ticker_data,
            target_strike=150.0,
            options_df=options_df,
        )
        assert result is not None
        assert result.strike == 150.0
        assert result.bid == 2.0
        assert result.apy == pytest.approx((2.0 / 150.0) * (365 / 50) * 100, rel=1e-2)
        assert result.earnings_risk is False

    def test_earnings_within_dte_flags_risk(self):
        ticker_data = make_ticker(
            ticker="AAPL",
            earnings_date=date(2026, 3, 15),
            days_to_earnings=23,
        )
        options_df = pd.DataFrame({
            "strike": [150.0],
            "bid": [3.0],
            "dte": [50],
            "expiration": [date(2026, 4, 11)],
            "impliedVolatility": [0.3],
        })
        result = scan_sell_put(ticker_data, 150.0, options_df)
        assert result is not None
        assert result.earnings_risk is True

    def test_apy_below_threshold_returns_none(self):
        ticker_data = make_ticker(ticker="AAPL")
        options_df = pd.DataFrame({
            "strike": [150.0],
            "bid": [0.10],
            "dte": [50],
            "expiration": [date(2026, 4, 11)],
            "impliedVolatility": [0.1],
        })
        result = scan_sell_put(ticker_data, 150.0, options_df)
        assert result is None

    def test_closest_strike_below_target(self):
        ticker_data = make_ticker(ticker="AAPL")
        options_df = pd.DataFrame({
            "strike": [145.0, 148.0, 152.0, 155.0],
            "bid": [3.0, 2.5, 2.0, 1.5],
            "dte": [50, 50, 50, 50],
            "expiration": [date(2026, 4, 11)] * 4,
            "impliedVolatility": [0.3] * 4,
        })
        result = scan_sell_put(ticker_data, 150.0, options_df)
        assert result is not None
        assert result.strike == 148.0

    def test_empty_options_returns_none(self):
        ticker_data = make_ticker(ticker="AAPL")
        result = scan_sell_put(ticker_data, 150.0, pd.DataFrame())
        assert result is None
