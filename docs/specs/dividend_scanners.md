# Dividend Scanners Specification

**Modules**: `src/dividend_scanners.py`, `src/financial_service.py`, `src/dividend_store.py`
**Tests**: `tests/test_dividend_scanners.py`, `tests/test_financial_service.py`, `tests/test_dividend_store.py`
**Purpose**: Phase 2 高股息防御双打 — weekly pool screening + daily buy-signal monitoring

---

## Architecture

```
main.py
  → scan_dividend_buy_signal()       [dividend_scanners.py]
      → DividendStore.get_current_pool()
      → MarketDataProvider.get_price_data()
      → MarketDataProvider.get_dividend_history()
      → DividendStore.get_yield_percentile()
      → scan_dividend_sell_put()     [US market only]
  → format_html_report(dividend_signals=...) [html_report.py]

main.py (--mode dividend_screening, manual)
  → scan_dividend_pool_weekly()      [dividend_scanners.py]
      → MarketDataProvider.get_dividend_history()
      → MarketDataProvider.get_fundamentals()
      → FinancialServiceAnalyzer.analyze_dividend_quality()
      → DividendStore.save_pool()
```

**Import direction** (never reverse):
`main.py → dividend_scanners.py → financial_service.py / dividend_store.py → market_data.py`

---

## Module: dividend_store.py

### DividendStore

SQLite-backed storage for the dividend pool and yield history.

**DB path**: configurable via `config.yaml → data.dividend_db_path` (default `data/dividend_pool.db`)

**Tables**:
```sql
dividend_pool (ticker PK, name, market, quality_score, consecutive_years,
               dividend_growth_5y, payout_ratio, roe, debt_to_equity,
               industry, sector, added_date, version,
               forward_dividend_rate, max_yield_5y,
               golden_price)        -- 黄金位: forward_dividend / yield_75th_pct

dividend_history (ticker, date, dividend_yield, annual_dividend, price)
  PRIMARY KEY (ticker, date)

screening_versions (version PK, created_at, tickers_count, avg_quality_score)
```

**API**:
- `save_pool(tickers: List[TickerData], version: str)` — replaces entire pool
- `get_current_pool() -> List[str]` — ticker list from pool
- `save_dividend_history(ticker, date, dividend_yield, annual_dividend, price)`
- `get_yield_percentile(ticker, current_yield) -> YieldPercentileResult` — Winsorized percentile + p10/p90/hist_max
- `get_yield_percentile_value(ticker, percentile) -> Optional[float]` — raw yield value at given percentile (None if < 8 pts)
- `close()`

---

## Module: financial_service.py

### DividendQualityScore

```python
@dataclass
class DividendQualityScore:
    overall_score: float        # weighted average (0-100)
    stability_score: float      # consecutive years + growth rate
    health_score: float         # ROE + debt ratio + payout ratio
    defensiveness_score: float  # sector-based (fixed 50 in rule-based mode)
    risk_flags: List[str]       # ["HIGH_PAYOUT_RISK", ...]
```

### FinancialServiceAnalyzer

Rule-based scoring (no external API dependency):

```
stability  = min(consecutive_years * 10, 50) + min(dividend_growth_5y * 2, 30)  [capped 0-80]
health     = min(roe, 30) + max(0, 30 - debt_to_equity * 20) + (40 if payout<70 else 20)  [capped 0-100]
defensive  = 50  (fixed)
overall    = stability*0.4 + health*0.4 + defensive*0.2  [capped 0-100]
```

### Health Score — LLM override (anomalous companies)

Triggered when either condition holds:
- `debt_to_equity > 200` — negative book equity from buybacks/M&A
- `payout_ratio > 100` AND `sector NOT IN {Energy, Utilities, Real Estate}`

LLM call returns `{"health_score": float, "fcf_payout_est": float, "rationale": str}`. Overrides:
- `health_score` ← LLM value (0–100)
- `effective_payout_ratio` ← `fcf_payout_est`
- `payout_type` ← `"LLM"`
- `health_rationale` ← rationale string (shown in dashboard tooltip)

Cached in `analysis_cache` table with key `"{ticker}:health"` (7-day TTL).
Falls back to rule-based if LLM unavailable or call fails.

Risk flags: `HIGH_PAYOUT_RISK` when `payout_ratio > 80`.

### Utility functions

- `calculate_consecutive_years(dividend_history) -> int` — years with ≥1 payment
- `calculate_dividend_growth_rate(dividend_history, years=5) -> float` — CAGR %

---

## Module: dividend_scanners.py

### scan_dividend_pool_weekly

```python
scan_dividend_pool_weekly(
    universe: List[str],
    provider: MarketDataProvider,
    financial_service: FinancialServiceAnalyzer,
    config: dict,          # uses config["dividend_scanners"]
) -> List[TickerData]
```

**dividend_yield 数据源**:
- US: yfinance `trailingAnnualDividendYield`（优先）或 `dividendYield`，已处理小数/百分比单位
- CN: `stock_individual_spot_xq(symbol="SH600036")` → `股息率(TTM)` （雪球实时行情）
- HK: `dividend_yield = None`（雪球不支持港股，待后续补充）

**Filter rules** (all must pass):
| Rule | Default |
|------|---------|
| `dividend_yield >= 2%` | hard filter (CN/HK 通过雪球 TTM 保证准确) |
| `consecutive_years >= min_consecutive_years` | 5 |
| `payout_ratio <= max_payout_ratio` | 100 (hard exclude) |
| `quality_score >= min_quality_score` | 70 |

Payout > 100 → log error + skip. Per-ticker exception isolation.

**Floor price computation** (`_compute_floor_data`):

Uses 5-year daily close prices to compute the dividend-yield-implied price floor:

1. `min_5y_filtered` = 3rd percentile of 5-day rolling min — smooths out single-day spikes
2. `max_yield_5y` = `annual_dividend_ttm / min_5y_filtered * 100` — highest yield seen in normal market conditions
3. `floor_price` = `forward_dividend_rate / (max_yield_5y / 100)` — price at which stock would yield the historical max

**Extreme event detection**:

```python
extreme_detected = bool(raw_min_price < min_5y_filtered * 0.85)
```

If the raw 5-year close minimum is >15% below the filtered minimum, the low is treated as an extreme event and excluded from `max_yield_5y` (so `floor_price` reflects a "normal market" floor, not a crash floor).

When detected, `_label_extreme_event()` looks up the raw_min_date against a rule library:

```python
_EXTREME_EVENT_RULES = [
    {"label": "2020-03 COVID 抛售",  "start": date(2020,2,19), "end": date(2020,3,23),  "market": None},
    {"label": "2022 加息熊市",        "start": date(2022,1,1),  "end": date(2022,10,13), "market": None},
    {"label": "2018 Q4 崩盘",         "start": date(2018,10,1), "end": date(2018,12,24), "market": None},
    {"label": "2015 A股熔断",         "start": date(2015,6,12), "end": date(2016,2,29),  "market": "CN"},
]
```

Falls back to benchmark comparison (`SPY`/`HSI`/`CSI300`) if date matches no rule.

**Fields stored in pool and serialized to agent payload**:
- `floor_price` — filtered floor (normal market conditions)
- `floor_price_raw` — unfiltered floor (includes extreme events)
- `extreme_event_label` — human-readable event name, or `None` if no extreme detected
- `extreme_event_price` — raw min price that was excluded
- `extreme_event_days` — days price stayed at that low

**Dashboard rendering**: When `extreme_event_label` is set, a sub-line appears below the 极值底价 row:
```
已排除 2020-03 COVID 抛售 · 原始低 $73.20
```

**5-year window limitation**: `extreme_detected` only fires for events within the 5-year lookback window. Events older than 5 years (e.g., COVID crash in Mar 2020 becomes invisible after Mar 2025) will not appear, even if they were significant. This is expected — the pool is designed to reflect current market structure, not historical crises.

**Golden price computation** (added to step 8, after floor_data):

Using the already-fetched `close_5y` price series and `dividend_history`:
1. Build monthly yield series: resample price to month-end, compute trailing-12-month dividend yield per month
2. `yield_75th_pct = np.percentile(monthly_yields, 75)` — requires ≥ 8 data points
3. `golden_price = forward_dividend_rate / (yield_75th_pct / 100)` — requires `forward_dividend_rate > 0`
4. Stored on `TickerData.golden_price` and persisted to `dividend_pool.golden_price`

Interpretation: golden_price is the price at which the stock yields the 75th percentile historical yield — only 25% of history was cheaper than this level. Provides a genuine margin of safety vs. yield-math average.

### DividendBuySignal

```python
@dataclass
class DividendBuySignal:
    ticker_data: TickerData
    signal_type: str            # "STOCK" | "OPTION"
    current_yield: float        # %
    yield_percentile: float     # from DividendStore
    option_details: Optional[Dict]  # strike, bid, dte, expiration, apy,
                                    # golden_price, current_vs_golden_pct, strike_rationale
    golden_price: Optional[float]           # 黄金位
    current_vs_golden_pct: Optional[float]  # (current - golden) / current * 100
    strike_rationale: Optional[str]         # how the SELL PUT strike was chosen
```

### scan_dividend_buy_signal

```python
scan_dividend_buy_signal(
    pool: List[str],
    provider: MarketDataProvider,
    store: DividendStore,
    config: dict,
) -> List[DividendBuySignal]
```

**annual_dividend 计算规则**:
- **US**: `sum(yfinance dividends, last 365 days)` — 季度派息，yfinance 数据完整
- **CN/HK**: `fundamentals.dividend_yield / 100 * last_price` — 使用雪球 TTM 股息率推算。原因：yfinance 在 365 天窗口内可能只捕获到中期派息（interim），导致年度金额严重偏低（如招商银行实际 7.6%，yfinance 原始计算仅 1.4%）

**Trigger condition**: `current_yield >= min_yield AND yield_percentile >= min_yield_percentile`

**Option strategy** (US market only, when `option.enabled=true`):
- Reads `golden_price` from pool record (computed during weekly scan)
- Calls `scan_dividend_sell_put()` with `golden_price` as primary target strike
- `target_yield` (yield-math) passed as fallback when `golden_price` is None

### scan_dividend_sell_put

```python
scan_dividend_sell_put(
    ticker_data, provider, annual_dividend,
    target_yield,
    min_dte=45, max_dte=90,
    golden_price: Optional[float] = None,
    current_price: Optional[float] = None,
) -> Optional[Dict]
```

**Strike selection** (priority order):
1. `golden_price` → use directly as `target_strike` when provided and > 0
2. Fallback: `target_strike = annual_dividend / (target_yield / 100)` (yield-math, used when history insufficient)

Selects option from chain with minimum `abs(strike - target_strike)`.
APY (display only): `(mid / strike) * (365 / dte) * 100`.

**Return dict** includes: `strike`, `bid`, `ask`, `mid`, `spread_pct`, `dte`, `expiration`, `apy`, `golden_price`, `current_vs_golden_pct`, `strike_rationale`.

---

## Config (config.yaml)

```yaml
dividend_scanners:
  enabled: false           # master switch
  min_quality_score: 70
  min_consecutive_years: 5
  max_payout_ratio: 100
  min_yield: 4.0
  min_yield_percentile: 90
  option:
    enabled: false
    target_strike_percentile: 90  # kept for fallback target_yield calc; no longer primary
    min_dte: 45
    max_dte: 90

data:
  dividend_db_path: "data/dividend_pool.db"
```

---

## HTML Report Integration

`format_html_report()` accepts:
- `dividend_signals: Optional[List[DividendBuySignal]]`
- `dividend_pool_summary: Optional[Dict]` — `{count, last_update}`

Section rendered only when `dividend_signals` is non-empty.
Six-dimension card per signal: valuation · risk · events · action · worst-case · monitoring.
