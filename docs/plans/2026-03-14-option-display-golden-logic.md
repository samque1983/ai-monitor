# Option Display & Golden Price Logic Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix three issues: skip options when price is already at/below golden price; add expiration date to signal payload; show full option contract in dashboard with mid price.

**Architecture:** Three independent changes across backend scanner logic, payload builder, and frontend template. No new abstractions needed — all changes are minimal targeted edits.

**Tech Stack:** Python (dividend_scanners.py, main.py), Jinja2/JS (dashboard.html)

---

### Task 1: Skip option when current price ≤ golden price

**Files:**
- Modify: `src/dividend_scanners.py:643-668`
- Test: `tests/test_dividend_scanners.py`

**Background:**
`scan_dividend_entry_daily()` currently always calls `scan_dividend_sell_put()` when options are enabled. The new logic: if `last_price <= golden_price`, bypass the option scan and force `recommended_strategy = "spot"` with a specific reason. When `golden_price` is None, existing fallback behaviour is unchanged.

**Step 1: Write the failing test**

Add to `tests/test_dividend_scanners.py` (append near the other `scan_dividend_entry_daily` tests, after the existing golden_price tests around line 1463):

```python
def test_scan_entry_skips_option_when_price_at_or_below_golden(mock_provider_fixture):
    """When current_price <= golden_price, option scan is skipped and spot is recommended."""
    from src.dividend_scanners import scan_dividend_entry_daily

    # golden_price = 100, current price = 98 (below)
    pool = [{
        "ticker": "KO",
        "market": "US",
        "annual_dividend": 1.84,
        "forward_dividend_rate": 1.84,
        "quality_score": 80.0,
        "consecutive_years": 10,
        "dividend_growth_5y": 3.0,
        "payout_ratio": 60.0,
        "payout_type": "GAAP",
        "max_yield_5y": 4.5,
        "floor_price": 80.0,
        "floor_price_raw": 78.0,
        "extreme_event_label": None,
        "extreme_event_price": None,
        "extreme_event_days": None,
        "golden_price": 100.0,
        "data_version_date": "2026-01-01",
        "sgov_yield": 4.8,
        "health_rationale": "Stable",
        "quality_breakdown": {},
        "analysis_text": "",
    }]

    # Provider returns price BELOW golden_price
    td = MagicMock()
    td.ticker = "KO"
    td.last_price = 98.0   # <= golden_price of 100.0
    td.dividend_yield = 1.84 / 98.0 * 100
    td.dividend_yield_5y_percentile = 92.0
    td.sgov_yield = 4.8
    td.sgov_adjusted_apy = None
    td.recommended_strategy = None
    td.recommended_reason = None
    mock_provider_fixture.get_ticker_data.return_value = td
    mock_provider_fixture.should_skip_options.return_value = False

    config = {
        "dividend_scanners": {
            "min_yield": 3.5,
            "min_yield_percentile": 80.0,
            "option": {
                "enabled": True,
                "min_dte": 45,
                "max_dte": 90,
                "target_strike_percentile": 90,
            }
        }
    }

    results = scan_dividend_entry_daily(pool=pool, provider=mock_provider_fixture, config=config)

    # Signal should still be generated (price at high yield)
    assert len(results) == 1
    sig = results[0]

    # Option must be skipped — price already below golden
    assert sig.option_details is None
    assert sig.ticker_data.recommended_strategy == "spot"
    assert "黄金位" in sig.ticker_data.recommended_reason

    # Provider must NOT have been called to fetch options
    mock_provider_fixture.get_options_chain.assert_not_called()
```

**Step 2: Run test to verify it fails**

```bash
cd /Users/q/code/ai-monitor
python -m pytest tests/test_dividend_scanners.py::test_scan_entry_skips_option_when_price_at_or_below_golden -v
```

Expected: FAIL — test asserts `option_details is None` but current code still calls the option scan.

**Step 3: Implement the change**

In `src/dividend_scanners.py`, find the block at lines ~648-661:

```python
                    # 从 pool record 读取黄金位（周扫描时计算并存储）
                    _golden_price_from_pool = record.get("golden_price")

                    # 调用scan_dividend_sell_put获取期权详情
                    option_details = scan_dividend_sell_put(
                        ticker_data=ticker_data,
                        provider=provider,
                        annual_dividend=annual_dividend,
                        target_yield=target_yield,
                        min_dte=option_config.get("min_dte", 45),
                        max_dte=option_config.get("max_dte", 90),
                        golden_price=_golden_price_from_pool,
                        current_price=last_price,
                    )
```

Replace with:

```python
                    # 从 pool record 读取黄金位（周扫描时计算并存储）
                    _golden_price_from_pool = record.get("golden_price")

                    # 如果当前价已低于或等于黄金位，直接现货买入，跳过期权
                    if _golden_price_from_pool and last_price <= _golden_price_from_pool:
                        logger.info(
                            f"{ticker}: Price ${last_price:.2f} <= golden ${_golden_price_from_pool:.2f}, "
                            f"skipping option scan — recommend spot"
                        )
                        ticker_data.recommended_strategy = "spot"
                        ticker_data.recommended_reason = "当前价已低于黄金位，直接现货买入"
                    else:
                        # 调用scan_dividend_sell_put获取期权详情
                        option_details = scan_dividend_sell_put(
                            ticker_data=ticker_data,
                            provider=provider,
                            annual_dividend=annual_dividend,
                            target_yield=target_yield,
                            min_dte=option_config.get("min_dte", 45),
                            max_dte=option_config.get("max_dte", 90),
                            golden_price=_golden_price_from_pool,
                            current_price=last_price,
                        )
```

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_dividend_scanners.py::test_scan_entry_skips_option_when_price_at_or_below_golden -v
```

Expected: PASS

**Step 5: Run full scanner test suite**

```bash
python -m pytest tests/test_dividend_scanners.py -v
```

Expected: all pass

**Step 6: Commit**

```bash
git add src/dividend_scanners.py tests/test_dividend_scanners.py
git commit -m "feat: skip sell put when current price <= golden price, recommend spot"
```

---

### Task 2: Add option_expiration to signal payload

**Files:**
- Modify: `src/main.py:162-171`
- Test: `tests/test_integration.py`

**Background:**
`scan_dividend_sell_put()` returns an `expiration` key (a date string like `"2026-05-15"`), but `_build_agent_payload()` in `main.py` never copies it to the signal dict. The dashboard can't display the expiration date. Fix: add `"option_expiration"` next to `"option_dte"`.

**Step 1: Write the failing test**

Add to `tests/test_integration.py` (append after `test_build_agent_payload_illiquid_option_details` around line 353):

```python
def test_build_agent_payload_dividend_includes_option_expiration():
    """option_expiration must be present in dividend signal payload when option is liquid."""
    from src.main import _build_agent_payload
    from src.dividend_scanners import DividendBuySignal
    from src.data_engine import TickerData

    td = TickerData(
        ticker="KO", name="Coca-Cola", market="US",
        last_price=65.0, ma200=60.0, ma50w=62.0, rsi14=40.0,
        iv_rank=20.0, iv_momentum=None, prev_close=64.0,
        earnings_date=None, days_to_earnings=None,
        dividend_yield=5.0, dividend_yield_5y_percentile=95.0,
        dividend_quality_score=80.0, consecutive_years=10,
        dividend_growth_5y=3.5, payout_ratio=60.0,
        roe=15.0, debt_to_equity=1.0, industry="Beverages",
        sector="Consumer Staples", free_cash_flow=10_000_000,
        forward_dividend_rate=2.0, max_yield_5y=4.0,
        quality_breakdown={}, analysis_text="Strong payer.",
        data_version_date=str(date.today()),
    )

    option_details = {
        "strike": 60.0,
        "bid": 1.20,
        "ask": 1.40,
        "mid": 1.30,
        "spread_pct": 15.4,
        "liquidity_warn": False,
        "sell_put_illiquid": False,
        "dte": 55,
        "expiration": "2026-05-16",
        "apy": 14.4,
        "golden_price": 62.0,
        "current_vs_golden_pct": 4.8,
        "strike_rationale": "黄金位 = forward股息 / 历史75th收益率",
    }

    signal = DividendBuySignal(
        ticker_data=td, signal_type="OPTION",
        current_yield=5.0, yield_percentile=95.0,
        option_details=option_details,
        forward_dividend_rate=2.0, max_yield_5y=4.0,
        floor_price=50.0, floor_downside_pct=23.1,
        data_age_days=0, needs_reeval=False,
    )

    payload = _build_agent_payload(
        sell_puts=[], iv_low=[], iv_high=[], ma200_bull=[], ma200_bear=[],
        leaps=[], earnings_gaps=[], earnings_gap_ticker_map={},
        iv_momentum=[], dividend_signals=[signal],
    )

    entry = payload[0]
    assert "option_expiration" in entry
    assert entry["option_expiration"] == "2026-05-16"
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_integration.py::test_build_agent_payload_dividend_includes_option_expiration -v
```

Expected: FAIL — `"option_expiration" not in entry`

**Step 3: Implement the change**

In `src/main.py`, find line 163:

```python
            "option_dte": opt["dte"] if opt else None,
```

Add one line after it:

```python
            "option_dte": opt["dte"] if opt else None,
            "option_expiration": str(opt["expiration"]) if opt and opt.get("expiration") is not None else None,
```

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_integration.py::test_build_agent_payload_dividend_includes_option_expiration -v
```

Expected: PASS

**Step 5: Run full integration test suite**

```bash
python -m pytest tests/test_integration.py -v
```

Expected: all pass

**Step 6: Commit**

```bash
git add src/main.py tests/test_integration.py
git commit -m "feat: add option_expiration to dividend signal payload"
```

---

### Task 3: Dashboard — show full option contract, use mid price

**Files:**
- Modify: `agent/templates/dashboard.html:996-997`

**Background:**
Two display fixes in the Sell Put strategy panel inside `buildStrategySection()`:

1. **行权价 row** — currently: `$240 · 63 DTE`. Change to: `$240 PUT · Jun 20 · 63D`
   - Uses `p.option_expiration` (new field from Task 2)
   - Format expiration as `MMM DD` (e.g. `"2026-05-16"` → `"May 16"`)

2. **权利金 row** — currently uses `option_bid`. Change to `option_mid`.
   - APY is already computed from mid; display should match.

No test file for this (frontend JS). Verify manually in browser.

**Step 1: Add expiration formatter helper**

In `dashboard.html`, find the JS section near `buildStrategySection` (around line 958). Add a helper function just before `buildStrategySection`:

```javascript
function fmtExpiry(dateStr) {
  if (!dateStr) return '';
  var d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
```

**Step 2: Update the 行权价 row (line ~996)**

Find:
```javascript
      + '<div class="strategy-row"><span class="strategy-row-label">行权价</span><span class="strategy-row-value highlight">$' + (p.option_strike || 0).toFixed(2) + ' · ' + (p.option_dte || 0) + ' DTE</span></div>'
```

Replace with:
```javascript
      + '<div class="strategy-row"><span class="strategy-row-label">行权价</span><span class="strategy-row-value highlight">$' + (p.option_strike || 0).toFixed(2) + ' PUT' + (p.option_expiration ? ' · ' + fmtExpiry(p.option_expiration) : '') + ' · ' + (p.option_dte || 0) + 'D</span></div>'
```

**Step 3: Update the 权利金 row (line ~997)**

Find:
```javascript
      + '<div class="strategy-row"><span class="strategy-row-label">权利金</span><span class="strategy-row-value">$' + (p.option_bid || 0).toFixed(2) + ' → ' + (p.option_apy || 0).toFixed(1) + '% 年化</span></div>'
```

Replace with:
```javascript
      + '<div class="strategy-row"><span class="strategy-row-label">权利金</span><span class="strategy-row-value">$' + (p.option_mid || 0).toFixed(2) + ' → ' + (p.option_apy || 0).toFixed(1) + '% 年化</span></div>'
```

**Step 4: Verify in browser**

Open dashboard, find a dividend signal with option data. Confirm:
- 行权价 shows: `$240.00 PUT · May 16 · 63D`
- 权利金 shows: `$37.95 → 151.0% 年化` (value now from mid, not bid)

**Step 5: Commit**

```bash
git add agent/templates/dashboard.html
git commit -m "feat: show full option contract (PUT · expiry · DTE) and use mid price for premium display"
```

---

### Final: Run all tests

```bash
cd /Users/q/code/ai-monitor
python -m pytest tests/ -v
```

Expected: all pass. Then push.
