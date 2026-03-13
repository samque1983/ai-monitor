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
               industry, sector, added_date, version)

dividend_history (ticker, date, dividend_yield, annual_dividend, price)
  PRIMARY KEY (ticker, date)

screening_versions (version PK, created_at, tickers_count, avg_quality_score)
```

**API**:
- `save_pool(tickers: List[TickerData], version: str)` — replaces entire pool
- `get_current_pool() -> List[str]` — ticker list from pool
- `save_dividend_history(ticker, date, dividend_yield, annual_dividend, price)`
- `get_yield_percentile(ticker, current_yield) -> float` — % of history ≤ current_yield
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

### DividendBuySignal

```python
@dataclass
class DividendBuySignal:
    ticker_data: TickerData
    signal_type: str            # "STOCK" | "OPTION"
    current_yield: float        # %
    yield_percentile: float     # from DividendStore
    option_details: Optional[Dict]  # strike, bid, dte, expiration, apy
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
- `target_yield = current_yield * (target_strike_percentile / yield_percentile)`
- Calls `scan_dividend_sell_put()` to select strike

### scan_dividend_sell_put

```python
scan_dividend_sell_put(
    ticker_data, provider, annual_dividend,
    target_yield_percentile, target_yield,
    min_dte=45, max_dte=90,
) -> Optional[Dict]
```

Strike selection: `target_strike = annual_dividend / (target_yield / 100)`.
Selects option from chain with minimum `abs(strike - target_strike)`.
APY (display only): `(bid / strike) * (365 / dte) * 100`.

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
    target_strike_percentile: 90
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
