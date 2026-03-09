# Dividend Card Enrichment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enrich the dividend signal card with: (1) a business stability tooltip showing 5 dimensional scores + LLM analysis text, (2) a worst-case floor price in Dim 5 using forward dividend rate + 5-year max yield, and (3) data freshness tracking with event-triggered re-evaluation flags.

**Architecture:** Changes flow bottom-up: `financial_service.py` outputs richer scoring → `dividend_store.py` stores new fields → `dividend_scanners.py` computes and threads new data → `main.py` extends payload → `dashboard.html` + `html_report.py` render new UI.

**Tech Stack:** Python dataclasses, SQLite ALTER TABLE migration, yfinance `forwardAnnualDividendRate`, Anthropic Claude (analysis text), Vanilla JS tooltip toggle

---

## Context: Key Files

- `src/financial_service.py` — `DividendQualityScore` dataclass + `FinancialServiceAnalyzer`
- `src/dividend_store.py` — SQLite store, `dividend_pool` table
- `src/dividend_scanners.py` — `scan_dividend_pool_weekly`, `scan_dividend_buy_signal`, `DividendBuySignal`
- `src/data_engine.py` — `TickerData` dataclass
- `src/market_data.py` — `_yf_fundamentals` (returns fundamentals dict, currently missing `forward_dividend_rate`)
- `src/main.py` — `_build_agent_payload` + dividend section in `run_scan`
- `agent/static/dashboard.html` — `cardDividend` JS function
- `src/html_report.py` — `_dividend_card` Python function
- `tests/test_financial_service.py`, `tests/test_dividend_store.py`, `tests/test_dividend_scanners.py`, `tests/test_integration.py`

---

## Task 1: Extend `DividendQualityScore` with `quality_breakdown` and `analysis_text`

**Files:**
- Modify: `src/financial_service.py`
- Test: `tests/test_financial_service.py`

### Step 1: Write the failing tests

```python
# tests/test_financial_service.py — add these tests

def test_quality_score_has_breakdown():
    """DividendQualityScore should include quality_breakdown dict with 5 keys."""
    from src.financial_service import FinancialServiceAnalyzer
    fs = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    result = fs.analyze_dividend_quality("T", {
        "consecutive_years": 5,
        "dividend_growth_5y": 4.0,
        "roe": 15.0,
        "debt_to_equity": 1.0,
        "payout_ratio": 60.0,
        "sector": "Communication Services",
        "industry": "Telecom",
    })
    assert result is not None
    assert result.quality_breakdown is not None
    for key in ("continuity", "growth", "payout_safety", "financial_health", "defensiveness"):
        assert key in result.quality_breakdown
        assert 0.0 <= result.quality_breakdown[key] <= 20.0


def test_quality_breakdown_caps_at_20():
    """Each breakdown dimension should be capped at 20."""
    from src.financial_service import FinancialServiceAnalyzer
    fs = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    result = fs.analyze_dividend_quality("KO", {
        "consecutive_years": 62,   # would overflow without cap
        "dividend_growth_5y": 50.0,  # same
        "roe": 50.0,
        "debt_to_equity": 0.0,
        "payout_ratio": 40.0,
        "sector": "Consumer Staples",
        "industry": "Beverages",
    })
    for val in result.quality_breakdown.values():
        assert val <= 20.0


def test_quality_score_analysis_text_empty_without_api_key():
    """analysis_text should be empty string when no api_key provided."""
    from src.financial_service import FinancialServiceAnalyzer
    fs = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True, api_key="")
    result = fs.analyze_dividend_quality("KO", {
        "consecutive_years": 10, "dividend_growth_5y": 5.0,
        "roe": 20.0, "debt_to_equity": 0.5, "payout_ratio": 60.0,
        "sector": "Consumer Staples", "industry": "Beverages",
    })
    assert result.analysis_text == ""
```

### Step 2: Run tests to verify they fail

```bash
python3 -m pytest tests/test_financial_service.py::test_quality_score_has_breakdown tests/test_financial_service.py::test_quality_breakdown_caps_at_20 tests/test_financial_service.py::test_quality_score_analysis_text_empty_without_api_key -v
```
Expected: FAIL — `DividendQualityScore` has no `quality_breakdown` attribute.

### Step 3: Implement changes in `src/financial_service.py`

**3a. Add fields to `DividendQualityScore`** (after `effective_payout_ratio` field, around line 50):

```python
    quality_breakdown: Optional[Dict[str, float]] = None
    analysis_text: Optional[str] = None
```

Add `Optional` import if not present: `from typing import List, Dict, Any, Optional`

**3b. Compute `quality_breakdown` in `_calculate_rule_based_score`** (add after step 4, before `return`, around line 253):

```python
        quality_breakdown = {
            "continuity": min(round(consecutive_years * 2.0, 1), 20.0),
            "growth": min(round(max(dividend_growth * 0.67, 0.0), 1), 20.0),
            "payout_safety": round(payout_score / 2.0, 1),
            "financial_health": min(round((roe_score + debt_score) / 3.0, 1), 20.0),
            "defensiveness": round(defensiveness_score * 0.2, 1),
        }
```

**3c. Pass `quality_breakdown` in the `return` statement** (replace the existing `return DividendQualityScore(...)` around line 256):

```python
        return DividendQualityScore(
            overall_score=overall_score,
            stability_score=stability_score,
            health_score=health_score,
            defensiveness_score=defensiveness_score,
            risk_flags=risk_flags,
            payout_type=payout_type,
            effective_payout_ratio=effective_payout_ratio,
            quality_breakdown=quality_breakdown,
            analysis_text="",  # will be populated by analyze_dividend_quality
        )
```

**3d. Add `_get_analysis_text` method** (add before `analyze_dividend_quality` around line 141):

```python
    def _get_analysis_text(self, ticker: str, sector: str, industry: str,
                           quality_result: "DividendQualityScore") -> str:
        """Generate 2-3 sentence business stability analysis. Cached per ticker, 7-day TTL."""
        if self.store:
            cached = self.store.get_analysis_text(ticker)
            if cached:
                return cached
        if not self.api_key:
            return ""
        try:
            client = self._get_client()
            prompt = (
                f"股票: {ticker}\n"
                f"行业: {sector} / {industry}\n"
                f"综合质量评分: {quality_result.overall_score:.0f}/100\n"
                f"稳定性: {quality_result.stability_score:.0f}, "
                f"财务健康: {quality_result.health_score:.0f}, "
                f"防御性: {quality_result.defensiveness_score:.0f}\n"
                "用2-3句中文描述该公司作为长期股息标的的业务稳定性，"
                "突出最核心的护城河或主要风险点。"
            )
            resp = client.messages.create(
                model=self.model,
                max_tokens=200,
                system="你是专业股息投资分析师。直接返回分析文字，不加标题或格式符号。",
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            if self.store:
                self.store.save_analysis_text(ticker, text)
            logger.info(f"Analysis text generated for {ticker}")
            return text
        except Exception as e:
            logger.warning(f"Analysis text failed for {ticker}: {e}")
            return ""
```

**3e. Call `_get_analysis_text` in `analyze_dividend_quality`** (after the `return self._calculate_rule_based_score(...)` calls — refactor to capture result first):

Replace the body of `analyze_dividend_quality` (lines 164-172) with:

```python
        if self.enabled and self.api_key:
            sector = fundamentals.get("sector") or ""
            industry = fundamentals.get("industry") or ""
            defensiveness_score = self._get_defensiveness_score(sector, industry)
            result = self._calculate_rule_based_score(
                ticker, fundamentals, defensiveness_override=defensiveness_score
            )
            result.analysis_text = self._get_analysis_text(ticker, sector, industry, result)
            return result
        if not self.fallback_to_rules:
            logger.warning(f"{ticker}: Financial Service disabled, no fallback allowed")
            return None
        return self._calculate_rule_based_score(ticker, fundamentals)
```

### Step 4: Run tests to verify they pass

```bash
python3 -m pytest tests/test_financial_service.py::test_quality_score_has_breakdown tests/test_financial_service.py::test_quality_breakdown_caps_at_20 tests/test_financial_service.py::test_quality_score_analysis_text_empty_without_api_key -v
```
Expected: PASS

### Step 5: Run full test suite to check for regressions

```bash
python3 -m pytest tests/ -q
```
Expected: all previously passing tests still pass.

### Step 6: Commit

```bash
git add src/financial_service.py tests/test_financial_service.py
git commit -m "feat: extend DividendQualityScore with 5-dim breakdown and analysis_text"
```

---

## Task 2: Extend `DividendStore` — new columns, analysis cache, pool records accessor

**Files:**
- Modify: `src/dividend_store.py`
- Test: `tests/test_dividend_store.py`

### Step 1: Write failing tests

```python
# tests/test_dividend_store.py — add these tests

def test_pool_records_returns_new_columns(tmp_path):
    """get_pool_records should return quality_breakdown dict and analysis_text."""
    import json
    from src.dividend_store import DividendStore
    from src.data_engine import TickerData
    db_path = str(tmp_path / "test.db")
    store = DividendStore(db_path)

    # Create a minimal TickerData with new fields
    td = TickerData(
        ticker="KO", name="Coca-Cola", market="US",
        last_price=62.5, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=62.5,
        earnings_date=None, days_to_earnings=None,
        dividend_quality_score=85.0,
        quality_breakdown={"continuity": 18.0, "growth": 10.0, "payout_safety": 20.0,
                           "financial_health": 17.0, "defensiveness": 16.0},
        analysis_text="KO has 62 years of consecutive dividend growth.",
        forward_dividend_rate=1.94,
        max_yield_5y=4.5,
        data_version_date=None,
    )
    store.save_pool([td], version="2026-03-09")

    records = store.get_pool_records()
    assert len(records) == 1
    r = records[0]
    assert r["ticker"] == "KO"
    assert isinstance(r["quality_breakdown"], dict)
    assert r["quality_breakdown"]["continuity"] == 18.0
    assert r["analysis_text"] == "KO has 62 years of consecutive dividend growth."
    assert r["forward_dividend_rate"] == 1.94
    assert r["max_yield_5y"] == 4.5
    store.close()


def test_analysis_text_cache(tmp_path):
    """save_analysis_text and get_analysis_text should cache with TTL."""
    from src.dividend_store import DividendStore
    db_path = str(tmp_path / "test.db")
    store = DividendStore(db_path)
    store.save_analysis_text("KO", "KO is a moat stock.")
    assert store.get_analysis_text("KO") == "KO is a moat stock."
    assert store.get_analysis_text("MSFT") is None
    store.close()
```

### Step 2: Run tests to verify they fail

```bash
python3 -m pytest tests/test_dividend_store.py::test_pool_records_returns_new_columns tests/test_dividend_store.py::test_analysis_text_cache -v
```
Expected: FAIL — methods don't exist yet.

### Step 3: Implement changes in `src/dividend_store.py`

**3a. Add `import json` at the top** (line 1, after `import sqlite3`):
```python
import json
```

**3b. Add `analysis_cache` table creation** in `_create_tables` (after the `defensiveness_cache` CREATE, around line 87):

```python
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_cache (
                ticker   TEXT PRIMARY KEY,
                text     TEXT NOT NULL,
                expires  TEXT NOT NULL
            )
        """)
```

**3c. Add column migration for `dividend_pool`** in `_create_tables`, after the existing migration check (around line 33, before the CREATE TABLE):

```python
        # Migrate dividend_pool: add new enrichment columns if missing
        cursor.execute("PRAGMA table_info(dividend_pool)")
        pool_cols = {row[1] for row in cursor.fetchall()}
        new_pool_cols = {
            "quality_breakdown": "TEXT",
            "analysis_text": "TEXT",
            "forward_dividend_rate": "REAL",
            "max_yield_5y": "REAL",
            "data_version_date": "TEXT",
        }
        for col, col_type in new_pool_cols.items():
            if col not in pool_cols and pool_cols:  # only if table exists
                cursor.execute(f"ALTER TABLE dividend_pool ADD COLUMN {col} {col_type}")
                logger.info(f"Migrated dividend_pool: added column {col}")
```

**3d. Update `save_pool` INSERT** (replace the existing INSERT statement, lines 100-116):

```python
            cursor.execute("""
                INSERT INTO dividend_pool (
                    ticker, version, name, market, quality_score,
                    consecutive_years, dividend_growth_5y, payout_ratio,
                    payout_type, dividend_yield, roe, debt_to_equity,
                    industry, sector, added_date,
                    quality_breakdown, analysis_text, forward_dividend_rate,
                    max_yield_5y, data_version_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ))
```

**3e. Add `get_pool_records` method** (after `get_current_pool`, around line 151):

```python
    def get_pool_records(self) -> List[Dict]:
        """Return full records for the current pool version, including all enrichment fields."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT ticker, name, market, quality_score, consecutive_years,
                   dividend_growth_5y, payout_ratio, payout_type, dividend_yield,
                   roe, debt_to_equity, industry, sector,
                   quality_breakdown, analysis_text, forward_dividend_rate,
                   max_yield_5y, data_version_date
            FROM dividend_pool
            WHERE version = (
                SELECT version FROM screening_versions
                ORDER BY created_at DESC LIMIT 1
            )
            ORDER BY quality_score DESC
        """)
        cols = [
            "ticker", "name", "market", "quality_score", "consecutive_years",
            "dividend_growth_5y", "payout_ratio", "payout_type", "dividend_yield",
            "roe", "debt_to_equity", "industry", "sector",
            "quality_breakdown", "analysis_text", "forward_dividend_rate",
            "max_yield_5y", "data_version_date",
        ]
        records = []
        for row in cursor.fetchall():
            d = dict(zip(cols, row))
            if d.get("quality_breakdown"):
                try:
                    d["quality_breakdown"] = json.loads(d["quality_breakdown"])
                except Exception:
                    d["quality_breakdown"] = {}
            records.append(d)
        return records
```

**3f. Add `get_analysis_text` and `save_analysis_text` methods** (after `save_defensiveness_score`, around line 243):

```python
    def get_analysis_text(self, ticker: str) -> Optional[str]:
        """Return cached analysis text if not expired, else None."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT text, expires FROM analysis_cache WHERE ticker=?", (ticker,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        text, expires = row
        if expires < date.today().isoformat():
            return None
        return text

    def save_analysis_text(self, ticker: str, text: str, ttl_days: int = 7):
        """Persist analysis text with TTL (default 7 days)."""
        expires = (date.today() + timedelta(days=ttl_days)).isoformat()
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO analysis_cache (ticker, text, expires) VALUES (?,?,?)",
            (ticker, text, expires),
        )
        self.conn.commit()
```

### Step 4: Run tests to verify they pass

```bash
python3 -m pytest tests/test_dividend_store.py::test_pool_records_returns_new_columns tests/test_dividend_store.py::test_analysis_text_cache -v
```
Expected: PASS

### Step 5: Run full test suite

```bash
python3 -m pytest tests/ -q
```
Expected: all passing.

### Step 6: Commit

```bash
git add src/dividend_store.py tests/test_dividend_store.py
git commit -m "feat: extend DividendStore with enrichment columns and analysis cache"
```

---

## Task 3: Add `forward_dividend_rate` to `market_data.py` and new fields to `TickerData`

**Files:**
- Modify: `src/market_data.py` (around line 640 in `_yf_fundamentals`)
- Modify: `src/data_engine.py` (around line 41 in `TickerData`)
- Test: `tests/test_market_data.py`, `tests/test_data_engine.py`

### Step 1: Write failing tests

```python
# tests/test_data_engine.py — add:
def test_ticker_data_has_enrichment_fields():
    """TickerData should accept new enrichment fields without error."""
    from src.data_engine import TickerData
    td = TickerData(
        ticker="KO", name="Coca-Cola", market="US",
        last_price=62.5, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=62.5,
        earnings_date=None, days_to_earnings=None,
        quality_breakdown={"continuity": 18.0},
        analysis_text="Strong moat.",
        forward_dividend_rate=1.94,
        max_yield_5y=4.5,
        data_version_date=None,
        needs_reeval=False,
    )
    assert td.forward_dividend_rate == 1.94
    assert td.max_yield_5y == 4.5
    assert td.quality_breakdown["continuity"] == 18.0
```

```python
# tests/test_market_data.py — add:
def test_yf_fundamentals_includes_forward_dividend_rate(mocker):
    """_yf_fundamentals should include forward_dividend_rate from yfinance info."""
    import yfinance as yf
    from src.market_data import MarketDataProvider
    mock_info = {
        "payoutRatio": 0.6, "returnOnEquity": 0.15,
        "debtToEquity": 1.0, "industry": "Beverages",
        "sector": "Consumer Staples", "freeCashflow": 1e9,
        "trailingAnnualDividendYield": 0.032,
        "longName": "Coca-Cola",
        "forwardAnnualDividendRate": 1.94,
    }
    mocker.patch.object(yf.Ticker, "__init__", return_value=None)
    mocker.patch.object(yf.Ticker, "info", new_callable=lambda: property(lambda self: mock_info))
    provider = MarketDataProvider(ibkr_config=None, iv_db_path=":memory:")
    result = provider._yf_fundamentals("KO")
    assert result is not None
    assert result["forward_dividend_rate"] == 1.94
```

### Step 2: Run tests to verify they fail

```bash
python3 -m pytest tests/test_data_engine.py::test_ticker_data_has_enrichment_fields tests/test_market_data.py::test_yf_fundamentals_includes_forward_dividend_rate -v
```
Expected: FAIL.

### Step 3: Add new fields to `TickerData` in `src/data_engine.py`

Add after `payout_type` field (line 41), still in the Phase 2 section:

```python
    # Phase 2 enrichment: dividend card depth fields
    quality_breakdown: Optional[Dict] = None
    analysis_text: Optional[str] = None
    forward_dividend_rate: Optional[float] = None   # yfinance forwardAnnualDividendRate
    max_yield_5y: Optional[float] = None            # max yield over 5-year price history
    data_version_date: Optional[date] = None        # when pool record was last written
    needs_reeval: bool = False                       # True if earnings passed since last scan
```

Add `Dict` to the Optional import at top of data_engine.py if not already present: `from typing import Optional, Dict`

### Step 4: Add `forward_dividend_rate` to `_yf_fundamentals` in `src/market_data.py`

In `_yf_fundamentals`, add to the return dict (after `"company_name"`, around line 649):

```python
                "forward_dividend_rate": info.get("forwardAnnualDividendRate"),
```

### Step 5: Run tests to verify they pass

```bash
python3 -m pytest tests/test_data_engine.py::test_ticker_data_has_enrichment_fields tests/test_market_data.py::test_yf_fundamentals_includes_forward_dividend_rate -v
```
Expected: PASS

### Step 6: Run full test suite

```bash
python3 -m pytest tests/ -q
```

### Step 7: Commit

```bash
git add src/data_engine.py src/market_data.py tests/test_data_engine.py tests/test_market_data.py
git commit -m "feat: add forward_dividend_rate to market_data and enrichment fields to TickerData"
```

---

## Task 4: Extend `scan_dividend_pool_weekly` to compute and store new fields

**Files:**
- Modify: `src/dividend_scanners.py`
- Test: `tests/test_dividend_scanners.py`

### Step 1: Write the failing test

```python
# tests/test_dividend_scanners.py — add:

def test_weekly_scan_populates_forward_dividend_and_max_yield(mocker):
    """scan_dividend_pool_weekly should populate forward_dividend_rate and max_yield_5y."""
    import pandas as pd
    import numpy as np
    from datetime import date
    from src.dividend_scanners import scan_dividend_pool_weekly

    # Mock provider
    provider = mocker.MagicMock()
    provider.get_dividend_history.return_value = [
        {"date": "2020-03-01", "amount": 0.46},
        {"date": "2020-06-01", "amount": 0.46},
        {"date": "2020-09-01", "amount": 0.46},
        {"date": "2020-12-01", "amount": 0.46},
        {"date": "2021-03-01", "amount": 0.48},
        {"date": "2021-06-01", "amount": 0.48},
        {"date": "2025-03-01", "amount": 0.485},
        {"date": "2025-06-01", "amount": 0.485},
        {"date": "2025-09-01", "amount": 0.485},
        {"date": "2025-12-01", "amount": 0.485},
    ]
    # 5-year price history: min price = 45.0
    idx = pd.date_range("2021-01-01", periods=100, freq="ME")
    prices = pd.Series([62.5] * 99 + [45.0], index=idx)
    df = pd.DataFrame({"Close": prices})
    provider.get_price_data.return_value = df
    provider.get_fundamentals.return_value = {
        "payout_ratio": 72.0, "roe": 15.0, "debt_to_equity": 0.5,
        "sector": "Consumer Staples", "industry": "Beverages",
        "dividend_yield": 3.2, "company_name": "Coca-Cola",
        "free_cash_flow": 1e9, "forward_dividend_rate": 1.94,
    }
    provider.should_skip_options.return_value = True

    # Mock financial service
    financial_service = mocker.MagicMock()
    from src.financial_service import DividendQualityScore
    financial_service.analyze_dividend_quality.return_value = DividendQualityScore(
        overall_score=85.0, stability_score=80.0, health_score=70.0,
        defensiveness_score=75.0, risk_flags=[],
        quality_breakdown={"continuity": 18.0, "growth": 10.0,
                           "payout_safety": 20.0, "financial_health": 17.0,
                           "defensiveness": 15.0},
        analysis_text="Strong moat.",
    )

    config = {"dividend_scanners": {"min_quality_score": 70, "min_consecutive_years": 5,
                                    "max_payout_ratio": 100}}
    results = scan_dividend_pool_weekly(
        universe=["KO"], provider=provider,
        financial_service=financial_service, config=config
    )
    assert len(results) == 1
    td = results[0]
    assert td.forward_dividend_rate == 1.94
    assert td.max_yield_5y is not None
    assert td.max_yield_5y > 0
    assert td.quality_breakdown is not None
    assert td.analysis_text == "Strong moat."
```

### Step 2: Run test to verify it fails

```bash
python3 -m pytest tests/test_dividend_scanners.py::test_weekly_scan_populates_forward_dividend_and_max_yield -v
```
Expected: FAIL — `td.forward_dividend_rate` is None.

### Step 3: Implement in `src/dividend_scanners.py` — extend `scan_dividend_pool_weekly`

After `quality_score_result` is obtained (around line 155), add:

```python
            # Step 7b: Compute max_yield_5y from 5-year price history
            max_yield_5y = None
            forward_dividend_rate = fundamentals.get("forward_dividend_rate")
            try:
                hist = provider.get_price_data(ticker, period='5y')
                if (hist is not None and not hist.empty
                        and 'Close' in hist.columns and annual_dividend > 0):
                    min_price = float(hist['Close'].min())
                    if min_price > 0:
                        max_yield_5y = round((annual_dividend / min_price) * 100, 2)
            except Exception as e:
                logger.debug(f"{ticker}: Could not compute max_yield_5y: {e}")
```

In the `TickerData(...)` constructor (Step 7, around line 170), add new fields after `free_cash_flow`:

```python
                quality_breakdown=quality_score_result.quality_breakdown,
                analysis_text=quality_score_result.analysis_text or "",
                forward_dividend_rate=forward_dividend_rate,
                max_yield_5y=max_yield_5y,
                data_version_date=date.today(),
```

Add `from datetime import datetime, timedelta, date` if not present (check existing imports).

### Step 4: Run test to verify it passes

```bash
python3 -m pytest tests/test_dividend_scanners.py::test_weekly_scan_populates_forward_dividend_and_max_yield -v
```
Expected: PASS

### Step 5: Run full test suite

```bash
python3 -m pytest tests/ -q
```

### Step 6: Commit

```bash
git add src/dividend_scanners.py tests/test_dividend_scanners.py
git commit -m "feat: compute forward_dividend_rate and max_yield_5y in weekly dividend scan"
```

---

## Task 5: Enrich `scan_dividend_buy_signal` + extend agent payload in `main.py`

**Files:**
- Modify: `src/dividend_scanners.py` (`DividendBuySignal` + `scan_dividend_buy_signal`)
- Modify: `src/main.py` (`_build_agent_payload` + `run_scan` dividend section)
- Test: `tests/test_dividend_scanners.py`, `tests/test_integration.py`

### Step 1: Write failing tests

```python
# tests/test_dividend_scanners.py — add:

def test_buy_signal_computes_floor_price(mocker):
    """scan_dividend_buy_signal should compute floor_price and floor_downside_pct from pool records."""
    import pandas as pd
    from src.dividend_scanners import scan_dividend_buy_signal

    provider = mocker.MagicMock()
    prices = pd.DataFrame({"Close": [62.5, 62.8, 63.0]})
    provider.get_price_data.return_value = prices
    provider.get_dividend_history.return_value = [
        {"date": "2025-03-01", "amount": 0.485},
        {"date": "2025-06-01", "amount": 0.485},
        {"date": "2025-09-01", "amount": 0.485},
        {"date": "2025-12-01", "amount": 0.485},
    ]
    provider.should_skip_options.return_value = True

    store = mocker.MagicMock()
    store.get_yield_percentile.return_value = 92.0

    pool_records = [{
        "ticker": "KO", "quality_score": 85.0,
        "quality_breakdown": {"continuity": 18.0, "growth": 10.0,
                               "payout_safety": 20.0, "financial_health": 17.0,
                               "defensiveness": 16.0},
        "analysis_text": "Strong moat.",
        "forward_dividend_rate": 1.94,
        "max_yield_5y": 4.5,
        "data_version_date": "2026-03-02",
        "payout_ratio": 72.0, "payout_type": "GAAP",
        "consecutive_years": 10, "dividend_growth_5y": 4.8,
        "dividend_yield": 3.2, "roe": 15.0, "debt_to_equity": 0.5,
        "industry": "Beverages", "sector": "Consumer Staples",
    }]

    config = {"dividend_scanners": {"min_yield": 3.0, "min_yield_percentile": 80}}
    signals = scan_dividend_buy_signal(
        pool=pool_records, provider=provider, store=store, config=config
    )
    assert len(signals) == 1
    sig = signals[0]
    assert sig.floor_price is not None
    assert sig.floor_price == round(1.94 / (4.5 / 100), 2)  # ≈ 43.11
    assert sig.floor_downside_pct is not None
    assert sig.floor_downside_pct < 0  # downside is negative
    assert sig.ticker_data.quality_breakdown is not None
    assert sig.ticker_data.analysis_text == "Strong moat."
```

```python
# tests/test_integration.py — add:

def test_build_agent_payload_dividend_has_floor_price():
    """_build_agent_payload should include floor_price and floor_downside_pct in dividend signals."""
    from src.main import _build_agent_payload
    from src.dividend_scanners import DividendBuySignal
    from src.data_engine import TickerData

    td = TickerData(
        ticker="KO", name="Coca-Cola", market="US",
        last_price=62.5, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=62.5,
        earnings_date=None, days_to_earnings=None,
        dividend_quality_score=85.0,
        quality_breakdown={"continuity": 18.0, "growth": 10.0,
                           "payout_safety": 20.0, "financial_health": 17.0,
                           "defensiveness": 16.0},
        analysis_text="Strong moat.",
        forward_dividend_rate=1.94,
        max_yield_5y=4.5,
        payout_ratio=72.0,
    )
    sig = DividendBuySignal(
        ticker_data=td, signal_type="OPTION",
        current_yield=3.2, yield_percentile=92.0,
        floor_price=43.11, floor_downside_pct=-31.0,
        data_age_days=3, needs_reeval=False,
    )
    payload = _build_agent_payload(
        sell_puts=[], iv_low=[], iv_high=[], ma200_bull=[], ma200_bear=[],
        leaps=[], earnings_gaps=[], earnings_gap_ticker_map={},
        iv_momentum=[], dividend_signals=[sig],
    )
    div = next(p for p in payload if p["signal_type"] == "dividend")
    assert div["floor_price"] == 43.11
    assert div["floor_downside_pct"] == -31.0
    assert div["quality_breakdown"]["continuity"] == 18.0
    assert div["analysis_text"] == "Strong moat."
```

### Step 2: Run tests to verify they fail

```bash
python3 -m pytest tests/test_dividend_scanners.py::test_buy_signal_computes_floor_price tests/test_integration.py::test_build_agent_payload_dividend_has_floor_price -v
```

### Step 3: Update `DividendBuySignal` dataclass in `src/dividend_scanners.py`

Add new fields (after `option_details`, line 41):

```python
    floor_price: Optional[float] = None
    floor_downside_pct: Optional[float] = None
    data_age_days: Optional[int] = None
    needs_reeval: bool = False
```

### Step 4: Refactor `scan_dividend_buy_signal` to accept `pool: List[Dict]`

**Change signature** (line 212):
```python
def scan_dividend_buy_signal(
    pool: List[Dict[str, Any]],   # was List[str] — now full records from get_pool_records()
    provider: "MarketDataProvider",
    store: "DividendStore",
    config: dict,
) -> List[DividendBuySignal]:
```

**Change the loop** — replace `for ticker in pool:` with:
```python
    for record in pool:
        ticker = record["ticker"]
        try:
```

**After computing `current_yield` and `yield_percentile`**, enrich `TickerData` from the pool record and compute floor price. Replace the TickerData constructor (around line 298):

```python
                from datetime import date as _date
                # Compute data freshness
                version_date_str = record.get("data_version_date")
                data_age_days = None
                needs_reeval = False
                if version_date_str:
                    try:
                        version_date = _date.fromisoformat(version_date_str)
                        data_age_days = (_date.today() - version_date).days
                    except ValueError:
                        pass

                ticker_data = TickerData(
                    ticker=ticker,
                    name=record.get("name", ticker),
                    market=record.get("market", "US"),
                    last_price=last_price,
                    ma200=None, ma50w=None, rsi14=None, iv_rank=None,
                    iv_momentum=None, prev_close=0.0,
                    earnings_date=None, days_to_earnings=None,
                    dividend_yield=current_yield,
                    dividend_yield_5y_percentile=yield_percentile,
                    dividend_quality_score=record.get("quality_score"),
                    consecutive_years=record.get("consecutive_years"),
                    dividend_growth_5y=record.get("dividend_growth_5y"),
                    payout_ratio=record.get("payout_ratio"),
                    payout_type=record.get("payout_type"),
                    roe=record.get("roe"),
                    debt_to_equity=record.get("debt_to_equity"),
                    industry=record.get("industry"),
                    sector=record.get("sector"),
                    free_cash_flow=None,
                    quality_breakdown=record.get("quality_breakdown"),
                    analysis_text=record.get("analysis_text"),
                    forward_dividend_rate=record.get("forward_dividend_rate"),
                    max_yield_5y=record.get("max_yield_5y"),
                    data_version_date=None,
                    needs_reeval=needs_reeval,
                )

                # Compute floor price from forward_dividend_rate and max_yield_5y
                floor_price = None
                floor_downside_pct = None
                fwd = record.get("forward_dividend_rate")
                max_y = record.get("max_yield_5y")
                if fwd and max_y and max_y > 0:
                    floor_price = round(fwd / (max_y / 100), 2)
                    floor_downside_pct = round((last_price - floor_price) / last_price * 100, 1)
```

**Update `DividendBuySignal` construction** (around line 354):
```python
                signal = DividendBuySignal(
                    ticker_data=ticker_data,
                    signal_type=signal_type,
                    current_yield=current_yield,
                    yield_percentile=yield_percentile,
                    option_details=option_details,
                    floor_price=floor_price,
                    floor_downside_pct=floor_downside_pct,
                    data_age_days=data_age_days,
                    needs_reeval=needs_reeval,
                )
```

### Step 5: Update `src/main.py`

**5a. Change `get_current_pool()` → `get_pool_records()`** in `run_scan` (around line 288):
```python
            current_pool = dividend_store.get_pool_records()  # was get_current_pool()
```

**5b. Update `_build_agent_payload` dividend section** — replace the `for s in (dividend_signals or []):` block (lines 136-154) with:

```python
    for s in (dividend_signals or []):
        td = s.ticker_data
        opt = s.option_details
        signals.append({
            "signal_type": "dividend",
            "ticker": td.ticker,
            "last_price": round(float(td.last_price), 2),
            "current_yield": round(float(s.current_yield), 2),
            "yield_percentile": round(float(s.yield_percentile), 0),
            "quality_score": round(float(td.dividend_quality_score), 0) if td.dividend_quality_score is not None else None,
            "quality_breakdown": td.quality_breakdown or {},
            "analysis_text": td.analysis_text or "",
            "payout_ratio": round(float(td.payout_ratio), 1) if td.payout_ratio is not None else None,
            "earnings_date": str(td.earnings_date) if td.earnings_date else None,
            "days_to_earnings": td.days_to_earnings,
            "forward_dividend_rate": round(float(td.forward_dividend_rate), 2) if td.forward_dividend_rate else None,
            "max_yield_5y": round(float(td.max_yield_5y), 2) if td.max_yield_5y else None,
            "floor_price": s.floor_price,
            "floor_downside_pct": s.floor_downside_pct,
            "data_age_days": s.data_age_days,
            "needs_reeval": bool(s.needs_reeval),
            "option_strike": round(float(opt["strike"]), 0) if opt else None,
            "option_dte": opt["dte"] if opt else None,
            "option_bid": round(float(opt["bid"]), 2) if opt else None,
            "option_apy": round(float(opt["apy"]), 1) if opt else None,
            "combined_apy": round(float(s.current_yield) + float(opt["apy"]), 1) if opt else None,
        })
```

### Step 6: Run tests to verify they pass

```bash
python3 -m pytest tests/test_dividend_scanners.py::test_buy_signal_computes_floor_price tests/test_integration.py::test_build_agent_payload_dividend_has_floor_price -v
```
Expected: PASS

### Step 7: Run full test suite

```bash
python3 -m pytest tests/ -q
```

### Step 8: Commit

```bash
git add src/dividend_scanners.py src/main.py tests/test_dividend_scanners.py tests/test_integration.py
git commit -m "feat: enrich dividend signal with floor price, stability breakdown, freshness"
```

---

## Task 6: Update Dashboard UI and HTML Report

**Files:**
- Modify: `agent/static/dashboard.html`
- Modify: `src/html_report.py`
- No new tests needed (UI-only changes, covered by existing integration tests)

### Step 1: Update `agent/static/dashboard.html`

**1a. Add CSS for stability detail panel** — inside the `<style>` block after `.dividend-card .dc-warn` rule (around line 102):

```css
.stability-detail { background: rgba(0,0,0,0.3); border-radius:6px; padding:10px 12px; margin-top:8px; display:none; }
.stability-detail .bd-row { display:flex; align-items:center; margin:4px 0; font-size:12px; }
.stability-detail .bd-label { min-width:74px; color:#a8d8ea; }
.stability-detail .bd-bar { flex:1; height:5px; background:rgba(255,255,255,0.15); border-radius:3px; margin:0 8px; }
.stability-detail .bd-fill { height:100%; background:#7ec8e3; border-radius:3px; }
.stability-detail .bd-val { min-width:28px; text-align:right; color:#c0c0e0; }
.stability-detail .bd-text { margin-top:8px; line-height:1.5; color:#c0c0e0; font-size:12px; }
.info-icon { cursor:pointer; font-size:12px; opacity:0.7; margin-left:4px; user-select:none; }
.info-icon:hover { opacity:1; }
```

**1b. Replace the `cardDividend` function** (lines 379-433) with this updated version:

```javascript
function cardDividend(s) {
  const p = s.payload;
  const prWarn = p.payout_ratio != null && p.payout_ratio > 80
    ? ' <span style="color:#ff9f43">⚠️ 接近警戒线</span>' : (p.payout_ratio != null ? ' ✓' : '');
  const stab = stabilityLabel(p.quality_score);
  const detailId = `stab-${s.ticker}-${s.scanned_at}`.replace(/[^a-z0-9]/gi,'_');

  // Stability breakdown panel
  const bdLabels = {continuity:'股息连续性',growth:'股息增长',payout_safety:'派息可持续',financial_health:'财务健康',defensiveness:'业务护城河'};
  const bdHtml = p.quality_breakdown ? Object.entries(bdLabels).map(([k, label]) => {
    const v = p.quality_breakdown[k] ?? 0;
    return `<div class="bd-row">
      <span class="bd-label">${label}</span>
      <div class="bd-bar"><div class="bd-fill" style="width:${Math.min(v/20*100,100)}%"></div></div>
      <span class="bd-val">${v}/20</span>
    </div>`;
  }).join('') : '';
  const analysisHtml = p.analysis_text ? `<div class="bd-text">${p.analysis_text}</div>` : '';
  const breakdownPanel = (bdHtml || analysisHtml) ? `
    <div id="${detailId}" class="stability-detail">${bdHtml}${analysisHtml}</div>` : '';

  // Floor price section (Dim 5 / worst case)
  const earningsStr = p.earnings_date ? `${p.earnings_date} (${p.days_to_earnings}天)` : 'N/A';
  const floorHtml = p.floor_price != null ? `
    <div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.1);font-size:12px">
      <div>历史极值底价分析</div>
      <div style="margin-top:4px;color:#a8d8ea">
        历史最高股息率 (5年): ${p.max_yield_5y != null ? p.max_yield_5y + '%' : 'N/A'}<br>
        Forward 股息: ${p.forward_dividend_rate != null ? '$' + p.forward_dividend_rate + '/股 (已宣告)' : 'N/A'}<br>
        极值底价: <strong>$${p.floor_price}</strong>
        较当前 <span style="color:${p.floor_downside_pct < -20 ? '#ff9f43' : '#e0e0e0'}">${p.floor_downside_pct}%</span>
      </div>
    </div>` : '';

  // Cost basis warning (if sell put cost > floor)
  const costBasis = p.option_strike != null && p.option_bid != null
    ? p.option_strike - p.option_bid : null;
  const costWarn = (costBasis != null && p.floor_price != null && costBasis > p.floor_price)
    ? `<div style="color:#ff9f43;margin-top:4px;font-size:12px">⚠️ 行权成本 $${costBasis.toFixed(2)} 高于极值底价，极端熊市仍有浮亏风险</div>` : '';

  const optSection = p.option_strike != null ? `
      <div class="dc-dim">
        <h4>4️⃣ 建议操作</h4>
        <p>📈 现货买入: $${p.last_price} (股息率${p.current_yield}%)</p>
        <p>📊 Sell Put $${p.option_strike} Strike (${p.option_dte}DTE)</p>
        <p>Premium: $${p.option_bid} → 年化${p.option_apy}%</p>
        <p class="dc-combined">综合年化: ${p.combined_apy}%</p>
      </div>
      <div class="dc-dim">
        <h4>5️⃣ 最坏情景</h4>
        <p>行权成本: $${costBasis != null ? costBasis.toFixed(2) : 'N/A'}</p>
        ${floorHtml}${costWarn}
      </div>` : `
      <div class="dc-dim">
        <h4>4️⃣ 建议操作</h4>
        <p>📈 现货买入: $${p.last_price} (股息率${p.current_yield}%)</p>
      </div>
      <div class="dc-dim">
        <h4>5️⃣ 最坏情景</h4>
        <p>股息率已达历史高位，现货持有</p>
        ${floorHtml}
      </div>`;

  // Freshness badge
  const freshness = p.needs_reeval
    ? '<span style="color:#ff9f43;font-size:11px"> ⚠️ 财报后数据，建议重新评估</span>'
    : (p.data_age_days != null && p.data_age_days > 14
      ? `<span style="color:#888;font-size:11px"> 🕐 数据较旧 (${p.data_age_days}天前)</span>` : '');

  return `<div class="card dividend-card">
    <div class="dc-header">
      <div class="dc-ticker">${s.ticker} 🛡️</div>
      <div class="dc-yield">当前股息率: <strong>${p.current_yield}%</strong> (5年历史${p.yield_percentile}分位)</div>
    </div>
    <div class="dc-dim">
      <h4>1️⃣ 基本面估值</h4>
      <p>${yieldLogic(p.yield_percentile)}</p>
      ${stab ? `<p>${stab} <span class="info-icon" onclick="document.getElementById('${detailId}').style.display=document.getElementById('${detailId}').style.display==='none'?'block':'none'">ℹ️</span></p>${breakdownPanel}` : ''}
    </div>
    <div class="dc-dim">
      <h4>2️⃣ 风险分级</h4>
      <p>派息率: ${p.payout_ratio != null ? p.payout_ratio + '%' + prWarn : 'N/A'}</p>
    </div>
    <div class="dc-dim">
      <h4>3️⃣ 关键事件</h4>
      <p>下次财报: ${earningsStr}${freshness}</p>
    </div>
    ${optSection}
    <div class="dc-dim">
      <h4>6️⃣ AI监控承诺</h4>
      <ul style="padding-left:16px;margin:4px 0;font-size:12px">
        <li>✓ 派息率>100%时立即预警</li>
        <li>✓ 财报前7天提醒</li>
        <li>✓ 股息率回落至中位数时提示</li>
      </ul>
    </div>
    <div class="card-time">${fmtTime(s.scanned_at)}</div>
  </div>`;
}
```

### Step 2: Update `src/html_report.py` — `_dividend_card` function

**2a. Add floor price computation** before `parts = [...]` (around line 345):

```python
    # Floor price analysis
    fwd_div = getattr(td, 'forward_dividend_rate', None)
    max_y = getattr(td, 'max_yield_5y', None)
    floor_price = None
    floor_downside_pct = None
    if fwd_div and max_y and max_y > 0:
        floor_price = round(fwd_div / (max_y / 100), 2)
        floor_downside_pct = round((td.last_price - floor_price) / td.last_price * 100, 1)
```

**2b. Update Dim 1** to include `<details>` tooltip for stability (the section at lines 352-356 was already updated in a prior task; now we add the tooltip):

After the existing yield_logic + stability_str lines, update the `dim1_parts` to add the details element:

```python
    dim1_parts = [
        '  <div class="dc-dim">',
        "    <h4>1️⃣ 基本面估值</h4>",
        f"    <p>{yield_logic}</p>",
    ]
    if stability_str:
        qb = getattr(td, 'quality_breakdown', None)
        at = getattr(td, 'analysis_text', None) or ""
        if qb:
            bd_labels = [
                ("continuity", "股息连续性"), ("growth", "股息增长"),
                ("payout_safety", "派息可持续"), ("financial_health", "财务健康"),
                ("defensiveness", "业务护城河"),
            ]
            bd_rows = "\n".join(
                f'          <div>{label}: {qb.get(key, 0):.0f}/20</div>'
                for key, label in bd_labels
            )
            analysis_html = f"          <div style='margin-top:6px;font-size:11px'>{_escape(at)}</div>" if at else ""
            details_html = (
                f'    <details style="display:inline">'
                f'<summary style="cursor:pointer;list-style:none;display:inline">ℹ️</summary>'
                f'<div style="background:rgba(0,0,0,0.2);border-radius:6px;padding:8px;margin-top:4px;font-size:12px">'
                f'\n{bd_rows}\n{analysis_html}'
                f'</div></details>'
            )
            dim1_parts.append(f"    <p>{stability_str} {details_html}</p>")
        else:
            dim1_parts.append(f"    <p>{stability_str}</p>")
    dim1_parts.append("  </div>")
```

**2c. Update Dim 5 worst case** (around lines 385-393) to add floor price:

```python
    parts += [
        "  </div>",
        # Dim 5: worst case
        '  <div class="dc-dim">',
        "    <h4>5️⃣ 最坏情景</h4>",
    ]
    if opt:
        cost = opt["strike"] - opt["bid"]
        parts.append(f"    <p>行权成本: ${cost:.2f}</p>")

    if floor_price is not None:
        parts += [
            f"    <p style='margin-top:6px;font-size:12px;color:#a8d8ea'>"
            f"历史最高股息率 (5年): {max_y:.1f}%</p>",
            f"    <p style='font-size:12px;color:#a8d8ea'>"
            f"极值底价: <strong>${floor_price:.2f}</strong> 较当前 {floor_downside_pct:.1f}%</p>",
        ]
        if opt and (opt["strike"] - opt["bid"]) > floor_price:
            parts.append(
                "    <p style='color:#ff9f43;font-size:12px'>"
                "⚠️ 行权成本高于极值底价，极端熊市仍有浮亏风险</p>"
            )
    elif not opt:
        parts.append("    <p>股息率已达历史高位，现货持有</p>")
```

### Step 3: Verify dashboard renders correctly

Re-seed test data with enriched fields including `quality_breakdown`, `analysis_text`, `forward_dividend_rate`, `max_yield_5y`, `floor_price`, `floor_downside_pct`:

```bash
curl -s -X POST https://ai-monitor.fly.dev/api/scan_results \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${SCAN_API_KEY}" \
  -d '{
    "scan_date": "2026-03-09",
    "results": [{
      "signal_type": "dividend",
      "ticker": "KO",
      "last_price": 62.5,
      "current_yield": 3.2,
      "yield_percentile": 92.0,
      "quality_score": 85,
      "quality_breakdown": {"continuity": 18.0, "growth": 10.0, "payout_safety": 20.0, "financial_health": 17.0, "defensiveness": 16.0},
      "analysis_text": "可口可乐拥有全球最宽护城河之一，过去62年连续增长股息，自由现金流覆盖率稳定在1.4x以上，即使在经济衰退期也保持派息记录。",
      "payout_ratio": 72.0,
      "earnings_date": "2026-04-28",
      "days_to_earnings": 50,
      "forward_dividend_rate": 1.94,
      "max_yield_5y": 4.5,
      "floor_price": 43.11,
      "floor_downside_pct": -31.0,
      "data_age_days": 4,
      "needs_reeval": false,
      "option_strike": 60,
      "option_dte": 52,
      "option_bid": 1.2,
      "option_apy": 7.5,
      "combined_apy": 10.7
    }]
  }'
```

### Step 4: Run full test suite

```bash
python3 -m pytest tests/ -q
```
Expected: all passing.

### Step 5: Commit

```bash
git add agent/static/dashboard.html src/html_report.py
git commit -m "feat: dividend card tooltip for stability breakdown and floor price in Dim 5"
```

---

## Final Verification

```bash
python3 -m pytest tests/ -q
git log --oneline -6
```

Expected output:
```
feat: dividend card tooltip for stability breakdown and floor price in Dim 5
feat: enrich dividend signal with floor price, stability breakdown, freshness
feat: compute forward_dividend_rate and max_yield_5y in weekly dividend scan
feat: add forward_dividend_rate to market_data and enrichment fields to TickerData
feat: extend DividendStore with enrichment columns and analysis cache
feat: extend DividendQualityScore with 5-dim breakdown and analysis_text
```
