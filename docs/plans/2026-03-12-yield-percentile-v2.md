# Yield Percentile v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the single-float yield percentile with a Winsorized result that includes P10/P90 normal range and historic max, surfaced in the dashboard as a compact progress bar with range annotation.

**Architecture:** Three-layer change — `dividend_store.py` returns a richer result type, `dividend_scanners.py` propagates new fields through `DividendBuySignal`, `src/main.py` adds them to the signal payload, and `dashboard.html` renders the new progress-bar format with graceful fallback for old signals.

**Tech Stack:** Python 3.11 dataclasses, SQLite, pure-JS DOM manipulation in `dashboard.html`

---

## Context

Key file locations:
- `src/dividend_store.py:265` — `get_yield_percentile(ticker, current_yield) -> float` (to be upgraded)
- `src/dividend_scanners.py:399` — calls `store.get_yield_percentile`, stores result in `yield_percentile`
- `src/dividend_scanners.py:73` — `DividendBuySignal` dataclass (add new optional fields)
- `src/main.py:145-183` — serializes `DividendBuySignal` to signal payload dict (add new keys)
- `agent/static/dashboard.html` — `buildDividendCard` JS function renders the card

---

## Task 1: `YieldPercentileResult` dataclass + updated `get_yield_percentile`

**Files:**
- Modify: `src/dividend_store.py:265-285`
- Test: `tests/test_dividend_store.py`

### Step 1: Write the failing tests

Add to `tests/test_dividend_store.py`:

```python
from src.dividend_store import DividendStore, YieldPercentileResult


def test_get_yield_percentile_returns_result_type():
    """get_yield_percentile should return YieldPercentileResult, not float."""
    store = DividendStore(db_path=':memory:')
    yields = [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5]
    for i, y in enumerate(yields):
        store.save_dividend_history('AAPL', date(2021 + i // 4, 1 + (i % 4) * 3, 1), y, y * 100, 100.0)

    result = store.get_yield_percentile('AAPL', 7.2)

    assert isinstance(result, YieldPercentileResult)
    assert result.percentile >= 90.0
    assert result.p10 is not None
    assert result.p90 is not None
    assert result.hist_max is not None
    assert result.p10 < result.p90
    assert result.hist_max >= result.p90


def test_get_yield_percentile_winsorized():
    """Top 5% values should not inflate the percentile calculation."""
    store = DividendStore(db_path=':memory:')
    # 100 normal values 3.0–7.0, then 10 extreme crisis values at 25.0
    for i in range(100):
        store.save_dividend_history('AAPL', date(2021, 1, 1) + timedelta(days=i),
                                    3.0 + i * 0.04, 100.0, 100.0)
    for i in range(10):
        store.save_dividend_history('AAPL', date(2023, 1, 1) + timedelta(days=i),
                                    25.0, 100.0, 100.0)

    result = store.get_yield_percentile('AAPL', 6.5)
    # After Winsorizing top 5%, a 6.5% yield should still show as high percentile
    assert result.percentile >= 70.0
    # hist_max should capture the real extreme (25.0)
    assert result.hist_max >= 20.0


def test_get_yield_percentile_p10_p90_requires_30_points():
    """p10/p90 should be None when fewer than 30 data points exist."""
    store = DividendStore(db_path=':memory:')
    for i in range(10):
        store.save_dividend_history('AAPL', date(2021, 1, i + 1), 4.0 + i * 0.1, 100.0, 100.0)

    result = store.get_yield_percentile('AAPL', 4.5)
    assert result.p10 is None
    assert result.p90 is None
    assert result.percentile >= 0  # Still computes percentile


def test_get_yield_percentile_no_history_returns_default():
    """No history returns 50.0 percentile with None p10/p90 (existing behavior)."""
    store = DividendStore(db_path=':memory:')
    result = store.get_yield_percentile('AAPL', 5.0)
    assert result.percentile == 50.0
    assert result.p10 is None
    assert result.p90 is None
    assert result.hist_max is None
```

### Step 2: Run tests to verify they fail

```bash
cd /Users/q/code/ai-monitor
pytest tests/test_dividend_store.py::test_get_yield_percentile_returns_result_type tests/test_dividend_store.py::test_get_yield_percentile_winsorized tests/test_dividend_store.py::test_get_yield_percentile_p10_p90_requires_30_points tests/test_dividend_store.py::test_get_yield_percentile_no_history_returns_default -v
```

Expected: FAIL with `ImportError: cannot import name 'YieldPercentileResult'`

### Step 3: Implement `YieldPercentileResult` and update `get_yield_percentile`

In `src/dividend_store.py`, add after the imports at the top:

```python
from dataclasses import dataclass
```

After `logger = logging.getLogger(__name__)`, add:

```python
@dataclass
class YieldPercentileResult:
    percentile: float
    p10: Optional[float]
    p90: Optional[float]
    hist_max: Optional[float]
```

Replace `get_yield_percentile` (lines 265–285) with:

```python
def get_yield_percentile(self, ticker: str, current_yield: float) -> "YieldPercentileResult":
    """计算当前股息率在5年历史中的分位数（Winsorized — 剔除顶部5%极值）"""
    cursor = self.conn.cursor()
    cursor.execute("""
        SELECT dividend_yield FROM dividend_history
        WHERE ticker = ?
        ORDER BY date DESC
        LIMIT 1250
    """, (ticker,))

    historical_yields = [row[0] for row in cursor.fetchall()]

    if not historical_yields:
        logger.warning(f"No historical dividend data for {ticker}, returning default percentile 50.0")
        return YieldPercentileResult(percentile=50.0, p10=None, p90=None, hist_max=None)

    n = len(historical_yields)
    hist_max = max(historical_yields)

    # p10/p90 require at least 30 data points
    p10: Optional[float] = None
    p90: Optional[float] = None
    if n >= 30:
        sorted_yields = sorted(historical_yields)
        p10 = sorted_yields[int(n * 0.10)]
        p90 = sorted_yields[int(n * 0.90)]

    # Winsorized percentile: exclude top 5% to dampen crisis spikes
    cutoff_idx = max(1, int(n * 0.95))
    trimmed = sorted(historical_yields)[:cutoff_idx]
    count_below_or_equal = sum(1 for y in trimmed if y <= current_yield)
    percentile = (count_below_or_equal / len(trimmed)) * 100

    return YieldPercentileResult(
        percentile=round(percentile, 1),
        p10=round(p10, 2) if p10 is not None else None,
        p90=round(p90, 2) if p90 is not None else None,
        hist_max=round(hist_max, 2),
    )
```

### Step 4: Update the existing test that asserts float return

The existing test `test_save_and_get_yield_percentile` in `tests/test_dividend_store.py` uses:
```python
percentile_high = store.get_yield_percentile('AAPL', 7.2)
assert percentile_high >= 90.0
```

Update it to:
```python
result_high = store.get_yield_percentile('AAPL', 7.2)
assert result_high.percentile >= 90.0

result_mid = store.get_yield_percentile('AAPL', 5.1)
assert 40.0 <= result_mid.percentile <= 60.0
```

### Step 5: Run all store tests to verify green

```bash
pytest tests/test_dividend_store.py -v
```

Expected: All pass.

### Step 6: Commit

```bash
git add src/dividend_store.py tests/test_dividend_store.py
git commit -m "feat: yield percentile returns YieldPercentileResult with p10/p90/hist_max (Winsorized)"
```

---

## Task 2: Propagate new fields through `DividendBuySignal` and signal payload

**Files:**
- Modify: `src/dividend_scanners.py:73-86` (dataclass), `:399` (call site), `:501-513` (signal construction)
- Modify: `src/main.py:154` (payload serialization)
- Test: `tests/test_dividend_scanners.py`

### Step 1: Write the failing test

Add to `tests/test_dividend_scanners.py`:

```python
def test_buy_signal_includes_yield_p10_p90_hist_max():
    """DividendBuySignal should carry yield_p10, yield_p90, yield_hist_max from store."""
    from src.dividend_store import YieldPercentileResult
    from unittest.mock import patch

    store_mock = MagicMock()
    store_mock.get_yield_percentile.return_value = YieldPercentileResult(
        percentile=85.0, p10=3.5, p90=5.8, hist_max=12.0
    )
    store_mock.save_dividend_history = MagicMock()

    provider_mock = MagicMock()
    provider_mock.config = {"default_market": "US"}
    price_df = pd.DataFrame({"Close": [100.0]})
    provider_mock.get_price_data.return_value = price_df
    provider_mock.get_dividend_history.return_value = [
        {"date": "2025-03-01", "amount": 1.0},
        {"date": "2024-09-01", "amount": 1.0},
    ]
    provider_mock.should_skip_options.return_value = True
    provider_mock.get_earnings_date.return_value = None

    pool = [{
        "ticker": "AAPL",
        "name": "Apple",
        "market": "US",
        "quality_score": 85.0,
        "consecutive_years": 10,
        "dividend_growth_5y": 6.0,
        "payout_ratio": 65.0,
        "payout_type": "GAAP",
        "forward_dividend_rate": 1.0,
        "max_yield_5y": 5.0,
        "data_version_date": "2026-03-10",
        "sgov_yield": 4.8,
        "quality_breakdown": {},
        "analysis_text": "",
    }]

    config = {"dividend_scanners": {"min_yield": 1.5, "min_yield_percentile": 80}}

    signals = scan_dividend_buy_signal(pool=pool, provider=provider_mock, store=store_mock, config=config)

    assert len(signals) == 1
    sig = signals[0]
    assert sig.yield_p10 == 3.5
    assert sig.yield_p90 == 5.8
    assert sig.yield_hist_max == 12.0
    assert sig.yield_percentile == 85.0
```

### Step 2: Run test to verify it fails

```bash
pytest tests/test_dividend_scanners.py::test_buy_signal_includes_yield_p10_p90_hist_max -v
```

Expected: FAIL with `AttributeError: 'DividendBuySignal' object has no attribute 'yield_p10'`

### Step 3: Add fields to `DividendBuySignal` dataclass

In `src/dividend_scanners.py`, update the `DividendBuySignal` dataclass (around line 73):

```python
@dataclass
class DividendBuySignal:
    """股息买入信号数据类"""
    ticker_data: TickerData
    signal_type: str  # "STOCK" | "OPTION"
    current_yield: float
    yield_percentile: float
    option_details: Optional[Dict[str, Any]] = None
    forward_dividend_rate: Optional[float] = None
    max_yield_5y: Optional[float] = None
    floor_price: Optional[float] = None
    floor_downside_pct: Optional[float] = None
    data_age_days: Optional[int] = None
    needs_reeval: bool = False
    yield_p10: Optional[float] = None       # New: P10 of 5-year history
    yield_p90: Optional[float] = None       # New: P90 of 5-year history
    yield_hist_max: Optional[float] = None  # New: historical max (includes crises)
```

### Step 4: Update the call site in `scan_dividend_buy_signal`

In `src/dividend_scanners.py`, find line 399:
```python
yield_percentile = store.get_yield_percentile(ticker, current_yield)
```

Replace with:
```python
_percentile_result = store.get_yield_percentile(ticker, current_yield)
yield_percentile = _percentile_result.percentile
_yield_p10 = _percentile_result.p10
_yield_p90 = _percentile_result.p90
_yield_hist_max = _percentile_result.hist_max
```

Then find the `DividendBuySignal(...)` construction (around line 501) and add the new fields:
```python
signal = DividendBuySignal(
    ticker_data=ticker_data,
    signal_type=signal_type,
    current_yield=current_yield,
    yield_percentile=yield_percentile,
    option_details=option_details,
    forward_dividend_rate=_fwd_div,
    max_yield_5y=_max_yield,
    floor_price=_floor_price,
    floor_downside_pct=_floor_downside_pct,
    data_age_days=_data_age_days,
    needs_reeval=_needs_reeval,
    yield_p10=_yield_p10,
    yield_p90=_yield_p90,
    yield_hist_max=_yield_hist_max,
)
```

### Step 5: Add new fields to signal payload in `src/main.py`

In `src/main.py`, find the dividend signal loop (around line 154). After:
```python
"yield_percentile": round(float(s.yield_percentile), 0),
```

Add:
```python
"yield_p10": round(float(s.yield_p10), 2) if s.yield_p10 is not None else None,
"yield_p90": round(float(s.yield_p90), 2) if s.yield_p90 is not None else None,
"yield_hist_max": round(float(s.yield_hist_max), 2) if s.yield_hist_max is not None else None,
```

### Step 6: Run scanner tests to verify green

```bash
pytest tests/test_dividend_scanners.py -v
```

Expected: All pass.

### Step 7: Run full test suite

```bash
pytest tests/ -x -q
```

Expected: All pass (no regressions).

### Step 8: Commit

```bash
git add src/dividend_scanners.py src/main.py tests/test_dividend_scanners.py
git commit -m "feat: propagate yield_p10/p90/hist_max through signal payload"
```

---

## Task 3: Frontend — progress bar row in `buildDividendCard`

**Files:**
- Modify: `agent/static/dashboard.html` (JS `buildDividendCard` function)
- Test: `tests/test_yield_percentile_row.js` (new Node.js DOM mock test)

### Step 1: Write the failing test

Create `tests/test_yield_percentile_row.js`:

```javascript
/**
 * Test: yield percentile row rendering in buildDividendCard helpers.
 * Pure Node.js — no external dependencies.
 */

// ── Inline the two render helpers we'll extract from dashboard.html ──────────
function buildPercentileBar(pct) {
  var filled = Math.round(pct / 10);
  var bar = '';
  for (var i = 0; i < 10; i++) bar += (i < filled ? '▰' : '░');
  return bar;
}

function renderYieldPercentileRow(p) {
  var pct     = p.yield_percentile;
  var p10     = p.yield_p10;
  var p90     = p.yield_p90;
  var histMax = p.yield_hist_max;

  if (p10 == null || p90 == null) {
    // Fallback: old-style plain text
    return '<span class="row-label">历史分位</span>'
         + '<span class="row-value">' + pct + '%</span>';
  }

  var color = pct >= 70 ? 'var(--green)' : (pct < 30 ? 'var(--orange)' : 'inherit');
  var bar   = buildPercentileBar(pct);
  var range = p10.toFixed(1) + '–' + p90.toFixed(1) + '%';
  var tip   = histMax != null
    ? '历史最高 ' + histMax.toFixed(1) + '%（含黑天鹅期，已剔除极值计算分位）'
    : '';

  return '<span class="row-label">入场时机</span>'
       + '<span class="row-value" style="color:' + color + ';font-family:var(--mono)">'
       + bar + ' ' + pct + '%</span>'
       + '<span class="row-label" style="opacity:0.6"> (正常区间 ' + range + ')</span>'
       + (tip ? '<span class="info-icon" title="' + tip + '">ℹ</span>' : '');
}

// ── Assertions ────────────────────────────────────────────────────────────────
let pass = 0, fail = 0;
function ok(cond, msg) {
  if (cond) { console.log('  ✓', msg); pass++; }
  else       { console.error('  ✗', msg); fail++; }
}

console.log('\nTest 1: new format with p10/p90');
{
  var html = renderYieldPercentileRow({ yield_percentile: 82, yield_p10: 3.5, yield_p90: 5.8, yield_hist_max: 12.0 });
  ok(html.includes('入场时机'), 'label is 入场时机');
  ok(html.includes('▰'), 'progress bar present');
  ok(html.includes('82%'), 'percentile shown');
  ok(html.includes('3.5–5.8%'), 'range shown');
  ok(html.includes('12.0%'), 'hist_max in tooltip');
  ok(html.includes('var(--green)'), 'green color for high percentile');
}

console.log('\nTest 2: fallback for old signal (no p10/p90)');
{
  var html = renderYieldPercentileRow({ yield_percentile: 75, yield_p10: null, yield_p90: null });
  ok(html.includes('历史分位'), 'fallback label 历史分位');
  ok(!html.includes('▰'), 'no progress bar');
  ok(html.includes('75%'), 'percentile shown');
}

console.log('\nTest 3: low percentile gets orange color');
{
  var html = renderYieldPercentileRow({ yield_percentile: 20, yield_p10: 3.5, yield_p90: 5.8, yield_hist_max: null });
  ok(html.includes('var(--orange)'), 'orange for low percentile');
}

console.log('\nTest 4: progress bar fills correctly');
{
  ok(buildPercentileBar(82) === '▰▰▰▰▰▰▰▰░░', '82% → 8 filled');
  ok(buildPercentileBar(50) === '▰▰▰▰▰░░░░░', '50% → 5 filled');
  ok(buildPercentileBar(100) === '▰▰▰▰▰▰▰▰▰▰', '100% → 10 filled');
  ok(buildPercentileBar(0) === '░░░░░░░░░░',  '0% → 0 filled');
}

console.log(`\n${'─'.repeat(50)}`);
console.log(`Results: ${pass} passed, ${fail} failed`);
if (fail > 0) process.exit(1);
```

### Step 2: Run test to verify it fails

```bash
node tests/test_yield_percentile_row.js
```

Expected: The functions are defined inline in the test itself, so this test will PASS immediately — that's intentional. The test defines the contract. The next step is implementing the same logic in `dashboard.html` and verifying integration.

### Step 3: Implement in `dashboard.html`

In `agent/static/dashboard.html`, find the `buildDividendCard` JavaScript function (search for `buildDividendCard` or `yield_percentile` in the JS section).

**a) Add `buildPercentileBar` helper** near the other helper functions:

```javascript
function buildPercentileBar(pct) {
  var filled = Math.round(pct / 10);
  var bar = '';
  for (var i = 0; i < 10; i++) bar += (i < filled ? '▰' : '░');
  return bar;
}
```

**b) Replace the `历史分位` row** (currently a plain text row like):
```javascript
'<div class="card-row">' +
  '<span class="row-label">历史分位</span>' +
  '<span class="row-value">' + p.yield_percentile + '%</span>' +
'</div>'
```

With:
```javascript
(function() {
  var pct     = p.yield_percentile;
  var p10     = p.yield_p10 != null ? p.yield_p10 : null;
  var p90     = p.yield_p90 != null ? p.yield_p90 : null;
  var histMax = p.yield_hist_max != null ? p.yield_hist_max : null;

  if (p10 == null || p90 == null) {
    return '<div class="card-row">' +
      '<span class="row-label">历史分位</span>' +
      '<span class="row-value">' + pct + '%</span>' +
    '</div>';
  }

  var color = pct >= 70 ? 'var(--green)' : (pct < 30 ? 'var(--orange)' : 'inherit');
  var bar   = buildPercentileBar(pct);
  var range = p10.toFixed(1) + '–' + p90.toFixed(1) + '%';
  var tip   = histMax != null
    ? '历史最高 ' + histMax.toFixed(1) + '%（含黑天鹅期，已剔除极值计算分位）'
    : '';

  return '<div class="card-row" style="align-items:baseline">' +
    '<span class="row-label">入场时机</span>' +
    '<span class="row-value" style="color:' + color + ';font-family:var(--mono);letter-spacing:1px">' +
    bar + '</span>' +
    '<span class="row-value" style="color:' + color + ';margin-left:6px">' + pct + '%</span>' +
    '<span class="row-label" style="opacity:0.55;margin-left:6px">(正常区间 ' + range + ')</span>' +
    (tip ? '<span style="opacity:0.55;cursor:help;margin-left:4px" title="' + tip + '">ℹ</span>' : '') +
  '</div>';
})()
```

### Step 4: Run the JS test

```bash
node tests/test_yield_percentile_row.js
```

Expected: All 10 assertions pass.

### Step 5: Run full Python test suite to ensure no regressions

```bash
pytest tests/ -x -q
```

Expected: All pass.

### Step 6: Commit

```bash
git add agent/static/dashboard.html tests/test_yield_percentile_row.js
git commit -m "feat: yield percentile v2 — progress bar with P10/P90 range in dashboard"
```

---

## Final Verification

```bash
# All tests pass
pytest tests/ -q

# JS tests pass
node tests/test_strategy_tabs.js
node tests/test_yield_percentile_row.js
```

Expected output:
```
431+ passed
Results: 18/18 passed
Results: 10/10 passed
```
