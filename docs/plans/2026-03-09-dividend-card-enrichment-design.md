# Dividend Card Enrichment Design

**Goal:** Enrich the dividend signal card with three improvements: business stability tooltip (dimensional scores + LLM text), worst-case floor price analysis using forward dividends, and a pre-processed data infrastructure with event-driven freshness.

**Architecture:** Extend `financial_service.py` to output structured breakdown + analysis text; extend `DividendStore` with new fields; extend agent payload; update dashboard card and html_report.

**Tech Stack:** Python, SQLite (DividendStore), yfinance forwardAnnualDividendRate, Claude LLM (financial_service), Vanilla JS tooltip

---

## Feature 1: Business Stability Tooltip (B+C)

### Display

"业务稳定性: 优秀 (85/100)" gains an info icon. Clicking expands a panel showing:

**Top half — dimensional scores (B):**
- 股息连续性 (Dividend Continuity): X/20
- 派息率可持续性 (Payout Safety): X/20
- 盈利稳定性 (Earnings Stability): X/20
- 业务护城河 (Business Moat): X/20
- 负债水平 (Debt Level): X/20

**Bottom half — LLM analysis text (C):**
- 2-3 sentences describing business stability rationale, specific to the ticker

### Data Changes

**`financial_service.py` output — extend from single score to structured dict:**
```json
{
  "quality_score": 85,
  "quality_breakdown": {
    "continuity": 18,
    "payout_safety": 14,
    "earnings_stability": 17,
    "moat": 19,
    "debt_level": 17
  },
  "analysis_text": "KO is one of the widest-moat consumer staples globally, with 62 consecutive years of dividend growth..."
}
```

**`DividendStore` — new columns on `dividend_pool` table:**
- `quality_breakdown` TEXT (JSON)
- `analysis_text` TEXT

**Agent payload — new fields on `dividend` signal type:**
- `quality_breakdown`: dict
- `analysis_text`: string

### UI (dashboard.html)

- Add `ℹ️` icon inline after stability label
- Click toggles a `<div class="stability-detail">` panel
- Panel renders 5 progress bars + analysis_text paragraph
- CSS: panel inherits dark card theme, progress bars use rgba fills

### html_report.py

- Dim 1 tooltip rendered as a `<details><summary>` element (no JS needed in static HTML)
- Same dimensional breakdown + analysis_text inside

---

## Feature 2: Dim 5 Worst-Case Floor Price

### Display (Dim 5)

```
5️⃣ 最坏情景

行权成本: $58.80  (Sell Put $60 - $1.20 premium)

历史极值底价分析
  历史最高股息率 (5年): 4.5%
  Forward 股息: $1.94/股  (已宣告, yfinance 确认)
  分红增长率: +4.8%/年  (5年 CAGR)
  极值底价: $43.11  较当前 -31.0%

  [if cost_basis > floor_price]:
  ⚠️ 行权成本高于极值底价，极端熊市下仍有浮亏风险
     但届时股息率将达 4.5%，持有收租逻辑成立
```

If no option (no sell put): show only floor price analysis without cost basis row.

### Calculation

```python
floor_price = forward_dividend_rate / (max_yield_5y / 100)
floor_downside_pct = (last_price - floor_price) / last_price * 100  # negative
```

### Data Changes

**`DividendStore` — new columns:**
- `forward_dividend_rate` REAL  (yfinance forwardAnnualDividendRate)
- `dividend_growth_rate` REAL   (5-year CAGR, computed from dividend history)
- `max_yield_5y` REAL           (max yield over trailing 5 years)

**Agent payload — new fields:**
- `forward_dividend_rate`
- `dividend_growth_rate`
- `max_yield_5y`
- `floor_price` (pre-computed: forward_div / max_yield_5y)
- `floor_downside_pct` (pre-computed)

**`scan_dividend_pool_weekly` — fetch and compute:**
- `forward_dividend_rate`: `provider.get_ticker_info(ticker)['forwardAnnualDividendRate']`
- `dividend_growth_rate`: compute 5-year CAGR from `provider.get_price_history()` dividends column
- `max_yield_5y`: from 5-year price + dividend history: `max(annual_div / price_at_date)`

---

## Feature 3: Data Freshness Infrastructure

### DividendStore — new column

- `data_version_date` DATE  (set to scan date on each write)

### Event-triggered re-evaluation

In `run_scan()`, after the main scan loop, for each ticker in the current dividend pool:
```python
if ticker.earnings_date and last_scan_date <= ticker.earnings_date <= today:
    # earnings just passed since last pool scan — re-evaluate this ticker
    re_evaluate_single(ticker, provider, financial_service, dividend_store)
```

`re_evaluate_single`: fetches fresh data for one ticker, updates its row in dividend_pool.

### Freshness label in payload

- `data_age_days`: (today - data_version_date).days
- `needs_reeval`: bool — True if earnings passed since data_version_date

### Dashboard card freshness badge

- data_age_days <= 7: no badge
- needs_reeval = True: `⚠️ 财报后数据，建议重新评估`
- data_age_days > 14: `🕐 数据较旧 (X天前)`

---

## Data Flow

```
Weekly scan_dividend_pool_weekly:
  yfinance forwardAnnualDividendRate  ──┐
  5-year price history (dividends)    ──┼─> compute max_yield_5y, growth_rate
  financial_service LLM evaluation    ──┘
                                         ↓
                              DividendStore.save_pool()
                              (new columns written)

Daily run_scan():
  check earnings_date vs last scan    ──> re_evaluate_single() if stale
                                         ↓
                              scan_dividend_buy_signal()
                              build_agent_payload() with new fields
                                         ↓
                              agent /api/scan_results
                                         ↓
                              dashboard Dim 1 tooltip + Dim 5 floor analysis
```

---

## Scope / Not In This Design

- No external paid data sources (FMP, Alpha Vantage) — yfinance covers all needed fields
- No real-time SEC EDGAR monitoring — event-triggered check on existing earnings_date is sufficient
- Special dividend detection (one-time) — future enhancement, not in scope

---

## Files Touched

| File | Change |
|------|--------|
| `src/financial_service.py` | Extend LLM output to include `quality_breakdown` dict + `analysis_text` |
| `src/dividend_store.py` | Add 5 new columns, migration, getter/setter |
| `src/dividend_scanners.py` | Compute `forward_dividend_rate`, `max_yield_5y`, `dividend_growth_rate` in weekly scan; add `re_evaluate_single()` |
| `src/main.py` | Add post-scan event-triggered re-eval loop; extend `_build_agent_payload()` dividend fields |
| `agent/static/dashboard.html` | Dim 1 tooltip UI; Dim 5 floor price section; freshness badge |
| `src/html_report.py` | Dim 1 `<details>` tooltip; Dim 5 floor price section |
| `tests/test_financial_service.py` | Test new output structure |
| `tests/test_dividend_store.py` | Test new columns |
| `tests/test_dividend_scanners.py` | Test new computed fields, re_evaluate_single |
| `tests/test_integration.py` | Test extended payload fields |
