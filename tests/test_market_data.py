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


class TestGetIVMomentum:
    @patch("src.market_data.yf.Ticker")
    def test_iv_momentum_calculated(self, MockTicker):
        """成功计算 IV 动量"""
        mock_t = MockTicker.return_value
        mock_t.info = {"regularMarketPrice": 150.0}
        mock_t.options = ["2026-03-20"]

        # Mock 期权链
        from unittest.mock import MagicMock
        mock_chain = MagicMock()
        mock_calls = pd.DataFrame({
            "strike": [145, 150, 155],
            "impliedVolatility": [0.30, 0.28, 0.29],
        })
        mock_chain.calls = mock_calls
        mock_t.option_chain.return_value = mock_chain

        # Mock IVStore
        mock_store = MagicMock()
        mock_store.get_iv_n_days_ago.return_value = 0.20  # 5天前 IV = 0.20

        provider = MarketDataProvider()
        provider.iv_store = mock_store

        result = provider.get_iv_momentum("AAPL")

        # (0.28 - 0.20) / 0.20 * 100 = 40%
        assert result == pytest.approx(40.0, abs=1.0)

    def test_cn_market_returns_none(self):
        """CN 市场返回 None"""
        provider = MarketDataProvider()
        provider.iv_store = MagicMock()
        result = provider.get_iv_momentum("600900.SS")
        assert result is None

    def test_no_iv_store_returns_none(self):
        """无 IVStore 返回 None"""
        provider = MarketDataProvider()
        provider.iv_store = None
        result = provider.get_iv_momentum("AAPL")
        assert result is None

    @patch("src.market_data.yf.Ticker")
    def test_no_historical_iv_returns_none(self, MockTicker):
        """5天前无 IV 数据返回 None"""
        mock_t = MockTicker.return_value
        mock_t.info = {"regularMarketPrice": 150.0}
        mock_t.options = ["2026-03-20"]

        mock_chain = MagicMock()
        mock_calls = pd.DataFrame({
            "strike": [150],
            "impliedVolatility": [0.28],
        })
        mock_chain.calls = mock_calls
        mock_t.option_chain.return_value = mock_chain

        mock_store = MagicMock()
        mock_store.get_iv_n_days_ago.return_value = None  # 无历史数据

        provider = MarketDataProvider()
        provider.iv_store = mock_store

        result = provider.get_iv_momentum("AAPL")
        assert result is None


class TestGetDividendHistory:
    @patch("src.market_data.yf.Ticker")
    def test_get_dividend_history(self, MockTicker):
        """获取股息历史数据"""
        mock_t = MockTicker.return_value
        # Mock 6 dividends from 2020-2025 (current date: 2026-03-04)
        # Using years=6 to ensure cutoff includes 2020 data
        # Cutoff: 2026-03-04 - 2190 days = 2020-03-04
        # First dividend must be >= 2020-03-04 to pass filter
        mock_dividends = pd.Series({
            pd.Timestamp("2020-05-07"): 0.50,
            pd.Timestamp("2021-02-05"): 0.53,
            pd.Timestamp("2022-02-04"): 0.56,
            pd.Timestamp("2023-02-10"): 0.59,
            pd.Timestamp("2024-02-09"): 0.61,
            pd.Timestamp("2025-02-07"): 0.63,
        })
        mock_t.dividends = mock_dividends

        provider = MarketDataProvider()
        result = provider.get_dividend_history("AAPL", years=6)

        assert result is not None
        # Verify exact count as per spec
        assert len(result) == 6
        # Verify first entry exact year as per spec
        assert result[0]["date"].year == 2020
        # Verify first entry exact amount as per spec
        assert result[0]["amount"] == 0.50
        # Verify last entry exact amount as per spec
        assert result[-1]["amount"] == 0.63


class TestGetFundamentals:
    @patch("src.market_data.yf.Ticker")
    def test_get_fundamentals(self, MockTicker):
        """获取基本面数据"""
        mock_t = MockTicker.return_value
        mock_t.info = {
            "payoutRatio": 0.25,
            "returnOnEquity": 0.28,
            "debtToEquity": 1.5,
            "industry": "Technology",
            "sector": "Information Technology",
            "freeCashflow": 90000000000,
            "trailingPE": 25.0,  # Extra field should be ignored
        }

        provider = MarketDataProvider()
        result = provider.get_fundamentals("AAPL")

        assert result is not None
        assert result["payout_ratio"] == pytest.approx(25.0)  # Converted to percentage
        assert result["roe"] == pytest.approx(28.0)  # Converted to percentage
        assert result["debt_to_equity"] == 1.5
        assert result["industry"] == "Technology"
        assert result["sector"] == "Information Technology"
        assert result["free_cash_flow"] == 90000000000
        assert "trailingPE" not in result  # Should only include specified fields

    @patch("src.market_data.yf.Ticker")
    def test_get_fundamentals_returns_dividend_yield(self, MockTicker):
        """get_fundamentals() must return dividend_yield as percentage."""
        mock_t = MockTicker.return_value
        mock_t.info = {
            "payoutRatio": 0.65,
            "returnOnEquity": 0.15,
            "debtToEquity": 0.8,
            "industry": "Utilities",
            "sector": "Utilities",
            "freeCashflow": 5_000_000,
            "dividendYield": 0.035,  # 3.5% as decimal
            "longName": "Test Corp",
        }
        provider = MarketDataProvider()
        result = provider.get_fundamentals("TEST")
        assert result["dividend_yield"] == pytest.approx(3.5)
        assert result["company_name"] == "Test Corp"

    @patch("src.market_data.yf.Ticker")
    def test_get_fundamentals_dividend_yield_none_when_missing(self, MockTicker):
        """get_fundamentals() returns None for dividend_yield if not in info."""
        mock_t = MockTicker.return_value
        mock_t.info = {"payoutRatio": 0.5}
        provider = MarketDataProvider()
        result = provider.get_fundamentals("TEST")
        assert result["dividend_yield"] is None
        assert result["company_name"] == "TEST"  # falls back to ticker

    @patch("src.market_data.yf.Ticker")
    def test_get_fundamentals_dividend_yield_already_percentage(self, MockTicker):
        """yfinance returns dividendYield > 1 for HK/CN stocks (already percentage).
        get_fundamentals() must NOT multiply by 100 again."""
        mock_t = MockTicker.return_value
        mock_t.info = {
            "dividendYield": 5.43,   # yfinance returns 5.43 meaning 5.43%
            "longName": "HSBC Holdings",
        }
        provider = MarketDataProvider()
        result = provider.get_fundamentals("0005.HK")
        assert result["dividend_yield"] == pytest.approx(5.43)  # must stay 5.43%, not 543%


class TestIBKRPriceData:
    def test_get_price_data_uses_ibkr_when_connected(self):
        """When IBKR is connected, get_price_data must call _ibkr_price_data."""
        provider = MarketDataProvider(ibkr_config=None)
        provider.ibkr = MagicMock()  # Simulate connected IBKR

        dates = pd.date_range("2025-01-01", periods=3, freq="B")
        ibkr_df = pd.DataFrame({
            "Open": [100, 101, 102], "High": [105, 106, 107],
            "Low": [95, 96, 97], "Close": [102, 103, 104], "Volume": [1000, 1100, 1200],
        }, index=dates)

        with patch.object(provider, '_ibkr_price_data', return_value=ibkr_df) as mock_ibkr:
            result = provider.get_price_data("AAPL", period="1y")
            mock_ibkr.assert_called_once_with("AAPL", "1y")
            assert len(result) == 3

    def test_get_price_data_falls_back_to_yfinance_when_ibkr_fails(self):
        """If _ibkr_price_data raises, get_price_data must call _yf_price_data."""
        provider = MarketDataProvider(ibkr_config=None)
        provider.ibkr = MagicMock()  # Simulate connected IBKR

        dates = pd.date_range("2025-01-01", periods=2, freq="B")
        yf_df = pd.DataFrame({
            "Open": [100, 101], "High": [105, 106],
            "Low": [95, 96], "Close": [102, 103], "Volume": [1000, 1100],
        }, index=dates)

        with patch.object(provider, '_ibkr_price_data', side_effect=Exception("IBKR error")):
            with patch.object(provider, '_yf_price_data', return_value=yf_df) as mock_yf:
                result = provider.get_price_data("AAPL", period="1y")
                mock_yf.assert_called_once_with("AAPL", "1y")
                assert len(result) == 2

    def test_make_contract_us_ticker(self):
        """US tickers map to SMART/USD Stock contracts."""
        pytest.importorskip("ib_insync")
        provider = MarketDataProvider(ibkr_config=None)
        contract = provider._make_contract("AAPL")
        assert contract.symbol == "AAPL"
        assert contract.exchange == "SMART"
        assert contract.currency == "USD"

    def test_make_contract_hk_ticker(self):
        """HK tickers strip .HK and use SEHK/HKD."""
        pytest.importorskip("ib_insync")
        provider = MarketDataProvider(ibkr_config=None)
        contract = provider._make_contract("0700.HK")
        assert contract.symbol == "0700"
        assert contract.exchange == "SEHK"
        assert contract.currency == "HKD"

    def test_make_contract_cn_ss_ticker(self):
        """CN .SS tickers strip suffix and use SSE/CNH."""
        pytest.importorskip("ib_insync")
        provider = MarketDataProvider(ibkr_config=None)
        contract = provider._make_contract("600900.SS")
        assert contract.symbol == "600900"
        assert contract.exchange == "SSE"
        assert contract.currency == "CNH"

    def test_make_contract_cn_sz_ticker(self):
        """CN .SZ tickers strip suffix and use SZSE/CNH."""
        pytest.importorskip("ib_insync")
        provider = MarketDataProvider(ibkr_config=None)
        contract = provider._make_contract("000001.SZ")
        assert contract.symbol == "000001"
        assert contract.exchange == "SZSE"
        assert contract.currency == "CNH"

    def test_get_weekly_price_data_uses_ibkr_when_connected(self):
        """When IBKR connected, get_weekly_price_data calls _ibkr_weekly_price_data."""
        provider = MarketDataProvider(ibkr_config=None)
        provider.ibkr = MagicMock()

        dates = pd.date_range("2025-01-01", periods=3, freq="W")
        ibkr_df = pd.DataFrame({
            "Open": [100, 101, 102], "High": [105, 106, 107],
            "Low": [95, 96, 97], "Close": [102, 103, 104], "Volume": [1000, 1100, 1200],
        }, index=dates)

        with patch.object(provider, '_ibkr_weekly_price_data', return_value=ibkr_df) as mock_ibkr:
            result = provider.get_weekly_price_data("AAPL", period="1y")
            mock_ibkr.assert_called_once_with("AAPL", "1y")
            assert len(result) == 3

    def test_get_weekly_price_data_falls_back_to_yfinance(self):
        """If IBKR weekly fails, falls back to yfinance."""
        provider = MarketDataProvider(ibkr_config=None)
        provider.ibkr = MagicMock()

        dates = pd.date_range("2025-01-01", periods=2, freq="W")
        yf_df = pd.DataFrame({
            "Open": [100, 101], "High": [105, 106],
            "Low": [95, 96], "Close": [102, 103], "Volume": [1000, 1100],
        }, index=dates)

        with patch.object(provider, '_ibkr_weekly_price_data', side_effect=Exception("fail")):
            with patch.object(provider, '_yf_weekly_price_data', return_value=yf_df) as mock_yf:
                result = provider.get_weekly_price_data("AAPL")
                mock_yf.assert_called_once()
                assert len(result) == 2


class TestIBKROptionsChain:
    def test_get_options_chain_uses_ibkr_when_connected(self):
        """When IBKR connected, get_options_chain calls _ibkr_options_chain."""
        provider = MarketDataProvider(ibkr_config=None)
        provider.ibkr = MagicMock()

        ibkr_df = pd.DataFrame({
            "strike": [45.0, 50.0],
            "bid": [1.5, 1.0],
            "impliedVolatility": [0.25, 0.28],
            "dte": [55, 55],
            "expiration": [date(2026, 5, 15), date(2026, 5, 15)],
        })

        with patch.object(provider, '_ibkr_options_chain', return_value=ibkr_df) as mock_ibkr:
            result = provider.get_options_chain("AAPL", dte_min=45, dte_max=60)
            mock_ibkr.assert_called_once_with("AAPL", 45, 60)
            assert len(result) == 2

    def test_get_options_chain_falls_back_to_yfinance(self):
        """If IBKR options fails, falls back to yfinance."""
        provider = MarketDataProvider(ibkr_config=None)
        provider.ibkr = MagicMock()

        yf_df = pd.DataFrame({
            "strike": [50.0], "bid": [1.0],
            "impliedVolatility": [0.28], "dte": [55],
            "expiration": [date(2026, 5, 15)],
        })

        with patch.object(provider, '_ibkr_options_chain', side_effect=Exception("IBKR fail")):
            with patch.object(provider, '_yf_options_chain', return_value=yf_df) as mock_yf:
                result = provider.get_options_chain("AAPL")
                mock_yf.assert_called_once()
                assert len(result) == 1


class TestIBKREarningsDate:
    def test_get_earnings_date_uses_ibkr_when_connected(self):
        """When IBKR connected, get_earnings_date calls _ibkr_earnings_date."""
        provider = MarketDataProvider(ibkr_config=None)
        provider.ibkr = MagicMock()
        expected_date = date(2026, 4, 25)

        with patch.object(provider, '_ibkr_earnings_date', return_value=expected_date) as mock_ibkr:
            result = provider.get_earnings_date("AAPL")
            mock_ibkr.assert_called_once_with("AAPL")
            assert result == expected_date

    def test_get_earnings_date_falls_back_to_yfinance(self):
        """If IBKR earnings date fails, falls back to yfinance."""
        provider = MarketDataProvider(ibkr_config=None)
        provider.ibkr = MagicMock()
        expected_date = date(2026, 4, 25)

        with patch.object(provider, '_ibkr_earnings_date', side_effect=Exception("fail")):
            with patch("src.market_data.yf.Ticker") as MockTicker:
                MockTicker.return_value.calendar = {"Earnings Date": [datetime(2026, 4, 25)]}
                result = provider.get_earnings_date("AAPL")
                assert result == expected_date

    def test_ibkr_earnings_date_parses_xml(self):
        """_ibkr_earnings_date parses CalendarReport XML and returns nearest future date."""
        provider = MarketDataProvider(ibkr_config=None)
        provider.ibkr = MagicMock()

        xml_data = """<?xml version="1.0"?>
<CalendarReport>
  <Announcements>
    <Announcement type="Earnings">
      <Date>2026-04-25</Date>
    </Announcement>
    <Announcement type="Earnings">
      <Date>2025-01-20</Date>
    </Announcement>
  </Announcements>
</CalendarReport>"""
        provider.ibkr.reqFundamentalData.return_value = xml_data
        provider.ibkr.qualifyContracts.return_value = [MagicMock()]

        result = provider._ibkr_earnings_date("AAPL")
        assert result == date(2026, 4, 25)
