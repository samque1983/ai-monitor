# tests/test_data_loader.py
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from src.data_loader import fetch_universe, clean_strike_price, classify_market, normalize_ticker


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

    def test_clean_nan_value(self):
        assert clean_strike_price(float("nan")) is None


class TestNormalizeTicker:
    def test_us_ticker_unchanged(self):
        assert normalize_ticker("AAPL") == "AAPL"

    def test_hk_ticker_unchanged(self):
        assert normalize_ticker("0700.HK") == "0700.HK"

    def test_brk_dot_b_to_dash(self):
        assert normalize_ticker("BRK.B") == "BRK-B"

    def test_brk_dot_a_to_dash(self):
        assert normalize_ticker("BRK.A") == "BRK-A"

    def test_six_digit_starting_with_6_gets_ss(self):
        assert normalize_ticker("600900") == "600900.SS"

    def test_six_digit_starting_with_0_gets_sz(self):
        assert normalize_ticker("000001") == "000001.SZ"

    def test_six_digit_starting_with_3_gets_sz(self):
        assert normalize_ticker("300750") == "300750.SZ"

    def test_already_has_ss_suffix(self):
        assert normalize_ticker("600900.SS") == "600900.SS"

    def test_already_has_sz_suffix(self):
        assert normalize_ticker("000001.SZ") == "000001.SZ"

    def test_lowercase_brk(self):
        assert normalize_ticker("brk.b") == "BRK-B"


class TestClassifyMarket:
    def test_us_ticker(self):
        assert classify_market("AAPL") == "US"

    def test_hk_ticker(self):
        assert classify_market("0700.HK") == "HK"

    def test_shanghai_ticker(self):
        assert classify_market("600900.SS") == "CN"

    def test_shenzhen_ticker(self):
        assert classify_market("000001.SZ") == "CN"


def _mock_csv_response(csv_text):
    """Create a mock requests.Response with CSV content."""
    from unittest.mock import MagicMock
    resp = MagicMock()
    resp.text = csv_text
    resp.raise_for_status = MagicMock()
    return resp


class TestFetchUniverse:
    @patch("src.data_loader.requests.get")
    def test_returns_ticker_list_and_target_buys(self, mock_get):
        mock_get.return_value = _mock_csv_response(
            "代码,Strike (黄金位)\nAAPL,$150\nMSFT,280.5\n0700.HK,\n"
        )

        tickers, target_buys = fetch_universe("https://example.com/test.csv")

        assert tickers == ["AAPL", "MSFT", "0700.HK"]
        assert target_buys == {"AAPL": 150.0, "MSFT": 280.5}

    @patch("src.data_loader.requests.get")
    def test_strips_whitespace_from_tickers(self, mock_get):
        mock_get.return_value = _mock_csv_response(
            "代码,Strike (黄金位)\n AAPL ,150\nMSFT,280\n"
        )

        tickers, target_buys = fetch_universe("https://example.com/test.csv")
        assert tickers == ["AAPL", "MSFT"]

    @patch("src.data_loader.requests.get")
    def test_skips_rows_with_empty_ticker(self, mock_get):
        mock_get.return_value = _mock_csv_response(
            "代码,Strike (黄金位)\nAAPL,150\n,100\n,200\nMSFT,280\n"
        )

        tickers, target_buys = fetch_universe("https://example.com/test.csv")
        assert tickers == ["AAPL", "MSFT"]

    @patch("src.data_loader.requests.get")
    def test_csv_fetch_failure_raises(self, mock_get):
        mock_get.side_effect = Exception("Network error")
        with pytest.raises(Exception, match="Network error"):
            fetch_universe("https://example.com/test.csv")
