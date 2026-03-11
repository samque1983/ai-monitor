# Dividend Card UX v2 — Design Doc

> **Status:** Approved, ready for implementation plan
> **Date:** 2026-03-11

## Goal

Improve the dividend signal card from a static information display into an interactive strategy selector with AI-recommended entry points, SGOV yield stacking, structured analysis rendering, and a watch/monitor placeholder.

## Architecture

Five independent concerns, three require backend changes and two are frontend-only.

```
Backend (scan time)          Frontend (render time)
─────────────────────        ──────────────────────
SGOV yield fetch             Strategy tab UI
recommended_strategy gen     Analysis text parser
new payload fields           Watch rename + localStorage
TickerData + store schema
```

---

## 1. Header Spacing Fix (frontend-only)

**Problem:** `.card-head-left { flex: 1 }` stretches left side across full width, creating excessive space between ticker/badge and KPI number.

**Fix:** Remove `flex: 1` from `.card-head-left`. Both sides shrink to natural width, gap controlled by existing `gap: 12px` on `.card-head`.

---

## 2. Strategy Selector UI (frontend + backend)

### 2.1 UI Design

Replace the current "建议买入" static rows with a **tab-based strategy picker**:

```
策略  [★ Sell Put]  [现货]  [Spread ·]

AI 推荐：综合年化 27% 是现货股息率 5 倍，流动性正常，
        SGOV 叠加后收益显著高于单纯持仓。

── Sell Put ─────────────────────────────
行权价      $44.00 · 30 DTE
权利金      $0.85  →  22.0% 年化
SGOV 叠加   +4.8%     现金在短期国债期间收益
─────────────────────────────────────────
综合年化    26.8%     (Sell Put + SGOV 叠加)
```

**Tab states:**
- Active tab: filled background, accent color
- `Spread`: always disabled/grayed; click shows tooltip "功能开发中"
- If Sell Put unavailable: tab grayed, click shows reason (e.g., "流动性不足，价差 8.5%")
- If no options market: tab grayed, click shows "港股/A股暂无期权市场"

**Default tab logic:**
- Read `recommended_strategy` from payload
- If field missing (old data): fall back to rule — Sell Put if available and not illiquid, else 现货

### 2.2 SGOV Yield (backend — `dividend_scanners.py`)

**Source:** Fetch SGOV 30-day rolling yield via yfinance at scan start (once per scan, not per ticker).

```python
def get_sgov_yield() -> float:
    """Fetch current SGOV annualized yield. Returns fallback 4.8 on failure."""
    try:
        sgov = yf.Ticker("SGOV")
        # Use trailing 30-day dividend yield as proxy for current cash yield
        info = sgov.info
        return round(float(info.get("yield", 0.048)) * 100, 2)  # as percent
    except Exception:
        return 4.8  # fallback
```

**Computation per ticker (US only — SGOV not relevant for HK/CN):**
```python
sgov_yield: float            # e.g. 4.8 (%)
sgov_adjusted_apy: float     # option_apy + sgov_yield (only if option available)
```

Store both in payload. For HK/CN tickers: `sgov_yield = None`, `sgov_adjusted_apy = None`.

### 2.3 Recommended Strategy (backend — `financial_service.py`)

**New fields on `DividendQualityScore` (or directly on TickerData):**
```python
recommended_strategy: str   # "sell_put" | "spot"
recommended_reason: str     # one sentence, Chinese
```

**Generation logic** (called after quality scoring, same LLM call pattern as analysis_text):

```python
def _get_recommended_strategy(
    self, ticker, current_yield, combined_apy, sgov_adjusted_apy,
    option_available, option_illiquid, quality_score
) -> tuple[str, str]:
    """Return (strategy_name, reason_text)."""
    if not option_available or option_illiquid:
        reason = "期权流动性不足" if option_illiquid else "无期权市场，现货持仓吃股息"
        return "spot", reason
    # Ask LLM to compare and recommend
    prompt = (
        f"股票 {ticker}，当前股息率 {current_yield:.1f}%，"
        f"Sell Put 综合年化（含SGOV）{sgov_adjusted_apy:.1f}%，"
        f"质量评分 {quality_score:.0f}/100。\n"
        "比较现货持仓与 Sell Put 策略，给出最优策略推荐。\n"
        '返回严格 JSON: {"strategy": "sell_put"|"spot", "reason": "一句话中文理由"}'
    )
    # ... LLM call with fallback to rule-based
```

**Fallback rule** (when LLM unavailable):
- `sgov_adjusted_apy > current_yield * 1.5` → recommend `sell_put`
- else → recommend `spot`

### 2.4 New TickerData Fields

```python
# src/data_engine.py — TickerData dataclass
sgov_yield: Optional[float] = None
sgov_adjusted_apy: Optional[float] = None
recommended_strategy: Optional[str] = None   # "sell_put" | "spot"
recommended_reason: Optional[str] = None
```

### 2.5 Store Schema Migration

`dividend_store.py` — add columns to `dividend_pool` table:
```sql
ALTER TABLE dividend_pool ADD COLUMN sgov_yield REAL;
ALTER TABLE dividend_pool ADD COLUMN sgov_adjusted_apy REAL;
ALTER TABLE dividend_pool ADD COLUMN recommended_strategy TEXT;
ALTER TABLE dividend_pool ADD COLUMN recommended_reason TEXT;
```

Standard migration pattern (already used in `_create_tables`).

New fields must also be included in `save_pool()` INSERT and `get_pool_records()` SELECT.

---

## 3. Analysis Text Parser (frontend-only)

### 3.1 AI Output Format

`financial_service.py` already generates text in this format:
```
确定性业务：[description] → [price range]
增量新业务：[description] → [price range]
估值区间：[logic] → [综合 price range]
```

### 3.2 Parser Logic (JavaScript)

```javascript
function parseAnalysisText(raw) {
  if (!raw) return null;
  // Split on newlines, match "标签：内容 → 价格" pattern
  const lineRe = /^(.+?)：(.+?)→\s*(.+)$/;
  const lines = raw.split('\n').filter(l => l.trim());
  const dims = lines.map(l => {
    const m = l.match(lineRe);
    return m ? { label: m[1].trim(), body: m[2].trim(), price: m[3].trim() } : null;
  }).filter(Boolean);
  return dims.length >= 2 ? dims : null;  // fallback to raw if < 2 parsed dims
}
```

### 3.3 Rendered HTML

```html
<!-- Each dimension -->
<div class="analysis-dim">
  <div class="analysis-dim-label">确定性业务</div>
  <div class="analysis-dim-body">核心业务描述，稳定现金流来源</div>
  <div class="analysis-dim-price">→ $40–45</div>
</div>
<div class="analysis-divider"></div>
<div class="analysis-dim">...</div>
```

**CSS:**
- `.analysis-dim-label`: 11px, font-weight 600, `var(--text-2)`
- `.analysis-dim-body`: 13px, `var(--text-2)`, line-height 1.6
- `.analysis-dim-price`: 16px, DM Mono, `var(--amber)`, font-weight 500
- `.analysis-divider`: 1px `var(--border-2)` horizontal rule

**Fallback:** if parser returns null (non-standard format), render raw text as before.

---

## 4. Watch / 关注机会 (frontend-only)

### 4.1 Rename

- Section title: "关注监控" → "关注机会"
- Button text: "关注此标的" → "关注此机会" / "已关注"

### 4.2 localStorage Persistence

Watch state persists across page reloads per ticker:

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
  // update button UI
  btn.classList.toggle('watched', isWatched);
  btn.querySelector('.watch-star').textContent  = isWatched ? '★' : '☆';
  btn.querySelector('.watch-label').textContent = isWatched ? '已关注' : '关注此机会';
}
```

Cards are rendered with `data-ticker="${s.ticker}"` on the watch button for lookup.

### 4.3 Future Backend Integration (deferred)

When backend watch API is ready:
- `POST /api/watch` `{ ticker, signal_type }` on follow
- `DELETE /api/watch/:ticker` on unfollow
- `GET /api/watch` returns list → pre-populate UI state on load
- Monitoring triggers: server-side cron checks conditions, pushes notifications

---

## 5. Monitoring Commitments (display only, no change)

The three watch items remain as informational display:
1. 派息率 >100% 立即预警
2. 财报前 7 天提醒
3. 股息率回落至历史中位数时提示

These are promises to the user about what monitoring will do once backend is wired.

---

## File Change Summary

| File | Type | Change |
|------|------|--------|
| `src/data_engine.py` | Backend | Add 4 new fields to `TickerData` |
| `src/dividend_scanners.py` | Backend | Add `get_sgov_yield()`, compute `sgov_adjusted_apy` per ticker |
| `src/financial_service.py` | Backend | Add `_get_recommended_strategy()`, populate new fields |
| `src/dividend_store.py` | Backend | Schema migration + save/load new fields |
| `agent/static/dashboard.html` | Frontend | All UI changes (tabs, parser, watch, header fix) |

## Out of Scope

- Spread strategy implementation (UI placeholder only, disabled tab)
- Backend watch API / notifications (localStorage only for now)
- HK/CN SGOV equivalent (not applicable, fields will be null)
- Changing the LLM prompt format for analysis text (parser handles existing format)
