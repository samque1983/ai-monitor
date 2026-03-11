# AKShare Provider Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `AkshareProvider` to `src/providers/` and wire it into `MarketDataProvider` fallback chains for CN/HK/US markets.

**Architecture:** Single `AkshareProvider(BaseProvider)` class in `src/providers/akshare.py`. It handles CN/HK/US market routing internally. Activated via `config.yaml` `data_sources.akshare.enabled` (no API key). MarketDataProvider inserts it into 3 fallback chains: CN/HK price, CN/HK fundamentals, CN ETF options, US options fallback.

**Tech Stack:** `akshare` (pip), `pandas`, `unittest.mock.patch` for tests. Follows existing `BaseProvider` + `PolygonProvider` patterns exactly.

---

### Task 1: Add akshare dependency + provider skeleton

**Files:**
- Modify: `requirements.txt` (or check pyproject.toml)
- Create: `src/providers/akshare.py`
- Modify: `src/providers/__init__.py`
- Create: `tests/test_akshare_provider.py`

**Step 1: Check requirements file location**

```bash
ls /Users/q/code/ai-monitor/requirements*.txt /Users/q/code/ai-monitor/pyproject.toml 2>/dev/null
```

**Step 2: Add akshare to requirements**

Add `akshare` to whatever requirements file exists. If `requirements.txt`:
```
akshare
```

**Step 3: Write the failing skeleton test**

`tests/test_akshare_provider.py`:
```python
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
```

**Step 4: Run to confirm RED**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_akshare_provider.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError: No module named 'src.providers.akshare'`

**Step 5: Create the skeleton `src/providers/akshare.py`**

```python
# src/providers/akshare.py
"""AKShare data provider for CN/HK/US markets."""
import logging
from datetime import date, timedelta
from typing import Dict, Any, Optional
import pandas as pd

from src.providers.base import BaseProvider
from src.data_loader import classify_market

logger = logging.getLogger(__name__)

_PERIOD_DAYS = {
    "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
    "1y": 365, "2y": 730, "5y": 1825, "10y": 3650,
}

COLUMN_MAP = {
    "日期": "Date", "开盘": "Open", "最高": "High",
    "最低": "Low",  "收盘": "Close", "成交量": "Volume",
}


class AkshareProvider(BaseProvider):
    """AKShare data provider — free, no API key. Covers CN/HK/US markets."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def _normalize_cn(self, ticker: str) -> str:
        """'600519.SS' → '600519', '000001.SZ' → '000001'."""
        return ticker.replace(".SS", "").replace(".SZ", "")

    def _normalize_hk(self, ticker: str) -> str:
        """'0700.HK' → '00700' (5-digit, leading zeros)."""
        symbol = ticker.replace(".HK", "")
        return symbol.zfill(5)

    def _date_range(self, period: str) -> tuple:
        """Return (start_date_str, end_date_str) in 'YYYYMMDD' format."""
        days = _PERIOD_DAYS.get(period, 365)
        end = date.today()
        start = end - timedelta(days=days)
        return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    def get_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        return pd.DataFrame()

    def get_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
        return None

    def get_options_chain(self, ticker: str, dte_min: int = 45, dte_max: int = 60) -> pd.DataFrame:
        return pd.DataFrame()
```

**Step 6: Export from `src/providers/__init__.py`**

```python
# src/providers/__init__.py
from src.providers.base import BaseProvider
from src.providers.polygon import PolygonProvider
from src.providers.tradier import TradierProvider
from src.providers.akshare import AkshareProvider

__all__ = ["BaseProvider", "PolygonProvider", "TradierProvider", "AkshareProvider"]
```

**Step 7: Run to confirm GREEN**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_akshare_provider.py::test_provider_instantiation tests/test_akshare_provider.py::test_provider_disabled_returns_empty tests/test_akshare_provider.py::test_normalize_cn tests/test_akshare_provider.py::test_normalize_hk -v
```
Expected: 4 PASSED

**Step 8: Commit**

```bash
git add src/providers/akshare.py src/providers/__init__.py tests/test_akshare_provider.py requirements.txt
git commit -m "feat: add AkshareProvider skeleton with ticker normalization"
```

---

### Task 2: Implement get_price_data (CN + HK + US)

**Files:**
- Modify: `src/providers/akshare.py`
- Modify: `tests/test_akshare_provider.py`

**Step 1: Write failing tests**

Append to `tests/test_akshare_provider.py`:

```python
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
```

**Step 2: Run to confirm RED**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_akshare_provider.py::test_cn_price_data -v 2>&1 | tail -10
```
Expected: FAIL (get_price_data returns empty)

**Step 3: Implement get_price_data in `src/providers/akshare.py`**

Add at top of file (after other imports):
```python
try:
    import akshare as ak
except ImportError:
    ak = None  # type: ignore
```

Replace the `get_price_data` stub:
```python
def get_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
    """Fetch daily adjusted OHLCV. Routes by market: CN/HK/US."""
    if not self.enabled or ak is None:
        return pd.DataFrame()
    try:
        market = classify_market(ticker)
        start, end = self._date_range(period)
        if market == "CN":
            symbol = self._normalize_cn(ticker)
            raw = ak.stock_zh_a_hist(
                symbol=symbol, period="daily",
                start_date=start, end_date=end, adjust="hfq",
            )
        elif market == "HK":
            symbol = self._normalize_hk(ticker)
            raw = ak.stock_hk_hist(
                symbol=symbol, period="daily",
                start_date=start, end_date=end, adjust="hfq",
            )
        else:  # US
            raw = ak.stock_us_hist(
                symbol=ticker, period="daily",
                start_date=start, end_date=end, adjust="hfq",
            )
        if raw is None or raw.empty:
            return pd.DataFrame()
        return self._normalize_price_df(raw)
    except Exception as e:
        logger.warning(f"AKShare price data failed for {ticker}: {e}")
        return pd.DataFrame()

def _normalize_price_df(self, df: pd.DataFrame) -> pd.DataFrame:
    """Rename Chinese columns, set Date index, return standard OHLCV."""
    df = df.rename(columns=COLUMN_MAP)
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date")
        df.index.name = None
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    return df[keep]
```

**Step 4: Run to confirm GREEN**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_akshare_provider.py::test_cn_price_data tests/test_akshare_provider.py::test_hk_price_data tests/test_akshare_provider.py::test_us_price_data tests/test_akshare_provider.py::test_price_data_api_error_returns_empty -v
```
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add src/providers/akshare.py tests/test_akshare_provider.py
git commit -m "feat: AkshareProvider.get_price_data for CN/HK/US"
```

---

### Task 3: Implement get_fundamentals (CN + HK)

**Files:**
- Modify: `src/providers/akshare.py`
- Modify: `tests/test_akshare_provider.py`

**Step 1: Write failing tests**

Append to `tests/test_akshare_provider.py`:

```python
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
```

**Step 2: Run to confirm RED**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_akshare_provider.py::test_cn_fundamentals -v 2>&1 | tail -10
```

**Step 3: Implement get_fundamentals in `src/providers/akshare.py`**

Replace the `get_fundamentals` stub:
```python
def get_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
    """Fetch fundamentals. Supports CN and HK only. Returns None for US."""
    if not self.enabled or ak is None:
        return None
    market = classify_market(ticker)
    try:
        if market == "CN":
            return self._cn_fundamentals(ticker)
        elif market == "HK":
            return self._hk_fundamentals(ticker)
        return None  # US: not supported, triggers yfinance
    except Exception as e:
        logger.warning(f"AKShare fundamentals failed for {ticker}: {e}")
        return None

def _cn_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
    symbol = self._normalize_cn(ticker)
    info_df = ak.stock_individual_info_em(stock=symbol)
    info = dict(zip(info_df["item"], info_df["value"]))
    company_name = info.get("股票简称") or ticker
    industry = info.get("行业")

    dividend_yield = None
    try:
        ind_df = ak.stock_zh_a_lg_indicator(stock=symbol)
        if not ind_df.empty and "股息率" in ind_df.columns:
            dividend_yield = float(ind_df["股息率"].iloc[-1])
    except Exception:
        pass

    return {
        "company_name": company_name,
        "industry": industry,
        "sector": None,
        "roe": None,
        "free_cash_flow": None,
        "payout_ratio": None,
        "debt_to_equity": None,
        "dividend_yield": dividend_yield,
    }

def _hk_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
    symbol = self._normalize_hk(ticker)
    info_df = ak.stock_hk_company_profile_em(stock=symbol)
    info = dict(zip(info_df["item"], info_df["value"]))
    company_name = info.get("公司名称") or ticker
    industry = info.get("行业")
    return {
        "company_name": company_name,
        "industry": industry,
        "sector": None,
        "roe": None,
        "free_cash_flow": None,
        "payout_ratio": None,
        "debt_to_equity": None,
        "dividend_yield": None,
    }
```

**Step 4: Run to confirm GREEN**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_akshare_provider.py::test_cn_fundamentals tests/test_akshare_provider.py::test_hk_fundamentals tests/test_akshare_provider.py::test_fundamentals_api_error_returns_none tests/test_akshare_provider.py::test_us_fundamentals_returns_none -v
```
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add src/providers/akshare.py tests/test_akshare_provider.py
git commit -m "feat: AkshareProvider.get_fundamentals for CN/HK"
```

---

### Task 4: Implement get_options_chain (CN ETF + US fallback)

**Files:**
- Modify: `src/providers/akshare.py`
- Modify: `tests/test_akshare_provider.py`

**Background:** For CN ETF options, AKShare's `ak.option_finance_board(symbol)` returns a board with all contracts. Put options have "沽" in their name. The `symbol` is the underlying ETF name (e.g. "50ETF", "300ETF"). We need a mapping from CN ticker to AKShare symbol.

**Step 1: Write failing tests**

Append to `tests/test_akshare_provider.py`:

```python
# ── options chain ─────────────────────────────────────────────────────────────

# ak.option_finance_board returns DataFrame with option contracts
MOCK_CN_OPTIONS = pd.DataFrame({
    "期权名称": ["50ETF购3月2800", "50ETF沽3月2700", "50ETF沽4月2600"],
    "行权价":   [2.800,            2.700,            2.600],
    "最新价":   [0.05,             0.08,             0.12],
    "买量":     [100,              200,              150],
    "卖量":     [90,               180,              140],
    "买价":     [0.049,            0.079,            0.119],
    "卖价":     [0.051,            0.081,            0.121],
    "到期日":   ["2024-03-27",     "2024-03-27",     "2024-04-24"],
})

MOCK_US_OPTIONS = pd.DataFrame({
    "期权名称": ["AAPL沽4月170", "AAPL沽4月165"],
    "行权价":   [170.0,          165.0],
    "买价":     [2.50,           1.80],
    "到期日":   ["2024-04-19",   "2024-04-19"],
})


def test_cn_options_chain(monkeypatch):
    """50ETF options: filter puts by DTE range, return strike/bid/dte/expiration."""
    import datetime
    fixed_today = datetime.date(2024, 2, 1)
    monkeypatch.setattr("src.providers.akshare.date", type("D", (), {"today": staticmethod(lambda: fixed_today)})())

    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.option_finance_board.return_value = MOCK_CN_OPTIONS.copy()
        df = p.get_options_chain("510050.SS", dte_min=30, dte_max=120)

    assert not df.empty
    # Only puts (沽) should appear
    # March 27 = 55 DTE from Feb 1, April 24 = 83 DTE — both in range
    assert set(df.columns) >= {"strike", "bid", "dte", "expiration"}
    # No calls (购) in result
    assert len(df) == 2  # 2 put rows


def test_cn_options_outside_dte_filtered(monkeypatch):
    """Puts outside DTE range are excluded."""
    import datetime
    fixed_today = datetime.date(2024, 2, 1)
    monkeypatch.setattr("src.providers.akshare.date", type("D", (), {"today": staticmethod(lambda: fixed_today)})())

    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.option_finance_board.return_value = MOCK_CN_OPTIONS.copy()
        df = p.get_options_chain("510050.SS", dte_min=60, dte_max=120)

    # Only April put (83 DTE) should be in range; March (55 DTE) excluded
    assert len(df) == 1
    assert df.iloc[0]["strike"] == pytest.approx(2.600)


def test_options_chain_api_error_returns_empty():
    p = AkshareProvider(enabled=True)
    with patch("src.providers.akshare.ak") as mock_ak:
        mock_ak.option_finance_board.side_effect = Exception("API down")
        df = p.get_options_chain("510050.SS")
    assert df.empty


def test_unknown_cn_ticker_options_returns_empty():
    """CN tickers not in ETF option map return empty (no options available)."""
    p = AkshareProvider(enabled=True)
    df = p.get_options_chain("600519.SS")  # Moutai: no ETF options
    assert df.empty
```

**Step 2: Run to confirm RED**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_akshare_provider.py::test_cn_options_chain -v 2>&1 | tail -10
```

**Step 3: Implement get_options_chain in `src/providers/akshare.py`**

Add the ETF mapping constant after `COLUMN_MAP`:
```python
# CN ETF option underlying mapping: ticker suffix → AKShare symbol name
_CN_ETF_OPTION_MAP = {
    "510050": "50ETF",    # 上证50ETF
    "510300": "300ETF",   # 沪深300ETF (Shanghai)
    "159901": "深100ETF", # 深证100ETF
    "588000": "科创50",   # 科创50ETF
}
```

Replace the `get_options_chain` stub:
```python
def get_options_chain(self, ticker: str, dte_min: int = 45, dte_max: int = 60) -> pd.DataFrame:
    """Fetch put options. CN: ETF options only. US: via AKShare fallback."""
    if not self.enabled or ak is None:
        return pd.DataFrame()
    market = classify_market(ticker)
    try:
        if market == "CN":
            return self._cn_options_chain(ticker, dte_min, dte_max)
        elif market == "US":
            return self._us_options_chain(ticker, dte_min, dte_max)
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"AKShare options chain failed for {ticker}: {e}")
        return pd.DataFrame()

def _cn_options_chain(self, ticker: str, dte_min: int, dte_max: int) -> pd.DataFrame:
    symbol_key = self._normalize_cn(ticker)
    ak_symbol = _CN_ETF_OPTION_MAP.get(symbol_key)
    if not ak_symbol:
        return pd.DataFrame()  # not an optionable ETF

    board = ak.option_finance_board(symbol=ak_symbol)
    if board is None or board.empty:
        return pd.DataFrame()

    today = date.today()
    rows = []
    for _, row in board.iterrows():
        name = str(row.get("期权名称", ""))
        if "沽" not in name:
            continue  # skip calls
        try:
            exp_date = pd.to_datetime(row["到期日"]).date()
            dte = (exp_date - today).days
            if not (dte_min <= dte <= dte_max):
                continue
            rows.append({
                "strike": float(row["行权价"]),
                "bid": float(row.get("买价", 0.0) or 0.0),
                "dte": dte,
                "expiration": exp_date,
            })
        except Exception:
            continue

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)

def _us_options_chain(self, ticker: str, dte_min: int, dte_max: int) -> pd.DataFrame:
    """US options via AKShare — limited coverage, best-effort fallback."""
    try:
        board = ak.option_current_em(symbol=ticker)
        if board is None or board.empty:
            return pd.DataFrame()

        today = date.today()
        rows = []
        for _, row in board.iterrows():
            name = str(row.get("期权名称", ""))
            if "沽" not in name:
                continue
            try:
                exp_date = pd.to_datetime(row["到期日"]).date()
                dte = (exp_date - today).days
                if not (dte_min <= dte <= dte_max):
                    continue
                rows.append({
                    "strike": float(row["行权价"]),
                    "bid": float(row.get("买价", 0.0) or 0.0),
                    "dte": dte,
                    "expiration": exp_date,
                })
            except Exception:
                continue

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)
    except Exception as e:
        logger.warning(f"AKShare US options failed for {ticker}: {e}")
        return pd.DataFrame()
```

**Step 4: Run to confirm GREEN**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_akshare_provider.py::test_cn_options_chain tests/test_akshare_provider.py::test_cn_options_outside_dte_filtered tests/test_akshare_provider.py::test_options_chain_api_error_returns_empty tests/test_akshare_provider.py::test_unknown_cn_ticker_options_returns_empty -v
```
Expected: 4 PASSED

**Step 5: Run all provider tests**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_akshare_provider.py -v
```
Expected: all PASSED

**Step 6: Commit**

```bash
git add src/providers/akshare.py tests/test_akshare_provider.py
git commit -m "feat: AkshareProvider.get_options_chain for CN ETF and US fallback"
```

---

### Task 5: Wire AkshareProvider into MarketDataProvider.__init__

**Files:**
- Modify: `src/market_data.py` (lines ~18-50, the `__init__` method)
- Modify: `config.yaml`

**Step 1: Write failing test**

In `tests/test_market_data.py`, add a new test (find where Polygon/Tradier init tests are, add nearby):

```python
def test_akshare_activated_by_config():
    """MarketDataProvider creates _akshare when config enables it."""
    from src.market_data import MarketDataProvider
    config = {"data_sources": {"akshare": {"enabled": True}}}
    provider = MarketDataProvider(config=config)
    assert provider._akshare is not None
    assert provider._akshare.enabled is True


def test_akshare_disabled_by_config():
    """MarketDataProvider sets _akshare.enabled=False when config disables it."""
    from src.market_data import MarketDataProvider
    config = {"data_sources": {"akshare": {"enabled": False}}}
    provider = MarketDataProvider(config=config)
    assert provider._akshare is not None
    assert provider._akshare.enabled is False


def test_akshare_enabled_by_default():
    """AKShare is enabled by default when data_sources.akshare not in config."""
    from src.market_data import MarketDataProvider
    provider = MarketDataProvider(config={})
    assert provider._akshare is not None
    assert provider._akshare.enabled is True
```

**Step 2: Run to confirm RED**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_market_data.py::test_akshare_activated_by_config -v 2>&1 | tail -10
```
Expected: `AttributeError: 'MarketDataProvider' object has no attribute '_akshare'`

**Step 3: Update `src/market_data.py` `__init__`**

In `src/market_data.py`, add the import at the top (line ~10):
```python
from src.providers import PolygonProvider, TradierProvider, AkshareProvider
```

In `__init__` method, after the Tradier block (around line 50), add:
```python
        # AKShare — free, no API key; enabled by default
        akshare_cfg = ds_config.get("akshare", {})
        akshare_enabled = akshare_cfg.get("enabled", True)
        self._akshare = AkshareProvider(enabled=akshare_enabled)
```

**Step 4: Update `config.yaml`**

In the `data_sources:` section, add:
```yaml
  akshare:
    enabled: true      # free, no api_key needed
```

**Step 5: Run to confirm GREEN**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_market_data.py::test_akshare_activated_by_config tests/test_market_data.py::test_akshare_disabled_by_config tests/test_market_data.py::test_akshare_enabled_by_default -v
```
Expected: 3 PASSED

**Step 6: Commit**

```bash
git add src/market_data.py config.yaml tests/test_market_data.py
git commit -m "feat: wire AkshareProvider into MarketDataProvider init"
```

---

### Task 6: Update get_price_data routing (CN/HK/US chains)

**Files:**
- Modify: `src/market_data.py` (the `get_price_data` method, ~lines 144-156)
- Modify: `tests/test_market_data.py`

**Step 1: Write failing routing tests**

Append to `tests/test_market_data.py`:

```python
def test_cn_price_uses_akshare_before_yfinance():
    """For CN tickers, AKShare is tried before yfinance."""
    from src.market_data import MarketDataProvider
    from unittest.mock import MagicMock, patch
    import pandas as pd

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
    """If AKShare returns empty for CN, yfinance is used."""
    from src.market_data import MarketDataProvider
    from unittest.mock import MagicMock, patch
    import pandas as pd

    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": True}}})
    provider.ibkr = None
    provider._akshare.get_price_data = MagicMock(return_value=pd.DataFrame())

    mock_df = pd.DataFrame({"Close": [100.0]})
    with patch.object(provider, "_yf_price_data", return_value=mock_df) as mock_yf:
        result = provider.get_price_data("600519.SS")

    mock_yf.assert_called_once()
    assert not result.empty


def test_hk_price_uses_akshare_before_yfinance():
    """For HK tickers, AKShare is tried before yfinance."""
    from src.market_data import MarketDataProvider
    from unittest.mock import MagicMock, patch
    import pandas as pd

    mock_df = pd.DataFrame({"Open": [300.0], "Close": [301.0]})
    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": True}}})
    provider.ibkr = None
    provider._akshare.get_price_data = MagicMock(return_value=mock_df)

    with patch.object(provider, "_yf_price_data") as mock_yf:
        result = provider.get_price_data("0700.HK")

    provider._akshare.get_price_data.assert_called_once()
    mock_yf.assert_not_called()


def test_us_price_akshare_after_polygon():
    """For US tickers, AKShare is tried after Polygon, before yfinance."""
    from src.market_data import MarketDataProvider
    from unittest.mock import MagicMock, patch
    import pandas as pd

    mock_df = pd.DataFrame({"Open": [185.0], "Close": [186.0]})
    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": True}}})
    provider.ibkr = None
    provider._polygon = MagicMock()
    provider._polygon.get_price_data.return_value = pd.DataFrame()  # Polygon fails
    provider._akshare.get_price_data = MagicMock(return_value=mock_df)

    with patch.object(provider, "_yf_price_data") as mock_yf:
        result = provider.get_price_data("AAPL")

    provider._akshare.get_price_data.assert_called_once()
    mock_yf.assert_not_called()
```

**Step 2: Run to confirm RED**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_market_data.py::test_cn_price_uses_akshare_before_yfinance -v 2>&1 | tail -10
```

**Step 3: Update `get_price_data` in `src/market_data.py`**

Current code (lines ~144-156):
```python
def get_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
    """Fetch OHLCV. Routing: IBKR → Polygon (US only) → yfinance."""
    if self.ibkr:
        try:
            return self._ibkr_price_data(ticker, period)
        except Exception as e:
            logger.warning(f"IBKR price fetch failed for {ticker}, falling back: {e}")
    if self._polygon and classify_market(ticker) == "US":
        df = self._polygon.get_price_data(ticker, period)
        if not df.empty:
            logger.debug(f"{ticker}: price data via Polygon")
            return df
    return self._yf_price_data(ticker, period)
```

Replace with:
```python
def get_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
    """Fetch OHLCV. Routing: IBKR → Polygon (US) → AKShare (CN/HK/US) → yfinance."""
    if self.ibkr:
        try:
            return self._ibkr_price_data(ticker, period)
        except Exception as e:
            logger.warning(f"IBKR price fetch failed for {ticker}, falling back: {e}")
    market = classify_market(ticker)
    if self._polygon and market == "US":
        df = self._polygon.get_price_data(ticker, period)
        if not df.empty:
            logger.debug(f"{ticker}: price data via Polygon")
            return df
    if self._akshare:
        df = self._akshare.get_price_data(ticker, period)
        if not df.empty:
            logger.debug(f"{ticker}: price data via AKShare")
            return df
    return self._yf_price_data(ticker, period)
```

**Step 4: Run to confirm GREEN**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_market_data.py::test_cn_price_uses_akshare_before_yfinance tests/test_market_data.py::test_cn_price_falls_back_to_yfinance_when_akshare_empty tests/test_market_data.py::test_hk_price_uses_akshare_before_yfinance tests/test_market_data.py::test_us_price_akshare_after_polygon -v
```
Expected: 4 PASSED

**Step 5: Run full test suite to check no regressions**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_market_data.py -v 2>&1 | tail -20
```

**Step 6: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: insert AKShare into get_price_data fallback chain"
```

---

### Task 7: Update get_fundamentals and get_options_chain routing

**Files:**
- Modify: `src/market_data.py`
- Modify: `tests/test_market_data.py`

**Step 1: Write failing tests**

Append to `tests/test_market_data.py`:

```python
# ── fundamentals routing ──────────────────────────────────────────────────────

def test_cn_fundamentals_uses_akshare_before_yfinance():
    from src.market_data import MarketDataProvider
    from unittest.mock import MagicMock, patch

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


def test_cn_fundamentals_fallback_to_yfinance_when_akshare_none():
    from src.market_data import MarketDataProvider
    from unittest.mock import MagicMock, patch

    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": True}}})
    provider._akshare.get_fundamentals = MagicMock(return_value=None)

    with patch.object(provider, "_yf_fundamentals", return_value={"company_name": "Moutai"}) as mock_yf:
        result = provider.get_fundamentals("600519.SS")

    mock_yf.assert_called_once()
    assert result["company_name"] == "Moutai"


# ── options chain routing ─────────────────────────────────────────────────────

def test_cn_options_uses_akshare():
    from src.market_data import MarketDataProvider
    from unittest.mock import MagicMock, patch
    import pandas as pd

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
    """US options: AKShare tried after Tradier fails, before yfinance."""
    from src.market_data import MarketDataProvider
    from unittest.mock import MagicMock, patch
    import pandas as pd

    mock_opts = pd.DataFrame({"strike": [170.0], "bid": [2.5], "dte": [50], "expiration": ["2024-04-19"]})
    provider = MarketDataProvider(config={"data_sources": {"akshare": {"enabled": True}}})
    provider.ibkr = None
    provider._tradier = MagicMock()
    provider._tradier.get_options_chain.return_value = pd.DataFrame()  # Tradier fails
    provider._akshare.get_options_chain = MagicMock(return_value=mock_opts)

    with patch.object(provider, "_yf_options_chain") as mock_yf:
        result = provider.get_options_chain("AAPL")

    provider._akshare.get_options_chain.assert_called_once()
    mock_yf.assert_not_called()
    assert not result.empty
```

**Step 2: Run to confirm RED**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_market_data.py::test_cn_fundamentals_uses_akshare_before_yfinance tests/test_market_data.py::test_cn_options_uses_akshare -v 2>&1 | tail -15
```

**Step 3: Update `get_fundamentals` in `src/market_data.py`**

Current (lines ~661-673):
```python
def get_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
    """Fetch fundamentals. Routing: Polygon → yfinance (US); yfinance (HK/CN)."""
    if self._polygon and classify_market(ticker) == "US":
        poly = self._polygon.get_fundamentals(ticker)
        if poly is not None:
            yf = self._yf_fundamentals(ticker) or {}
            for key, val in poly.items():
                if val is None and yf.get(key) is not None:
                    poly[key] = yf[key]
            return poly
    return self._yf_fundamentals(ticker)
```

Replace with:
```python
def get_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
    """Fetch fundamentals.
    US: Polygon+yfinance merge → AKShare fallback → yfinance.
    CN/HK: AKShare → yfinance.
    """
    market = classify_market(ticker)
    if self._polygon and market == "US":
        poly = self._polygon.get_fundamentals(ticker)
        if poly is not None:
            yf_data = self._yf_fundamentals(ticker) or {}
            for key, val in poly.items():
                if val is None and yf_data.get(key) is not None:
                    poly[key] = yf_data[key]
            return poly
    if self._akshare and market in ("CN", "HK"):
        result = self._akshare.get_fundamentals(ticker)
        if result is not None:
            logger.debug(f"{ticker}: fundamentals via AKShare")
            return result
    return self._yf_fundamentals(ticker)
```

**Step 4: Update `get_options_chain` in `src/market_data.py`**

Current (lines ~409-423):
```python
def get_options_chain(self, ticker: str, dte_min: int = 45, dte_max: int = 60) -> pd.DataFrame:
    """Fetch put options. Routing: IBKR → Tradier (US only) → yfinance."""
    if self.should_skip_options(ticker):
        return pd.DataFrame()
    if self.ibkr:
        try:
            return self._ibkr_options_chain(ticker, dte_min, dte_max)
        except Exception as e:
            logger.warning(f"IBKR options chain failed for {ticker}, falling back: {e}")
    if self._tradier and classify_market(ticker) == "US":
        df = self._tradier.get_options_chain(ticker, dte_min=dte_min, dte_max=dte_max)
        if not df.empty:
            logger.debug(f"{ticker}: options via Tradier")
            return df
    return self._yf_options_chain(ticker, dte_min, dte_max)
```

Replace with:
```python
def get_options_chain(self, ticker: str, dte_min: int = 45, dte_max: int = 60) -> pd.DataFrame:
    """Fetch put options. Routing: IBKR → Tradier (US) → AKShare → yfinance."""
    if self.should_skip_options(ticker):
        return pd.DataFrame()
    if self.ibkr:
        try:
            return self._ibkr_options_chain(ticker, dte_min, dte_max)
        except Exception as e:
            logger.warning(f"IBKR options chain failed for {ticker}, falling back: {e}")
    market = classify_market(ticker)
    if self._tradier and market == "US":
        df = self._tradier.get_options_chain(ticker, dte_min=dte_min, dte_max=dte_max)
        if not df.empty:
            logger.debug(f"{ticker}: options via Tradier")
            return df
    if self._akshare:
        df = self._akshare.get_options_chain(ticker, dte_min=dte_min, dte_max=dte_max)
        if not df.empty:
            logger.debug(f"{ticker}: options via AKShare")
            return df
    return self._yf_options_chain(ticker, dte_min, dte_max)
```

**Note:** `should_skip_options` currently skips CN/HK entirely. CN ETF options ARE supported via AKShare, so check if this needs updating. Read `should_skip_options` first:

```bash
cd /Users/q/code/ai-monitor && grep -n "should_skip_options" src/market_data.py
```

If it returns True for all CN tickers, update it to allow CN ETF option tickers through:
```python
def should_skip_options(self, ticker: str) -> bool:
    market = classify_market(ticker)
    if market == "HK":
        return True
    if market == "CN":
        # Allow ETF option tickers through (handled by AKShare)
        symbol = ticker.replace(".SS", "").replace(".SZ", "")
        from src.providers.akshare import _CN_ETF_OPTION_MAP
        return symbol not in _CN_ETF_OPTION_MAP
    return False
```

**Step 5: Run to confirm GREEN**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/test_market_data.py::test_cn_fundamentals_uses_akshare_before_yfinance tests/test_market_data.py::test_cn_fundamentals_fallback_to_yfinance_when_akshare_none tests/test_market_data.py::test_cn_options_uses_akshare tests/test_market_data.py::test_us_options_akshare_after_tradier -v
```
Expected: 4 PASSED

**Step 6: Run full test suite**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/ -v 2>&1 | tail -30
```
Expected: all existing tests still pass + new ones pass.

**Step 7: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: wire AKShare into get_fundamentals and get_options_chain routing"
```

---

### Task 8: Final verification + spec update

**Step 1: Run all tests**

```bash
cd /Users/q/code/ai-monitor && python -m pytest tests/ -v 2>&1 | tail -30
```
Expected: 100% PASS

**Step 2: Update `docs/specs/data_pipeline.md`**

In the `Data Source Fallback Chain` table, update:
- `get_price_data`: add AKShare column for CN/HK/US
- `get_fundamentals`: add AKShare for CN/HK
- `get_options_chain`: add AKShare

In the `Provider Architecture` section, add `AkshareProvider` entry.

In the `Priority Chains` table, update all three rows.

In `config.yaml` section, show the new `akshare` block.

**Step 3: Delete the design doc (now superseded by spec)**

```bash
git rm docs/plans/2026-03-11-akshare-provider-design.md
```

**Step 4: Final commit**

```bash
git add docs/specs/data_pipeline.md
git commit -m "docs: update data_pipeline spec with AKShare provider routing"
```
