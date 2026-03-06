# IBKR Gateway Primary Data Source Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make all `MarketDataProvider` data methods use IBKR Gateway as primary source with yfinance as automatic fallback.

**Architecture:** Add `_ibkr_*` private methods mirroring each `_yf_*` method. Each public method tries IBKR first (if connected), falls back to yfinance on any error or disconnection. Dividend history and fundamentals stay yfinance-only (IBKR lacks clean APIs for these). Contract creation is centralized in `_make_contract(ticker)`.

**Tech Stack:** `ib_insync` (already in codebase), `pandas`, `unittest.mock` for tests.

---

### Task 1: `_make_contract()` helper + IBKR price data

**Files:**
- Modify: `src/market_data.py`
- Test: `tests/test_market_data.py`

IBKR needs a `Contract` object per ticker. Market classification drives exchange/currency selection:
- US: `Stock(ticker, 'SMART', 'USD')`
- HK: strip `.HK`, use `Stock(symbol, 'SEHK', 'HKD')`
- CN `.SS`: strip `.SS`, use `Stock(symbol, 'SSE', 'CNH')`
- CN `.SZ`: strip `.SZ`, use `Stock(symbol, 'SZSE', 'CNH')`

`period` string mapping (same as yfinance): `"5d"→"5 D"`, `"1mo"→"1 M"`, `"1y"→"1 Y"`, `"2y"→"2 Y"`, `"5y"→"5 Y"`, `"10y"→"10 Y"`. Default fallback: `"1 Y"`.

`reqHistoricalData` returns a list of `BarData` objects. Use `ib_insync.util.df(bars)` to convert to DataFrame. Column names are lowercase (`open, high, low, close, volume`); rename to title-case to match yfinance output (`Open, High, Low, Close, Volume`). Set `date` column as DatetimeIndex.

**Step 1: Write the failing tests**

In `tests/test_market_data.py`, add a new class `TestIBKRPriceData`:

```python
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
        provider = MarketDataProvider(ibkr_config=None)
        from ib_insync import Stock
        contract = provider._make_contract("AAPL")
        assert contract.symbol == "AAPL"
        assert contract.exchange == "SMART"
        assert contract.currency == "USD"

    def test_make_contract_hk_ticker(self):
        """HK tickers strip .HK and use SEHK/HKD."""
        provider = MarketDataProvider(ibkr_config=None)
        contract = provider._make_contract("0700.HK")
        assert contract.symbol == "0700"
        assert contract.exchange == "SEHK"
        assert contract.currency == "HKD"

    def test_make_contract_cn_ss_ticker(self):
        """CN .SS tickers strip suffix and use SSE/CNH."""
        provider = MarketDataProvider(ibkr_config=None)
        contract = provider._make_contract("600900.SS")
        assert contract.symbol == "600900"
        assert contract.exchange == "SSE"
        assert contract.currency == "CNH"

    def test_make_contract_cn_sz_ticker(self):
        """CN .SZ tickers strip suffix and use SZSE/CNH."""
        provider = MarketDataProvider(ibkr_config=None)
        contract = provider._make_contract("000001.SZ")
        assert contract.symbol == "000001"
        assert contract.exchange == "SZSE"
        assert contract.currency == "CNH"
```

**Step 2: Run to confirm RED**

```bash
python3 -m pytest tests/test_market_data.py::TestIBKRPriceData -v
```
Expected: FAIL — `_make_contract` and `_ibkr_price_data` not defined.

**Step 3: Implement `_make_contract` and `_ibkr_price_data`**

In `src/market_data.py`, add after `_try_connect_ibkr`:

```python
def _make_contract(self, ticker: str):
    """Create an ib_insync Contract for the given ticker."""
    from ib_insync import Stock
    market = classify_market(ticker)
    if market == "HK":
        symbol = ticker.replace(".HK", "")
        return Stock(symbol, "SEHK", "HKD")
    elif market == "CN":
        if ticker.endswith(".SS"):
            symbol = ticker.replace(".SS", "")
            return Stock(symbol, "SSE", "CNH")
        else:
            symbol = ticker.replace(".SZ", "")
            return Stock(symbol, "SZSE", "CNH")
    else:
        return Stock(ticker, "SMART", "USD")

_PERIOD_MAP = {
    "5d": "5 D", "1mo": "1 M", "3mo": "3 M",
    "6mo": "6 M", "1y": "1 Y", "2y": "2 Y",
    "5y": "5 Y", "10y": "10 Y",
}

def _ibkr_price_data(self, ticker: str, period: str) -> pd.DataFrame:
    """Fetch daily OHLCV from IBKR Gateway."""
    from ib_insync import util
    contract = self._make_contract(ticker)
    duration = self._PERIOD_MAP.get(period, "1 Y")
    bars = self.ibkr.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=duration,
        barSizeSetting="1 day",
        whatToShow="ADJUSTED_LAST",
        useRTH=True,
        formatDate=1,
    )
    if not bars:
        raise ValueError(f"No IBKR price data for {ticker}")
    df = util.df(bars)
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    df.index = pd.to_datetime(df["date"])
    df.index.name = None
    return df.drop(columns=["date"], errors="ignore")
```

Update `get_price_data`:

```python
def get_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
    """Fetch OHLCV price data. IBKR first, yfinance fallback."""
    if self.ibkr:
        try:
            return self._ibkr_price_data(ticker, period)
        except Exception as e:
            logger.warning(f"IBKR price fetch failed for {ticker}, falling back: {e}")
    return self._yf_price_data(ticker, period)
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_market_data.py::TestIBKRPriceData -v
```
Expected: 6 PASSED.

**Step 5: Run full suite to confirm no regressions**

```bash
python3 -m pytest --tb=short -q
```
Expected: all pass.

**Step 6: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: add IBKR primary price data with yfinance fallback"
```

---

### Task 2: IBKR weekly price data

**Files:**
- Modify: `src/market_data.py`
- Test: `tests/test_market_data.py`

Same pattern as Task 1 but `barSizeSetting="1 week"`.

**Step 1: Write the failing test**

Add to `TestIBKRPriceData`:

```python
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
```

**Step 2: Run to confirm RED**

```bash
python3 -m pytest tests/test_market_data.py::TestIBKRPriceData::test_get_weekly_price_data_uses_ibkr_when_connected tests/test_market_data.py::TestIBKRPriceData::test_get_weekly_price_data_falls_back_to_yfinance -v
```

**Step 3: Implement**

Add `_ibkr_weekly_price_data` (reuses `_make_contract` and `_PERIOD_MAP`):

```python
def _ibkr_weekly_price_data(self, ticker: str, period: str) -> pd.DataFrame:
    """Fetch weekly OHLCV from IBKR Gateway."""
    from ib_insync import util
    contract = self._make_contract(ticker)
    duration = self._PERIOD_MAP.get(period, "1 Y")
    bars = self.ibkr.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=duration,
        barSizeSetting="1 week",
        whatToShow="ADJUSTED_LAST",
        useRTH=True,
        formatDate=1,
    )
    if not bars:
        raise ValueError(f"No IBKR weekly data for {ticker}")
    from ib_insync import util
    df = util.df(bars)
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    df.index = pd.to_datetime(df["date"])
    df.index.name = None
    return df.drop(columns=["date"], errors="ignore")
```

Extract existing yfinance weekly method (rename inline call):

```python
def _yf_weekly_price_data(self, ticker: str, period: str) -> pd.DataFrame:
    """Fetch weekly OHLCV from yfinance."""
    try:
        df = yf.download(ticker, period=period, interval="1wk", progress=False, timeout=30)
        return df
    except Exception as e:
        logger.error(f"yfinance weekly data failed for {ticker}: {e}")
        return pd.DataFrame()

def get_weekly_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
    """Fetch weekly OHLCV data. IBKR first, yfinance fallback."""
    if self.ibkr:
        try:
            return self._ibkr_weekly_price_data(ticker, period)
        except Exception as e:
            logger.warning(f"IBKR weekly fetch failed for {ticker}, falling back: {e}")
    return self._yf_weekly_price_data(ticker, period)
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_market_data.py -v -q
```
Expected: all pass.

**Step 5: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: add IBKR primary weekly price data with yfinance fallback"
```

---

### Task 3: IBKR options chain

**Files:**
- Modify: `src/market_data.py`
- Test: `tests/test_market_data.py`

IBKR options chain approach:
1. `reqSecDefOptParams(symbol, '', secType, conId)` → available expirations + strikes
2. Filter expirations to DTE range
3. For each valid expiration, create `Option(symbol, exp_yyyymmdd, strike, 'P', exchange)` contracts
4. `qualifyContracts(*puts)` → fill in conId
5. `reqTickers(*qualified_puts)` → get bid + impliedVolatility per contract
6. Build DataFrame matching yfinance output schema: `strike, bid, impliedVolatility, dte, expiration`

To avoid requesting thousands of contracts, filter strikes to ±50% of current price before creating options.

**Step 1: Write the failing test**

Add a new class `TestIBKROptionsChain`:

```python
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
```

**Step 2: Run to confirm RED**

```bash
python3 -m pytest tests/test_market_data.py::TestIBKROptionsChain -v
```

**Step 3: Implement `_ibkr_options_chain`**

```python
def _ibkr_options_chain(self, ticker: str, dte_min: int, dte_max: int) -> pd.DataFrame:
    """Fetch put options chain from IBKR Gateway."""
    from ib_insync import Option, util

    contract = self._make_contract(ticker)
    self.ibkr.qualifyContracts(contract)

    # Get available expirations and strikes
    chains = self.ibkr.reqSecDefOptParams(
        contract.symbol, "", contract.secType, contract.conId
    )
    if not chains:
        raise ValueError(f"No option chain params for {ticker}")

    # Prefer SMART exchange for US; SEHK for HK
    chain = chains[0]
    for c in chains:
        if c.exchange == contract.exchange:
            chain = c
            break

    # Filter expirations by DTE
    today = date.today()
    valid_exps = []
    for exp_str in chain.expirations:
        exp_date = datetime.strptime(exp_str, "%Y%m%d").date()
        dte = (exp_date - today).days
        if dte_min <= dte <= dte_max:
            valid_exps.append((exp_str, exp_date, dte))

    if not valid_exps:
        raise ValueError(f"No expirations in DTE range {dte_min}-{dte_max} for {ticker}")

    # Get current price to filter strikes (±50% range)
    tickers_info = self.ibkr.reqTickers(contract)
    current_price = tickers_info[0].marketPrice() if tickers_info else 0
    if current_price <= 0:
        current_price = tickers_info[0].close if tickers_info else 0

    # Build put option contracts (filter strikes if price available)
    put_contracts = []
    for exp_str, exp_date, dte in valid_exps:
        for strike in sorted(chain.strikes):
            if current_price > 0:
                if strike < current_price * 0.5 or strike > current_price * 1.5:
                    continue
            put_contracts.append(
                Option(contract.symbol, exp_str, strike, "P", chain.exchange)
            )

    if not put_contracts:
        raise ValueError(f"No valid put contracts for {ticker}")

    qualified = self.ibkr.qualifyContracts(*put_contracts)
    tickers_data = self.ibkr.reqTickers(*qualified)

    rows = []
    exp_map = {exp_str: (exp_date, dte) for exp_str, exp_date, dte in valid_exps}
    for t in tickers_data:
        exp_date, dte = exp_map.get(t.contract.lastTradeDateOrContractMonth, (None, None))
        if exp_date is None:
            continue
        rows.append({
            "strike": t.contract.strike,
            "bid": t.bid if t.bid > 0 else 0.0,
            "impliedVolatility": t.modelGreeks.impliedVol if t.modelGreeks else 0.0,
            "dte": dte,
            "expiration": exp_date,
        })

    if not rows:
        raise ValueError(f"No option tickers returned for {ticker}")
    return pd.DataFrame(rows)
```

Update `get_options_chain`:

```python
def get_options_chain(self, ticker: str, dte_min: int = 45, dte_max: int = 60) -> pd.DataFrame:
    """Fetch put options chain. IBKR first, yfinance fallback."""
    if self.should_skip_options(ticker):
        return pd.DataFrame()
    if self.ibkr:
        try:
            return self._ibkr_options_chain(ticker, dte_min, dte_max)
        except Exception as e:
            logger.warning(f"IBKR options chain failed for {ticker}, falling back: {e}")
    return self._yf_options_chain(ticker, dte_min, dte_max)
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_market_data.py -v -q
```
Expected: all pass.

**Step 5: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: add IBKR primary options chain with yfinance fallback"
```

---

### Task 4: IBKR earnings date

**Files:**
- Modify: `src/market_data.py`
- Test: `tests/test_market_data.py`

IBKR `reqFundamentalData(contract, 'CalendarReport')` returns XML with earnings dates. Parse with `xml.etree.ElementTree`. Look for `<Announcements>` → `<Announcement type="Earnings">` → `<Date>` elements. Filter to future dates, return the nearest.

**Step 1: Write the failing tests**

Add a new class `TestIBKREarningsDate`:

```python
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
```

**Step 2: Run to confirm RED**

```bash
python3 -m pytest tests/test_market_data.py::TestIBKREarningsDate -v
```

**Step 3: Implement `_ibkr_earnings_date`**

```python
def _ibkr_earnings_date(self, ticker: str) -> Optional[date]:
    """Fetch next earnings date from IBKR CalendarReport."""
    import xml.etree.ElementTree as ET
    contract = self._make_contract(ticker)
    self.ibkr.qualifyContracts(contract)
    xml_data = self.ibkr.reqFundamentalData(contract, "CalendarReport")
    if not xml_data:
        raise ValueError(f"No IBKR CalendarReport for {ticker}")
    root = ET.fromstring(xml_data)
    today = date.today()
    future_dates = []
    for ann in root.findall(".//Announcement[@type='Earnings']"):
        date_el = ann.find("Date")
        if date_el is not None and date_el.text:
            try:
                d = date.fromisoformat(date_el.text.strip())
                if d >= today:
                    future_dates.append(d)
            except ValueError:
                continue
    if not future_dates:
        raise ValueError(f"No future earnings dates in IBKR data for {ticker}")
    return min(future_dates)
```

Update `get_earnings_date`:

```python
def get_earnings_date(self, ticker: str) -> Optional[date]:
    """Fetch next earnings date. IBKR first, yfinance fallback."""
    if self.ibkr:
        try:
            return self._ibkr_earnings_date(ticker)
        except Exception as e:
            logger.warning(f"IBKR earnings date failed for {ticker}, falling back: {e}")
    # yfinance fallback (existing logic)
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if isinstance(cal, dict) and "Earnings Date" in cal:
            dates = cal["Earnings Date"]
            if dates:
                dt = dates[0]
                if isinstance(dt, datetime):
                    return dt.date()
                if isinstance(dt, date):
                    return dt
        return None
    except Exception as e:
        logger.warning(f"Earnings date fetch failed for {ticker}: {e}")
        return None
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_market_data.py -v -q
```
Expected: all pass.

**Step 5: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: add IBKR primary earnings date with yfinance fallback"
```

---

### Task 5: Full suite verification + spec sync

**Step 1: Run full test suite**

```bash
python3 -m pytest --tb=short -q
```
Expected: all tests pass (was 189 before this feature).

**Step 2: Update `docs/specs/data_pipeline.md`**

Add IBKR section documenting:
- `_make_contract(ticker)` — contract creation logic per market
- `_PERIOD_MAP` — period string conversion table
- IBKR-primary methods: `get_price_data`, `get_weekly_price_data`, `get_options_chain`, `get_earnings_date`
- yfinance-only methods: `get_dividend_history`, `get_fundamentals`, `get_historical_earnings_dates`
- Fallback pattern: try IBKR → on any Exception → log warning → call yfinance equivalent

**Step 3: Final commit**

```bash
git add docs/specs/data_pipeline.md
git commit -m "docs: update data_pipeline spec with IBKR Gateway integration"
```
