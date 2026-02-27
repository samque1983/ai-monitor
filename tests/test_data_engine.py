# tests/test_data_engine.py
import pandas as pd
import numpy as np
import pytest
from datetime import date
from typing import Optional
from unittest.mock import MagicMock, patch
from src.data_engine import TickerData, compute_sma, compute_rsi, build_ticker_data, validate_price_df


class TestComputeSMA:
    def test_sma_basic(self):
        prices = pd.Series([1, 2, 3, 4, 5])
        assert compute_sma(prices, 3) == pytest.approx(4.0)  # (3+4+5)/3

    def test_sma_insufficient_data(self):
        prices = pd.Series([1, 2])
        assert compute_sma(prices, 200) is None

    def test_sma_empty_series(self):
        assert compute_sma(pd.Series(dtype=float), 200) is None


class TestComputeRSI:
    def test_rsi_all_gains(self):
        prices = pd.Series(range(1, 20))  # steadily rising
        rsi = compute_rsi(prices, 14)
        assert rsi is not None
        assert rsi > 90  # should be near 100

    def test_rsi_all_losses(self):
        prices = pd.Series(range(20, 1, -1))  # steadily falling
        rsi = compute_rsi(prices, 14)
        assert rsi is not None
        assert rsi < 10  # should be near 0

    def test_rsi_insufficient_data(self):
        prices = pd.Series([1, 2, 3])
        assert compute_rsi(prices, 14) is None


class TestBuildTickerData:
    @patch("src.data_engine.MarketDataProvider")
    def test_builds_complete_ticker_data(self, MockProvider):
        provider = MockProvider()

        # Mock daily price data — 250 days
        dates = pd.date_range("2025-03-01", periods=250, freq="B")
        close_prices = np.linspace(100, 200, 250)
        daily_df = pd.DataFrame({"Close": close_prices}, index=dates)
        provider.get_price_data.return_value = daily_df

        # Mock weekly price data — 60 weeks
        weekly_dates = pd.date_range("2025-01-01", periods=60, freq="W")
        weekly_close = np.linspace(90, 190, 60)
        weekly_df = pd.DataFrame({"Close": weekly_close}, index=weekly_dates)
        provider.get_weekly_price_data.return_value = weekly_df

        # Mock earnings
        provider.get_earnings_date.return_value = date(2026, 4, 25)
        provider.get_iv_rank.return_value = 15.0

        result = build_ticker_data("AAPL", provider, reference_date=date(2026, 2, 20))

        assert result is not None
        assert result.ticker == "AAPL"
        assert result.market == "US"
        assert result.last_price == pytest.approx(close_prices[-1])
        assert result.ma200 is not None
        assert result.ma50w is not None
        assert result.rsi14 is not None
        assert result.iv_rank == 15.0
        assert result.earnings_date == date(2026, 4, 25)
        assert result.days_to_earnings == 64

    @patch("src.data_engine.MarketDataProvider")
    def test_empty_price_data_returns_none(self, MockProvider):
        provider = MockProvider()
        provider.get_price_data.return_value = pd.DataFrame()

        result = build_ticker_data("INVALID", provider)
        assert result is None


class TestValidatePriceDF:
    def test_valid_dataframe_passes(self):
        """正常数据通过验证"""
        dates = pd.date_range("2025-01-01", periods=100, freq="B")
        df = pd.DataFrame({
            "Open": np.linspace(100, 110, 100),
            "Close": np.linspace(100, 110, 100),
        }, index=dates)

        assert validate_price_df(df, "AAPL") is True

    def test_empty_dataframe_fails(self):
        """空 DataFrame 验证失败"""
        df = pd.DataFrame()
        assert validate_price_df(df, "AAPL") is False

    def test_missing_columns_fails(self):
        """缺少必需列 (Open)"""
        df = pd.DataFrame({"Close": [100, 101, 102]})
        assert validate_price_df(df, "AAPL") is False

    def test_negative_prices_fail(self):
        """负价格验证失败"""
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "Open": [100, -5, 102, 103, 104, 105, 106, 107, 108, 109],
            "Close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
        }, index=dates)

        assert validate_price_df(df, "AAPL") is False

    def test_zero_prices_fail(self):
        """零价格验证失败"""
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "Open": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
            "Close": [100, 0, 102, 103, 104, 105, 106, 107, 108, 109],
        }, index=dates)

        assert validate_price_df(df, "AAPL") is False

    def test_too_many_nans_fail(self):
        """NaN 占比 > 5% 验证失败"""
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "Open": [100, np.nan, np.nan, np.nan, np.nan, np.nan, 106, 107, 108, 109],
            "Close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
        }, index=dates)

        assert validate_price_df(df, "AAPL") is False

    def test_acceptable_nan_ratio_passes(self):
        """NaN 占比 < 5% 通过验证"""
        dates = pd.date_range("2025-01-01", periods=100, freq="B")
        opens = np.linspace(100, 110, 100)
        opens[0] = np.nan  # 1% NaN
        df = pd.DataFrame({
            "Open": opens,
            "Close": np.linspace(100, 110, 100),
        }, index=dates)

        assert validate_price_df(df, "AAPL") is True
