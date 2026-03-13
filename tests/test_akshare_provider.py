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

# ak.stock_individual_spot_xq returns DataFrame with columns 'item', 'value'
MOCK_XQ_SPOT = pd.DataFrame({
    "item":  ["代码", "名称", "现价", "股息(TTM)", "股息率(TTM)", "市盈率(TTM)"],
    "value": ["SH600519", "贵州茅台", "1800.0", "28.5", "2.5", "30.0"],
})


def test_cn_fundamentals():
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.stock_individual_info_em.return_value = MOCK_CN_INFO.copy()
        mock_ak.stock_individual_spot_xq.return_value = MOCK_XQ_SPOT.copy()
        result = p.get_fundamentals("600519.SS")
    assert result is not None
    assert result["company_name"] == "贵州茅台"
    assert result["industry"] == "白酒"
    assert result["dividend_yield"] == pytest.approx(2.5)


def test_cn_xq_symbol():
    p = AkshareProvider(enabled=True)
    assert p._cn_xq_symbol("600036.SS") == "SH600036"
    assert p._cn_xq_symbol("000001.SZ") == "SZ000001"
    assert p._cn_xq_symbol("510050.SS") == "SH510050"


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


# ── options chain ─────────────────────────────────────────────────────────────

MOCK_CN_OPTIONS = pd.DataFrame({
    "期权名称": ["50ETF购3月2800", "50ETF沽3月2700", "50ETF沽4月2600"],
    "行权价":   [2.800,            2.700,            2.600],
    "买价":     [0.049,            0.079,            0.119],
    "到期日":   ["2024-03-27",     "2024-03-27",     "2024-04-24"],
})


def test_cn_options_chain():
    """50ETF options: filter puts by DTE range, return strike/bid/dte/expiration."""
    import datetime
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        with patch("src.providers.akshare.date") as mock_date:
            mock_date.today.return_value = datetime.date(2024, 2, 1)
            mock_ak.option_finance_board.return_value = MOCK_CN_OPTIONS.copy()
            df = p.get_options_chain("510050.SS", dte_min=30, dte_max=120)
    assert not df.empty
    assert set(df.columns) >= {"strike", "bid", "dte", "expiration"}
    # Only puts (沽) — 2 put rows
    assert len(df) == 2
    assert all("strike" in df.columns for _ in [1])


def test_cn_options_outside_dte_filtered():
    """Puts outside DTE range are excluded."""
    import datetime
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        with patch("src.providers.akshare.date") as mock_date:
            mock_date.today.return_value = datetime.date(2024, 2, 1)
            mock_ak.option_finance_board.return_value = MOCK_CN_OPTIONS.copy()
            # March 27 = 55 DTE, April 24 = 83 DTE — only April in [60,120]
            df = p.get_options_chain("510050.SS", dte_min=60, dte_max=120)
    assert len(df) == 1
    assert df.iloc[0]["strike"] == pytest.approx(2.600)


def test_unknown_cn_ticker_options_returns_empty():
    """CN tickers not in ETF option map return empty."""
    p = AkshareProvider(enabled=True)
    df = p.get_options_chain("600519.SS")
    assert df.empty


def test_options_chain_api_error_returns_empty():
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.option_finance_board.side_effect = Exception("API down")
        df = p.get_options_chain("510050.SS")
    assert df.empty


# ── dividend history ──────────────────────────────────────────────────────────

import datetime as _dt

MOCK_HK_DIVIDEND = pd.DataFrame({
    "最新公告日期": [_dt.date(2024, 4, 1), _dt.date(2023, 4, 3), _dt.date(2022, 4, 4)],
    "财政年度":     ["2023",              "2022",              "2021"],
    "分红方案":     ["每股派息0.45港元",  "每股派息0.38港元",  "每股派息0.30港元"],
    "分配类型":     ["末期息",            "末期息",            "末期息"],
    "除净日":       [_dt.date(2024, 5, 10), _dt.date(2023, 5, 12), _dt.date(2022, 5, 6)],
    "截至过户日":   [None, None, None],
    "发放日":       [None, None, None],
})

MOCK_CN_DIVIDEND = pd.DataFrame({
    "实施方案公告日期": [_dt.date(2024, 6, 1), _dt.date(2023, 6, 2), _dt.date(2022, 6, 3)],
    "分红类型":     ["现金分红", "现金分红", "现金分红"],
    "送股比例":     [0.0, 0.0, 0.0],
    "转增比例":     [0.0, 0.0, 0.0],
    "派息比例":     [25.0, 20.0, 18.0],  # per 10 shares → /10 = per share
    "股权登记日":   [None, None, None],
    "除权日":       [_dt.date(2024, 6, 10), _dt.date(2023, 6, 9), _dt.date(2022, 6, 8)],
    "派息日":       [None, None, None],
    "股份到账日":   [None, None, None],
    "实施方案分红说明": ["", "", ""],
    "报告时间":     ["2024", "2023", "2022"],
})


def test_hk_dividend_history():
    """HK: parse 分红方案 text, use 除净日 as date."""
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.stock_hk_dividend_payout_em.return_value = MOCK_HK_DIVIDEND.copy()
        result = p.get_dividend_history("0267.HK", years=5)
    assert result is not None
    assert len(result) == 3
    assert result[0]["date"] == _dt.date(2022, 5, 6)   # sorted ascending
    assert result[0]["amount"] == pytest.approx(0.30)
    assert result[-1]["amount"] == pytest.approx(0.45)
    call_kwargs = mock_ak.stock_hk_dividend_payout_em.call_args
    symbol_used = call_kwargs.kwargs.get("symbol") or call_kwargs.args[0]
    assert symbol_used == "00267"


def test_cn_dividend_history():
    """CN: 派息比例 / 10 gives per-share amount, use 除权日 as date."""
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.stock_dividend_cninfo.return_value = MOCK_CN_DIVIDEND.copy()
        result = p.get_dividend_history("600519.SS", years=5)
    assert result is not None
    assert len(result) == 3
    assert result[0]["date"] == _dt.date(2022, 6, 8)   # ascending
    assert result[0]["amount"] == pytest.approx(1.8)   # 18.0 / 10
    assert result[-1]["amount"] == pytest.approx(2.5)  # 25.0 / 10
    call_kwargs = mock_ak.stock_dividend_cninfo.call_args
    symbol_used = call_kwargs.kwargs.get("symbol") or call_kwargs.args[0]
    assert symbol_used == "600519"


def test_hk_dividend_history_years_filter():
    """Only records within years window are returned."""
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        with patch("src.providers.akshare.date") as mock_date:
            mock_date.today.return_value = _dt.date(2024, 12, 1)
            mock_ak.stock_hk_dividend_payout_em.return_value = MOCK_HK_DIVIDEND.copy()
            result = p.get_dividend_history("0267.HK", years=2)
    assert result is not None
    assert len(result) == 2


def test_hk_dividend_text_parsing_variants():
    """Various 分红方案 text formats are parsed correctly."""
    p = AkshareProvider(enabled=True)
    variants = pd.DataFrame({
        "分红方案": [
            "每股末期股息港币0.16元",
            "每股派发末期股息港币1.70元",
            "每股派息2.00港元",
        ],
        "除净日": [
            _dt.date(2024, 5, 1),
            _dt.date(2023, 5, 1),
            _dt.date(2022, 5, 1),
        ],
    })
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.stock_hk_dividend_payout_em.return_value = variants
        result = p.get_dividend_history("0267.HK", years=5)
    assert result is not None
    amounts = [r["amount"] for r in result]
    assert pytest.approx(0.16) in amounts
    assert pytest.approx(1.70) in amounts
    assert pytest.approx(2.00) in amounts


def test_us_dividend_history_returns_none():
    """AKShare does not provide US dividend history — return None."""
    p = AkshareProvider(enabled=True)
    result = p.get_dividend_history("AAPL", years=5)
    assert result is None


def test_dividend_history_api_error_returns_none():
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.stock_hk_dividend_payout_em.side_effect = Exception("timeout")
        result = p.get_dividend_history("0267.HK", years=5)
    assert result is None


def test_dividend_history_disabled_returns_none():
    p = AkshareProvider(enabled=False)
    result = p.get_dividend_history("0267.HK", years=5)
    assert result is None


def test_dividend_history_empty_df_returns_none():
    """Empty API response returns None."""
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.stock_hk_dividend_payout_em.return_value = pd.DataFrame()
        result = p.get_dividend_history("0267.HK", years=5)
    assert result is None


def test_cn_dividend_zero_payout_skipped():
    """Rows with 派息比例=0 are skipped."""
    p = AkshareProvider(enabled=True)
    df = MOCK_CN_DIVIDEND.copy()
    df.loc[1, "派息比例"] = 0.0
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.stock_dividend_cninfo.return_value = df
        result = p.get_dividend_history("600519.SS", years=5)
    assert result is not None
    assert len(result) == 2
