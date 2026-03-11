"""Tests for AkshareProvider."""
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from src.providers.akshare import AkshareProvider


def test_provider_instantiation():
    p = AkshareProvider(enabled=True)
    assert p.enabled is True


def test_provider_disabled_returns_empty():
    p = AkshareProvider(enabled=False)
    assert p.get_price_data("600519.SS").empty
    assert p.get_fundamentals("600519.SS") is None
    assert p.get_options_chain("600519.SS").empty


def test_normalize_cn():
    p = AkshareProvider()
    assert p._normalize_cn("600519.SS") == "600519"
    assert p._normalize_cn("000001.SZ") == "000001"
    assert p._normalize_cn("510050.SS") == "510050"


def test_normalize_hk():
    p = AkshareProvider()
    assert p._normalize_hk("0700.HK") == "00700"
    assert p._normalize_hk("0005.HK") == "00005"
    assert p._normalize_hk("0823.HK") == "00823"
    assert p._normalize_hk("09988.HK") == "09988"  # already 5 digits


# ── price data ──────────────────────────────────────────────────────────────

MOCK_CN_PRICE = pd.DataFrame({
    "日期": ["2024-01-02", "2024-01-03"],
    "开盘": [100.0, 101.0], "最高": [102.0, 103.0],
    "最低": [99.0, 100.0],  "收盘": [101.0, 102.0],
    "成交量": [1_000_000, 1_200_000],
})

MOCK_HK_PRICE = pd.DataFrame({
    "日期": ["2024-01-02", "2024-01-03"],
    "开盘": [300.0, 302.0], "最高": [305.0, 306.0],
    "最低": [298.0, 300.0], "收盘": [303.0, 304.0],
    "成交量": [5_000_000, 6_000_000],
})

MOCK_US_PRICE = pd.DataFrame({
    "日期": ["2024-01-02", "2024-01-03"],
    "开盘": [185.0, 186.0], "最高": [187.0, 188.0],
    "最低": [184.0, 185.0], "收盘": [186.0, 187.0],
    "成交量": [50_000_000, 55_000_000],
})


def test_cn_price_data():
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.stock_zh_a_hist.return_value = MOCK_CN_PRICE.copy()
        df = p.get_price_data("600519.SS", "1y")
    assert not df.empty
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert df.index.name is None
    mock_ak.stock_zh_a_hist.assert_called_once()
    call_kwargs = mock_ak.stock_zh_a_hist.call_args
    assert call_kwargs.kwargs.get("symbol") == "600519" or call_kwargs.args[0] == "600519"
    assert call_kwargs.kwargs.get("adjust") == "hfq"


def test_hk_price_data():
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.stock_hk_hist.return_value = MOCK_HK_PRICE.copy()
        df = p.get_price_data("0700.HK", "1y")
    assert not df.empty
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    call_kwargs = mock_ak.stock_hk_hist.call_args
    symbol_used = call_kwargs.kwargs.get("symbol") or call_kwargs.args[0]
    assert symbol_used == "00700"


def test_us_price_data():
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.stock_us_hist.return_value = MOCK_US_PRICE.copy()
        df = p.get_price_data("AAPL", "1y")
    assert not df.empty
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    call_kwargs = mock_ak.stock_us_hist.call_args
    symbol_used = call_kwargs.kwargs.get("symbol") or call_kwargs.args[0]
    assert symbol_used == "AAPL"


def test_price_data_api_error_returns_empty():
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.stock_zh_a_hist.side_effect = Exception("network error")
        df = p.get_price_data("600519.SS")
    assert df.empty


# ── fundamentals ─────────────────────────────────────────────────────────────

# ak.stock_individual_info_em returns a 2-column DataFrame: item, value
MOCK_CN_INFO = pd.DataFrame({
    "item":  ["股票简称", "行业", "总市值", "流通市值"],
    "value": ["贵州茅台",  "白酒", "2000亿", "1500亿"],
})

MOCK_HK_INFO = pd.DataFrame({
    "item":  ["公司名称",       "行业"],
    "value": ["腾讯控股有限公司", "互联网"],
})

# ak.stock_zh_a_lg_indicator returns DataFrame with columns 股息率, 市盈率 etc.
MOCK_CN_INDICATOR = pd.DataFrame({
    "股息率": [2.5],
    "市盈率": [35.0],
    "市净率": [12.0],
})


def test_cn_fundamentals():
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.stock_individual_info_em.return_value = MOCK_CN_INFO.copy()
        mock_ak.stock_zh_a_lg_indicator.return_value = MOCK_CN_INDICATOR.copy()
        result = p.get_fundamentals("600519.SS")
    assert result is not None
    assert result["company_name"] == "贵州茅台"
    assert result["industry"] == "白酒"
    assert result["dividend_yield"] == pytest.approx(2.5)


def test_hk_fundamentals():
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.stock_hk_company_profile_em.return_value = MOCK_HK_INFO.copy()
        result = p.get_fundamentals("0700.HK")
    assert result is not None
    assert result["company_name"] == "腾讯控股有限公司"
    assert result["industry"] == "互联网"


def test_fundamentals_api_error_returns_none():
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.stock_individual_info_em.side_effect = Exception("timeout")
        result = p.get_fundamentals("600519.SS")
    assert result is None


def test_us_fundamentals_returns_none():
    """AKShare does not provide US fundamentals — return None to trigger yfinance."""
    p = AkshareProvider(enabled=True)
    result = p.get_fundamentals("AAPL")
    assert result is None
