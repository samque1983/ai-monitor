# tests/test_data_engine.py
import pandas as pd
import numpy as np
import pytest
from datetime import date
from typing import Optional
from unittest.mock import MagicMock, patch
from src.data_engine import TickerData, compute_sma, compute_rsi, build_ticker_data


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
