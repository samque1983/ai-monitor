# Dividend Card UX v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade dividend signal cards with strategy selector (现货/Sell Put tabs), SGOV yield stacking, structured analysis text, and watch/关注机会 persistence.

**Architecture:** Backend adds `sgov_yield` to weekly scan (stored); `sgov_adjusted_apy`, `recommended_strategy`, `recommended_reason` computed rule-based in daily signal scan from live option data. Frontend adds tab UI, analysis parser, localStorage watch state.

**Tech Stack:** Python dataclasses, SQLite ALTER TABLE migration, vanilla JS/CSS in `agent/static/dashboard.html`

**Design doc:** `docs/plans/2026-03-11-dividend-card-ux-design.md`

**Architectural note vs. design doc:** Design doc places `recommended_strategy` generation in `financial_service.py` (weekly scan). This is infeasible — `scan_dividend_pool_weekly` has no option data. Instead: `sgov_yield` is fetched in weekly scan and stored; `recommended_strategy` and `sgov_adjusted_apy` are computed rule-based inline in `scan_dividend_buy_signal` after `option_details` is known. Only `sgov_yield` is added to the DB schema (the others are ephemeral).

---

## Task 1: TickerData new fields

**Files:**
- Modify: `src/data_engine.py:49` (after `needs_reeval: bool = False`)
- Test: `tests/test_data_engine.py`

**Step 1: Write failing test**

In `tests/test_data_engine.py`, add a test that instantiates TickerData with the new fields:

```python
def test_ticker_data_new_sgov_fields():
    td = TickerData(
        ticker="AAPL", name="Apple", market="US",
        last_price=150.0, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=0.0,
        earnings_date=None, days_to_earnings=None,
        sgov_yield=4.8,
        sgov_adjusted_apy=26.8,
        recommended_strategy="sell_put",
        recommended_reason="综合年化显著高于股息率",
    )
    assert td.sgov_yield == 4.8
    assert td.sgov_adjusted_apy == 26.8
    assert td.recommended_strategy == "sell_put"
    assert td.recommended_reason == "综合年化显著高于股息率"

def test_ticker_data_new_fields_default_none():
    td = TickerData(
        ticker="AAPL", name="Apple", market="US",
        last_price=150.0, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=0.0,
        earnings_date=None, days_to_earnings=None,
    )
    assert td.sgov_yield is None
    assert td.sgov_adjusted_apy is None
    assert td.recommended_strategy is None
    assert td.recommended_reason is None
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_data_engine.py::test_ticker_data_new_sgov_fields -v
```
Expected: `TypeError: __init__() got an unexpected keyword argument 'sgov_yield'`

**Step 3: Add 4 fields to TickerData**

In `src/data_engine.py`, after line 49 (`needs_reeval: bool = False`):

```python
    # Phase 4 / Dividend Card UX v2: SGOV + strategy fields (computed at signal time)
    sgov_yield: Optional[float] = None          # SGOV annualized yield % (US only)
    sgov_adjusted_apy: Optional[float] = None   # option_apy + sgov_yield
    recommended_strategy: Optional[str] = None  # "sell_put" | "spot"
    recommended_reason: Optional[str] = None    # one-sentence Chinese reason
```

**Step 4: Run tests**

```bash
pytest tests/test_data_engine.py -v
```
Expected: All pass.

**Step 5: Commit**

```bash
git add src/data_engine.py tests/test_data_engine.py
git commit -m "feat: add sgov_yield, sgov_adjusted_apy, recommended_strategy/reason to TickerData"
```

---

## Task 2: dividend_store.py — sgov_yield schema migration + save/load

**Files:**
- Modify: `src/dividend_store.py:60-69` (migration loop), `src/dividend_store.py:123-146` (save_pool INSERT), `src/dividend_store.py:215-234` (get_pool_records SELECT)
- Test: `tests/test_dividend_store.py`

**Step 1: Write failing tests**

In `tests/test_dividend_store.py`:

```python
def test_save_and_load_sgov_yield(tmp_path):
    from src.dividend_store import DividendStore
    from src.data_engine import TickerData
    store = DividendStore(str(tmp_path / "test.db"))
    td = TickerData(
        ticker="AAPL", name="Apple", market="US",
        last_price=0.0, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=0.0,
        earnings_date=None, days_to_earnings=None,
        dividend_quality_score=80.0,
        sgov_yield=4.8,
    )
    store.save_pool([td], "2026-03-11")
    records = store.get_pool_records()
    assert records[0]["sgov_yield"] == 4.8

def test_sgov_yield_defaults_none(tmp_path):
    from src.dividend_store import DividendStore
    from src.data_engine import TickerData
    store = DividendStore(str(tmp_path / "test.db"))
    td = TickerData(
        ticker="VZ", name="Verizon", market="US",
        last_price=0.0, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=0.0,
        earnings_date=None, days_to_earnings=None,
    )
    store.save_pool([td], "2026-03-11")
    records = store.get_pool_records()
    assert records[0]["sgov_yield"] is None
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_dividend_store.py::test_save_and_load_sgov_yield -v
```
Expected: `KeyError: 'sgov_yield'` or assertion error.

**Step 3: Add sgov_yield to migration loop**

In `src/dividend_store.py`, in the existing migration loop (lines 60-69), add `sgov_yield`:

```python
        for col, col_type in [
            ("quality_breakdown", "TEXT"),
            ("analysis_text", "TEXT"),
            ("forward_dividend_rate", "REAL"),
            ("max_yield_5y", "REAL"),
            ("data_version_date", "TEXT"),
            ("sgov_yield", "REAL"),          # NEW
        ]:
```

**Step 4: Add to save_pool INSERT**

In `save_pool()`, expand the INSERT statement and values tuple:

```python
            cursor.execute("""
                INSERT INTO dividend_pool (
                    ticker, version, name, market, quality_score,
                    consecutive_years, dividend_growth_5y, payout_ratio,
                    payout_type, dividend_yield, roe, debt_to_equity,
                    industry, sector, added_date,
                    quality_breakdown, analysis_text, forward_dividend_rate,
                    max_yield_5y, data_version_date, sgov_yield
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker.ticker, version, ticker.name, ticker.market,
                ticker.dividend_quality_score, ticker.consecutive_years,
                ticker.dividend_growth_5y, ticker.payout_ratio,
                getattr(ticker, 'payout_type', None),
                getattr(ticker, 'dividend_yield', None),
                ticker.roe, ticker.debt_to_equity,
                ticker.industry, ticker.sector,
                date.today().isoformat(),
                json.dumps(getattr(ticker, 'quality_breakdown', None) or {}),
                getattr(ticker, 'analysis_text', None) or "",
                getattr(ticker, 'forward_dividend_rate', None),
                getattr(ticker, 'max_yield_5y', None),
                date.today().isoformat(),
                getattr(ticker, 'sgov_yield', None),
            ))
```

**Step 5: Add to get_pool_records SELECT**

In `get_pool_records()`, expand the SELECT and cols list:

```python
        cursor.execute("""
            SELECT ticker, name, market, quality_score, consecutive_years,
                   dividend_growth_5y, payout_ratio, payout_type, dividend_yield,
                   roe, debt_to_equity, industry, sector,
                   quality_breakdown, analysis_text, forward_dividend_rate,
                   max_yield_5y, data_version_date, sgov_yield
            FROM dividend_pool
            ...
        """)
        cols = [
            "ticker", "name", "market", "quality_score", "consecutive_years",
            "dividend_growth_5y", "payout_ratio", "payout_type", "dividend_yield",
            "roe", "debt_to_equity", "industry", "sector",
            "quality_breakdown", "analysis_text", "forward_dividend_rate",
            "max_yield_5y", "data_version_date", "sgov_yield",
        ]
```

**Step 6: Run tests**

```bash
pytest tests/test_dividend_store.py -v
```
Expected: All pass.

**Step 7: Commit**

```bash
git add src/dividend_store.py tests/test_dividend_store.py
git commit -m "feat: add sgov_yield column to dividend_pool store"
```

---

## Task 3: get_sgov_yield() + wire into weekly scan

**Files:**
- Modify: `src/dividend_scanners.py:57` (top of `scan_dividend_pool_weekly`, before ticker loop)
- Add function near top of module (after `_to_dt`)
- Test: `tests/test_dividend_scanners.py`

**Step 1: Write failing tests**

In `tests/test_dividend_scanners.py`:

```python
def test_get_sgov_yield_returns_float(monkeypatch):
    import yfinance as yf
    from src.dividend_scanners import get_sgov_yield

    mock_info = {"yield": 0.0523}  # 5.23%
    monkeypatch.setattr(yf.Ticker, "info", property(lambda self: mock_info))
    result = get_sgov_yield()
    assert result == 5.23

def test_get_sgov_yield_fallback_on_error(monkeypatch):
    import yfinance as yf
    from src.dividend_scanners import get_sgov_yield

    def bad_info(self):
        raise RuntimeError("network error")
    monkeypatch.setattr(yf.Ticker, "info", property(bad_info))
    result = get_sgov_yield()
    assert result == 4.8

def test_weekly_scan_sets_sgov_yield_for_us(mock_provider, mock_fs, base_config):
    # Given a US ticker passes all filters
    # When scan_dividend_pool_weekly runs
    # Then ticker_data.sgov_yield is set to the fetched SGOV yield (not None)
    from unittest.mock import patch
    from src.dividend_scanners import scan_dividend_pool_weekly
    with patch("src.dividend_scanners.get_sgov_yield", return_value=4.8):
        results = scan_dividend_pool_weekly(["AAPL"], mock_provider, mock_fs, base_config)
    assert len(results) == 1
    assert results[0].sgov_yield == 4.8

def test_weekly_scan_sgov_none_for_hk(mock_provider_hk, mock_fs, base_config):
    # Given a HK ticker
    # Then ticker_data.sgov_yield is None
    from unittest.mock import patch
    from src.dividend_scanners import scan_dividend_pool_weekly
    with patch("src.dividend_scanners.get_sgov_yield", return_value=4.8):
        results = scan_dividend_pool_weekly(["0005.HK"], mock_provider_hk, mock_fs, base_config)
    assert len(results) == 1
    assert results[0].sgov_yield is None
```

(Note: use existing test fixtures or add minimal ones needed for the weekly scan mock setup.)

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_dividend_scanners.py::test_get_sgov_yield_returns_float -v
```
Expected: `ImportError: cannot import name 'get_sgov_yield'`

**Step 3: Add get_sgov_yield() to dividend_scanners.py**

After the `_to_dt` helper (around line 38), add:

```python
def get_sgov_yield() -> float:
    """Fetch current SGOV annualized yield. Returns 4.8 fallback on failure."""
    try:
        import yfinance as yf
        info = yf.Ticker("SGOV").info
        return round(float(info.get("yield", 0.048)) * 100, 2)
    except Exception:
        return 4.8
```

**Step 4: Wire into scan_dividend_pool_weekly**

In `scan_dividend_pool_weekly`, just before the `for ticker in universe:` loop (after line 102 `results = []`), add:

```python
    # Fetch SGOV yield once for the whole scan (US cash collateral yield)
    sgov_yield = get_sgov_yield()
    logger.info(f"SGOV yield for this scan: {sgov_yield:.2f}%")
```

In `scan_dividend_pool_weekly`, in the TickerData constructor (around line 238), add the new fields:

```python
                # SGOV yield: US market only (SGOV is a US short-term treasury ETF)
                sgov_yield=sgov_yield if classify_market(ticker) == "US" else None,
```

**Step 5: Run tests**

```bash
pytest tests/test_dividend_scanners.py -v
```
Expected: All pass.

**Step 6: Commit**

```bash
git add src/dividend_scanners.py tests/test_dividend_scanners.py
git commit -m "feat: add get_sgov_yield(), wire sgov_yield into weekly scan for US tickers"
```

---

## Task 4: _get_recommended_strategy() + wire into daily scan

**Files:**
- Modify: `src/dividend_scanners.py` (add function, wire in `scan_dividend_buy_signal`)
- Test: `tests/test_dividend_scanners.py`

**Step 1: Write failing tests**

```python
from src.dividend_scanners import _get_recommended_strategy

def test_recommend_spot_no_options():
    strategy, reason = _get_recommended_strategy(
        ticker="0005.HK", current_yield=5.0, sgov_adjusted_apy=None,
        option_available=False, option_illiquid=False,
    )
    assert strategy == "spot"
    assert "无期权" in reason

def test_recommend_spot_illiquid():
    strategy, reason = _get_recommended_strategy(
        ticker="AAPL", current_yield=5.0, sgov_adjusted_apy=22.0,
        option_available=True, option_illiquid=True,
    )
    assert strategy == "spot"
    assert "流动性" in reason

def test_recommend_sell_put_when_superior():
    # sgov_adjusted_apy > current_yield * 1.5 → sell_put
    strategy, reason = _get_recommended_strategy(
        ticker="AAPL", current_yield=5.0, sgov_adjusted_apy=8.5,
        option_available=True, option_illiquid=False,
    )
    assert strategy == "sell_put"

def test_recommend_spot_when_option_not_much_better():
    # sgov_adjusted_apy ≤ current_yield * 1.5 → spot
    strategy, reason = _get_recommended_strategy(
        ticker="AAPL", current_yield=5.0, sgov_adjusted_apy=6.0,
        option_available=True, option_illiquid=False,
    )
    assert strategy == "spot"

def test_daily_scan_sets_recommended_strategy_on_signal(mock_provider_with_options, mock_store, base_config):
    """When option data is available, signal's ticker_data has recommended_strategy set."""
    from src.dividend_scanners import scan_dividend_buy_signal
    from unittest.mock import patch
    pool = [{"ticker": "AAPL", "market": "US", "sgov_yield": 4.8, ...}]  # minimal pool record
    signals = scan_dividend_buy_signal(pool, mock_provider_with_options, mock_store, base_config)
    assert len(signals) == 1
    assert signals[0].ticker_data.recommended_strategy in ("spot", "sell_put")
    assert signals[0].ticker_data.recommended_reason is not None
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_dividend_scanners.py::test_recommend_spot_no_options -v
```
Expected: `ImportError: cannot import name '_get_recommended_strategy'`

**Step 3: Add _get_recommended_strategy() to dividend_scanners.py**

After `get_sgov_yield()` (before `scan_dividend_pool_weekly`):

```python
def _get_recommended_strategy(
    ticker: str,
    current_yield: float,
    sgov_adjusted_apy: Optional[float],
    option_available: bool,
    option_illiquid: bool,
) -> tuple:
    """Rule-based strategy recommendation. Returns (strategy, reason_text)."""
    if not option_available:
        return "spot", "无期权市场，现货持仓吃股息"
    if option_illiquid:
        return "spot", "期权流动性不足，现货持仓更稳"
    if sgov_adjusted_apy is not None and sgov_adjusted_apy > current_yield * 1.5:
        multiplier = sgov_adjusted_apy / current_yield
        return (
            "sell_put",
            f"Sell Put 综合年化 {sgov_adjusted_apy:.1f}% 是股息率 {current_yield:.1f}% 的 {multiplier:.1f} 倍",
        )
    return "spot", "Sell Put 综合年化与股息率接近，现货持仓吃股息更稳"
```

**Step 4: Wire into scan_dividend_buy_signal**

In `scan_dividend_buy_signal`, after the `if option_details and not option_details.get("sell_put_illiquid"):` block (after line 432, before `_floor_downside_pct` computation), add:

```python
                # Compute SGOV-adjusted APY and recommended strategy
                _sgov = ticker_data.sgov_yield  # loaded from pool record
                _option_illiquid = option_details is not None and option_details.get("sell_put_illiquid", False)
                _option_available = (option_details is not None) and record.get("market", "US") == "US"
                _option_apy = option_details.get("apy") if option_details and not _option_illiquid else None
                if _option_apy is not None and _sgov is not None:
                    ticker_data.sgov_adjusted_apy = round(_option_apy + _sgov, 2)
                _rec_strategy, _rec_reason = _get_recommended_strategy(
                    ticker=ticker,
                    current_yield=current_yield,
                    sgov_adjusted_apy=ticker_data.sgov_adjusted_apy,
                    option_available=_option_available,
                    option_illiquid=_option_illiquid,
                )
                ticker_data.recommended_strategy = _rec_strategy
                ticker_data.recommended_reason = _rec_reason
```

Also update the TickerData construction in `scan_dividend_buy_signal` (line 375-402) to load `sgov_yield` from pool record:

```python
                ticker_data = TickerData(
                    ...
                    analysis_text=record.get("analysis_text") or "",
                    sgov_yield=record.get("sgov_yield"),   # NEW: loaded from store
                )
```

**Step 5: Run tests**

```bash
pytest tests/test_dividend_scanners.py -v
```
Expected: All pass.

**Step 6: Commit**

```bash
git add src/dividend_scanners.py tests/test_dividend_scanners.py
git commit -m "feat: add _get_recommended_strategy(), wire sgov_adjusted_apy + strategy into daily scan"
```

---

## Task 5: Frontend — header spacing fix

**Files:**
- Modify: `agent/static/dashboard.html` (CSS `.card-head-left`)

**Step 1: Find the CSS rule**

Search for `.card-head-left` in `dashboard.html`. The current rule has `flex: 1` which stretches it across the full width.

**Step 2: Remove flex: 1**

Change:
```css
.card-head-left { flex: 1; ... }
```
to:
```css
.card-head-left { ... }  /* remove flex: 1; gap handled by .card-head { gap: 12px } */
```

**Step 3: Verify visually**

Open `dashboard.html` in browser. Confirm ticker/badge group and KPI number appear close together (natural gap ~12px), not stretched across card width.

**Step 4: Commit**

```bash
git add agent/static/dashboard.html
git commit -m "fix: remove flex:1 from .card-head-left to fix header spacing"
```

---

## Task 6: Frontend — strategy tab UI

**Files:**
- Modify: `agent/static/dashboard.html` (`cardDividend` JS function + CSS)

**Step 1: Read current cardDividend function**

Read `agent/static/dashboard.html` to find the `cardDividend(s)` function and the "建议买入" section (dc-group for entry strategy).

**Step 2: Add CSS for strategy tabs**

In the `<style>` block, add:

```css
/* ── Strategy Tabs ────────────────── */
.strategy-tabs {
  display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap;
}
.strategy-tab {
  padding: 5px 14px; border-radius: 20px; font-size: 12px; font-weight: 500;
  border: 1px solid var(--border); background: var(--surface-2);
  color: var(--text-2); cursor: pointer; transition: all 0.15s;
  user-select: none;
}
.strategy-tab.active {
  background: var(--blue); border-color: var(--blue);
  color: #fff; font-weight: 600;
}
.strategy-tab.active-green {
  background: rgba(52,199,89,0.15); border-color: rgba(52,199,89,0.4);
  color: var(--green);
}
.strategy-tab.disabled {
  opacity: 0.38; cursor: default; pointer-events: none;
}
.strategy-tab.disabled-reason { cursor: pointer; }

.strategy-panel { display: none; }
.strategy-panel.visible { display: block; }

.strategy-row { display: flex; justify-content: space-between; align-items: baseline;
  padding: 6px 0; border-bottom: 1px solid var(--border-2); }
.strategy-row:last-child { border-bottom: none; }
.strategy-row-label { font-size: 12px; color: var(--text-2); }
.strategy-row-value { font-family: 'DM Mono', monospace; font-size: 14px; color: var(--text); }
.strategy-row-value.highlight { color: var(--amber); font-size: 16px; font-weight: 500; }

.strategy-ai-reason {
  font-size: 12px; color: var(--text-2); line-height: 1.6;
  padding: 8px 0; border-bottom: 1px solid var(--border-2); margin-bottom: 8px;
}
.strategy-ai-reason .ai-label {
  font-size: 10px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--text-3); margin-bottom: 2px;
}
```

**Step 3: Replace "建议买入" dc-group in cardDividend**

Find the block rendering `建议买入` rows inside `cardDividend`. Replace it with this strategy tab section:

```javascript
function buildStrategySection(s) {
  const td = s.ticker_data || {};
  const opt = s.option_details || {};
  const market = td.market || 'US';
  const isUS = market === 'US';
  const illiquid = opt.sell_put_illiquid;
  const hasOption = isUS && opt.apy != null && !illiquid;
  const sgov = td.sgov_yield;
  const sgov_apy = td.sgov_adjusted_apy;
  const rec = td.recommended_strategy || (hasOption ? 'sell_put' : 'spot');
  const recReason = td.recommended_reason || '';

  // Tab states
  const tabSellPut = isUS
    ? (illiquid ? 'disabled-reason' : (hasOption ? '' : 'disabled'))
    : 'disabled';
  const tabSpread = 'disabled';

  const activeSpot = rec === 'spot' ? 'active active-green' : '';
  const activeSellPut = rec === 'sell_put' && hasOption ? 'active' : '';

  // Sell Put panel content
  let sellPutPanel = '';
  if (hasOption) {
    sellPutPanel = `
      <div class="strategy-row">
        <span class="strategy-row-label">行权价</span>
        <span class="strategy-row-value">$${opt.strike?.toFixed(2)} · ${opt.dte} DTE</span>
      </div>
      <div class="strategy-row">
        <span class="strategy-row-label">权利金</span>
        <span class="strategy-row-value">$${opt.bid?.toFixed(2)} → ${opt.apy?.toFixed(1)}% 年化</span>
      </div>
      ${sgov != null ? `<div class="strategy-row">
        <span class="strategy-row-label">SGOV 叠加</span>
        <span class="strategy-row-value">+${sgov.toFixed(1)}%<span style="color:var(--text-3);font-size:11px;margin-left:6px">现金在短期国债期间收益</span></span>
      </div>` : ''}
      <div class="strategy-row">
        <span class="strategy-row-label">综合年化</span>
        <span class="strategy-row-value highlight">${sgov_apy != null ? sgov_apy.toFixed(1) : opt.apy?.toFixed(1)}%
          <span style="color:var(--text-3);font-size:11px;margin-left:6px">${sgov_apy != null ? '(Sell Put + SGOV 叠加)' : '(Sell Put)'}</span>
        </span>
      </div>`;
  }

  // Spot panel content
  const spotPanel = `
    <div class="strategy-row">
      <span class="strategy-row-label">当前股息率</span>
      <span class="strategy-row-value highlight">${s.current_yield?.toFixed(2)}%</span>
    </div>
    <div class="strategy-row">
      <span class="strategy-row-label">历史分位</span>
      <span class="strategy-row-value">${s.yield_percentile?.toFixed(0)}%</span>
    </div>`;

  // Tab click reason for illiquid/no-options
  const illiquidMsg = illiquid
    ? `流动性不足，价差 ${(opt.spread_pct * 100)?.toFixed(1)}%`
    : (!isUS ? '港股/A股暂无期权市场' : '');

  return `
<div class="strategy-tabs" id="stabs-${td.ticker}">
  <span class="strategy-tab ${activeSpot}" onclick="switchTab('${td.ticker}','spot',this)">现货</span>
  <span class="strategy-tab ${tabSellPut} ${activeSellPut}"
        onclick="${illiquidMsg ? `showTabReason('${illiquidMsg}',this)` : `switchTab('${td.ticker}','sell_put',this)`}"
    >Sell Put</span>
  <span class="strategy-tab ${tabSpread}"
        onclick="showTabReason('功能开发中',this)">Spread ·</span>
</div>
${recReason ? `<div class="strategy-ai-reason"><div class="ai-label">AI 推荐</div>${recReason}</div>` : ''}
<div class="strategy-panel ${rec === 'spot' ? 'visible' : ''}" id="spanel-${td.ticker}-spot">${spotPanel}</div>
<div class="strategy-panel ${rec === 'sell_put' && hasOption ? 'visible' : ''}" id="spanel-${td.ticker}-sell_put">${sellPutPanel}</div>`;
}
```

**Step 4: Add tab switching JS functions**

In the `<script>` block, add:

```javascript
function switchTab(ticker, strategy, tabEl) {
  // Deactivate all tabs for this ticker
  document.querySelectorAll(`#stabs-${ticker} .strategy-tab`).forEach(t => {
    t.classList.remove('active', 'active-green');
  });
  // Activate clicked tab
  tabEl.classList.add(strategy === 'spot' ? 'active-green' : 'active');
  // Show correct panel
  ['spot', 'sell_put'].forEach(s => {
    const p = document.getElementById(`spanel-${ticker}-${s}`);
    if (p) p.classList.toggle('visible', s === strategy);
  });
}

function showTabReason(msg, el) {
  // Show tooltip-like reason
  const existing = el.querySelector('.tab-tooltip');
  if (existing) { existing.remove(); return; }
  const tip = document.createElement('span');
  tip.className = 'tab-tooltip';
  tip.textContent = msg;
  tip.style.cssText = 'position:absolute;background:var(--surface-2);border:1px solid var(--border);' +
    'padding:4px 8px;border-radius:6px;font-size:11px;white-space:nowrap;top:28px;left:0;z-index:10;color:var(--text-2)';
  el.style.position = 'relative';
  el.appendChild(tip);
  setTimeout(() => tip.remove(), 2500);
}
```

**Step 5: Update cardDividend to use buildStrategySection**

In `cardDividend(s)`, replace the "建议买入" dc-group HTML with a call to `buildStrategySection(s)`.

**Step 6: Commit**

```bash
git add agent/static/dashboard.html
git commit -m "feat: strategy tab UI — 现货/Sell Put tabs with SGOV stacking, AI recommendation"
```

---

## Task 7: Frontend — analysis text parser

**Files:**
- Modify: `agent/static/dashboard.html` (JS function + CSS)

**Step 1: Add CSS for structured analysis**

```css
/* ── Analysis dims ────────────────── */
.analysis-dim { padding: 10px 0; border-bottom: 1px solid var(--border-2); }
.analysis-dim:last-child { border-bottom: none; }
.analysis-dim-label {
  font-size: 11px; font-weight: 600; color: var(--text-3);
  letter-spacing: 0.05em; margin-bottom: 3px;
}
.analysis-dim-body { font-size: 13px; color: var(--text-2); line-height: 1.6; }
.analysis-dim-price {
  font-family: 'DM Mono', monospace; font-size: 15px;
  color: var(--amber); font-weight: 500; margin-top: 2px;
}
```

**Step 2: Add parseAnalysisText JS function**

```javascript
function parseAnalysisText(raw) {
  if (!raw) return null;
  const lineRe = /^(.+?)：(.+?)→\s*(.+)$/;
  const lines = raw.split('\n').filter(l => l.trim());
  const dims = lines.map(l => {
    const m = l.match(lineRe);
    return m ? { label: m[1].trim(), body: m[2].trim(), price: m[3].trim() } : null;
  }).filter(Boolean);
  return dims.length >= 2 ? dims : null;
}

function renderAnalysisText(raw) {
  const dims = parseAnalysisText(raw);
  if (!dims) {
    return `<div class="dc-body">${raw}</div>`;
  }
  return dims.map(d => `
    <div class="analysis-dim">
      <div class="analysis-dim-label">${d.label}</div>
      <div class="analysis-dim-body">${d.body}</div>
      <div class="analysis-dim-price">→ ${d.price}</div>
    </div>`).join('');
}
```

**Step 3: Use renderAnalysisText in cardDividend**

In `cardDividend`, find where `analysis_text` is rendered (currently as `<div class="dc-body">${s.ticker_data.analysis_text}</div>` or similar). Replace with:

```javascript
renderAnalysisText(s.ticker_data?.analysis_text || '')
```

**Step 4: Verify fallback**

Test with a signal that has non-standard analysis_text format — it should render as plain text, not crash.

**Step 5: Commit**

```bash
git add agent/static/dashboard.html
git commit -m "feat: analysis text parser — parse label:desc→price format into structured HTML dims"
```

---

## Task 8: Frontend — watch rename + localStorage

**Files:**
- Modify: `agent/static/dashboard.html` (watch section HTML + JS)

**Step 1: Rename "关注标的" → "关注机会" everywhere**

Search for `关注标的`, `关注此标的` in `dashboard.html`. Replace:
- Section title: `关注监控` → `关注机会`
- Button text: `关注此标的` → `关注此机会`
- Button watched state: → `已关注`

**Step 2: Add localStorage persistence JS**

```javascript
const WATCH_KEY = 'watched_opportunities';

function getWatched() {
  try { return JSON.parse(localStorage.getItem(WATCH_KEY) || '{}'); }
  catch { return {}; }
}

function toggleWatch(btn, ticker) {
  const watched = getWatched();
  const isWatched = !watched[ticker];
  if (isWatched) watched[ticker] = Date.now();
  else delete watched[ticker];
  localStorage.setItem(WATCH_KEY, JSON.stringify(watched));
  btn.classList.toggle('watched', isWatched);
  btn.querySelector('.watch-star').textContent = isWatched ? '★' : '☆';
  btn.querySelector('.watch-label').textContent = isWatched ? '已关注' : '关注此机会';
}

function initWatchStates() {
  const watched = getWatched();
  document.querySelectorAll('[data-watch-ticker]').forEach(btn => {
    const ticker = btn.dataset.watchTicker;
    if (watched[ticker]) {
      btn.classList.add('watched');
      btn.querySelector('.watch-star').textContent = '★';
      btn.querySelector('.watch-label').textContent = '已关注';
    }
  });
}
```

**Step 3: Update watch button HTML in cardDividend**

In `cardDividend`, find the watch button render. Update to use `data-watch-ticker` attribute and call `toggleWatch(this, ticker)`:

```javascript
`<button class="watch-btn" data-watch-ticker="${s.ticker_data.ticker}"
    onclick="toggleWatch(this, '${s.ticker_data.ticker}')">
  <span class="watch-star">☆</span>
  <span class="watch-label">关注此机会</span>
</button>`
```

**Step 4: Call initWatchStates after render**

At the end of the `renderDashboard()` function (after all cards are rendered), add:
```javascript
initWatchStates();
```

**Step 5: Verify persistence**

Open in browser, click watch button, reload page — confirm button shows `★ 已关注`.

**Step 6: Commit**

```bash
git add agent/static/dashboard.html
git commit -m "feat: watch rename to 关注机会 + localStorage persistence"
```

---

## Final Verification

```bash
# Run full test suite
pytest --tb=short -q

# Expected: all tests pass (no regressions from TickerData, store, scanners changes)
```

Confirm that existing scan tests still pass — the new fields are all `Optional` with `None` defaults so no existing test should break.

---

## File Change Summary

| File | Tasks | Key Changes |
|------|-------|-------------|
| `src/data_engine.py` | 1 | +4 optional fields on TickerData |
| `src/dividend_store.py` | 2 | +sgov_yield migration, save_pool, get_pool_records |
| `src/dividend_scanners.py` | 3, 4 | +get_sgov_yield(), +_get_recommended_strategy(), wire both |
| `agent/static/dashboard.html` | 5–8 | Header fix, strategy tabs, analysis parser, watch localStorage |
| `tests/test_data_engine.py` | 1 | New field tests |
| `tests/test_dividend_store.py` | 2 | sgov_yield save/load tests |
| `tests/test_dividend_scanners.py` | 3, 4 | get_sgov_yield, strategy recommendation tests |
