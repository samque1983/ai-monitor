# Phase 2: IV Anomaly Radar + Earnings Gap Profiler Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add IV Momentum monitoring and Earnings Gap analysis to the existing quant radar scanner.

**Architecture:** Extend existing modules — `iv_store.py` gets a date-offset query, `data_engine.py` gets `EarningsGap` dataclass and `iv_momentum` field, `scanners.py` gets two new scanners, reports get two new sections. No new files created.

**Tech Stack:** Python, pandas, yfinance, SQLite, pytest

---

### Task 1: IVStore — Add `get_iv_n_days_ago()` method

**Files:**
- Modify: `src/iv_store.py:37-43`
- Test: `tests/test_iv_store.py`

**Step 1: Write the failing test**

Add to `tests/test_iv_store.py`:

```python
class TestGetIVNDaysAgo:
    def test_returns_iv_from_n_days_ago(self, store):
        from datetime import date, timedelta
        today = date(2026, 2, 25)
        store.save_iv("AAPL", today - timedelta(days=5), 0.25)
        store.save_iv("AAPL", today - timedelta(days=3), 0.28)
        store.save_iv("AAPL", today, 0.30)
        result = store.get_iv_n_days_ago("AAPL", n=5, reference_date=today)
        assert result == 0.25

    def test_returns_closest_record_within_window(self, store):
        from datetime import date, timedelta
        today = date(2026, 2, 25)
        # No exact match at day-5, but day-6 exists
        store.save_iv("AAPL", today - timedelta(days=6), 0.22)
        store.save_iv("AAPL", today, 0.30)
        result = store.get_iv_n_days_ago("AAPL", n=5, reference_date=today)
        assert result == 0.22

    def test_returns_none_when_no_data(self, store):
        from datetime import date
        result = store.get_iv_n_days_ago("AAPL", n=5, reference_date=date(2026, 2, 25))
        assert result is None

    def test_returns_none_when_data_too_recent(self, store):
        from datetime import date, timedelta
        today = date(2026, 2, 25)
        store.save_iv("AAPL", today - timedelta(days=1), 0.30)
        result = store.get_iv_n_days_ago("AAPL", n=5, reference_date=today)
        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_iv_store.py::TestGetIVNDaysAgo -v`
Expected: FAIL — `IVStore` has no `get_iv_n_days_ago` method

**Step 3: Write minimal implementation**

Add after `get_iv_history()` in `src/iv_store.py`:

```python
def get_iv_n_days_ago(self, ticker: str, n: int = 5, reference_date: Optional[date] = None) -> Optional[float]:
    """Get IV from approximately n days ago. Returns closest record within [n, n+3] day window."""
    if reference_date is None:
        reference_date = date.today()
    target = reference_date - timedelta(days=n)
    window_start = reference_date - timedelta(days=n + 3)
    cursor = self.conn.execute(
        "SELECT iv FROM iv_history WHERE ticker = ? AND date >= ? AND date <= ? ORDER BY date DESC LIMIT 1",
        (ticker, window_start.isoformat(), target.isoformat()),
    )
    row = cursor.fetchone()
    return row[0] if row else None
```

Note: Add `Optional` to the typing import at line 4 if not already there (it's already imported).

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_iv_store.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/iv_store.py tests/test_iv_store.py
git commit -m "feat: add get_iv_n_days_ago() to IVStore for IV momentum"
```

---

### Task 2: TickerData — Add `iv_momentum` field

**Files:**
- Modify: `src/data_engine.py:14-27` (TickerData dataclass)
- Modify: `src/data_engine.py:58-121` (build_ticker_data)
- Test: `tests/test_data_engine.py`

**Step 1: Write the failing test**

Add to `tests/test_data_engine.py`:

```python
class TestIVMomentum:
    @patch("src.data_engine.MarketDataProvider")
    def test_iv_momentum_calculated(self, MockProvider):
        provider = MockProvider()
        dates = pd.date_range("2025-03-01", periods=250, freq="B")
        close_prices = np.linspace(100, 200, 250)
        daily_df = pd.DataFrame({"Close": close_prices}, index=dates)
        provider.get_price_data.return_value = daily_df

        weekly_dates = pd.date_range("2025-01-01", periods=60, freq="W")
        weekly_df = pd.DataFrame({"Close": np.linspace(90, 190, 60)}, index=weekly_dates)
        provider.get_weekly_price_data.return_value = weekly_df

        provider.get_earnings_date.return_value = None
        provider.get_iv_rank.return_value = 50.0
        provider.get_iv_momentum.return_value = 35.0

        result = build_ticker_data("AAPL", provider, reference_date=date(2026, 2, 20))
        assert result is not None
        assert result.iv_momentum == 35.0

    @patch("src.data_engine.MarketDataProvider")
    def test_iv_momentum_none_when_unavailable(self, MockProvider):
        provider = MockProvider()
        dates = pd.date_range("2025-03-01", periods=250, freq="B")
        daily_df = pd.DataFrame({"Close": np.linspace(100, 200, 250)}, index=dates)
        provider.get_price_data.return_value = daily_df

        weekly_dates = pd.date_range("2025-01-01", periods=60, freq="W")
        weekly_df = pd.DataFrame({"Close": np.linspace(90, 190, 60)}, index=weekly_dates)
        provider.get_weekly_price_data.return_value = weekly_df

        provider.get_earnings_date.return_value = None
        provider.get_iv_rank.return_value = 50.0
        provider.get_iv_momentum.return_value = None

        result = build_ticker_data("AAPL", provider, reference_date=date(2026, 2, 20))
        assert result is not None
        assert result.iv_momentum is None
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_data_engine.py::TestIVMomentum -v`
Expected: FAIL — TickerData has no `iv_momentum` field

**Step 3: Write minimal implementation**

In `src/data_engine.py`, add field to TickerData (after `iv_rank` line 23):
```python
    iv_momentum: Optional[float]  # 5-day IV change %
```

In `src/market_data.py`, add method (after `get_iv_rank()`):
```python
def get_iv_momentum(self, ticker: str) -> Optional[float]:
    """Get 5-day IV momentum: (current_iv - iv_5d_ago) / iv_5d_ago * 100."""
    if self.should_skip_options(ticker) or not self.iv_store:
        return None
    try:
        t = yf.Ticker(ticker)
        current_price = t.info.get("regularMarketPrice") or t.info.get("previousClose")
        if not current_price:
            return None
        exps = t.options
        if not exps:
            return None
        chain = t.option_chain(exps[0])
        calls = chain.calls
        if calls.empty:
            return None
        calls = calls.copy()
        calls["diff"] = abs(calls["strike"] - current_price)
        atm = calls.loc[calls["diff"].idxmin()]
        current_iv = float(atm["impliedVolatility"])

        iv_5d_ago = self.iv_store.get_iv_n_days_ago(ticker, n=5)
        if iv_5d_ago is None or iv_5d_ago == 0:
            return None
        return round((current_iv - iv_5d_ago) / iv_5d_ago * 100, 1)
    except Exception as e:
        logger.warning(f"IV momentum fetch failed for {ticker}: {e}")
        return None
```

In `build_ticker_data()`, after `iv_rank = provider.get_iv_rank(ticker)` (line 96), add:
```python
    iv_momentum = provider.get_iv_momentum(ticker)
```

In the return statement, add `iv_momentum=iv_momentum` after `iv_rank=iv_rank`.

**Important:** Update ALL existing test helpers `make_ticker()` in `tests/test_scanners.py`, `tests/test_report.py`, and `tests/test_integration.py` to include `iv_momentum=None` in their defaults dict.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS (including all existing tests with updated defaults)

**Step 5: Commit**

```bash
git add src/data_engine.py src/market_data.py tests/test_data_engine.py tests/test_scanners.py tests/test_report.py tests/test_integration.py
git commit -m "feat: add iv_momentum field to TickerData"
```

---

### Task 3: Scanner — `scan_iv_momentum()`

**Files:**
- Modify: `src/scanners.py`
- Test: `tests/test_scanners.py`

**Step 1: Write the failing test**

Add to `tests/test_scanners.py`:

```python
from src.scanners import scan_iv_momentum

class TestIVMomentum:
    def test_high_momentum_detected(self):
        data = [make_ticker(ticker="SPIKE", iv_momentum=45.0)]
        result = scan_iv_momentum(data)
        assert len(result) == 1
        assert result[0].ticker == "SPIKE"

    def test_low_momentum_not_included(self):
        data = [make_ticker(ticker="CALM", iv_momentum=10.0)]
        result = scan_iv_momentum(data)
        assert len(result) == 0

    def test_none_momentum_skipped(self):
        data = [make_ticker(ticker="NODATA", iv_momentum=None)]
        result = scan_iv_momentum(data)
        assert len(result) == 0

    def test_custom_threshold(self):
        data = [make_ticker(ticker="MED", iv_momentum=25.0)]
        assert len(scan_iv_momentum(data, threshold=20.0)) == 1
        assert len(scan_iv_momentum(data, threshold=30.0)) == 0

    def test_boundary_value_not_included(self):
        data = [make_ticker(ticker="EXACT", iv_momentum=30.0)]
        result = scan_iv_momentum(data, threshold=30.0)
        assert len(result) == 0  # must be > threshold, not >=
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_scanners.py::TestIVMomentum -v`
Expected: FAIL — `scan_iv_momentum` not found

**Step 3: Write minimal implementation**

Add to `src/scanners.py` (after `scan_iv_extremes`):

```python
def scan_iv_momentum(data: List[TickerData], threshold: float = 30.0) -> List[TickerData]:
    """Detect tickers with rapid IV expansion (5-day momentum > threshold%)."""
    return [t for t in data if t.iv_momentum is not None and t.iv_momentum > threshold]
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_scanners.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/scanners.py tests/test_scanners.py
git commit -m "feat: add scan_iv_momentum() scanner"
```

---

### Task 4: EarningsGap dataclass + `compute_earnings_gaps()`

**Files:**
- Modify: `src/data_engine.py`
- Test: `tests/test_data_engine.py`

**Step 1: Write the failing test**

Add to `tests/test_data_engine.py`:

```python
from src.data_engine import EarningsGap, compute_earnings_gaps

class TestComputeEarningsGaps:
    def test_basic_gap_calculation(self):
        """Two earnings events with known gaps."""
        earnings_dates = [date(2025, 7, 25), date(2025, 10, 24)]
        # Build price data covering both earnings dates
        dates = pd.date_range("2025-06-01", "2025-11-30", freq="B")
        prices = pd.DataFrame({
            "Open": [100.0] * len(dates),
            "Close": [100.0] * len(dates),
        }, index=dates)

        # Set specific prices around first earnings (2025-07-25 is a Friday)
        # prev day close = 100, earnings day open = 105 → gap = +5%
        ed1 = pd.Timestamp("2025-07-25")
        ed1_prev = pd.Timestamp("2025-07-24")
        if ed1 in prices.index and ed1_prev in prices.index:
            prices.loc[ed1_prev, "Close"] = 100.0
            prices.loc[ed1, "Open"] = 105.0

        # Second earnings (2025-10-24 is a Friday)
        ed2 = pd.Timestamp("2025-10-24")
        ed2_prev = pd.Timestamp("2025-10-23")
        if ed2 in prices.index and ed2_prev in prices.index:
            prices.loc[ed2_prev, "Close"] = 100.0
            prices.loc[ed2, "Open"] = 97.0  # gap = -3%

        result = compute_earnings_gaps("AAPL", earnings_dates, prices)
        assert result is not None
        assert result.ticker == "AAPL"
        assert result.sample_count == 2
        assert result.avg_gap == pytest.approx(4.0, abs=0.1)  # mean(|5|, |3|) = 4.0
        assert result.up_ratio == pytest.approx(50.0)  # 1 up, 1 down
        assert result.max_gap == pytest.approx(5.0, abs=0.1)  # max by absolute value

    def test_returns_none_with_insufficient_data(self):
        """Need at least 2 valid earnings events."""
        earnings_dates = [date(2025, 7, 25)]
        dates = pd.date_range("2025-06-01", "2025-08-30", freq="B")
        prices = pd.DataFrame({
            "Open": [100.0] * len(dates),
            "Close": [100.0] * len(dates),
        }, index=dates)
        result = compute_earnings_gaps("AAPL", earnings_dates, prices)
        assert result is None

    def test_returns_none_with_empty_dates(self):
        prices = pd.DataFrame({"Open": [100.0], "Close": [100.0]})
        result = compute_earnings_gaps("AAPL", [], prices)
        assert result is None

    def test_skips_earnings_dates_without_price_data(self):
        """If a date is not in the price DataFrame, skip it gracefully."""
        earnings_dates = [date(2020, 1, 1), date(2020, 4, 1)]  # not in price data
        dates = pd.date_range("2025-06-01", "2025-08-30", freq="B")
        prices = pd.DataFrame({
            "Open": [100.0] * len(dates),
            "Close": [100.0] * len(dates),
        }, index=dates)
        result = compute_earnings_gaps("AAPL", earnings_dates, prices)
        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_data_engine.py::TestComputeEarningsGaps -v`
Expected: FAIL — `EarningsGap` and `compute_earnings_gaps` not found

**Step 3: Write minimal implementation**

Add to `src/data_engine.py` after `TickerData` dataclass:

```python
@dataclass
class EarningsGap:
    """Historical earnings gap statistics for a ticker."""
    ticker: str
    avg_gap: float       # mean(|gap|) as percentage
    up_ratio: float      # percentage of gaps > 0
    max_gap: float       # largest gap by absolute value (preserves sign)
    sample_count: int    # number of earnings events analyzed


def compute_earnings_gaps(
    ticker: str,
    earnings_dates: list,
    price_df: pd.DataFrame,
    min_samples: int = 2,
) -> Optional[EarningsGap]:
    """Compute historical earnings gap statistics.

    Gap = (earnings_date Open - prev_trading_day Close) / prev_trading_day Close * 100
    """
    if not earnings_dates or price_df.empty:
        return None

    gaps = []
    for ed in earnings_dates:
        ed_ts = pd.Timestamp(ed)
        # Find earnings date and its previous trading day in the price data
        if ed_ts not in price_df.index:
            continue
        # Get the previous trading day (the row before ed_ts in the index)
        idx = price_df.index.get_loc(ed_ts)
        if idx == 0:
            continue
        prev_ts = price_df.index[idx - 1]

        prev_close = float(price_df.loc[prev_ts, "Close"])
        ed_open = float(price_df.loc[ed_ts, "Open"])

        if prev_close == 0:
            continue
        gap = (ed_open - prev_close) / prev_close * 100
        gaps.append(gap)

    if len(gaps) < min_samples:
        return None

    abs_gaps = [abs(g) for g in gaps]
    avg_gap = sum(abs_gaps) / len(abs_gaps)
    up_count = sum(1 for g in gaps if g > 0)
    up_ratio = up_count / len(gaps) * 100
    max_gap_val = max(gaps, key=abs)

    return EarningsGap(
        ticker=ticker,
        avg_gap=round(avg_gap, 1),
        up_ratio=round(up_ratio, 1),
        max_gap=round(max_gap_val, 1),
        sample_count=len(gaps),
    )
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_data_engine.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/data_engine.py tests/test_data_engine.py
git commit -m "feat: add EarningsGap dataclass and compute_earnings_gaps()"
```

---

### Task 5: MarketDataProvider — `get_historical_earnings_dates()`

**Files:**
- Modify: `src/market_data.py`
- Test: `tests/test_market_data.py`

**Step 1: Write the failing test**

Read `tests/test_market_data.py` first to understand existing test patterns, then add:

```python
from unittest.mock import patch, MagicMock

class TestGetHistoricalEarningsDates:
    @patch("src.market_data.yf.Ticker")
    def test_returns_past_earnings_dates(self, MockTicker):
        from datetime import date
        import pandas as pd
        mock_t = MockTicker.return_value
        # yfinance returns earnings_dates as a DatetimeIndex
        mock_t.earnings_dates = pd.DataFrame(
            {"EPS Estimate": [1.0, 1.1, 1.2, 1.3]},
            index=pd.to_datetime(["2026-04-25", "2026-01-20", "2025-10-15", "2025-07-10"]),
        )
        provider = MarketDataProvider()
        result = provider.get_historical_earnings_dates("AAPL", count=4)
        assert len(result) <= 4
        assert all(isinstance(d, date) for d in result)

    @patch("src.market_data.yf.Ticker")
    def test_returns_empty_on_failure(self, MockTicker):
        mock_t = MockTicker.return_value
        mock_t.earnings_dates = None
        provider = MarketDataProvider()
        result = provider.get_historical_earnings_dates("AAPL")
        assert result == []
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_market_data.py::TestGetHistoricalEarningsDates -v`
Expected: FAIL — no such method

**Step 3: Write minimal implementation**

Add to `src/market_data.py` after `get_earnings_date()`:

```python
def get_historical_earnings_dates(self, ticker: str, count: int = 8) -> list:
    """Get past earnings dates from yfinance. Returns list of date objects."""
    if self.should_skip_options(ticker):
        return []
    try:
        t = yf.Ticker(ticker)
        ed = t.earnings_dates
        if ed is None or ed.empty:
            return []
        today = date.today()
        past_dates = [d.date() for d in ed.index if d.date() < today]
        past_dates.sort(reverse=True)
        return past_dates[:count]
    except Exception as e:
        logger.warning(f"Historical earnings dates fetch failed for {ticker}: {e}")
        return []
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_market_data.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: add get_historical_earnings_dates() to MarketDataProvider"
```

---

### Task 6: Scanner — `scan_earnings_gap()`

**Files:**
- Modify: `src/scanners.py`
- Test: `tests/test_scanners.py`

**Step 1: Write the failing test**

Add to `tests/test_scanners.py`:

```python
from src.scanners import scan_earnings_gap
from src.data_engine import EarningsGap

class TestEarningsGapScanner:
    def test_ticker_within_threshold_gets_gap_analysis(self):
        data = [make_ticker(ticker="AAPL", days_to_earnings=2, earnings_date=date(2026, 2, 27))]
        # Mock provider
        mock_provider = MagicMock()
        mock_provider.should_skip_options.return_value = False

        # Mock historical earnings dates
        mock_provider.get_historical_earnings_dates.return_value = [
            date(2026, 1, 20), date(2025, 10, 15), date(2025, 7, 10),
        ]
        # Mock price data with gaps
        dates_idx = pd.date_range("2025-06-01", "2026-02-25", freq="B")
        price_df = pd.DataFrame({
            "Open": [100.0] * len(dates_idx),
            "Close": [100.0] * len(dates_idx),
        }, index=dates_idx)
        # Set gaps at earnings dates
        for ed, gap_open in [(pd.Timestamp("2026-01-20"), 106.0),
                              (pd.Timestamp("2025-10-15"), 95.0),
                              (pd.Timestamp("2025-07-10"), 103.0)]:
            if ed in price_df.index:
                price_df.loc[ed, "Open"] = gap_open
        mock_provider.get_price_data.return_value = price_df

        result = scan_earnings_gap(data, mock_provider, days_threshold=3)
        assert len(result) == 1
        assert result[0].ticker == "AAPL"
        assert result[0].sample_count >= 2

    def test_ticker_outside_threshold_skipped(self):
        data = [make_ticker(ticker="MSFT", days_to_earnings=10)]
        mock_provider = MagicMock()
        result = scan_earnings_gap(data, mock_provider, days_threshold=3)
        assert len(result) == 0

    def test_ticker_with_no_earnings_date_skipped(self):
        data = [make_ticker(ticker="NOEARN", days_to_earnings=None, earnings_date=None)]
        mock_provider = MagicMock()
        result = scan_earnings_gap(data, mock_provider, days_threshold=3)
        assert len(result) == 0
```

Note: Add `from unittest.mock import MagicMock` to the imports if not already there.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_scanners.py::TestEarningsGapScanner -v`
Expected: FAIL — `scan_earnings_gap` not found

**Step 3: Write minimal implementation**

Add to `src/scanners.py`:

```python
from src.data_engine import TickerData, EarningsGap, compute_earnings_gaps
from src.market_data import MarketDataProvider

def scan_earnings_gap(
    data: List[TickerData],
    provider: MarketDataProvider,
    days_threshold: int = 3,
) -> List[EarningsGap]:
    """Scan tickers approaching earnings for historical gap analysis."""
    results = []
    for t in data:
        if t.days_to_earnings is None or t.days_to_earnings > days_threshold:
            continue
        if provider.should_skip_options(t.ticker):
            continue
        try:
            hist_dates = provider.get_historical_earnings_dates(t.ticker)
            if len(hist_dates) < 2:
                continue
            price_df = provider.get_price_data(t.ticker, period="3y")
            if price_df.empty:
                continue
            gap = compute_earnings_gaps(t.ticker, hist_dates, price_df)
            if gap:
                results.append(gap)
        except Exception:
            continue
    return results
```

Update the import at the top of `src/scanners.py` — change:
```python
from src.data_engine import TickerData
```
to:
```python
from src.data_engine import TickerData, EarningsGap, compute_earnings_gaps
```

Add the MarketDataProvider import (for type hint only):
```python
from src.market_data import MarketDataProvider
```

**IMPORTANT: Check for circular imports.** `scanners.py` importing from `market_data.py` — this follows the architecture rule: `scanners → data_engine → market_data`. But `scanners` importing `MarketDataProvider` directly is a new dependency. If circular import occurs, use `TYPE_CHECKING`:
```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.market_data import MarketDataProvider
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_scanners.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/scanners.py tests/test_scanners.py
git commit -m "feat: add scan_earnings_gap() scanner"
```

---

### Task 7: Config — Add Phase 2 scanner settings

**Files:**
- Modify: `config.yaml`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

Read `tests/test_config.py` to understand existing test patterns, then add:

```python
def test_config_has_scanner_settings(self):
    config = load_config("config.yaml")
    scanners = config.get("scanners", {})
    assert "iv_momentum_threshold" in scanners
    assert "earnings_gap_days" in scanners
    assert "earnings_lookback" in scanners
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: FAIL — no `scanners` section in config

**Step 3: Write minimal implementation**

Add to `config.yaml`:

```yaml
scanners:
  iv_momentum_threshold: 30
  earnings_gap_days: 3
  earnings_lookback: 8
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add config.yaml tests/test_config.py
git commit -m "feat: add Phase 2 scanner config settings"
```

---

### Task 8: Report — Add IV Momentum and Earnings Gap sections

**Files:**
- Modify: `src/report.py`
- Modify: `src/html_report.py`
- Test: `tests/test_report.py`

**Step 1: Write the failing test**

Add to `tests/test_report.py`:

```python
from src.data_engine import EarningsGap

class TestIVMomentumSection:
    def test_momentum_tickers_in_report(self):
        momentum = [make_ticker(ticker="SPIKE", iv_momentum=45.0, iv_rank=72.0)]
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            iv_momentum=momentum,
            elapsed_seconds=5.0,
        )
        assert "波动率异动雷达" in report
        assert "SPIKE" in report
        assert "45.0" in report

    def test_empty_momentum_shows_none(self):
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            iv_momentum=[],
            elapsed_seconds=5.0,
        )
        assert "波动率异动雷达" in report
        assert "无符合条件的标的" in report


class TestEarningsGapSection:
    def test_gap_data_in_report(self):
        gaps = [EarningsGap(ticker="AAPL", avg_gap=4.2, up_ratio=62.5, max_gap=-8.1, sample_count=4)]
        ticker_map = {"AAPL": make_ticker(ticker="AAPL", iv_rank=85.3, days_to_earnings=2)}
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            earnings_gaps=gaps,
            earnings_gap_ticker_map=ticker_map,
            elapsed_seconds=5.0,
        )
        assert "财报 Gap 预警" in report
        assert "AAPL" in report
        assert "4.2" in report
        assert "62.5" in report

    def test_empty_gaps_shows_none(self):
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            earnings_gaps=[],
            elapsed_seconds=5.0,
        )
        assert "财报 Gap 预警" in report
        assert "无符合条件的标的" in report
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_report.py -v`
Expected: FAIL — `format_report` doesn't accept `iv_momentum` or `earnings_gaps` params

**Step 3: Write minimal implementation**

Update `format_report()` signature in `src/report.py` to add new params:
```python
def format_report(
    scan_date: date,
    data_source: str,
    universe_count: int,
    iv_low: List[TickerData],
    iv_high: List[TickerData],
    ma200_bullish: List[TickerData],
    ma200_bearish: List[TickerData],
    leaps: List[TickerData],
    sell_puts: List[Tuple[SellPutSignal, TickerData]],
    iv_momentum: Optional[List[TickerData]] = None,
    earnings_gaps: Optional[list] = None,
    earnings_gap_ticker_map: Optional[dict] = None,
    skipped: Optional[List[Tuple[str, str]]] = None,
    elapsed_seconds: float = 0.0,
) -> str:
```

Add import at top: `from src.data_engine import TickerData, EarningsGap` (add EarningsGap).

Add after the Sell Put section (before Skipped tickers):

```python
    # IV Momentum
    iv_momentum_list = iv_momentum or []
    lines.append("── 波动率异动雷达 (5日IV动量) ──────────────────────")
    lines.append("")
    if iv_momentum_list:
        for t in iv_momentum_list:
            lines.append(f"  {t.ticker:<8} IV动量: +{t.iv_momentum:.1f}%  IV Rank: {t.iv_rank:.1f}%  │ {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (无符合条件的标的)")
    lines.append("")

    # Earnings Gap
    gaps_list = earnings_gaps or []
    gap_map = earnings_gap_ticker_map or {}
    lines.append("── 财报 Gap 预警 ─────────────────────────────────")
    lines.append("")
    if gaps_list:
        for g in gaps_list:
            td = gap_map.get(g.ticker)
            days_str = f"{td.days_to_earnings}天" if td and td.days_to_earnings is not None else "N/A"
            iv_str = f"{td.iv_rank:.1f}%" if td and td.iv_rank is not None else "N/A"
            lines.append(f"  ⚠️ {g.ticker} 财报还有 {days_str}")
            lines.append(f"     历史平均 Gap ±{g.avg_gap:.1f}%  |  上涨概率 {g.up_ratio:.1f}%  |  历史最大跳空 {g.max_gap:+.1f}%")
            lines.append(f"     当前 IV Rank: {iv_str}  (样本数: {g.sample_count})")
    else:
        lines.append("  (无符合条件的标的)")
    lines.append("")
```

Do the same for `format_html_report()` in `src/html_report.py` — add the same new params and two new card sections. Create helper functions:

```python
def _iv_momentum_table(tickers: List[TickerData]) -> str:
    if not tickers:
        return f"<table>{_empty_row(4)}</table>"
    rows = []
    for t in tickers:
        mom = f"+{t.iv_momentum:.1f}%" if t.iv_momentum is not None else "N/A"
        iv = f"{t.iv_rank:.1f}%" if t.iv_rank is not None else "N/A"
        rows.append(
            f"<tr>"
            f'<td class="ticker">{_escape(t.ticker)}</td>'
            f"<td>IV动量: {_escape(mom)}</td>"
            f"<td>IV Rank: {_escape(iv)}</td>"
            f"<td>{_escape(_format_earnings(t.earnings_date, t.days_to_earnings))}</td>"
            f"</tr>"
        )
    return "<table>" + "".join(rows) + "</table>"


def _earnings_gap_table(gaps: list, ticker_map: dict) -> str:
    if not gaps:
        return f"<table>{_empty_row(4)}</table>"
    rows = []
    for g in gaps:
        td = ticker_map.get(g.ticker)
        days_str = f"{td.days_to_earnings}天" if td and td.days_to_earnings is not None else "N/A"
        iv_str = f"{td.iv_rank:.1f}%" if td and td.iv_rank is not None else "N/A"
        rows.append(
            f"<tr>"
            f'<td class="ticker">⚠️ {_escape(g.ticker)}</td>'
            f"<td>财报还有 {_escape(days_str)}<br>"
            f"平均Gap ±{g.avg_gap:.1f}% · 上涨概率 {g.up_ratio:.1f}%</td>"
            f"<td>最大跳空 {g.max_gap:+.1f}%<br>样本数: {g.sample_count}</td>"
            f"<td>IV Rank: {_escape(iv_str)}</td>"
            f"</tr>"
        )
    return "<table>" + "".join(rows) + "</table>"
```

Add cards in `format_html_report()` before the Skipped section:

```python
    # --- Card: IV Momentum ---
    iv_momentum_list = iv_momentum or []
    parts.append('<div class="card">')
    parts.append("<h2>波动率异动雷达 (5日IV动量)</h2>")
    parts.append(_iv_momentum_table(iv_momentum_list))
    parts.append("</div>")

    # --- Card: Earnings Gap ---
    gaps_list = earnings_gaps or []
    gap_map = earnings_gap_ticker_map or {}
    parts.append('<div class="card">')
    parts.append("<h2>财报 Gap 预警</h2>")
    parts.append(_earnings_gap_table(gaps_list, gap_map))
    parts.append("</div>")
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_report.py -v`
Expected: ALL PASS

Also run: `python3 -m pytest tests/ -v`
Expected: ALL PASS (ensure existing tests still work with new optional params)

**Step 5: Commit**

```bash
git add src/report.py src/html_report.py tests/test_report.py
git commit -m "feat: add IV Momentum and Earnings Gap sections to reports"
```

---

### Task 9: Main pipeline — Wire Phase 2 scanners

**Files:**
- Modify: `src/main.py`
- Test: `tests/test_integration.py`

**Step 1: Write the failing test**

Add to `tests/test_integration.py`:

```python
from src.data_engine import EarningsGap

def test_phase2_pipeline(mock_provider):
    """Test Phase 2 scanners integrate with report."""
    td = build_ticker_data("AAPL", mock_provider, reference_date=date(2026, 2, 20))
    assert td is not None

    all_data = [td]

    # Phase 1 scanners
    iv_low, iv_high = scan_iv_extremes(all_data)
    ma200_bull, ma200_bear = scan_ma200_crossover(all_data)
    leaps = scan_leaps_setup(all_data)

    # Phase 2 scanners
    from src.scanners import scan_iv_momentum, scan_earnings_gap
    iv_momentum = scan_iv_momentum(all_data)

    # Generate report with Phase 2 data
    report = format_report(
        scan_date=date(2026, 2, 20),
        data_source="mock",
        universe_count=1,
        iv_low=iv_low, iv_high=iv_high,
        ma200_bullish=ma200_bull, ma200_bearish=ma200_bear,
        leaps=leaps, sell_puts=[],
        iv_momentum=iv_momentum,
        earnings_gaps=[],
        elapsed_seconds=1.0,
    )
    assert "波动率异动雷达" in report
    assert "财报 Gap 预警" in report
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_integration.py::test_phase2_pipeline -v`
Expected: FAIL — missing imports or mismatched signatures

**Step 3: Write minimal implementation**

Update `src/main.py`:

1. Update imports:
```python
from src.scanners import scan_iv_extremes, scan_ma200_crossover, scan_leaps_setup, scan_sell_put, scan_iv_momentum, scan_earnings_gap
```

2. After the Phase 1 scanners block (after line 77), add:
```python
    # Phase 2: IV Momentum
    scanner_config = config.get("scanners", {})
    iv_momentum = scan_iv_momentum(all_data, threshold=scanner_config.get("iv_momentum_threshold", 30))

    # Phase 2: Earnings Gap
    earnings_gaps = scan_earnings_gap(
        all_data, provider,
        days_threshold=scanner_config.get("earnings_gap_days", 3),
    )
    earnings_gap_ticker_map = {td.ticker: td for td in all_data}
```

3. Update both `format_report()` and `format_html_report()` calls to pass the new params:
```python
    report = format_report(
        ...existing params...,
        iv_momentum=iv_momentum,
        earnings_gaps=earnings_gaps,
        earnings_gap_ticker_map=earnings_gap_ticker_map,
        skipped=skipped,
        elapsed_seconds=elapsed,
    )

    html_report = format_html_report(
        ...existing params...,
        iv_momentum=iv_momentum,
        earnings_gaps=earnings_gaps,
        earnings_gap_ticker_map=earnings_gap_ticker_map,
        skipped=skipped,
        elapsed_seconds=elapsed,
    )
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/main.py tests/test_integration.py
git commit -m "feat: wire Phase 2 scanners into main pipeline"
```

---

### Task 10: Final verification

**Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: ALL PASS, zero failures

**Step 2: Commit and push**

```bash
git push
```
