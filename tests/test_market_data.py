# tests/test_market_data.py
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
