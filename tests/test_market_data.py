# tests/test_market_data.py
import os
import tempfile
import pandas as pd
import numpy as np
import pytest
from datetime import date, datetime, timedelta
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

    def test_should_skip_options_hk_ticker(self, provider_no_ibkr):
        # HK has no options per GLOBAL_MASTER.md §2.1
        assert provider_no_ibkr.should_skip_options("0700.HK") is True


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

    def test_hk_dividend_history_uses_akshare_first(self):
        """HK: AKShare is tried before yfinance."""
        import datetime as _dt
        from unittest.mock import MagicMock, patch
        mock_akshare = MagicMock()
        mock_akshare.get_dividend_history.return_value = [
            {"date": _dt.date(2024, 5, 10), "amount": 0.45},
        ]
        provider = MarketDataProvider()
        provider._akshare = mock_akshare
        with patch("src.market_data.yf.Ticker") as MockTicker:
            result = provider.get_dividend_history("0267.HK", years=5)
        mock_akshare.get_dividend_history.assert_called_once_with("0267.HK", 5)
        MockTicker.assert_not_called()
        assert result == [{"date": _dt.date(2024, 5, 10), "amount": 0.45}]

    def test_hk_dividend_history_falls_back_to_yfinance(self):
        """HK: falls back to yfinance if AKShare returns None."""
        import datetime as _dt
        from unittest.mock import MagicMock, patch
        import pandas as pd
        mock_akshare = MagicMock()
        mock_akshare.get_dividend_history.return_value = None
        provider = MarketDataProvider()
        provider._akshare = mock_akshare
        mock_dividends = pd.Series({pd.Timestamp("2024-05-10"): 0.45})
        with patch("src.market_data.yf.Ticker") as MockTicker:
            MockTicker.return_value.dividends = mock_dividends
            result = provider.get_dividend_history("0267.HK", years=5)
        assert result is not None
        assert result[0]["amount"] == pytest.approx(0.45)

    def test_cn_dividend_history_uses_akshare_first(self):
        """CN: AKShare is tried before yfinance."""
        import datetime as _dt
        from unittest.mock import MagicMock, patch
        mock_akshare = MagicMock()
        mock_akshare.get_dividend_history.return_value = [
            {"date": _dt.date(2024, 6, 10), "amount": 2.5},
        ]
        provider = MarketDataProvider()
        provider._akshare = mock_akshare
        with patch("src.market_data.yf.Ticker") as MockTicker:
            result = provider.get_dividend_history("600519.SS", years=5)
        mock_akshare.get_dividend_history.assert_called_once_with("600519.SS", 5)
        MockTicker.assert_not_called()
        assert result[0]["amount"] == pytest.approx(2.5)

    def test_us_dividend_history_uses_polygon_first(self):
        """US: Polygon is tried before yfinance."""
        import datetime as _dt
        from unittest.mock import MagicMock, patch
        mock_polygon = MagicMock()
        mock_polygon.get_dividend_history.return_value = [
            {"date": _dt.date(2024, 2, 9), "amount": 0.61},
        ]
        provider = MarketDataProvider()
        provider._polygon = mock_polygon
        with patch("src.market_data.yf.Ticker") as MockTicker:
            result = provider.get_dividend_history("AAPL", years=5)
        mock_polygon.get_dividend_history.assert_called_once_with("AAPL", 5)
        MockTicker.assert_not_called()
        assert result == [{"date": _dt.date(2024, 2, 9), "amount": 0.61}]

    def test_us_dividend_history_falls_back_to_yfinance(self):
        """US: falls back to yfinance if Polygon returns None."""
        import pandas as pd
        from unittest.mock import MagicMock, patch
        mock_polygon = MagicMock()
        mock_polygon.get_dividend_history.return_value = None
        provider = MarketDataProvider()
        provider._polygon = mock_polygon
        mock_dividends = pd.Series({pd.Timestamp("2024-02-09"): 0.61})
        with patch("src.market_data.yf.Ticker") as MockTicker:
            MockTicker.return_value.dividends = mock_dividends
            result = provider.get_dividend_history("AAPL", years=5)
        assert result is not None
        assert result[0]["amount"] == pytest.approx(0.61)

    def test_us_dividend_history_skips_akshare(self):
        """US: AKShare is not called; Polygon/yfinance handles it."""
        import pandas as pd
        from unittest.mock import MagicMock, patch
        mock_akshare = MagicMock()
        provider = MarketDataProvider()
        provider._akshare = mock_akshare
        mock_dividends = pd.Series({pd.Timestamp("2024-02-09"): 0.61})
        with patch("src.market_data.yf.Ticker") as MockTicker:
            MockTicker.return_value.dividends = mock_dividends
            result = provider.get_dividend_history("AAPL", years=5)
        mock_akshare.get_dividend_history.assert_not_called()
        assert result is not None


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

    @patch("src.market_data.yf.Ticker")
    def test_yf_fundamentals_includes_forward_dividend_rate(self, MockTicker):
        """_yf_fundamentals should include forward_dividend_rate from yfinance info."""
        mock_t = MockTicker.return_value
        mock_t.info = {
            "payoutRatio": 0.6,
            "returnOnEquity": 0.15,
            "debtToEquity": 1.0,
            "industry": "Beverages",
            "sector": "Consumer Staples",
            "freeCashflow": 1_000_000_000,
            "trailingAnnualDividendYield": 0.032,
            "longName": "Coca-Cola",
            "forwardAnnualDividendRate": 1.94,
        }
        provider = MarketDataProvider()
        result = provider._yf_fundamentals("KO")
        assert result is not None
        assert result["forward_dividend_rate"] == pytest.approx(1.94)


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

    def test_ibkr_price_data_tries_realtime_then_delayed(self):
        """_ibkr_price_data tries ADJUSTED_LAST first; on empty result, retries with TRADES."""
        provider = MarketDataProvider(ibkr_config=None)
        provider.ibkr = MagicMock()

        dates = pd.date_range("2025-01-01", periods=3, freq="B")
        fake_df = pd.DataFrame({
            "date": [str(d.date()) for d in dates],
            "open": [100.0, 101.0, 102.0], "high": [105.0, 106.0, 107.0],
            "low": [95.0, 96.0, 97.0], "close": [102.0, 103.0, 104.0],
            "volume": [1000, 1100, 1200],
        })

        fake_bars = [MagicMock()]  # non-empty list = success

        # First call (ADJUSTED_LAST) → empty; second (TRADES) → data
        provider.ibkr.reqHistoricalData.side_effect = [[], fake_bars]

        with patch("ib_insync.util.df", return_value=fake_df):
            result = provider._ibkr_price_data("AAPL", "1y")

        assert provider.ibkr.reqHistoricalData.call_count == 2
        calls = provider.ibkr.reqHistoricalData.call_args_list
        assert calls[0][1]["whatToShow"] == "ADJUSTED_LAST"
        assert calls[1][1]["whatToShow"] == "TRADES"

    def test_ibkr_price_data_raises_when_both_fail(self):
        """_ibkr_price_data raises ValueError when both real-time and delayed return empty."""
        provider = MarketDataProvider(ibkr_config=None)
        provider.ibkr = MagicMock()
        provider.ibkr.reqHistoricalData.return_value = []

        with pytest.raises(ValueError, match="No IBKR data.*tried real-time and delayed"):
            provider._ibkr_price_data("AAPL", "1y")

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
        """HK tickers strip .HK, strip leading zeros, and use SEHK/HKD."""
        pytest.importorskip("ib_insync")
        provider = MarketDataProvider(ibkr_config=None)
        contract = provider._make_contract("0700.HK")
        assert contract.symbol == "700"   # IBKR uses no leading zeros
        assert contract.exchange == "SEHK"
        assert contract.currency == "HKD"

    def test_make_contract_hk_ticker_no_leading_zeros(self):
        """0941.HK → 941 (strip leading zero); 2388.HK → 2388 (no change)."""
        pytest.importorskip("ib_insync")
        provider = MarketDataProvider(ibkr_config=None)
        assert provider._make_contract("0941.HK").symbol == "941"
        assert provider._make_contract("0002.HK").symbol == "2"
        assert provider._make_contract("2388.HK").symbol == "2388"

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


def test_get_options_chain_includes_ask_column(provider_no_ibkr):
    """Options chain DataFrame must include ask column."""
    with patch("yfinance.Ticker") as mock_yf:
        mock_ticker = MagicMock()
        mock_yf.return_value = mock_ticker
        mock_ticker.options = ["2026-05-16"]
        chain = MagicMock()
        chain.puts = pd.DataFrame({
            "strike": [50.0, 55.0],
            "bid": [1.0, 1.5],
            "ask": [1.2, 1.8],
            "impliedVolatility": [0.3, 0.35],
        })
        mock_ticker.option_chain.return_value = chain
        result = provider_no_ibkr.get_options_chain("AAPL", dte_min=30, dte_max=90)
        assert "ask" in result.columns


def test_get_options_chain_ask_fallback_when_absent(provider_no_ibkr):
    """When ask column is missing from source, fallback to 0.0."""
    with patch("yfinance.Ticker") as mock_yf:
        mock_ticker = MagicMock()
        mock_yf.return_value = mock_ticker
        mock_ticker.options = ["2026-05-16"]
        chain = MagicMock()
        chain.puts = pd.DataFrame({
            "strike": [50.0],
            "bid": [1.0],
            "impliedVolatility": [0.3],
            # no "ask" column
        })
        mock_ticker.option_chain.return_value = chain
        result = provider_no_ibkr.get_options_chain("AAPL", dte_min=30, dte_max=90)
        assert "ask" in result.columns
        assert result["ask"].iloc[0] == 0.0


# ---------------------------------------------------------------------------
# Task 1: PolygonProvider — price data
# ---------------------------------------------------------------------------

def _polygon_aggs_response(n_bars=5):
    """Build a fake Polygon /v2/aggs response."""
    import time as _time
    today = date.today()
    results = []
    for i in range(n_bars):
        d = today - timedelta(days=n_bars - i)
        epoch_ms = int(_time.mktime(d.timetuple())) * 1000
        results.append({"t": epoch_ms, "o": 100.0, "h": 105.0, "l": 99.0, "c": 102.0, "v": 1000000})
    return {"results": results, "status": "OK"}


def test_polygon_provider_get_price_data_returns_dataframe():
    from src.providers.polygon import PolygonProvider
    provider = PolygonProvider(api_key="test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _polygon_aggs_response(5)

    with patch("src.providers.polygon.requests.get", return_value=mock_resp):
        with patch("src.providers.polygon.time.sleep"):  # skip rate-limit sleep in tests
            df = provider.get_price_data("AAPL", "5d")

    assert not df.empty
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 5


def test_polygon_provider_returns_empty_on_http_error():
    from src.providers.polygon import PolygonProvider
    provider = PolygonProvider(api_key="test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.raise_for_status.side_effect = Exception("403 Forbidden")
    mock_resp.json.return_value = {"status": "ERROR", "error": "Forbidden"}

    with patch("src.providers.polygon.requests.get", return_value=mock_resp):
        with patch("src.providers.polygon.time.sleep"):
            df = provider.get_price_data("AAPL", "1y")

    assert df.empty


def test_polygon_provider_returns_empty_on_exception():
    from src.providers.polygon import PolygonProvider
    provider = PolygonProvider(api_key="test-key")

    with patch("src.providers.polygon.requests.get", side_effect=Exception("network error")):
        with patch("src.providers.polygon.time.sleep"):
            df = provider.get_price_data("AAPL", "1y")

    assert df.empty


# ---------------------------------------------------------------------------
# Task 2: PolygonProvider — fundamentals
# ---------------------------------------------------------------------------

def _polygon_ticker_response():
    return {
        "results": {
            "name": "Apple Inc.",
            "sic_description": "Electronic Computers",
        }
    }


def _polygon_financials_response():
    return {
        "results": [
            {
                "financials": {
                    "income_statement": {
                        "net_income": {"value": 96995000000.0}
                    },
                    "balance_sheet": {
                        "equity": {"value": 62146000000.0}
                    },
                    "cash_flow_statement": {
                        "net_cash_flow_from_operating_activities": {"value": 110543000000.0},
                        "capital_expenditure": {"value": -10708000000.0},
                    },
                }
            }
        ]
    }


def test_polygon_provider_get_fundamentals_returns_dict():
    from src.providers.polygon import PolygonProvider
    provider = PolygonProvider(api_key="test-key")

    responses = {
        "/v3/reference/tickers/AAPL": _polygon_ticker_response(),
        "/vX/reference/financials": _polygon_financials_response(),
    }

    def fake_get(url, params=None, timeout=15):
        mock = MagicMock()
        mock.status_code = 200
        mock.raise_for_status = MagicMock()
        for path, resp in responses.items():
            if path in url:
                mock.json.return_value = resp
                return mock
        mock.json.return_value = {}
        return mock

    with patch("src.providers.polygon.requests.get", side_effect=fake_get):
        with patch("src.providers.polygon.time.sleep"):
            result = provider.get_fundamentals("AAPL")

    assert result is not None
    assert result["company_name"] == "Apple Inc."
    assert result["industry"] == "Electronic Computers"
    assert result["roe"] is not None
    assert result["roe"] > 0
    assert result["free_cash_flow"] is not None
    # Fields Polygon can't provide → None (yfinance fills them)
    assert result["payout_ratio"] is None
    assert result["dividend_yield"] is None


def test_polygon_provider_get_fundamentals_returns_none_on_failure():
    from src.providers.polygon import PolygonProvider
    provider = PolygonProvider(api_key="test-key")

    with patch("src.providers.polygon.requests.get", side_effect=Exception("network error")):
        with patch("src.providers.polygon.time.sleep"):
            result = provider.get_fundamentals("AAPL")

    assert result is None


def _polygon_dividends_response():
    """Fake Polygon /v3/reference/dividends response."""
    return {
        "results": [
            {"cash_amount": 0.25, "ex_dividend_date": "2024-11-08"},
            {"cash_amount": 0.25, "ex_dividend_date": "2024-08-09"},
            {"cash_amount": 0.24, "ex_dividend_date": "2024-05-10"},
        ],
        "status": "OK",
    }


def test_polygon_provider_get_dividend_history_returns_list():
    """Polygon /v3/reference/dividends → sorted [{date, amount}] list."""
    from src.providers.polygon import PolygonProvider
    from datetime import date as _date
    provider = PolygonProvider(api_key="test-key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _polygon_dividends_response()
    with patch("src.providers.polygon.requests.get", return_value=mock_resp):
        with patch("src.providers.polygon.time.sleep"):
            result = provider.get_dividend_history("AAPL", years=5)
    assert result is not None
    assert len(result) == 3
    # sorted ascending by date
    assert result[0]["date"] == _date(2024, 5, 10)
    assert result[0]["amount"] == pytest.approx(0.24)
    assert result[-1]["date"] == _date(2024, 11, 8)
    assert result[-1]["amount"] == pytest.approx(0.25)


def test_polygon_provider_get_dividend_history_empty_returns_none():
    """Empty results from Polygon returns None."""
    from src.providers.polygon import PolygonProvider
    provider = PolygonProvider(api_key="test-key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": [], "status": "OK"}
    with patch("src.providers.polygon.requests.get", return_value=mock_resp):
        with patch("src.providers.polygon.time.sleep"):
            result = provider.get_dividend_history("AAPL", years=5)
    assert result is None


def test_polygon_provider_get_dividend_history_error_returns_none():
    """Network error returns None."""
    from src.providers.polygon import PolygonProvider
    provider = PolygonProvider(api_key="test-key")
    with patch("src.providers.polygon.requests.get", side_effect=Exception("timeout")):
        with patch("src.providers.polygon.time.sleep"):
            result = provider.get_dividend_history("AAPL", years=5)
    assert result is None


# ---------------------------------------------------------------------------
# Task 3: TradierProvider — options chain
# ---------------------------------------------------------------------------

def _tradier_expirations_response():
    from datetime import date as _date, timedelta as _td
    future = _date.today() + _td(days=60)
    return {"expirations": {"date": [future.strftime("%Y-%m-%d")]}}


def _tradier_chain_response(expiration_str):
    return {
        "options": {
            "option": [
                {"option_type": "put", "strike": 150.0, "bid": 3.50, "symbol": "AAPL..."},
                {"option_type": "put", "strike": 155.0, "bid": 4.20, "symbol": "AAPL..."},
                {"option_type": "call", "strike": 160.0, "bid": 5.00, "symbol": "AAPL..."},
            ]
        }
    }


def test_tradier_provider_returns_put_options_dataframe():
    from src.market_data import TradierProvider
    from datetime import date as _date, timedelta as _td
    provider = TradierProvider(api_key="test-key")

    future = _date.today() + _td(days=60)
    future_str = future.strftime("%Y-%m-%d")

    expirations_resp = MagicMock()
    expirations_resp.status_code = 200
    expirations_resp.raise_for_status = MagicMock()
    expirations_resp.json.return_value = _tradier_expirations_response()

    chain_resp = MagicMock()
    chain_resp.status_code = 200
    chain_resp.raise_for_status = MagicMock()
    chain_resp.json.return_value = _tradier_chain_response(future_str)

    def fake_get(url, *args, **kwargs):
        if "expirations" in url:
            return expirations_resp
        return chain_resp

    with patch("src.market_data.requests.get", side_effect=fake_get):
        df = provider.get_options_chain("AAPL", dte_min=45, dte_max=90)

    assert not df.empty
    assert set(df.columns) >= {"strike", "bid", "dte", "expiration"}
    # Only puts, no calls
    assert len(df) == 2
    assert all(df["bid"] > 0)


def test_tradier_provider_returns_empty_when_no_expirations_in_range():
    from src.market_data import TradierProvider
    from datetime import date as _date, timedelta as _td
    provider = TradierProvider(api_key="test-key")

    # Expiration outside dte_min/dte_max
    near_future = _date.today() + _td(days=10)
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"expirations": {"date": [near_future.strftime("%Y-%m-%d")]}}

    with patch("src.market_data.requests.get", return_value=resp):
        df = provider.get_options_chain("AAPL", dte_min=45, dte_max=90)

    assert df.empty


def test_tradier_provider_returns_empty_on_exception():
    from src.market_data import TradierProvider
    provider = TradierProvider(api_key="test-key")

    with patch("src.market_data.requests.get", side_effect=Exception("network error")):
        df = provider.get_options_chain("AAPL", dte_min=45, dte_max=90)

    assert df.empty


# ---------------------------------------------------------------------------
# Enabled flag: per-source on/off control
# ---------------------------------------------------------------------------

def test_polygon_not_instantiated_when_disabled():
    """polygon.enabled=false → _polygon is None even if api_key is set."""
    from src.market_data import MarketDataProvider
    provider = MarketDataProvider(
        config={"data_sources": {"polygon": {"enabled": False, "api_key": "fake-key"}}}
    )
    assert provider._polygon is None


def test_tradier_not_instantiated_when_disabled():
    """tradier.enabled=false → _tradier is None even if api_key is set."""
    from src.market_data import MarketDataProvider
    provider = MarketDataProvider(
        config={"data_sources": {"tradier": {"enabled": False, "api_key": "fake-key"}}}
    )
    assert provider._tradier is None


def test_ibkr_tws_not_connected_when_disabled():
    """ibkr_tws.enabled=false → no connection attempt even with ibkr_config."""
    from src.market_data import MarketDataProvider
    with patch.object(MarketDataProvider, "_try_connect_ibkr") as mock_connect:
        provider = MarketDataProvider(
            ibkr_config={"host": "127.0.0.1", "port": 4001, "client_id": 1},
            config={"data_sources": {"ibkr_tws": {"enabled": False}}},
        )
    mock_connect.assert_not_called()
    assert provider.ibkr is None


# ---------------------------------------------------------------------------
# Task 4: Wire providers into MarketDataProvider routing
# ---------------------------------------------------------------------------

def test_market_data_provider_uses_polygon_for_us_price_when_no_ibkr():
    """When IBKR is not connected and Polygon key is set, Polygon is used for US tickers."""
    from src.market_data import MarketDataProvider

    provider = MarketDataProvider(
        config={"data_sources": {"polygon": {"api_key": "fake-polygon-key"}}}
    )

    mock_df = pd.DataFrame(
        {"Open": [100.0], "High": [105.0], "Low": [99.0], "Close": [102.0], "Volume": [1e6]},
        index=pd.to_datetime(["2026-03-07"]),
    )

    with patch.object(provider._polygon, "get_price_data", return_value=mock_df) as mock_poly:
        df = provider.get_price_data("AAPL", "5d")

    mock_poly.assert_called_once_with("AAPL", "5d")
    assert not df.empty


def test_market_data_provider_falls_back_to_yfinance_when_polygon_empty():
    """When Polygon returns empty, yfinance is used."""
    from src.market_data import MarketDataProvider

    provider = MarketDataProvider(
        config={"data_sources": {"polygon": {"api_key": "fake-polygon-key"}}}
    )

    yf_df = pd.DataFrame(
        {"Open": [100.0], "High": [105.0], "Low": [99.0], "Close": [102.0], "Volume": [1e6]},
        index=pd.to_datetime(["2026-03-07"]),
    )

    with patch.object(provider._polygon, "get_price_data", return_value=pd.DataFrame()):
        with patch.object(provider, "_yf_price_data", return_value=yf_df) as mock_yf:
            df = provider.get_price_data("AAPL", "5d")

    mock_yf.assert_called_once()
    assert not df.empty


def test_market_data_provider_skips_polygon_for_hk_ticker():
    """HK tickers always go to yfinance, Polygon is not called."""
    from src.market_data import MarketDataProvider

    provider = MarketDataProvider(
        config={"data_sources": {"polygon": {"api_key": "fake-polygon-key"}}}
    )

    yf_df = pd.DataFrame(
        {"Close": [50.0]},
        index=pd.to_datetime(["2026-03-07"]),
    )

    with patch.object(provider._polygon, "get_price_data") as mock_poly:
        with patch.object(provider, "_yf_price_data", return_value=yf_df):
            provider.get_price_data("0700.HK", "5d")

    mock_poly.assert_not_called()


def test_market_data_provider_uses_tradier_for_options_fallback():
    """When IBKR not connected and Tradier key is set, Tradier is used for options."""
    from src.market_data import MarketDataProvider

    provider = MarketDataProvider(
        config={"data_sources": {"tradier": {"api_key": "fake-tradier-key"}}}
    )

    tradier_df = pd.DataFrame({
        "strike": [150.0], "bid": [3.5],
        "dte": [60], "expiration": [date.today() + timedelta(days=60)],
    })

    with patch.object(provider._tradier, "get_options_chain", return_value=tradier_df) as mock_tr:
        df = provider.get_options_chain("AAPL", dte_min=45, dte_max=90)

    mock_tr.assert_called_once_with("AAPL", dte_min=45, dte_max=90)
    assert not df.empty


def test_market_data_provider_merges_polygon_and_yfinance_fundamentals():
    """Polygon provides ROE/FCF; yfinance fills None fields (payout_ratio, dividend_yield)."""
    from src.market_data import MarketDataProvider

    provider = MarketDataProvider(
        config={"data_sources": {"polygon": {"api_key": "fake-polygon-key"}}}
    )

    polygon_result = {
        "company_name": "Apple Inc.", "industry": "Electronic Computers",
        "sector": None, "roe": 156.0, "free_cash_flow": 99e9,
        "payout_ratio": None, "debt_to_equity": None, "dividend_yield": None,
    }
    yf_result = {
        "company_name": "Apple Inc.", "industry": "Consumer Electronics",
        "sector": "Technology", "roe": 150.0, "free_cash_flow": 95e9,
        "payout_ratio": 15.0, "debt_to_equity": 1.5, "dividend_yield": 0.52,
    }

    with patch.object(provider._polygon, "get_fundamentals", return_value=polygon_result):
        with patch.object(provider, "_yf_fundamentals", return_value=yf_result):
            result = provider.get_fundamentals("AAPL")

    assert result is not None
    # Polygon values used where available
    assert result["roe"] == 156.0
    assert result["free_cash_flow"] == 99e9
    # yfinance fills None fields
    assert result["payout_ratio"] == 15.0
    assert result["dividend_yield"] == 0.52
    assert result["sector"] == "Technology"


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


# ── TradierProvider tests ──────────────────────────────────────────────────

def _tradier_expirations_response():
    from datetime import date, timedelta
    future = date.today() + timedelta(days=60)
    return {"expirations": {"date": [future.strftime("%Y-%m-%d")]}}


def _tradier_chain_response():
    return {
        "options": {
            "option": [
                {"option_type": "put", "strike": 150.0, "bid": 3.50, "symbol": "AAPL..."},
                {"option_type": "put", "strike": 155.0, "bid": 4.20, "symbol": "AAPL..."},
                {"option_type": "call", "strike": 160.0, "bid": 5.00, "symbol": "AAPL..."},
            ]
        }
    }


def test_tradier_provider_returns_put_options_dataframe():
    from src.providers.tradier import TradierProvider
    provider = TradierProvider(api_key="test-key")

    expirations_resp = MagicMock()
    expirations_resp.status_code = 200
    expirations_resp.json.return_value = _tradier_expirations_response()

    chain_resp = MagicMock()
    chain_resp.status_code = 200
    chain_resp.json.return_value = _tradier_chain_response()

    def fake_get(url, *args, **kwargs):
        if "expirations" in url:
            return expirations_resp
        return chain_resp

    with patch("src.providers.tradier.requests.get", side_effect=fake_get):
        df = provider.get_options_chain("AAPL", dte_min=45, dte_max=90)

    assert not df.empty
    assert set(df.columns) >= {"strike", "bid", "dte", "expiration"}
    assert len(df) == 2   # 2 puts, 1 call filtered out
    assert all(df["bid"] > 0)


def test_tradier_provider_returns_empty_when_no_expirations_in_range():
    from src.providers.tradier import TradierProvider
    from datetime import date, timedelta
    provider = TradierProvider(api_key="test-key")

    near_future = date.today() + timedelta(days=10)
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"expirations": {"date": [near_future.strftime("%Y-%m-%d")]}}

    with patch("src.providers.tradier.requests.get", return_value=resp):
        df = provider.get_options_chain("AAPL", dte_min=45, dte_max=90)

    assert df.empty


def test_tradier_provider_returns_empty_on_exception():
    from src.providers.tradier import TradierProvider
    provider = TradierProvider(api_key="test-key")

    with patch("src.providers.tradier.requests.get", side_effect=Exception("network error")):
        df = provider.get_options_chain("AAPL", dte_min=45, dte_max=90)

    assert df.empty


# ── AKShare wiring ────────────────────────────────────────────────────────────

def test_akshare_enabled_by_default():
    provider = MarketDataProvider(config={})
    assert provider._akshare is not None
    assert provider._akshare.enabled is True


def test_akshare_activated_by_config():
    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": True}}})
    assert provider._akshare.enabled is True


def test_akshare_disabled_by_config():
    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": False}}})
    assert provider._akshare.enabled is False


# ── get_price_data routing ────────────────────────────────────────────────────

def test_cn_price_uses_akshare_before_yfinance():
    mock_df = pd.DataFrame({"Open": [1.0], "Close": [1.0]})
    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": True}}})
    provider.ibkr = None
    provider._akshare.get_price_data = MagicMock(return_value=mock_df)

    with patch.object(provider, "_yf_price_data") as mock_yf:
        result = provider.get_price_data("600519.SS")

    provider._akshare.get_price_data.assert_called_once_with("600519.SS", "1y")
    mock_yf.assert_not_called()
    assert not result.empty


def test_cn_price_falls_back_to_yfinance_when_akshare_empty():
    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": True}}})
    provider.ibkr = None
    provider._akshare.get_price_data = MagicMock(return_value=pd.DataFrame())

    with patch.object(provider, "_yf_price_data", return_value=pd.DataFrame({"Close": [100.0]})) as mock_yf:
        result = provider.get_price_data("600519.SS")

    mock_yf.assert_called_once()
    assert not result.empty


def test_hk_price_uses_akshare_before_yfinance():
    mock_df = pd.DataFrame({"Open": [300.0], "Close": [301.0]})
    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": True}}})
    provider.ibkr = None
    provider._akshare.get_price_data = MagicMock(return_value=mock_df)

    with patch.object(provider, "_yf_price_data") as mock_yf:
        provider.get_price_data("0700.HK")

    provider._akshare.get_price_data.assert_called_once()
    mock_yf.assert_not_called()


def test_us_price_akshare_after_polygon():
    mock_df = pd.DataFrame({"Open": [185.0], "Close": [186.0]})
    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": True}}})
    provider.ibkr = None
    provider._polygon = MagicMock()
    provider._polygon.get_price_data.return_value = pd.DataFrame()
    provider._akshare.get_price_data = MagicMock(return_value=mock_df)

    with patch.object(provider, "_yf_price_data") as mock_yf:
        provider.get_price_data("AAPL")

    provider._akshare.get_price_data.assert_called_once()
    mock_yf.assert_not_called()


# ── get_fundamentals routing ──────────────────────────────────────────────────

def test_cn_fundamentals_uses_akshare_before_yfinance():
    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": True}}})
    provider._akshare.get_fundamentals = MagicMock(return_value={
        "company_name": "贵州茅台", "industry": "白酒",
        "sector": None, "roe": None, "free_cash_flow": None,
        "payout_ratio": None, "debt_to_equity": None, "dividend_yield": 2.5,
    })

    with patch.object(provider, "_yf_fundamentals") as mock_yf:
        result = provider.get_fundamentals("600519.SS")

    provider._akshare.get_fundamentals.assert_called_once_with("600519.SS")
    mock_yf.assert_not_called()
    assert result["company_name"] == "贵州茅台"


def test_cn_fundamentals_falls_back_to_yfinance_when_akshare_none():
    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": True}}})
    provider._akshare.get_fundamentals = MagicMock(return_value=None)

    with patch.object(provider, "_yf_fundamentals", return_value={"company_name": "Moutai"}) as mock_yf:
        result = provider.get_fundamentals("600519.SS")

    mock_yf.assert_called_once()
    assert result["company_name"] == "Moutai"


# ── get_options_chain routing ─────────────────────────────────────────────────

def test_cn_options_uses_akshare():
    mock_opts = pd.DataFrame({"strike": [2.7], "bid": [0.08], "dte": [55], "expiration": ["2024-03-27"]})
    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": True}}})
    provider.ibkr = None
    provider._akshare.get_options_chain = MagicMock(return_value=mock_opts)

    with patch.object(provider, "_yf_options_chain") as mock_yf:
        result = provider.get_options_chain("510050.SS")

    provider._akshare.get_options_chain.assert_called_once()
    mock_yf.assert_not_called()
    assert not result.empty


def test_us_options_akshare_after_tradier():
    mock_opts = pd.DataFrame({"strike": [170.0], "bid": [2.5], "dte": [50], "expiration": ["2024-04-19"]})
    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": True}}})
    provider.ibkr = None
    provider._tradier = MagicMock()
    provider._tradier.get_options_chain.return_value = pd.DataFrame()
    provider._akshare.get_options_chain = MagicMock(return_value=mock_opts)

    with patch.object(provider, "_yf_options_chain") as mock_yf:
        result = provider.get_options_chain("AAPL")

    provider._akshare.get_options_chain.assert_called_once()
    mock_yf.assert_not_called()
    assert not result.empty
