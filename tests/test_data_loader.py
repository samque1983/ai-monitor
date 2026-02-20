# tests/test_data_loader.py
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from src.data_loader import fetch_universe, clean_strike_price, classify_market


class TestCleanStrikePrice:
    def test_clean_numeric_string(self):
        assert clean_strike_price("150.50") == 150.50

    def test_clean_with_dollar_sign(self):
        assert clean_strike_price("$150.50") == 150.50

    def test_clean_with_chinese_chars(self):
        assert clean_strike_price("$150.50元") == 150.50

    def test_clean_empty_string(self):
        assert clean_strike_price("") is None

    def test_clean_none(self):
        assert clean_strike_price(None) is None

    def test_clean_pure_text(self):
        assert clean_strike_price("无目标") is None

    def test_clean_numeric_value(self):
        assert clean_strike_price(150.50) == 150.50


class TestClassifyMarket:
    def test_us_ticker(self):
        assert classify_market("AAPL") == "US"

    def test_hk_ticker(self):
        assert classify_market("0700.HK") == "HK"

    def test_shanghai_ticker(self):
        assert classify_market("600900.SS") == "CN"

    def test_shenzhen_ticker(self):
        assert classify_market("000001.SZ") == "CN"


class TestFetchUniverse:
    @patch("src.data_loader.pd.read_csv")
    def test_returns_ticker_list_and_target_buys(self, mock_read_csv):
        mock_df = pd.DataFrame({
            "代码": ["AAPL", "MSFT", "0700.HK"],
            "Strike (黄金位)": ["$150", "280.5", ""],
        })
        mock_read_csv.return_value = mock_df

        tickers, target_buys = fetch_universe("https://example.com/test.csv")

        assert tickers == ["AAPL", "MSFT", "0700.HK"]
        assert target_buys == {"AAPL": 150.0, "MSFT": 280.5}

    @patch("src.data_loader.pd.read_csv")
    def test_strips_whitespace_from_tickers(self, mock_read_csv):
        mock_df = pd.DataFrame({
            "代码": [" AAPL ", "MSFT"],
            "Strike (黄金位)": ["150", "280"],
        })
        mock_read_csv.return_value = mock_df

        tickers, target_buys = fetch_universe("https://example.com/test.csv")
        assert tickers == ["AAPL", "MSFT"]

    @patch("src.data_loader.pd.read_csv")
    def test_skips_rows_with_empty_ticker(self, mock_read_csv):
        mock_df = pd.DataFrame({
            "代码": ["AAPL", "", None, "MSFT"],
            "Strike (黄金位)": ["150", "100", "200", "280"],
        })
        mock_read_csv.return_value = mock_df

        tickers, target_buys = fetch_universe("https://example.com/test.csv")
        assert tickers == ["AAPL", "MSFT"]

    @patch("src.data_loader.pd.read_csv")
    def test_csv_fetch_failure_raises(self, mock_read_csv):
        mock_read_csv.side_effect = Exception("Network error")
        with pytest.raises(Exception, match="Network error"):
            fetch_universe("https://example.com/test.csv")
