# Dividend Pool V2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the dividend pool from a personal-watchlist scanner to a curated 3-market (US/HK/A) retirement-income pool with sector-aware payout ratio logic, monthly versioning, a standalone HTML explanation page, and a CLI viewer.

**Architecture:** Static seed universe in `config.yaml` → monthly `scan_dividend_pool_weekly()` applies fixed rules (yield ≥ 2%, consecutive ≥ 5yr, score ≥ 70, sector-aware payout ≤ 100%) → results saved to versioned SQLite → `dividend_pool.html` generated for pool browser → ⓘ badge in daily report links to it.

**Tech Stack:** Python, SQLite (sqlite3), yfinance, pytest, existing `DividendStore` / `FinancialServiceAnalyzer` / `MarketDataProvider` / `html_report.py`

---

### Task 1: market_data.py — add dividend_yield and company_name to get_fundamentals()

**Files:**
- Modify: `src/market_data.py` (function `get_fundamentals`, currently returns 6 fields)
- Test: `tests/test_market_data.py`

**Context:** `scan_dividend_pool_weekly()` already calls `fundamentals.get("dividend_yield")` and `fundamentals.get("company_name")` but `get_fundamentals()` doesn't return these. Also needed: `annual_dividend` is calculated from dividend_history in scanner (not fetched here).

**Step 1: Write failing tests**

In `tests/test_market_data.py`, add to the existing test class or at module level:

```python
def test_get_fundamentals_returns_dividend_yield(mock_yf_ticker):
    """get_fundamentals() must return dividend_yield as percentage."""
    mock_yf_ticker.info = {
        "payoutRatio": 0.65,
        "returnOnEquity": 0.15,
        "debtToEquity": 0.8,
        "industry": "Utilities",
        "sector": "Utilities",
        "freeCashflow": 5_000_000,
        "dividendYield": 0.035,          # 3.5% as decimal
        "longName": "Test Corp",
    }
    provider = MarketDataProvider()
    result = provider.get_fundamentals("TEST")
    assert result["dividend_yield"] == pytest.approx(3.5)
    assert result["company_name"] == "Test Corp"


def test_get_fundamentals_dividend_yield_none_when_missing(mock_yf_ticker):
    """get_fundamentals() returns None for dividend_yield if not in info."""
    mock_yf_ticker.info = {"payoutRatio": 0.5}
    provider = MarketDataProvider()
    result = provider.get_fundamentals("TEST")
    assert result["dividend_yield"] is None
    assert result["company_name"] == "TEST"   # falls back to ticker
```

**Step 2: Run to confirm RED**

```bash
cd /Users/q/code/ai-monitor
pytest tests/test_market_data.py -k "dividend_yield or company_name" -v
```

Expected: `FAILED` — KeyError or None assertion failure.

**Step 3: Implement**

In `src/market_data.py`, inside `get_fundamentals()`, extend the return dict:

```python
# Add after existing roe conversion:
dividend_yield_raw = info.get("dividendYield")
dividend_yield = dividend_yield_raw * 100 if dividend_yield_raw is not None else None

company_name = info.get("longName") or info.get("shortName") or ticker

return {
    "payout_ratio": payout_ratio,
    "roe": roe,
    "debt_to_equity": info.get("debtToEquity"),
    "industry": info.get("industry"),
    "sector": info.get("sector"),
    "free_cash_flow": info.get("freeCashflow"),
    "dividend_yield": dividend_yield,    # NEW: percentage (e.g. 3.5 = 3.5%)
    "company_name": company_name,        # NEW: display name
}
```

**Step 4: Run GREEN**

```bash
pytest tests/test_market_data.py -k "dividend_yield or company_name" -v
```

**Step 5: Run full suite — confirm no regressions**

```bash
pytest tests/ -x -q
```

**Step 6: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat(market_data): add dividend_yield and company_name to get_fundamentals"
```

---

### Task 2: data_engine.py + financial_service.py — sector-aware payout ratio

**Files:**
- Modify: `src/data_engine.py` — add `payout_type` field to `TickerData`
- Modify: `src/financial_service.py` — `_calculate_rule_based_score()` uses FCF payout for capital-intensive sectors
- Test: `tests/test_financial_service.py`

**Context:** FCF sectors = `{"Energy", "Utilities", "Real Estate"}`. FCF payout = `annual_dividend / free_cash_flow * 100`. `annual_dividend` is passed via `fundamentals_with_stats` (set in scanner). GAAP payout = existing `payout_ratio`. The result `payout_type` ("FCF" or "GAAP") is stored for display in the pool page.

**Step 1: Add `payout_type` to TickerData**

In `src/data_engine.py`, add after `free_cash_flow`:

```python
payout_type: Optional[str] = None   # "FCF" | "GAAP" | None
```

No test needed — dataclass field addition is covered by existing instantiation tests.

**Step 2: Write failing tests for sector-aware payout**

In `tests/test_financial_service.py`, add:

```python
FCF_SECTORS = ["Energy", "Utilities", "Real Estate"]

@pytest.mark.parametrize("sector", FCF_SECTORS)
def test_fcf_payout_used_for_capital_intensive_sectors(sector):
    """Energy/Utilities/Real Estate must use FCF payout ratio, not GAAP."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    fundamentals = {
        'consecutive_years': 10,
        'dividend_growth_5y': 3.0,
        'roe': 12.0,
        'debt_to_equity': 1.5,
        'payout_ratio': 120.0,      # GAAP payout > 100 — would trigger exclusion
        'sector': sector,
        'free_cash_flow': 5_000_000,
        'annual_dividend': 3_000_000,  # FCF payout = 60% — healthy
    }
    result = analyzer.analyze_dividend_quality("TEST", fundamentals)
    assert result is not None
    assert result.payout_type == "FCF"
    assert result.effective_payout_ratio == pytest.approx(60.0)


def test_gaap_payout_used_for_non_fcf_sectors():
    """Consumer/Tech/Healthcare sectors must use GAAP payout ratio."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    fundamentals = {
        'consecutive_years': 10,
        'dividend_growth_5y': 5.0,
        'roe': 20.0,
        'debt_to_equity': 0.5,
        'payout_ratio': 65.0,
        'sector': 'Consumer Staples',
        'free_cash_flow': 5_000_000,
        'annual_dividend': 3_000_000,
    }
    result = analyzer.analyze_dividend_quality("TEST", fundamentals)
    assert result.payout_type == "GAAP"
    assert result.effective_payout_ratio == pytest.approx(65.0)


def test_fcf_payout_fallback_when_free_cash_flow_missing():
    """FCF sector with missing free_cash_flow falls back to GAAP payout."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    fundamentals = {
        'consecutive_years': 8,
        'dividend_growth_5y': 2.0,
        'roe': 10.0,
        'debt_to_equity': 1.0,
        'payout_ratio': 75.0,
        'sector': 'Utilities',
        'free_cash_flow': None,
        'annual_dividend': None,
    }
    result = analyzer.analyze_dividend_quality("TEST", fundamentals)
    assert result.payout_type == "GAAP"
    assert result.effective_payout_ratio == pytest.approx(75.0)
```

**Step 3: Run to confirm RED**

```bash
pytest tests/test_financial_service.py -k "fcf_payout or gaap_payout" -v
```

Expected: `AttributeError: 'DividendQualityScore' object has no attribute 'payout_type'`

**Step 4: Update DividendQualityScore and implement sector-aware logic**

In `src/financial_service.py`:

1. Add fields to `DividendQualityScore` dataclass:

```python
@dataclass
class DividendQualityScore:
    overall_score: float
    stability_score: float
    health_score: float
    defensiveness_score: float
    risk_flags: List[str]
    payout_type: str = "GAAP"           # NEW: "FCF" | "GAAP"
    effective_payout_ratio: float = 0.0  # NEW: the ratio actually used
```

2. At module level, add the constant:

```python
FCF_PAYOUT_SECTORS = {"Energy", "Utilities", "Real Estate"}
```

3. In `_calculate_rule_based_score()`, replace the payout_ratio extraction and payout_score calculation:

```python
# Determine sector-aware payout ratio
sector = fundamentals.get('sector') or ''
free_cash_flow = fundamentals.get('free_cash_flow')
annual_dividend = fundamentals.get('annual_dividend')

if sector in FCF_PAYOUT_SECTORS and free_cash_flow and annual_dividend and free_cash_flow > 0:
    effective_payout_ratio = (annual_dividend / free_cash_flow) * 100
    payout_type = "FCF"
else:
    effective_payout_ratio = fundamentals.get('payout_ratio') or 0.0
    payout_type = "GAAP"

# 2. 计算财务健康度评分
roe_score = min(roe or 0.0, 30.0)
debt_score = max(0.0, 30.0 - (debt_to_equity or 0.0) * 20)
payout_score = 40.0 if effective_payout_ratio < 70 else 20.0
health_score = min(100.0, roe_score + debt_score + payout_score)
```

4. Update risk_flags to use `effective_payout_ratio`:

```python
if effective_payout_ratio > 100:
    risk_flags.append("PAYOUT_RATIO_CRITICAL")
elif effective_payout_ratio > 80:
    risk_flags.append("HIGH_PAYOUT_RISK")
```

5. Update the return statement:

```python
return DividendQualityScore(
    overall_score=overall_score,
    stability_score=stability_score,
    health_score=health_score,
    defensiveness_score=defensiveness_score,
    risk_flags=risk_flags,
    payout_type=payout_type,
    effective_payout_ratio=effective_payout_ratio,
)
```

**Step 5: Run GREEN**

```bash
pytest tests/test_financial_service.py -v
```

**Step 6: Run full suite**

```bash
pytest tests/ -x -q
```

**Step 7: Commit**

```bash
git add src/data_engine.py src/financial_service.py tests/test_financial_service.py
git commit -m "feat(financial_service): sector-aware payout ratio (FCF for Energy/Utilities/Real Estate)"
```

---

### Task 3: dividend_store.py — schema migration + list_versions() + get_pool_by_version()

**Files:**
- Modify: `src/dividend_store.py`
- Test: `tests/test_dividend_store.py`

**Context:** Current `dividend_pool` table has `ticker TEXT PRIMARY KEY` — only stores one pool snapshot. Need to change to `PRIMARY KEY (ticker, version)` to keep historical snapshots. Also need two new columns: `dividend_yield REAL`, `payout_type TEXT`. Migrate gracefully by detecting old schema and dropping/recreating.

**Step 1: Write failing tests**

In `tests/test_dividend_store.py`, add:

```python
def test_list_versions_returns_version_history(tmp_path):
    """list_versions() returns all saved versions sorted by created_at DESC."""
    store = DividendStore(str(tmp_path / "test.db"))
    pool_v1 = [_make_ticker("AAPL", score=80)]
    pool_v2 = [_make_ticker("AAPL", score=82), _make_ticker("MSFT", score=85)]

    store.save_pool(pool_v1, version="monthly_2026-01")
    store.save_pool(pool_v2, version="monthly_2026-02")

    versions = store.list_versions()
    assert len(versions) == 2
    assert versions[0]["version"] == "monthly_2026-02"   # most recent first
    assert versions[0]["tickers_count"] == 2
    assert versions[1]["version"] == "monthly_2026-01"
    assert versions[1]["tickers_count"] == 1
    store.close()


def test_get_pool_by_version_returns_correct_snapshot(tmp_path):
    """get_pool_by_version() retrieves the exact tickers for a given version."""
    store = DividendStore(str(tmp_path / "test.db"))
    pool_v1 = [_make_ticker("KO", score=85)]
    pool_v2 = [_make_ticker("KO", score=86), _make_ticker("PG", score=88)]

    store.save_pool(pool_v1, version="monthly_2026-01")
    store.save_pool(pool_v2, version="monthly_2026-02")

    result_v1 = store.get_pool_by_version("monthly_2026-01")
    assert len(result_v1) == 1
    assert result_v1[0]["ticker"] == "KO"

    result_v2 = store.get_pool_by_version("monthly_2026-02")
    assert len(result_v2) == 2
    tickers = {r["ticker"] for r in result_v2}
    assert tickers == {"KO", "PG"}
    store.close()


def test_save_pool_preserves_payout_type(tmp_path):
    """save_pool() stores payout_type field and get_pool_by_version() returns it."""
    store = DividendStore(str(tmp_path / "test.db"))
    td = _make_ticker("ENB", score=78)
    td.payout_type = "FCF"
    td.payout_ratio = 64.0

    store.save_pool([td], version="monthly_2026-03")
    result = store.get_pool_by_version("monthly_2026-03")
    assert result[0]["payout_type"] == "FCF"
    store.close()


def test_get_current_pool_uses_latest_version(tmp_path):
    """get_current_pool() returns tickers from the most recently saved version."""
    store = DividendStore(str(tmp_path / "test.db"))
    store.save_pool([_make_ticker("KO")], version="monthly_2026-01")
    store.save_pool([_make_ticker("PG"), _make_ticker("JNJ")], version="monthly_2026-02")

    pool = store.get_current_pool()
    assert set(pool) == {"PG", "JNJ"}
    store.close()
```

Add helper at top of test file if not present:

```python
from src.data_engine import TickerData

def _make_ticker(ticker: str, score: float = 75.0) -> TickerData:
    return TickerData(
        ticker=ticker, name=ticker, market="US",
        last_price=100.0, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=99.0,
        earnings_date=None, days_to_earnings=None,
        dividend_quality_score=score, consecutive_years=8,
        dividend_growth_5y=5.0, payout_ratio=65.0,
        dividend_yield=3.5, payout_type="GAAP",
    )
```

**Step 2: Run to confirm RED**

```bash
pytest tests/test_dividend_store.py -k "list_versions or get_pool_by_version or payout_type or latest_version" -v
```

**Step 3: Implement**

Replace `_create_tables()` in `src/dividend_store.py` with migration-aware version:

```python
def _create_tables(self):
    cursor = self.conn.cursor()

    # Migrate old schema if it exists (ticker was sole PK, no version column)
    cursor.execute("PRAGMA table_info(dividend_pool)")
    cols = {row[1] for row in cursor.fetchall()}
    if cols and 'version' not in cols:
        cursor.execute("DROP TABLE IF EXISTS dividend_pool")
        logger.info("Migrated dividend_pool table: old schema dropped")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dividend_pool (
            ticker TEXT NOT NULL,
            version TEXT NOT NULL,
            name TEXT,
            market TEXT,
            quality_score REAL,
            consecutive_years INTEGER,
            dividend_growth_5y REAL,
            payout_ratio REAL,
            payout_type TEXT,
            dividend_yield REAL,
            roe REAL,
            debt_to_equity REAL,
            industry TEXT,
            sector TEXT,
            added_date TEXT,
            PRIMARY KEY (ticker, version)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dividend_history (
            ticker TEXT,
            date TEXT,
            dividend_yield REAL,
            annual_dividend REAL,
            price REAL,
            PRIMARY KEY (ticker, date)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS screening_versions (
            version TEXT PRIMARY KEY,
            created_at TEXT,
            tickers_count INTEGER,
            avg_quality_score REAL
        )
    """)

    self.conn.commit()
```

Update `save_pool()` — change DELETE to version-scoped:

```python
def save_pool(self, tickers: List[TickerData], version: str):
    cursor = self.conn.cursor()

    # Delete only this version's records (preserve other versions)
    cursor.execute("DELETE FROM dividend_pool WHERE version = ?", (version,))

    for ticker in tickers:
        cursor.execute("""
            INSERT INTO dividend_pool (
                ticker, version, name, market, quality_score,
                consecutive_years, dividend_growth_5y, payout_ratio,
                payout_type, dividend_yield, roe, debt_to_equity,
                industry, sector, added_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker.ticker, version, ticker.name, ticker.market,
            ticker.dividend_quality_score, ticker.consecutive_years,
            ticker.dividend_growth_5y, ticker.payout_ratio,
            getattr(ticker, 'payout_type', None),
            getattr(ticker, 'dividend_yield', None),
            ticker.roe, ticker.debt_to_equity,
            ticker.industry, ticker.sector,
            date.today().isoformat(),
        ))

    quality_scores = [t.dividend_quality_score for t in tickers if t.dividend_quality_score is not None]
    avg_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

    cursor.execute("""
        INSERT OR REPLACE INTO screening_versions (
            version, created_at, tickers_count, avg_quality_score
        ) VALUES (?, ?, ?, ?)
    """, (version, datetime.now().isoformat(), len(tickers), avg_score))

    self.conn.commit()
    logger.info(f"Saved {len(tickers)} tickers to pool (version: {version})")
```

Update `get_current_pool()`:

```python
def get_current_pool(self) -> List[str]:
    cursor = self.conn.cursor()
    cursor.execute("""
        SELECT ticker FROM dividend_pool
        WHERE version = (
            SELECT version FROM screening_versions
            ORDER BY created_at DESC LIMIT 1
        )
    """)
    return [row[0] for row in cursor.fetchall()]
```

Add new methods:

```python
def list_versions(self) -> List[Dict]:
    """Return all screening versions sorted by created_at DESC."""
    cursor = self.conn.cursor()
    cursor.execute("""
        SELECT version, created_at, tickers_count, avg_quality_score
        FROM screening_versions
        ORDER BY created_at DESC
    """)
    return [
        {"version": row[0], "created_at": row[1],
         "tickers_count": row[2], "avg_quality_score": row[3]}
        for row in cursor.fetchall()
    ]

def get_pool_by_version(self, version: str) -> List[Dict]:
    """Return full pool records for a given version, sorted by quality_score DESC."""
    cursor = self.conn.cursor()
    cursor.execute("""
        SELECT ticker, name, market, quality_score, consecutive_years,
               dividend_growth_5y, payout_ratio, payout_type, dividend_yield,
               roe, debt_to_equity, industry, sector
        FROM dividend_pool
        WHERE version = ?
        ORDER BY quality_score DESC
    """, (version,))
    cols = ["ticker", "name", "market", "quality_score", "consecutive_years",
            "dividend_growth_5y", "payout_ratio", "payout_type", "dividend_yield",
            "roe", "debt_to_equity", "industry", "sector"]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]
```

Add `from typing import Dict` to imports if missing.

**Step 4: Run GREEN**

```bash
pytest tests/test_dividend_store.py -v
```

**Step 5: Run full suite**

```bash
pytest tests/ -x -q
```

**Step 6: Commit**

```bash
git add src/dividend_store.py tests/test_dividend_store.py
git commit -m "feat(dividend_store): versioned pool schema + list_versions() + get_pool_by_version()"
```

---

### Task 4: dividend_scanners.py — new filter rules + annual_dividend + payout_type

**Files:**
- Modify: `src/dividend_scanners.py`
- Test: `tests/test_dividend_scanners.py`

**Context:** `scan_dividend_pool_weekly()` currently reads universe from the `universe` parameter (a list of tickers passed by caller). New design: caller still passes a list, but the list comes from `config['dividend_universe']` in the script. Scanner gains two new hard filters: `dividend_yield >= 2.0%` and `dividend_growth_5y >= 0%`. Also calculates `annual_dividend` from dividend_history and sets `payout_type` on the returned TickerData.

**Step 1: Write failing tests**

In `tests/test_dividend_scanners.py`, add:

```python
def test_scan_excludes_low_yield_tickers(mock_provider, mock_fs, config):
    """Tickers with dividend_yield < 2.0% must be excluded from pool."""
    mock_provider.get_dividend_history.return_value = _history_5yr()
    mock_provider.get_fundamentals.return_value = {
        "dividend_yield": 1.5,    # below 2% threshold
        "payout_ratio": 40.0,
        "roe": 15.0,
        "debt_to_equity": 0.5,
        "sector": "Consumer Staples",
        "industry": "Beverages",
        "free_cash_flow": 5_000_000,
        "company_name": "Low Yield Co",
    }
    mock_fs.analyze_dividend_quality.return_value = _mock_score(80.0)
    result = scan_dividend_pool_weekly(["LOW_YIELD"], mock_provider, mock_fs, config)
    assert result == []


def test_scan_excludes_negative_growth_tickers(mock_provider, mock_fs, config):
    """Tickers with 5yr dividend growth < 0% must be excluded."""
    # Use a history with a declining dividend
    declining_history = [
        {"date": "2021-03-01", "amount": 1.0},
        {"date": "2022-03-01", "amount": 1.0},
        {"date": "2023-03-01", "amount": 0.9},
        {"date": "2024-03-01", "amount": 0.8},
        {"date": "2025-03-01", "amount": 0.7},
    ]
    mock_provider.get_dividend_history.return_value = declining_history
    mock_provider.get_fundamentals.return_value = {
        "dividend_yield": 4.0,
        "payout_ratio": 60.0,
        "roe": 10.0,
        "debt_to_equity": 0.5,
        "sector": "Utilities",
        "free_cash_flow": 5_000_000,
        "company_name": "Declining Co",
    }
    mock_fs.analyze_dividend_quality.return_value = _mock_score(75.0)
    result = scan_dividend_pool_weekly(["NEG_GROWTH"], mock_provider, mock_fs, config)
    assert result == []


def test_scan_passes_annual_dividend_to_financial_service(mock_provider, mock_fs, config):
    """annual_dividend (sum of last 5yr history) must be in fundamentals passed to FS."""
    history = [
        {"date": "2024-03-01", "amount": 0.5},
        {"date": "2024-06-01", "amount": 0.5},
        {"date": "2024-09-01", "amount": 0.5},
        {"date": "2024-12-01", "amount": 0.5},
    ]
    mock_provider.get_dividend_history.return_value = history
    mock_provider.get_fundamentals.return_value = {
        "dividend_yield": 3.5,
        "payout_ratio": 60.0,
        "roe": 15.0,
        "debt_to_equity": 0.5,
        "sector": "Consumer Staples",
        "free_cash_flow": 10_000_000,
        "company_name": "Test Co",
    }
    mock_fs.analyze_dividend_quality.return_value = _mock_score(80.0)
    scan_dividend_pool_weekly(["TEST"], mock_provider, mock_fs, config)

    call_args = mock_fs.analyze_dividend_quality.call_args
    fundamentals_passed = call_args[1]["fundamentals"] if call_args[1] else call_args[0][1]
    assert "annual_dividend" in fundamentals_passed
    assert fundamentals_passed["annual_dividend"] == pytest.approx(2.0)  # 4 × 0.5


def test_scan_sets_payout_type_on_ticker_data(mock_provider, mock_fs, config):
    """payout_type from quality_score_result must be set on returned TickerData."""
    mock_provider.get_dividend_history.return_value = _history_5yr()
    mock_provider.get_fundamentals.return_value = {
        "dividend_yield": 7.0,
        "payout_ratio": 115.0,
        "roe": 10.0,
        "debt_to_equity": 1.2,
        "sector": "Energy",
        "free_cash_flow": 10_000_000,
        "company_name": "Pipeline Co",
    }
    from src.financial_service import DividendQualityScore
    fcf_score = DividendQualityScore(
        overall_score=78.0, stability_score=80.0, health_score=76.0,
        defensiveness_score=80.0, risk_flags=[],
        payout_type="FCF", effective_payout_ratio=64.0,
    )
    mock_fs.analyze_dividend_quality.return_value = fcf_score
    result = scan_dividend_pool_weekly(["ENB"], mock_provider, mock_fs, config)
    assert len(result) == 1
    assert result[0].payout_type == "FCF"
    assert result[0].payout_ratio == pytest.approx(64.0)
```

**Step 2: Run to confirm RED**

```bash
pytest tests/test_dividend_scanners.py -k "low_yield or negative_growth or annual_dividend or payout_type" -v
```

**Step 3: Implement**

In `src/dividend_scanners.py`, update `scan_dividend_pool_weekly()`:

After calculating `consecutive_years` and `dividend_growth_5y`, add the growth filter:

```python
# New: hard filter — no negative growth
if dividend_growth_5y < 0:
    logger.debug(f"{ticker}: Dividend growth {dividend_growth_5y:.1f}% < 0, skipping")
    continue
```

After fetching `fundamentals`, add yield filter:

```python
# New: hard filter — minimum yield 2%
dividend_yield = fundamentals.get("dividend_yield") or 0.0
if dividend_yield < 2.0:
    logger.debug(f"{ticker}: Dividend yield {dividend_yield:.1f}% < 2%, skipping")
    continue
```

Before calling `financial_service.analyze_dividend_quality()`, calculate annual_dividend:

```python
# Calculate annual_dividend from full 5yr history (sum all amounts)
annual_dividend = sum(d['amount'] for d in dividend_history)
# Use most recent 12 months for current annual rate
from datetime import datetime, timedelta
one_year_ago = datetime.now() - timedelta(days=365)
annual_dividend_ttm = sum(
    d['amount'] for d in dividend_history
    if (datetime.fromisoformat(str(d['date'])) if isinstance(d['date'], str)
        else datetime.combine(d['date'], datetime.min.time())) >= one_year_ago
)
annual_dividend = annual_dividend_ttm if annual_dividend_ttm > 0 else sum(d['amount'] for d in dividend_history) / 5

fundamentals_with_stats = fundamentals.copy()
fundamentals_with_stats["consecutive_years"] = consecutive_years
fundamentals_with_stats["dividend_growth_5y"] = dividend_growth_5y
fundamentals_with_stats["annual_dividend"] = annual_dividend  # NEW
```

After getting `quality_score_result`, update TickerData creation to include `payout_type` and use `effective_payout_ratio`:

```python
ticker_data = TickerData(
    ...
    payout_ratio=quality_score_result.effective_payout_ratio,  # use effective (FCF or GAAP)
    payout_type=quality_score_result.payout_type,              # NEW
    dividend_yield=fundamentals.get("dividend_yield"),
    ...
)
```

**Step 4: Run GREEN**

```bash
pytest tests/test_dividend_scanners.py -v
```

**Step 5: Run full suite**

```bash
pytest tests/ -x -q
```

**Step 6: Commit**

```bash
git add src/dividend_scanners.py tests/test_dividend_scanners.py
git commit -m "feat(dividend_scanners): yield/growth hard filters + annual_dividend + payout_type"
```

---

### Task 5: config.yaml — add dividend_universe seed list

**Files:**
- Modify: `config.yaml`

**Context:** Add the full ~70-ticker seed universe. No code test needed — this is a static config read by the screening script. Tickers with `.HK` suffix are classified as HK market; `.SS`/`.SZ` as CN market by the existing `classify_market()` function.

**Step 1: Add to config.yaml**

Append to `config.yaml` after the `dividend_scanners` block:

```yaml
# 高股息养老股种子池 — 月度筛选的候选标的
# 排除名单 (已割息): T, MMM, KMI
dividend_universe:
  # === 美股 Dividend Kings (连续提息40年+) ===
  - KO       # Coca-Cola, 61yr
  - PG       # Procter & Gamble, 67yr
  - JNJ      # Johnson & Johnson, 61yr
  - CL       # Colgate-Palmolive, 61yr
  - KMB      # Kimberly-Clark, 51yr
  - FRT      # Federal Realty REIT, 55yr
  - EMR      # Emerson Electric, 47yr
  - ITW      # Illinois Tool Works, 50yr+

  # === 美股 Dividend Aristocrats (连续提息25年+) ===
  - O        # Realty Income (月付息)
  - NEE      # NextEra Energy
  - SO       # Southern Company
  - DUK      # Duke Energy
  - WEC      # WEC Energy Group
  - ATO      # Atmos Energy
  - HD       # Home Depot
  - LOW      # Lowe's
  - ABT      # Abbott Labs
  - GD       # General Dynamics
  - LMT      # Lockheed Martin

  # === 美股 高质量高收益 ===
  - ABBV     # AbbVie, ~3.8%
  - VZ       # Verizon, ~6.5%
  - ENB      # Enbridge (管道, FCF派息健康)
  - TRP      # TC Energy (管道)
  - MO       # Altria, ~8.5%
  - JPM      # JPMorgan Chase
  - BLK      # BlackRock
  - MSFT     # Microsoft

  # === 美股 股息ETF ===
  - SCHD     # Schwab US Dividend Equity
  - VYM      # Vanguard High Dividend Yield
  - HDV      # iShares Core High Dividend
  - DGRO     # iShares Dividend Growth
  - VIG      # Vanguard Dividend Appreciation

  # === 港股 公用事业 ===
  - "0002.HK"  # CLP Holdings 中电, 80yr连续
  - "0006.HK"  # HK Electric 港灯, 岛屿垄断
  - "0003.HK"  # HK & China Gas 煤气

  # === 港股 REIT ===
  - "0823.HK"  # Link REIT 领展, 亚洲最大
  - "0778.HK"  # Fortune REIT 富豪

  # === 港股 银行 ===
  - "0005.HK"  # HSBC Holdings 汇丰
  - "0011.HK"  # Hang Seng Bank 恒生
  - "2388.HK"  # BOC Hong Kong 中银香港
  - "0939.HK"  # CCB 建行H股
  - "1398.HK"  # ICBC 工行H股

  # === 港股 电信/能源 ===
  - "0941.HK"  # China Mobile 中移动
  - "0762.HK"  # China Unicom 中联通
  - "0267.HK"  # CNOOC 中海油

  # === 港股 地产/多元 ===
  - "0016.HK"  # Sun Hung Kai 新鸿基
  - "0001.HK"  # CK Hutchison 长和

  # === A股 国有银行 ===
  - "601398.SS"  # 工商银行
  - "601939.SS"  # 建设银行
  - "601988.SS"  # 中国银行
  - "601288.SS"  # 农业银行
  - "600036.SS"  # 招商银行

  # === A股 公用事业/能源 ===
  - "600900.SS"  # 长江电力
  - "600025.SS"  # 华能水电
  - "601088.SS"  # 中国神华
  - "600941.SS"  # 中国移动A股

  # === A股 红利ETF ===
  - "510880.SS"  # 红利ETF
  - "515080.SS"  # 中证红利ETF
  - "512890.SS"  # 红利低波ETF
```

**Step 2: Verify config loads correctly**

```bash
python -c "from src.config import load_config; c = load_config('config.yaml'); print(len(c['dividend_universe']), 'tickers in universe')"
```

Expected output: `52 tickers in universe` (or similar count).

**Step 3: Commit**

```bash
git add config.yaml
git commit -m "config: add dividend_universe seed pool (US/HK/A shares, ~52 tickers)"
```

---

### Task 6: src/dividend_pool_page.py — standalone HTML pool page

**Files:**
- Create: `src/dividend_pool_page.py`
- Test: `tests/test_dividend_pool_page.py`

**Context:** Generates `reports/dividend_pool.html` — a standalone page showing (1) screening methodology explanation, (2) current pool table with all metrics + payout type badge, (3) version history list. Called from `run_dividend_screening.py` after saving the pool.

**Step 1: Write failing tests**

Create `tests/test_dividend_pool_page.py`:

```python
"""Tests for dividend_pool_page.py — standalone pool HTML generator."""
import pytest
from src.dividend_pool_page import generate_dividend_pool_page


def _versions():
    return [
        {"version": "monthly_2026-03", "created_at": "2026-03-05T14:23:00",
         "tickers_count": 2, "avg_quality_score": 81.0},
        {"version": "monthly_2026-02", "created_at": "2026-02-03T09:11:00",
         "tickers_count": 1, "avg_quality_score": 80.0},
    ]


def _pool_records():
    return [
        {"ticker": "KO", "name": "Coca-Cola", "market": "US",
         "quality_score": 85.0, "consecutive_years": 61,
         "dividend_growth_5y": 4.5, "payout_ratio": 65.0,
         "payout_type": "GAAP", "dividend_yield": 3.0,
         "roe": 45.0, "debt_to_equity": 1.8,
         "industry": "Beverages", "sector": "Consumer Staples"},
        {"ticker": "ENB", "name": "Enbridge", "market": "US",
         "quality_score": 78.0, "consecutive_years": 28,
         "dividend_growth_5y": 3.0, "payout_ratio": 64.0,
         "payout_type": "FCF", "dividend_yield": 7.2,
         "roe": 10.0, "debt_to_equity": 1.5,
         "industry": "Oil & Gas Midstream", "sector": "Energy"},
    ]


def test_generate_page_returns_html_string():
    html = generate_dividend_pool_page(_versions(), _pool_records(), "monthly_2026-03")
    assert isinstance(html, str)
    assert html.startswith("<!DOCTYPE html>")


def test_page_contains_ticker_data():
    html = generate_dividend_pool_page(_versions(), _pool_records(), "monthly_2026-03")
    assert "KO" in html
    assert "ENB" in html
    assert "Coca-Cola" in html


def test_page_shows_payout_type_badge():
    html = generate_dividend_pool_page(_versions(), _pool_records(), "monthly_2026-03")
    assert "FCF" in html
    assert "GAAP" in html


def test_page_shows_version_history():
    html = generate_dividend_pool_page(_versions(), _pool_records(), "monthly_2026-03")
    assert "monthly_2026-03" in html
    assert "monthly_2026-02" in html
    assert "2 支" in html or "tickers_count" in html or "2</" in html


def test_page_contains_methodology_explanation():
    html = generate_dividend_pool_page(_versions(), _pool_records(), "monthly_2026-03")
    # Should explain the screening logic
    assert "连续派息" in html or "consecutive" in html.lower()
    assert "FCF" in html


def test_page_handles_empty_pool():
    html = generate_dividend_pool_page(_versions(), [], "monthly_2026-03")
    assert "<!DOCTYPE html>" in html
    # Should not crash, should show empty state
```

**Step 2: Run to confirm RED**

```bash
pytest tests/test_dividend_pool_page.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.dividend_pool_page'`

**Step 3: Implement**

Create `src/dividend_pool_page.py`:

```python
"""
Dividend Pool Page Generator

生成高股息养老股池的独立 HTML 解释页面。
包含：选股逻辑说明、当前池子完整表格（含派息类型）、版本历史。
"""
from html import escape as _esc
from typing import List, Dict, Any


def generate_dividend_pool_page(
    versions: List[Dict[str, Any]],
    pool_records: List[Dict[str, Any]],
    current_version: str,
) -> str:
    """生成 dividend_pool.html 独立页面。

    Args:
        versions: list of {version, created_at, tickers_count, avg_quality_score}
        pool_records: list of pool rows from get_pool_by_version()
        current_version: version string to highlight as current

    Returns:
        Complete HTML string.
    """
    pool_table = _pool_table(pool_records)
    version_list = _version_list(versions, current_version)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>高股息养老股池 — 选股逻辑</title>
{_css()}
</head>
<body>
<div class="container">
  <h1>高股息养老股池 <span class="subtitle">长期吃股息 · 养老防御</span></h1>

  <section class="methodology">
    <h2>选股逻辑</h2>
    <p>参考 <strong>SCHD（Schwab US Dividend Equity ETF）</strong> 方法论，覆盖美股、港股、A股，月度更新。目标：高确定性、基本面稳健、适合长期持有吃股息。</p>

    <h3>硬性筛选规则</h3>
    <table class="rules-table">
      <tr><th>规则</th><th>阈值</th><th>说明</th></tr>
      <tr><td>连续派息年限</td><td>≥ 5 年</td><td>至少经历一个完整市场周期</td></tr>
      <tr><td>当前股息率</td><td>≥ 2.0%</td><td>过滤名义派息但收益极低的标的</td></tr>
      <tr><td>5 年股息增长率</td><td>≥ 0%</td><td>排除持续削减股息的标的</td></tr>
      <tr><td>派息率（行业感知）</td><td>≤ 100%</td><td>见下方行业说明</td></tr>
      <tr><td>股息质量综合评分</td><td>≥ 70</td><td>稳定性×40% + 财务健康×40% + 防御性×20%</td></tr>
    </table>

    <h3>派息率行业分类逻辑</h3>
    <p>GAAP 净利润对资本密集型行业存在严重失真（大量折旧摊销压低净利润），因此按行业选择不同指标：</p>
    <table class="rules-table">
      <tr><th>行业</th><th>使用指标</th><th>原因</th></tr>
      <tr>
        <td><span class="badge badge-fcf">Energy</span> <span class="badge badge-fcf">Utilities</span> <span class="badge badge-fcf">Real Estate</span></td>
        <td><strong>FCF 派息率</strong><br>年度股息 / 自由现金流</td>
        <td>管道/电力/REIT 资产折旧周期 20-40 年，D&A 极大，GAAP 净利润严重低估真实盈利能力</td>
      </tr>
      <tr>
        <td>其他行业</td>
        <td><strong>GAAP 派息率</strong><br>股息 / 净利润</td>
        <td>轻资产行业 D&A 影响较小，GAAP 派息率准确</td>
      </tr>
    </table>
  </section>

  <section class="pool-section">
    <h2>当前池子
      <span class="version-badge">{_esc(current_version)}</span>
      <span class="count-badge">{len(pool_records)} 支标的</span>
    </h2>
    {pool_table}
  </section>

  <section class="versions-section">
    <h2>版本历史</h2>
    {version_list}
  </section>
</div>
</body>
</html>"""


def _pool_table(records: List[Dict]) -> str:
    if not records:
        return '<p class="empty">当前池子为空</p>'

    rows = []
    for r in records:
        payout_badge = (
            '<span class="badge badge-fcf">FCF</span>'
            if r.get("payout_type") == "FCF"
            else '<span class="badge badge-gaap">GAAP</span>'
        )
        yield_str = f"{r['dividend_yield']:.1f}%" if r.get('dividend_yield') else "N/A"
        payout_str = f"{r['payout_ratio']:.0f}%" if r.get('payout_ratio') else "N/A"
        score_str = f"{r['quality_score']:.0f}" if r.get('quality_score') else "N/A"
        growth_str = f"{r['dividend_growth_5y']:+.1f}%" if r.get('dividend_growth_5y') is not None else "N/A"
        rows.append(f"""
      <tr>
        <td class="ticker">{_esc(r['ticker'])}</td>
        <td>{_esc(r.get('name') or r['ticker'])}</td>
        <td><span class="market-badge">{_esc(r.get('market',''))}</span></td>
        <td class="score">{score_str}</td>
        <td>{r.get('consecutive_years', 'N/A')}年</td>
        <td>{yield_str}</td>
        <td>{payout_badge} {payout_str}</td>
        <td>{growth_str}</td>
        <td>{_esc(r.get('sector') or '')}</td>
      </tr>""")

    return f"""<table class="pool-table">
    <thead>
      <tr>
        <th>代码</th><th>名称</th><th>市场</th><th>评分</th>
        <th>连续年限</th><th>股息率</th><th>派息率</th><th>5年增长</th><th>行业</th>
      </tr>
    </thead>
    <tbody>{''.join(rows)}
    </tbody>
  </table>"""


def _version_list(versions: List[Dict], current: str) -> str:
    if not versions:
        return '<p class="empty">暂无历史版本</p>'
    rows = []
    for v in versions:
        cls = "version-row current" if v["version"] == current else "version-row"
        created = v.get("created_at", "")[:16].replace("T", " ")
        rows.append(f"""
    <tr class="{cls}">
      <td>{_esc(v['version'])}</td>
      <td>{_esc(created)}</td>
      <td>{v.get('tickers_count', 0)} 支</td>
      <td>{v.get('avg_quality_score', 0):.1f}</td>
    </tr>""")
    return f"""<table class="version-table">
  <thead><tr><th>版本</th><th>筛选时间</th><th>入池数</th><th>平均评分</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>"""


def _css() -> str:
    return """<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif;
       background: #0d1117; color: #c9d1d9; line-height: 1.6; }
.container { max-width: 1100px; margin: 0 auto; padding: 2rem; }
h1 { font-size: 1.8rem; color: #f0f6fc; margin-bottom: 0.3rem; }
h2 { font-size: 1.2rem; color: #58a6ff; margin: 2rem 0 0.8rem; border-bottom: 1px solid #30363d; padding-bottom: 0.4rem; }
h3 { font-size: 1rem; color: #8b949e; margin: 1.2rem 0 0.5rem; }
.subtitle { font-size: 0.9rem; color: #8b949e; font-weight: 400; margin-left: 0.5rem; }
section { margin-bottom: 2.5rem; }
p { color: #8b949e; margin-bottom: 0.8rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th { background: #161b22; color: #8b949e; padding: 0.5rem 0.7rem; text-align: left; font-weight: 500; }
td { padding: 0.45rem 0.7rem; border-bottom: 1px solid #21262d; }
tr:hover td { background: #161b22; }
.ticker { font-weight: 600; color: #f0f6fc; font-family: monospace; }
.score { font-weight: 600; color: #3fb950; }
.empty { color: #8b949e; font-style: italic; padding: 1rem 0; }
.badge { display: inline-block; padding: 0.1rem 0.45rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
.badge-fcf  { background: #1f4a2e; color: #3fb950; }
.badge-gaap { background: #1a2942; color: #58a6ff; }
.market-badge { background: #21262d; color: #8b949e; padding: 0.1rem 0.35rem; border-radius: 3px; font-size: 0.75rem; }
.version-badge { background: #1f4a2e; color: #3fb950; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.8rem; margin-left: 0.5rem; }
.count-badge   { background: #1a2942; color: #58a6ff; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.8rem; }
.version-row.current td { color: #3fb950; }
</style>"""
```

**Step 4: Run GREEN**

```bash
pytest tests/test_dividend_pool_page.py -v
```

**Step 5: Run full suite**

```bash
pytest tests/ -x -q
```

**Step 6: Commit**

```bash
git add src/dividend_pool_page.py tests/test_dividend_pool_page.py
git commit -m "feat(dividend_pool_page): generate standalone pool HTML explanation page"
```

---

### Task 7: html_report.py — add ⓘ badge linking to dividend_pool.html

**Files:**
- Modify: `src/html_report.py` — find the dividend section heading and add ⓘ anchor
- Test: `tests/test_html_report.py`

**Context:** The daily report's dividend section has a heading rendered by `_dividend_section()`. Add `<a href="dividend_pool.html" class="info-badge" title="查看选股逻辑与完整池子">ⓘ</a>` next to it.

**Step 1: Write failing test**

In `tests/test_html_report.py`, add to `TestDividendSection`:

```python
def test_dividend_section_has_info_badge_linking_to_pool_page(self):
    """Dividend section heading must have ⓘ badge linking to dividend_pool.html."""
    signal = _make_dividend_signal("KO", yield_pct=4.5, percentile=93.0)
    html = format_html_report(
        **_base_kwargs(),
        dividend_signals=[signal],
        dividend_pool_summary={"count": 30, "last_update": "2026-03"},
    )
    assert 'href="dividend_pool.html"' in html
    assert 'ⓘ' in html or '&#9432;' in html
```

**Step 2: Run to confirm RED**

```bash
pytest tests/test_html_report.py -k "info_badge" -v
```

**Step 3: Implement**

In `src/html_report.py`, find `_dividend_section()`. Locate where the section `<h2>` or section title is rendered and add the badge:

```python
# In _dividend_section(), change the heading line from e.g.:
#   <h2>高股息防御双打</h2>
# to:
#   <h2>高股息防御双打 <a href="dividend_pool.html" class="info-badge" title="查看选股逻辑与完整池子">ⓘ</a></h2>
```

Also add CSS for `.info-badge` in the report's `<style>` block if not already present:

```css
.info-badge { color: #58a6ff; text-decoration: none; font-size: 0.85rem;
              border: 1px solid #30363d; border-radius: 50%; padding: 0 0.3rem;
              margin-left: 0.4rem; vertical-align: middle; }
.info-badge:hover { background: #161b22; }
```

**Step 4: Run GREEN**

```bash
pytest tests/test_html_report.py -v
```

**Step 5: Run full suite**

```bash
pytest tests/ -x -q
```

**Step 6: Commit**

```bash
git add src/html_report.py tests/test_html_report.py
git commit -m "feat(html_report): add ⓘ badge on dividend section linking to pool page"
```

---

### Task 8: scripts — monthly version format + pool page generation + CLI viewer

**Files:**
- Modify: `scripts/run_dividend_screening.py`
- Create: `scripts/view_dividend_pool.py`

**Context:** No unit tests for scripts — they are integration-tested manually. `run_dividend_screening.py` changes version format to `monthly_YYYY-MM` and generates `dividend_pool.html` after saving the pool. `view_dividend_pool.py` is a new CLI tool to browse versions and pool data.

**Step 1: Update run_dividend_screening.py**

Change version format (find the line `version = f"weekly_{date.today().isoformat()}"` and replace):

```python
from datetime import date
version = f"monthly_{date.today().strftime('%Y-%m')}"
```

After `store.save_pool(pool, version=version)`, add pool page generation:

```python
# Generate dividend_pool.html
from src.dividend_pool_page import generate_dividend_pool_page
versions = store.list_versions()
pool_records = store.get_pool_by_version(version)
pool_html = generate_dividend_pool_page(versions, pool_records, version)

reports_dir = config.get("reports", {}).get("output_dir", "reports")
os.makedirs(reports_dir, exist_ok=True)
pool_page_path = os.path.join(reports_dir, "dividend_pool.html")
with open(pool_page_path, "w", encoding="utf-8") as f:
    f.write(pool_html)
logger.info(f"Pool page saved: {pool_page_path}")
```

Also update the script to read `dividend_universe` from config instead of `csv_url`:

```python
# Replace:
#   tickers, _ = fetch_universe(config["csv_url"])
# With:
universe = config.get("dividend_universe", [])
if not universe:
    logger.error("No dividend_universe configured in config.yaml")
    sys.exit(1)
tickers = universe
logger.info(f"Universe: {len(tickers)} tickers from dividend_universe config")
```

**Step 2: Create scripts/view_dividend_pool.py**

```python
#!/usr/bin/env python3
"""
高股息养老股池 — 命令行查看工具

用法:
    python scripts/view_dividend_pool.py              # 查看最新版本
    python scripts/view_dividend_pool.py --list       # 列出所有版本
    python scripts/view_dividend_pool.py --version monthly_2026-02
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config
from src.dividend_store import DividendStore


def main():
    parser = argparse.ArgumentParser(description="查看高股息养老股池")
    parser.add_argument("--list", action="store_true", help="列出所有历史版本")
    parser.add_argument("--version", type=str, help="查看指定版本 (e.g. monthly_2026-02)")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    db_path = config.get("data", {}).get("dividend_db_path", "data/dividend_pool.db")

    if not os.path.exists(db_path):
        print(f"数据库不存在: {db_path}")
        print("请先运行: python scripts/run_dividend_screening.py")
        sys.exit(1)

    store = DividendStore(db_path)

    try:
        if args.list:
            _print_versions(store)
        else:
            version = args.version
            if not version:
                versions = store.list_versions()
                if not versions:
                    print("池子为空，请先运行筛选脚本")
                    return
                version = versions[0]["version"]
            _print_pool(store, version)
    finally:
        store.close()


def _print_versions(store: DividendStore):
    versions = store.list_versions()
    if not versions:
        print("暂无历史版本")
        return
    print(f"\n{'版本':<22} {'筛选时间':<20} {'入池数':>6} {'平均评分':>8}")
    print("-" * 62)
    for v in versions:
        created = v.get("created_at", "")[:16].replace("T", " ")
        marker = " ← 当前" if v == versions[0] else ""
        print(f"{v['version']:<22} {created:<20} {v['tickers_count']:>6} {v['avg_quality_score']:>8.1f}{marker}")


def _print_pool(store: DividendStore, version: str):
    records = store.get_pool_by_version(version)
    if not records:
        print(f"版本 {version} 不存在或池子为空")
        return

    print(f"\n版本: {version} | 入池: {len(records)} 支标的\n")
    header = f"{'代码':<12} {'市场':<5} {'评分':>5} {'连续年':>6} {'股息率':>7} {'派息类型':<8} {'派息率':>7} {'行业'}"
    print(header)
    print("-" * 80)
    for r in records:
        yield_str = f"{r['dividend_yield']:.1f}%" if r.get('dividend_yield') else "N/A "
        payout_str = f"{r['payout_ratio']:.0f}%" if r.get('payout_ratio') else "N/A"
        score_str = f"{r['quality_score']:.0f}" if r.get('quality_score') else "N/A"
        ptype = r.get('payout_type') or 'GAAP'
        print(
            f"{r['ticker']:<12} {r.get('market',''):<5} {score_str:>5} "
            f"{str(r.get('consecutive_years','N/A')):>6} {yield_str:>7} "
            f"{ptype:<8} {payout_str:>7}  {r.get('sector','')}"
        )


if __name__ == "__main__":
    main()
```

**Step 3: Manual verification**

```bash
# After running the screening script once:
python scripts/view_dividend_pool.py --list
python scripts/view_dividend_pool.py
```

**Step 4: Run full test suite one final time**

```bash
pytest tests/ -v --tb=short
```

Expected: All green.

**Step 5: Commit**

```bash
git add scripts/run_dividend_screening.py scripts/view_dividend_pool.py
git commit -m "feat(scripts): monthly versioning + pool page generation + CLI viewer"
```

---

## Summary

| Task | Files | Key Change |
|------|-------|-----------|
| 1 | `market_data.py` | `get_fundamentals()` adds `dividend_yield`, `company_name` |
| 2 | `data_engine.py`, `financial_service.py` | `payout_type` field + FCF sectors logic |
| 3 | `dividend_store.py` | Versioned schema + `list_versions()` + `get_pool_by_version()` |
| 4 | `dividend_scanners.py` | yield/growth hard filters + `annual_dividend` + `payout_type` on TickerData |
| 5 | `config.yaml` | ~52-ticker `dividend_universe` seed list |
| 6 | `src/dividend_pool_page.py` (new) | Standalone HTML pool explanation page |
| 7 | `html_report.py` | ⓘ badge → `dividend_pool.html` |
| 8 | `scripts/run_dividend_screening.py`, `scripts/view_dividend_pool.py` (new) | Monthly versioning + page gen + CLI viewer |
