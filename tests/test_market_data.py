# tests/test_market_data.py
import os
import tempfile
import pandas as pd
import numpy as np
import pytest
from datetime import date, datetime
from typing import Optional
from unittest.mock import patch, MagicMock, PropertyMock
from src.market_data import MarketDataProvider


@pytest.fixture
def provider_no_ibkr():
    """Provider with IBKR disabled (yfinance only)."""
    return MarketDataProvider(ibkr_config=None)


class TestGetPriceData:
    @patch("src.market_data.yf.download")
    def test_returns_ohlcv_dataframe(self, mock_download, provider_no_ibkr):
        dates = pd.date_range("2025-01-01", periods=5, freq="B")
        mock_df = pd.DataFrame({
            "Open": [100, 101, 102, 103, 104],
            "High": [105, 106, 107, 108, 109],
            "Low": [95, 96, 97, 98, 99],
            "Close": [102, 103, 104, 105, 106],
            "Volume": [1000, 1100, 1200, 1300, 1400],
        }, index=dates)
        mock_download.return_value = mock_df

        result = provider_no_ibkr.get_price_data("AAPL", period="1y")
        assert "Close" in result.columns
        assert len(result) == 5

    @patch("src.market_data.yf.download")
    def test_empty_data_returns_empty_df(self, mock_download, provider_no_ibkr):
        mock_download.return_value = pd.DataFrame()
        result = provider_no_ibkr.get_price_data("INVALID", period="1y")
        assert result.empty


class TestGetEarningsDate:
    @patch("src.market_data.yf.Ticker")
    def test_returns_next_earnings_date(self, mock_ticker_cls, provider_no_ibkr):
        mock_ticker = MagicMock()
        mock_ticker.calendar = {"Earnings Date": [datetime(2026, 4, 25)]}
        mock_ticker_cls.return_value = mock_ticker

        result = provider_no_ibkr.get_earnings_date("AAPL")
        assert result == date(2026, 4, 25)

    @patch("src.market_data.yf.Ticker")
    def test_no_earnings_returns_none(self, mock_ticker_cls, provider_no_ibkr):
        mock_ticker = MagicMock()
        mock_ticker.calendar = {}
        mock_ticker_cls.return_value = mock_ticker

        result = provider_no_ibkr.get_earnings_date("AAPL")
        assert result is None


class TestClassifyAndSkip:
    def test_should_skip_options_cn_ticker(self, provider_no_ibkr):
        assert provider_no_ibkr.should_skip_options("600900.SS") is True

    def test_should_not_skip_options_us_ticker(self, provider_no_ibkr):
        assert provider_no_ibkr.should_skip_options("AAPL") is False

    def test_should_not_skip_options_hk_ticker(self, provider_no_ibkr):
        assert provider_no_ibkr.should_skip_options("0700.HK") is False


class TestLoadEarningsFromCSV:
    def test_load_from_csv_success(self):
        """成功从 CSV 加载财报日期"""
        # 创建临时 CSV
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("ticker,date,time_type\n")
            f.write("AAPL,2026-01-30,AMC\n")
            f.write("AAPL,2025-10-31,AMC\n")
            f.write("MSFT,2026-01-28,BMO\n")
            csv_path = f.name

        try:
            config = {"data": {"earnings_csv_path": csv_path}}
            provider = MarketDataProvider(ibkr_config=None, iv_db_path=None)
            provider.config = config

            result = provider._load_earnings_from_csv("AAPL", count=2)

            assert len(result) == 2
            assert all(isinstance(d, date) for d in result)
            assert result[0] == date(2026, 1, 30)
            assert result[1] == date(2025, 10, 31)
        finally:
            os.unlink(csv_path)

    def test_csv_not_exists_returns_empty(self):
        """CSV 不存在时返回空列表"""
        config = {"data": {"earnings_csv_path": "/nonexistent/path.csv"}}
        provider = MarketDataProvider(ibkr_config=None, iv_db_path=None)
        provider.config = config

        result = provider._load_earnings_from_csv("AAPL", count=5)
        assert result == []

    def test_ticker_not_in_csv_returns_empty(self):
        """Ticker 不在 CSV 中返回空列表"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("ticker,date,time_type\n")
            f.write("AAPL,2026-01-30,AMC\n")
            csv_path = f.name

        try:
            config = {"data": {"earnings_csv_path": csv_path}}
            provider = MarketDataProvider(ibkr_config=None, iv_db_path=None)
            provider.config = config

            result = provider._load_earnings_from_csv("MSFT", count=5)
            assert result == []
        finally:
            os.unlink(csv_path)


class TestGetHistoricalEarningsDates:
    @patch("src.market_data.yf.Ticker")
    def test_yfinance_success(self, MockTicker):
        """yfinance 成功返回历史财报日期"""
        mock_t = MockTicker.return_value
        # Use past dates that will pass the filter
        mock_t.earnings_dates = pd.DataFrame(
            {"EPS Estimate": [1.0, 1.1, 1.2]},
            index=pd.to_datetime(["2025-04-25", "2025-01-20", "2024-10-15"]),
        )

        provider = MarketDataProvider()
        result = provider.get_historical_earnings_dates("AAPL", count=3)

        # Verify count
        assert len(result) == 3
        # Verify type
        assert all(isinstance(d, date) for d in result)
        # Verify descending order (most recent first)
        assert result == sorted(result, reverse=True)
        # Verify past dates only
        today = date.today()
        assert all(d < today for d in result)
        # Verify actual values
        assert result[0] == date(2025, 4, 25)  # Most recent
        assert result[1] == date(2025, 1, 20)
        assert result[2] == date(2024, 10, 15)

    @patch("src.market_data.yf.Ticker")
    def test_yfinance_fails_fallback_to_csv(self, MockTicker):
        """yfinance 失败时降级到 CSV"""
        mock_t = MockTicker.return_value
        mock_t.earnings_dates = None  # 模拟失败

        # 创建临时 CSV
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("ticker,date,time_type\n")
            f.write("AAPL,2026-01-30,AMC\n")
            csv_path = f.name

        try:
            provider = MarketDataProvider()
            provider.config = {"data": {"earnings_csv_path": csv_path}}

            result = provider.get_historical_earnings_dates("AAPL", count=5)

            assert len(result) == 1
            assert result[0] == date(2026, 1, 30)
        finally:
            os.unlink(csv_path)

    def test_cn_market_returns_empty(self):
        """CN 市场直接返回空列表"""
        provider = MarketDataProvider()
        result = provider.get_historical_earnings_dates("600900.SS", count=5)
        assert result == []
