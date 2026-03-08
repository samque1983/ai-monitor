# Phase 4 Multi-Datasource Failover Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Polygon (price + fundamentals), Tradier (options), and IBKR REST API (price + options, cloud OAuth) as providers behind IBKR TWS/yfinance, with market-aware routing in `MarketDataProvider`.

**Architecture:** Add `PolygonProvider`, `TradierProvider`, and `IBKRRestProvider` as standalone classes in `src/market_data.py`. Routing chains: price → IBKR TWS → IBKR REST → Polygon (US) → yfinance; options → IBKR TWS → IBKR REST → Tradier → yfinance; fundamentals → Polygon+yfinance merge → yfinance. IBKR REST uses OAuth 2.0 (access_token + refresh_token via env vars, auto-refresh before expiry).

**Tech Stack:** Python `requests`, `time.sleep` (Polygon rate limit), env vars `POLYGON_API_KEY` / `TRADIER_API_KEY` / `IBKR_CLIENT_ID` / `IBKR_ACCESS_TOKEN` / `IBKR_REFRESH_TOKEN`.

**Implementation order (P1 first):** Task 1 Polygon price → Task 2 Polygon fundamentals → Task 3 Tradier options → Task 4 IBKR REST API → Task 5 routing wiring → Task 6 config+spec.

> IBKR REST API requires registering at developer.ibkr.com (1-3 day approval). Tasks 1-3 can be done while waiting for approval. Task 4 (IBKRRestProvider) can be skipped and added later once access is granted.

---

### Task 1: PolygonProvider — price data (OHLCV)

**Files:**
- Modify: `src/market_data.py` (add `PolygonProvider` class before `MarketDataProvider`)
- Test: `tests/test_market_data.py`

**Background:**
- Polygon free tier: `GET https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}?adjusted=true&sort=asc&apiKey={key}`
- Response: `{"results": [{"t": epoch_ms, "o": float, "h": float, "l": float, "c": float, "v": float}, ...]}`
- Rate limit: 5 req/min on free tier → enforce 250ms sleep after each call
- Period mapping (same as existing `_PERIOD_MAP`): "5d"→5 days, "1mo"→30, "3mo"→90, "6mo"→180, "1y"→365, "2y"→730

**Step 1: Write the failing tests**

Add to `tests/test_market_data.py`:

```python
from unittest.mock import patch, MagicMock
import pandas as pd
from datetime import date, timedelta


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
    from src.market_data import PolygonProvider
    provider = PolygonProvider(api_key="test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _polygon_aggs_response(5)

    with patch("src.market_data.requests.get", return_value=mock_resp):
        with patch("src.market_data.time.sleep"):  # skip rate-limit sleep in tests
            df = provider.get_price_data("AAPL", "5d")

    assert not df.empty
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 5


def test_polygon_provider_returns_empty_on_http_error():
    from src.market_data import PolygonProvider
    provider = PolygonProvider(api_key="test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.json.return_value = {"status": "ERROR", "error": "Forbidden"}

    with patch("src.market_data.requests.get", return_value=mock_resp):
        with patch("src.market_data.time.sleep"):
            df = provider.get_price_data("AAPL", "1y")

    assert df.empty


def test_polygon_provider_returns_empty_on_exception():
    from src.market_data import PolygonProvider
    provider = PolygonProvider(api_key="test-key")

    with patch("src.market_data.requests.get", side_effect=Exception("network error")):
        with patch("src.market_data.time.sleep"):
            df = provider.get_price_data("AAPL", "1y")

    assert df.empty
```

**Step 2: Run tests to confirm RED**

```bash
python3 -m pytest tests/test_market_data.py::test_polygon_provider_get_price_data_returns_dataframe tests/test_market_data.py::test_polygon_provider_returns_empty_on_http_error tests/test_market_data.py::test_polygon_provider_returns_empty_on_exception -v
```
Expected: FAIL — `ImportError: cannot import name 'PolygonProvider'`

**Step 3: Add `PolygonProvider` class to `src/market_data.py`**

Add `import requests` and `import time` at the top of the file (after existing imports).

Add this class before the `MarketDataProvider` class:

```python
class PolygonProvider:
    """Polygon.io cloud API provider for US price and fundamental data."""

    BASE_URL = "https://api.polygon.io"
    _PERIOD_DAYS = {
        "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
        "1y": 365, "2y": 730, "5y": 1825, "10y": 3650,
    }

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _get(self, path: str, params: dict = None) -> dict:
        """Make a rate-limited GET request. Returns parsed JSON or raises."""
        url = f"{self.BASE_URL}{path}"
        p = dict(params or {})
        p["apiKey"] = self.api_key
        resp = requests.get(url, params=p, timeout=15)
        time.sleep(0.25)  # 5 req/min free tier
        resp.raise_for_status()
        return resp.json()

    def get_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Fetch daily adjusted OHLCV. Returns empty DataFrame on any failure."""
        try:
            days = self._PERIOD_DAYS.get(period, 365)
            to_date = date.today()
            from_date = to_date - timedelta(days=days)
            data = self._get(
                f"/v2/aggs/ticker/{ticker}/range/1/day/{from_date}/{to_date}",
                {"adjusted": "true", "sort": "asc", "limit": 5000},
            )
            results = data.get("results")
            if not results:
                return pd.DataFrame()
            rows = []
            for bar in results:
                rows.append({
                    "Date": pd.to_datetime(bar["t"], unit="ms", utc=True).normalize(),
                    "Open": bar["o"], "High": bar["h"],
                    "Low": bar["l"], "Close": bar["c"], "Volume": bar["v"],
                })
            df = pd.DataFrame(rows).set_index("Date")
            df.index = df.index.tz_localize(None)
            return df
        except Exception as e:
            logger.warning(f"Polygon price data failed for {ticker}: {e}")
            return pd.DataFrame()
```

**Step 4: Run tests to confirm GREEN**

```bash
python3 -m pytest tests/test_market_data.py::test_polygon_provider_get_price_data_returns_dataframe tests/test_market_data.py::test_polygon_provider_returns_empty_on_http_error tests/test_market_data.py::test_polygon_provider_returns_empty_on_exception -v
```
Expected: 3 PASS

**Step 5: Run full suite to confirm no regressions**

```bash
python3 -m pytest tests/ -q
```
Expected: all pass

**Step 6: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: add PolygonProvider with get_price_data (rate-limited)"
```

---

### Task 2: PolygonProvider — fundamentals

**Files:**
- Modify: `src/market_data.py` (add `get_fundamentals` method to `PolygonProvider`)
- Test: `tests/test_market_data.py`

**Background:**
- Polygon `/v3/reference/tickers/{ticker}` → `results.name`, `results.sic_description` (industry proxy)
- Polygon `/vX/reference/financials?ticker={ticker}&timeframe=annual&limit=1` → financial statements
  - `results[0].financials.income_statement.net_income.value`
  - `results[0].financials.balance_sheet.equity.value`
  - `results[0].financials.cash_flow_statement.net_cash_flow_from_operating_activities.value`
  - `results[0].financials.cash_flow_statement.capital_expenditure.value` (may be negative)
- Computed fields:
  - `roe` = (net_income / equity) * 100 if equity > 0 else None
  - `free_cash_flow` = operating_cf + capex (capex is usually negative in data)
- Fields Polygon cannot provide (return None, yfinance will fill): `payout_ratio`, `debt_to_equity`, `dividend_yield`

**Step 1: Write the failing tests**

Add to `tests/test_market_data.py`:

```python
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
    from src.market_data import PolygonProvider
    provider = PolygonProvider(api_key="test-key")

    responses = {
        "/v3/reference/tickers/AAPL": _polygon_ticker_response(),
        "/vX/reference/financials": _polygon_financials_response(),
    }

    def fake_get(url, params=None, timeout=15):
        mock = MagicMock()
        mock.status_code = 200
        for path, resp in responses.items():
            if path in url:
                mock.json.return_value = resp
                return mock
        mock.json.return_value = {}
        return mock

    with patch("src.market_data.requests.get", side_effect=fake_get):
        with patch("src.market_data.time.sleep"):
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
    from src.market_data import PolygonProvider
    provider = PolygonProvider(api_key="test-key")

    with patch("src.market_data.requests.get", side_effect=Exception("network error")):
        with patch("src.market_data.time.sleep"):
            result = provider.get_fundamentals("AAPL")

    assert result is None
```

**Step 2: Run tests to confirm RED**

```bash
python3 -m pytest tests/test_market_data.py::test_polygon_provider_get_fundamentals_returns_dict tests/test_market_data.py::test_polygon_provider_get_fundamentals_returns_none_on_failure -v
```
Expected: FAIL — `AttributeError: 'PolygonProvider' has no attribute 'get_fundamentals'`

**Step 3: Add `get_fundamentals` to `PolygonProvider`**

Add this method inside `PolygonProvider` (after `get_price_data`):

```python
def get_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
    """Fetch fundamentals from Polygon. Returns partial dict; None fields fall back to yfinance."""
    try:
        # Basic info: name, industry
        ticker_data = self._get(f"/v3/reference/tickers/{ticker}")
        results = ticker_data.get("results", {})
        company_name = results.get("name") or ticker
        industry = results.get("sic_description")

        # Financial statements: ROE + FCF
        roe = None
        free_cash_flow = None
        try:
            fin_data = self._get(
                "/vX/reference/financials",
                {"ticker": ticker, "timeframe": "annual", "limit": 1},
            )
            fin_results = fin_data.get("results", [])
            if fin_results:
                fin = fin_results[0]["financials"]
                net_income = fin.get("income_statement", {}).get("net_income", {}).get("value")
                equity = fin.get("balance_sheet", {}).get("equity", {}).get("value")
                op_cf = fin.get("cash_flow_statement", {}).get(
                    "net_cash_flow_from_operating_activities", {}
                ).get("value")
                capex = fin.get("cash_flow_statement", {}).get(
                    "capital_expenditure", {}
                ).get("value")

                if net_income is not None and equity and equity > 0:
                    roe = (net_income / equity) * 100
                if op_cf is not None and capex is not None:
                    free_cash_flow = op_cf + capex  # capex is typically negative
        except Exception as e:
            logger.debug(f"Polygon financials fetch failed for {ticker}: {e}")

        return {
            "company_name": company_name,
            "industry": industry,
            "sector": None,          # Polygon doesn't map SIC to sector
            "roe": roe,
            "free_cash_flow": free_cash_flow,
            "payout_ratio": None,    # not available from Polygon free tier
            "debt_to_equity": None,  # not available from Polygon free tier
            "dividend_yield": None,  # not available from Polygon free tier
        }
    except Exception as e:
        logger.warning(f"Polygon fundamentals failed for {ticker}: {e}")
        return None
```

**Step 4: Run tests to confirm GREEN**

```bash
python3 -m pytest tests/test_market_data.py::test_polygon_provider_get_fundamentals_returns_dict tests/test_market_data.py::test_polygon_provider_get_fundamentals_returns_none_on_failure -v
```
Expected: 2 PASS

**Step 5: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: add PolygonProvider.get_fundamentals (ROE + FCF from annual statements)"
```

---

### Task 3: TradierProvider — options chain

**Files:**
- Modify: `src/market_data.py` (add `TradierProvider` class)
- Test: `tests/test_market_data.py`

**Background:**
- Tradier sandbox: `https://sandbox.tradier.com/v1/`
- Tradier production: `https://api.tradier.com/v1/` (use when key is set)
- Auth: `Authorization: Bearer {api_key}`, `Accept: application/json`
- Get expirations: `GET /v1/markets/options/expirations?symbol={ticker}`
  - Response: `{"expirations": {"date": ["2026-03-21", ...]}}`
- Get chain for one expiry: `GET /v1/markets/options/chains?symbol={ticker}&expiration={date}&greeks=false`
  - Response: `{"options": {"option": [{symbol, strike, option_type, bid, ask, ...}, ...]}}`
- Filter: `option_type == "put"`, `dte_min <= dte <= dte_max`
- Output DataFrame columns: `strike`, `bid`, `dte`, `expiration` (matching existing yfinance format)

**Step 1: Write the failing tests**

Add to `tests/test_market_data.py`:

```python
def _tradier_expirations_response():
    from datetime import date, timedelta
    future = date.today() + timedelta(days=60)
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
    provider = TradierProvider(api_key="test-key")

    from datetime import date, timedelta
    future = date.today() + timedelta(days=60)
    future_str = future.strftime("%Y-%m-%d")

    expirations_resp = MagicMock()
    expirations_resp.status_code = 200
    expirations_resp.json.return_value = _tradier_expirations_response()

    chain_resp = MagicMock()
    chain_resp.status_code = 200
    chain_resp.json.return_value = _tradier_chain_response(future_str)

    call_count = [0]
    def fake_get(url, *args, **kwargs):
        call_count[0] += 1
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
    from datetime import date, timedelta
    provider = TradierProvider(api_key="test-key")

    # Expiration outside dte_min/dte_max
    near_future = date.today() + timedelta(days=10)
    resp = MagicMock()
    resp.status_code = 200
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
```

**Step 2: Run tests to confirm RED**

```bash
python3 -m pytest tests/test_market_data.py::test_tradier_provider_returns_put_options_dataframe tests/test_market_data.py::test_tradier_provider_returns_empty_when_no_expirations_in_range tests/test_market_data.py::test_tradier_provider_returns_empty_on_exception -v
```
Expected: FAIL — `ImportError: cannot import name 'TradierProvider'`

**Step 3: Add `TradierProvider` class to `src/market_data.py`**

Add after `PolygonProvider` (before `MarketDataProvider`):

```python
class TradierProvider:
    """Tradier cloud API provider for US options chains (15-min delayed on sandbox)."""

    SANDBOX_URL = "https://sandbox.tradier.com/v1"
    PROD_URL = "https://api.tradier.com/v1"

    def __init__(self, api_key: str, sandbox: bool = True):
        self.api_key = api_key
        self.base_url = self.SANDBOX_URL if sandbox else self.PROD_URL

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        resp = requests.get(url, params=params or {}, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_options_chain(self, ticker: str, dte_min: int = 45, dte_max: int = 60) -> pd.DataFrame:
        """Fetch put options filtered by DTE. Returns empty DataFrame on failure."""
        try:
            exp_data = self._get("/markets/options/expirations", {"symbol": ticker})
            expirations = (exp_data.get("expirations") or {}).get("date") or []
            if not expirations:
                return pd.DataFrame()

            today = date.today()
            valid = []
            for exp_str in expirations:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                dte = (exp_date - today).days
                if dte_min <= dte <= dte_max:
                    valid.append((exp_str, exp_date, dte))

            if not valid:
                return pd.DataFrame()

            rows = []
            for exp_str, exp_date, dte in valid:
                chain_data = self._get(
                    "/markets/options/chains",
                    {"symbol": ticker, "expiration": exp_str, "greeks": "false"},
                )
                options = (chain_data.get("options") or {}).get("option") or []
                for opt in options:
                    if opt.get("option_type") != "put":
                        continue
                    bid = float(opt.get("bid") or 0.0)
                    rows.append({
                        "strike": float(opt["strike"]),
                        "bid": bid,
                        "dte": dte,
                        "expiration": exp_date,
                    })

            if not rows:
                return pd.DataFrame()
            return pd.DataFrame(rows)

        except Exception as e:
            logger.warning(f"Tradier options chain failed for {ticker}: {e}")
            return pd.DataFrame()
```

**Step 4: Run tests to confirm GREEN**

```bash
python3 -m pytest tests/test_market_data.py::test_tradier_provider_returns_put_options_dataframe tests/test_market_data.py::test_tradier_provider_returns_empty_when_no_expirations_in_range tests/test_market_data.py::test_tradier_provider_returns_empty_on_exception -v
```
Expected: 3 PASS

**Step 5: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: add TradierProvider for US put options chains"
```

---

### Task 4: Wire providers into MarketDataProvider routing

**Files:**
- Modify: `src/market_data.py` (`MarketDataProvider.__init__`, `get_price_data`, `get_options_chain`, `get_fundamentals`)
- Test: `tests/test_market_data.py`

**Routing logic:**
```
get_price_data:
  US market  → IBKR (if connected) → Polygon (if api_key) → yfinance
  HK/CN      → yfinance

get_options_chain:
  US market  → IBKR (if connected) → Tradier (if api_key) → yfinance
  HK/CN      → empty DataFrame (existing behavior)

get_fundamentals:
  US market  → Polygon (if api_key) → yfinance; merge: yfinance fills None fields
  HK/CN      → yfinance
```

**Merging fundamentals:** When Polygon returns a partial dict (some None fields), call yfinance and fill in the None fields from yfinance. This ensures `payout_ratio`, `dividend_yield`, `debt_to_equity` (not in Polygon free tier) still get populated.

**Step 1: Write the failing tests**

Add to `tests/test_market_data.py`:

```python
def test_market_data_provider_uses_polygon_for_us_price_when_no_ibkr():
    """When IBKR is not connected and Polygon key is set, Polygon is used for US tickers."""
    import os
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

    from datetime import date, timedelta
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
```

**Step 2: Run tests to confirm RED**

```bash
python3 -m pytest tests/test_market_data.py::test_market_data_provider_uses_polygon_for_us_price_when_no_ibkr tests/test_market_data.py::test_market_data_provider_falls_back_to_yfinance_when_polygon_empty tests/test_market_data.py::test_market_data_provider_skips_polygon_for_hk_ticker tests/test_market_data.py::test_market_data_provider_uses_tradier_for_options_fallback tests/test_market_data.py::test_market_data_provider_merges_polygon_and_yfinance_fundamentals -v
```
Expected: FAIL — `AttributeError: '_polygon'` / missing routing logic

**Step 3: Update `MarketDataProvider`**

In `MarketDataProvider.__init__`, add provider initialization after `self._yf_session = ...`:

```python
# Initialize cloud providers from config
ds_config = (config or {}).get("data_sources", {})

polygon_key = (
    ds_config.get("polygon", {}).get("api_key")
    or os.environ.get("POLYGON_API_KEY", "")
)
self._polygon: Optional[PolygonProvider] = PolygonProvider(polygon_key) if polygon_key else None

tradier_key = (
    ds_config.get("tradier", {}).get("api_key")
    or os.environ.get("TRADIER_API_KEY", "")
)
tradier_sandbox = ds_config.get("tradier", {}).get("sandbox", True)
self._tradier: Optional[TradierProvider] = TradierProvider(tradier_key, sandbox=tradier_sandbox) if tradier_key else None
```

Replace `get_price_data` with:

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

Replace `get_options_chain` with:

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

Extract `get_fundamentals`'s yfinance logic into `_yf_fundamentals` (rename the existing method body), then replace `get_fundamentals` with:

```python
def _yf_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
    """Fetch fundamentals from yfinance (existing logic, renamed)."""
    # ... (exact same body as existing get_fundamentals)

def get_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
    """Fetch fundamentals. Routing: Polygon → yfinance (US); yfinance (HK/CN).
    Polygon result has None for fields it can't provide; yfinance fills them in."""
    if self._polygon and classify_market(ticker) == "US":
        poly = self._polygon.get_fundamentals(ticker)
        if poly is not None:
            # Fill None fields from yfinance
            yf = self._yf_fundamentals(ticker) or {}
            for key, val in poly.items():
                if val is None and yf.get(key) is not None:
                    poly[key] = yf[key]
            return poly
    return self._yf_fundamentals(ticker)
```

**Step 4: Run the new routing tests**

```bash
python3 -m pytest tests/test_market_data.py::test_market_data_provider_uses_polygon_for_us_price_when_no_ibkr tests/test_market_data.py::test_market_data_provider_falls_back_to_yfinance_when_polygon_empty tests/test_market_data.py::test_market_data_provider_skips_polygon_for_hk_ticker tests/test_market_data.py::test_market_data_provider_uses_tradier_for_options_fallback tests/test_market_data.py::test_market_data_provider_merges_polygon_and_yfinance_fundamentals -v
```
Expected: 5 PASS

**Step 5: Run full suite**

```bash
python3 -m pytest tests/ -q
```
Expected: all pass

**Step 6: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: wire Polygon and Tradier into MarketDataProvider routing"
```

---

### Task 5: Config update + spec sync

**Files:**
- Modify: `config.yaml`
- Modify: `docs/specs/data_pipeline.md`

**Step 1: Add `data_sources` block to `config.yaml`**

Find the `data:` section and add below it:

```yaml
data_sources:
  polygon:
    enabled: true
    api_key: ""        # set via env: POLYGON_API_KEY
  tradier:
    enabled: false     # set to true after getting API key
    api_key: ""        # set via env: TRADIER_API_KEY
    sandbox: true      # true=sandbox (delayed), false=production
```

**Step 2: Update `docs/specs/data_pipeline.md`**

Add a new section describing the multi-datasource routing. Open the file and add after the existing `MarketDataProvider` section:

```markdown
## Multi-Datasource Routing (Phase 4)

### Providers

**PolygonProvider** (`src/market_data.py`)
- `get_price_data(ticker, period) → pd.DataFrame` — daily adjusted OHLCV via `/v2/aggs`
- `get_fundamentals(ticker) → Optional[Dict]` — name/industry via `/v3/reference/tickers`, ROE+FCF via `/vX/reference/financials`
- Rate limit: 250ms sleep after each request (5 req/min free tier)
- Activated via: `POLYGON_API_KEY` env var or `config.data_sources.polygon.api_key`

**TradierProvider** (`src/market_data.py`)
- `get_options_chain(ticker, dte_min, dte_max) → pd.DataFrame` — put options via `/v1/markets/options/chains`
- 15-min delayed data (sandbox); suitable for end-of-day scanning
- Activated via: `TRADIER_API_KEY` env var or `config.data_sources.tradier.api_key`

### Priority Chains

| Method | US Market | HK/CN Market |
|--------|-----------|--------------|
| `get_price_data` | IBKR → Polygon → yfinance | yfinance |
| `get_options_chain` | IBKR → Tradier → yfinance | skip |
| `get_fundamentals` | Polygon+yfinance merge → yfinance fallback | yfinance |

**Fundamentals merge:** Polygon provides `company_name`, `industry`, `roe`, `free_cash_flow`. yfinance fills in `sector`, `payout_ratio`, `debt_to_equity`, `dividend_yield`.
```

**Step 3: Verify config loads without error**

```bash
python3 -c "from src.config import load_config; c = load_config('config.yaml'); print(c.get('data_sources', {}))"
```
Expected: `{'polygon': {'enabled': True, 'api_key': ''}, 'tradier': {'enabled': False, 'api_key': '', 'sandbox': True}}`

**Step 4: Run full test suite one final time**

```bash
python3 -m pytest tests/ -q
```
Expected: all pass

**Step 5: Commit**

```bash
git add config.yaml docs/specs/data_pipeline.md
git commit -m "chore: add data_sources config block and update data_pipeline spec for Phase 4"
```

---

### Task 6: IBKRRestProvider — price + options (P2，需先在 developer.ibkr.com 申请 API access)

> **前置条件：** 已在 `https://developer.ibkr.com` 注册并获得 `client_id`、`access_token`、`refresh_token`。Tasks 1-5 可在等待审批期间先完成。

**Files:**
- Modify: `src/market_data.py` (add `IBKRRestProvider` class, update `MarketDataProvider` routing)
- Test: `tests/test_market_data.py`

**Background:**
- Base URL: `https://api.ibkr.com/v1/api/`
- Auth: `Authorization: Bearer {access_token}`
- Token refresh: `POST https://api.ibkr.com/v1/api/oauth/token` with `grant_type=refresh_token`
- Token expiry: check `expires_at` (stored in provider), refresh if within 60s of expiry
- Key endpoints:
  - Resolve conid: `GET /iserver/secdef/search?symbol={ticker}` → `results[0].conid`
  - Price history: `GET /iserver/marketdata/history?conid={conid}&period={period}&bar=1d&outsideRth=false`
    - Response: `{"data": [{"t": epoch_ms, "o": float, "h": float, "l": float, "c": float, "v": float}, ...]}`
  - Option strikes: `GET /iserver/secdef/strikes?sectype=OPT&symbol={ticker}`
  - Option chain: `GET /iserver/secdef/info?symbol={ticker}&sectype=OPT&right=P&expiration={YYYYMMDD}&strike={strike}`
  - Option market data: `GET /iserver/marketdata/snapshot?conids={conid}&fields=84,86` (84=bid, 86=ask)
- Period mapping: same as `_PERIOD_MAP` ("1y" → "1Y", "6mo" → "6M", etc.)

**Step 1: Write the failing tests**

Add to `tests/test_market_data.py`:

```python
def _ibkr_rest_search_response():
    return [{"conid": 265598, "symbol": "AAPL", "companyName": "APPLE INC"}]


def _ibkr_rest_history_response(n_bars=5):
    import time as _time
    from datetime import date, timedelta
    today = date.today()
    data = []
    for i in range(n_bars):
        d = today - timedelta(days=n_bars - i)
        epoch_ms = int(_time.mktime(d.timetuple())) * 1000
        data.append({"t": epoch_ms, "o": 100.0, "h": 105.0, "l": 99.0, "c": 102.0, "v": 1000000})
    return {"data": data}


def test_ibkr_rest_provider_get_price_data_returns_dataframe():
    from src.market_data import IBKRRestProvider
    provider = IBKRRestProvider(
        client_id="test-id",
        access_token="test-token",
        refresh_token="test-refresh",
        expires_at=9999999999.0,  # far future, no refresh needed
    )

    responses = {
        "/iserver/secdef/search": _ibkr_rest_search_response(),
        "/iserver/marketdata/history": _ibkr_rest_history_response(5),
    }

    def fake_get(url, *args, **kwargs):
        mock = MagicMock()
        mock.status_code = 200
        for path, resp in responses.items():
            if path in url:
                mock.json.return_value = resp
                return mock
        mock.json.return_value = {}
        return mock

    with patch("src.market_data.requests.get", side_effect=fake_get):
        df = provider.get_price_data("AAPL", "1y")

    assert not df.empty
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_ibkr_rest_provider_returns_empty_on_failure():
    from src.market_data import IBKRRestProvider
    provider = IBKRRestProvider(
        client_id="test-id",
        access_token="test-token",
        refresh_token="test-refresh",
        expires_at=9999999999.0,
    )

    with patch("src.market_data.requests.get", side_effect=Exception("network error")):
        df = provider.get_price_data("AAPL", "1y")

    assert df.empty


def test_ibkr_rest_provider_refreshes_token_when_expired():
    """When expires_at is in the past, a token refresh is triggered before the API call."""
    from src.market_data import IBKRRestProvider
    import time
    provider = IBKRRestProvider(
        client_id="test-id",
        access_token="old-token",
        refresh_token="test-refresh",
        expires_at=time.time() - 100,  # already expired
    )

    refresh_resp = MagicMock()
    refresh_resp.status_code = 200
    refresh_resp.json.return_value = {
        "access_token": "new-token",
        "expires_in": 3600,
    }

    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = _ibkr_rest_search_response()

    history_resp = MagicMock()
    history_resp.status_code = 200
    history_resp.json.return_value = _ibkr_rest_history_response(3)

    post_mock = MagicMock(return_value=refresh_resp)
    call_order = []

    def fake_get(url, *args, **kwargs):
        if "secdef/search" in url:
            call_order.append("search")
            return search_resp
        call_order.append("history")
        return history_resp

    with patch("src.market_data.requests.post", post_mock):
        with patch("src.market_data.requests.get", side_effect=fake_get):
            df = provider.get_price_data("AAPL", "1y")

    post_mock.assert_called_once()  # refresh was called
    assert provider.access_token == "new-token"
    assert not df.empty


def test_market_data_provider_uses_ibkr_rest_before_polygon():
    """IBKR REST API is tried before Polygon when both are configured."""
    from src.market_data import MarketDataProvider
    import time

    provider = MarketDataProvider(config={
        "data_sources": {
            "polygon": {"api_key": "fake-polygon-key"},
            "ibkr_rest": {
                "access_token": "fake-token",
                "refresh_token": "fake-refresh",
                "expires_at": time.time() + 3600,
            },
        }
    })

    ibkr_df = pd.DataFrame(
        {"Open": [100.0], "High": [105.0], "Low": [99.0], "Close": [102.0], "Volume": [1e6]},
        index=pd.to_datetime(["2026-03-07"]),
    )

    with patch.object(provider._ibkr_rest, "get_price_data", return_value=ibkr_df) as mock_ibkr:
        with patch.object(provider._polygon, "get_price_data") as mock_poly:
            df = provider.get_price_data("AAPL", "1y")

    mock_ibkr.assert_called_once()
    mock_poly.assert_not_called()
    assert not df.empty
```

**Step 2: Run tests to confirm RED**

```bash
python3 -m pytest tests/test_market_data.py::test_ibkr_rest_provider_get_price_data_returns_dataframe tests/test_market_data.py::test_ibkr_rest_provider_returns_empty_on_failure tests/test_market_data.py::test_ibkr_rest_provider_refreshes_token_when_expired tests/test_market_data.py::test_market_data_provider_uses_ibkr_rest_before_polygon -v
```
Expected: FAIL — `ImportError: cannot import name 'IBKRRestProvider'`

**Step 3: Add `IBKRRestProvider` class to `src/market_data.py`**

Add `import time as time_module` at top (or use the existing `time` import).

Add after `TradierProvider` (before `MarketDataProvider`):

```python
class IBKRRestProvider:
    """IBKR OAuth 2.0 REST API — cloud-native, no local gateway required."""

    BASE_URL = "https://api.ibkr.com/v1/api"
    TOKEN_URL = "https://api.ibkr.com/v1/api/oauth/token"
    _PERIOD_MAP = {
        "5d": "5D", "1mo": "1M", "3mo": "3M",
        "6mo": "6M", "1y": "1Y", "2y": "2Y",
    }

    def __init__(self, client_id: str, access_token: str, refresh_token: str, expires_at: float):
        self.client_id = client_id
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at  # unix timestamp

    def _refresh_if_needed(self):
        """Refresh access_token if expired or expiring within 60s."""
        import time as _time
        if _time.time() < self.expires_at - 60:
            return
        try:
            resp = requests.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data["access_token"]
            import time as _time2
            self.expires_at = _time2.time() + data.get("expires_in", 3600)
            logger.info("IBKR REST token refreshed")
        except Exception as e:
            logger.warning(f"IBKR REST token refresh failed: {e}")

    def _get(self, path: str, params: dict = None) -> dict:
        self._refresh_if_needed()
        url = f"{self.BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        resp = requests.get(url, params=params or {}, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _resolve_conid(self, ticker: str) -> Optional[int]:
        """Resolve ticker to IBKR conid."""
        results = self._get("/iserver/secdef/search", {"symbol": ticker})
        if results and isinstance(results, list):
            return results[0].get("conid")
        return None

    def get_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Fetch daily OHLCV from IBKR REST API. Returns empty DataFrame on failure."""
        try:
            conid = self._resolve_conid(ticker)
            if not conid:
                return pd.DataFrame()
            ibkr_period = self._PERIOD_MAP.get(period, "1Y")
            data = self._get(
                "/iserver/marketdata/history",
                {"conid": conid, "period": ibkr_period, "bar": "1d", "outsideRth": "false"},
            )
            bars = data.get("data") or []
            if not bars:
                return pd.DataFrame()
            rows = []
            for bar in bars:
                rows.append({
                    "Date": pd.to_datetime(bar["t"], unit="ms", utc=True).normalize(),
                    "Open": bar["o"], "High": bar["h"],
                    "Low": bar["l"], "Close": bar["c"], "Volume": bar["v"],
                })
            df = pd.DataFrame(rows).set_index("Date")
            df.index = df.index.tz_localize(None)
            logger.debug(f"{ticker}: price data via IBKR REST")
            return df
        except Exception as e:
            logger.warning(f"IBKR REST price data failed for {ticker}: {e}")
            return pd.DataFrame()

    def get_options_chain(self, ticker: str, dte_min: int = 45, dte_max: int = 60) -> pd.DataFrame:
        """Fetch put options from IBKR REST API. Returns empty DataFrame on failure."""
        try:
            strikes_data = self._get(
                "/iserver/secdef/strikes",
                {"sectype": "OPT", "symbol": ticker},
            )
            # strikes_data: {"put": [...], "call": [...], "expirations": [...]}
            expirations = strikes_data.get("expirations") or []
            put_strikes = strikes_data.get("put") or []
            if not expirations or not put_strikes:
                return pd.DataFrame()

            today = date.today()
            rows = []
            for exp_str in expirations:
                exp_date = datetime.strptime(exp_str, "%Y%m%d").date()
                dte = (exp_date - today).days
                if not (dte_min <= dte <= dte_max):
                    continue
                for strike in put_strikes:
                    info = self._get(
                        "/iserver/secdef/info",
                        {"symbol": ticker, "sectype": "OPT", "right": "P",
                         "expiration": exp_str, "strike": str(strike)},
                    )
                    conids = [r.get("conid") for r in (info if isinstance(info, list) else []) if r.get("conid")]
                    if not conids:
                        continue
                    snap = self._get(
                        "/iserver/marketdata/snapshot",
                        {"conids": str(conids[0]), "fields": "84"},  # 84=bid
                    )
                    bid = 0.0
                    if isinstance(snap, list) and snap:
                        bid = float(snap[0].get("84") or 0.0)
                    rows.append({"strike": float(strike), "bid": bid, "dte": dte, "expiration": exp_date})

            if not rows:
                return pd.DataFrame()
            return pd.DataFrame(rows)
        except Exception as e:
            logger.warning(f"IBKR REST options chain failed for {ticker}: {e}")
            return pd.DataFrame()
```

**Step 4: Update `MarketDataProvider.__init__` to initialize `IBKRRestProvider`**

In `__init__`, after the Tradier initialization block, add:

```python
import time as _time
ibkr_rest_cfg = ds_config.get("ibkr_rest", {})
ibkr_rest_token = (
    ibkr_rest_cfg.get("access_token")
    or os.environ.get("IBKR_ACCESS_TOKEN", "")
)
if ibkr_rest_token:
    self._ibkr_rest: Optional[IBKRRestProvider] = IBKRRestProvider(
        client_id=ibkr_rest_cfg.get("client_id") or os.environ.get("IBKR_CLIENT_ID", ""),
        access_token=ibkr_rest_token,
        refresh_token=ibkr_rest_cfg.get("refresh_token") or os.environ.get("IBKR_REFRESH_TOKEN", ""),
        expires_at=float(ibkr_rest_cfg.get("expires_at") or os.environ.get("IBKR_TOKEN_EXPIRES_AT") or (_time.time() + 3600)),
    )
else:
    self._ibkr_rest = None
```

**Step 5: Update routing to include IBKR REST**

In `get_price_data`, add IBKR REST between IBKR TWS and Polygon:

```python
def get_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
    if self.ibkr:
        try:
            return self._ibkr_price_data(ticker, period)
        except Exception as e:
            logger.warning(f"IBKR price fetch failed for {ticker}, falling back: {e}")
    if self._ibkr_rest:
        df = self._ibkr_rest.get_price_data(ticker, period)
        if not df.empty:
            return df
    if self._polygon and classify_market(ticker) == "US":
        df = self._polygon.get_price_data(ticker, period)
        if not df.empty:
            return df
    return self._yf_price_data(ticker, period)
```

In `get_options_chain`, add IBKR REST between IBKR TWS and Tradier:

```python
def get_options_chain(self, ticker: str, dte_min: int = 45, dte_max: int = 60) -> pd.DataFrame:
    if self.should_skip_options(ticker):
        return pd.DataFrame()
    if self.ibkr:
        try:
            return self._ibkr_options_chain(ticker, dte_min, dte_max)
        except Exception as e:
            logger.warning(f"IBKR options chain failed for {ticker}, falling back: {e}")
    if self._ibkr_rest and classify_market(ticker) == "US":
        df = self._ibkr_rest.get_options_chain(ticker, dte_min=dte_min, dte_max=dte_max)
        if not df.empty:
            return df
    if self._tradier and classify_market(ticker) == "US":
        df = self._tradier.get_options_chain(ticker, dte_min=dte_min, dte_max=dte_max)
        if not df.empty:
            return df
    return self._yf_options_chain(ticker, dte_min, dte_max)
```

**Step 6: Run all new tests**

```bash
python3 -m pytest tests/test_market_data.py::test_ibkr_rest_provider_get_price_data_returns_dataframe tests/test_market_data.py::test_ibkr_rest_provider_returns_empty_on_failure tests/test_market_data.py::test_ibkr_rest_provider_refreshes_token_when_expired tests/test_market_data.py::test_market_data_provider_uses_ibkr_rest_before_polygon -v
```
Expected: 4 PASS

**Step 7: Run full suite**

```bash
python3 -m pytest tests/ -q
```
Expected: all pass

**Step 8: Update config.yaml** — add `ibkr_rest` block to `data_sources`:

```yaml
data_sources:
  ibkr_rest:
    enabled: false
    client_id: ""        # env: IBKR_CLIENT_ID
    # access_token, refresh_token, expires_at via env vars — never commit
  polygon:
    ...
```

**Step 9: Commit**

```bash
git add src/market_data.py tests/test_market_data.py config.yaml
git commit -m "feat: add IBKRRestProvider (OAuth 2.0, cloud-native, no local gateway)"
```
