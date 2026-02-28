# tests/test_scanners.py
import pytest
import pandas as pd
from datetime import date
from src.data_engine import TickerData
from src.scanners import scan_iv_extremes, scan_ma200_crossover, scan_leaps_setup
from src.scanners import scan_sell_put, SellPutSignal
from src.scanners import scan_iv_momentum
from src.scanners import scan_earnings_gap
from src.data_engine import EarningsGap
from unittest.mock import MagicMock


def make_ticker(**kwargs) -> TickerData:
    """Helper to create TickerData with sensible defaults."""
    defaults = dict(
        ticker="TEST", name="Test", market="US",
        last_price=100.0, ma200=95.0, ma50w=98.0,
        rsi14=40.0, iv_rank=25.0, iv_momentum=None,
        prev_close=99.0,
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


class TestIVMomentumScanner:
    def test_high_momentum_detected(self):
        """高动量标的被筛选"""
        data = [
            make_ticker(ticker="SPIKE", iv_momentum=45.0),
            make_ticker(ticker="CALM", iv_momentum=10.0),
        ]
        result = scan_iv_momentum(data, threshold=30.0)

        assert len(result) == 1
        assert result[0].ticker == "SPIKE"

    def test_boundary_excluded(self):
        """边界值 (30.0) 不触发"""
        data = [make_ticker(ticker="EXACT", iv_momentum=30.0)]
        result = scan_iv_momentum(data, threshold=30.0)

        assert len(result) == 0

    def test_none_momentum_skipped(self):
        """iv_momentum=None 的标的被跳过"""
        data = [make_ticker(ticker="NODATA", iv_momentum=None)]
        result = scan_iv_momentum(data, threshold=30.0)

        assert len(result) == 0

    def test_sorted_descending(self):
        """结果按 iv_momentum 降序排列"""
        data = [
            make_ticker(ticker="A", iv_momentum=35.0),
            make_ticker(ticker="B", iv_momentum=50.0),
            make_ticker(ticker="C", iv_momentum=40.0),
        ]
        result = scan_iv_momentum(data, threshold=30.0)

        assert [t.ticker for t in result] == ["B", "C", "A"]

    def test_custom_threshold(self):
        """自定义阈值"""
        data = [make_ticker(ticker="MED", iv_momentum=25.0)]
        assert len(scan_iv_momentum(data, threshold=20.0)) == 1
        assert len(scan_iv_momentum(data, threshold=30.0)) == 0


class TestEarningsGapScanner:
    def test_ticker_within_threshold_analyzed(self):
        """临近财报的标的被分析"""
        data = [
            make_ticker(ticker="AAPL", days_to_earnings=2, earnings_date=date(2026, 2, 27)),
            make_ticker(ticker="MSFT", days_to_earnings=10, earnings_date=date(2026, 3, 7)),
        ]

        mock_provider = MagicMock()
        mock_provider.should_skip_options.return_value = False

        # Mock 历史财报日期
        mock_provider.get_historical_earnings_dates.return_value = [
            date(2026, 1, 20), date(2025, 10, 15), date(2025, 7, 10),
        ]

        # Mock 价格数据
        dates_idx = pd.date_range("2025-06-01", "2026-02-25", freq="B")
        price_df = pd.DataFrame({
            "Open": [100.0] * len(dates_idx),
            "Close": [100.0] * len(dates_idx),
        }, index=dates_idx)

        # 设置 Gap
        for ed, gap_open in [
            (pd.Timestamp("2026-01-20"), 106.0),
            (pd.Timestamp("2025-10-15"), 95.0),
            (pd.Timestamp("2025-07-10"), 103.0)
        ]:
            if ed in price_df.index:
                price_df.loc[ed, "Open"] = gap_open

        mock_provider.get_price_data.return_value = price_df

        result = scan_earnings_gap(data, mock_provider, days_threshold=3)

        assert len(result) == 1
        assert result[0].ticker == "AAPL"
        assert result[0].sample_count >= 2

    def test_ticker_outside_threshold_skipped(self):
        """超过阈值的标的被跳过"""
        data = [make_ticker(ticker="MSFT", days_to_earnings=10)]
        mock_provider = MagicMock()

        result = scan_earnings_gap(data, mock_provider, days_threshold=3)
        assert len(result) == 0

    def test_ticker_with_no_earnings_date_skipped(self):
        """无财报日期的标的被跳过"""
        data = [make_ticker(ticker="NOEARN", days_to_earnings=None, earnings_date=None)]
        mock_provider = MagicMock()

        result = scan_earnings_gap(data, mock_provider, days_threshold=3)
        assert len(result) == 0

    def test_cn_market_skipped(self):
        """CN 市场被跳过"""
        data = [make_ticker(ticker="600900.SS", days_to_earnings=2)]
        mock_provider = MagicMock()
        mock_provider.should_skip_options.return_value = True

        result = scan_earnings_gap(data, mock_provider, days_threshold=3)
        assert len(result) == 0
