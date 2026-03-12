# Financial Health LLM Assessment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace distorted GAAP health scoring for negative-equity/high-payout companies with LLM assessment, while keeping rule-based scoring for normal companies.

**Architecture:** Anomaly detection (D/E > 200 or GAAP payout > 100% outside FCF sectors) gates LLM calls. LLM returns `{health_score, fcf_payout_est, rationale}`. Anomalous companies get their `payout_ratio` overridden with `fcf_payout_est`, `payout_type` set to `"LLM"`, and `health_rationale` stored for tooltip display. Normal companies unchanged.

**Tech Stack:** Python, SQLite, existing `FinancialServiceAnalyzer` / `DividendStore`, FastAPI agent, vanilla JS dashboard.

**Key files to understand before starting:**
- `src/financial_service.py` — `FinancialServiceAnalyzer._calculate_rule_based_score()`, `FCF_PAYOUT_SECTORS`
- `src/dividend_store.py` — `save_pool()`, `get_pool_records()`, `analysis_cache` table, `_create_tables()` migration pattern
- `src/data_engine.py:14-57` — `TickerData` dataclass
- `src/dividend_scanners.py:430-460` — how signal payload is assembled from pool record
- `agent/static/dashboard.html:1130-1148` — `payoutRiskRow` JS block

---

### Task 1: Anomaly Detection + DividendQualityScore Field

**Files:**
- Modify: `src/financial_service.py`
- Test: `tests/test_financial_service.py`

**Context:** `FCF_PAYOUT_SECTORS = {"Energy", "Utilities", "Real Estate"}` is defined at module level. `DividendQualityScore` is a dataclass with `overall_score`, `health_score`, `payout_type`, `effective_payout_ratio`, `risk_flags`, `analysis_text`. We need to add `health_rationale` and a static anomaly detector.

**Step 1: Write the failing tests**

Add to `tests/test_financial_service.py`:

```python
def test_anomaly_detection_negative_equity():
    """D/E > 200 triggers anomaly detection (negative book equity signal)."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    assert analyzer._is_anomalous({"debt_to_equity": 250, "payout_ratio": 60, "sector": "Consumer Defensive"}) is True

def test_anomaly_detection_gaap_payout_over_100():
    """GAAP payout > 100% outside FCF sectors triggers anomaly."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    assert analyzer._is_anomalous({"debt_to_equity": 50, "payout_ratio": 103, "sector": "Consumer Defensive"}) is True

def test_anomaly_detection_normal_company():
    """Normal company (D/E 50, payout 65%) does NOT trigger."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    assert analyzer._is_anomalous({"debt_to_equity": 50, "payout_ratio": 65, "sector": "Consumer Defensive"}) is False

def test_anomaly_detection_fcf_sector_payout_over_100_not_anomalous():
    """Energy sector with payout > 100% is handled by FCF logic, not anomaly."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    assert analyzer._is_anomalous({"debt_to_equity": 50, "payout_ratio": 110, "sector": "Energy"}) is False

def test_dividend_quality_score_has_health_rationale():
    """DividendQualityScore supports health_rationale field."""
    score = DividendQualityScore(
        overall_score=77.0, stability_score=80.0, health_score=70.0,
        defensiveness_score=75.0, risk_flags=[],
        health_rationale="KMB负净资产结构，FCF派息率约55%，实际安全"
    )
    assert score.health_rationale == "KMB负净资产结构，FCF派息率约55%，实际安全"
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_financial_service.py::test_anomaly_detection_negative_equity \
       tests/test_financial_service.py::test_anomaly_detection_gaap_payout_over_100 \
       tests/test_financial_service.py::test_anomaly_detection_normal_company \
       tests/test_financial_service.py::test_anomaly_detection_fcf_sector_payout_over_100_not_anomalous \
       tests/test_financial_service.py::test_dividend_quality_score_has_health_rationale -v
```
Expected: FAIL — `_is_anomalous` does not exist, `health_rationale` field missing.

**Step 3: Implement**

In `src/financial_service.py`:

1. Add `health_rationale` to `DividendQualityScore` dataclass (after `analysis_text`):
```python
health_rationale: Optional[str] = None
```

2. Add `_is_anomalous()` method to `FinancialServiceAnalyzer` (after `_has_llm_key`):
```python
@staticmethod
def _is_anomalous(fundamentals: Dict[str, Any]) -> bool:
    """Return True if GAAP metrics are likely distorted (negative equity or payout > 100% outside FCF sectors)."""
    de = fundamentals.get("debt_to_equity") or 0.0
    payout = fundamentals.get("payout_ratio") or 0.0
    sector = fundamentals.get("sector") or ""
    if de > 200:
        return True
    if payout > 100 and sector not in FCF_PAYOUT_SECTORS:
        return True
    return False
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_financial_service.py::test_anomaly_detection_negative_equity \
       tests/test_financial_service.py::test_anomaly_detection_gaap_payout_over_100 \
       tests/test_financial_service.py::test_anomaly_detection_normal_company \
       tests/test_financial_service.py::test_anomaly_detection_fcf_sector_payout_over_100_not_anomalous \
       tests/test_financial_service.py::test_dividend_quality_score_has_health_rationale -v
```
Expected: PASS

**Step 5: Run full test suite**

```bash
pytest tests/test_financial_service.py -v
```
Expected: All pass.

**Step 6: Commit**

```bash
git add src/financial_service.py tests/test_financial_service.py
git commit -m "feat: add anomaly detection and health_rationale field to DividendQualityScore"
```

---

### Task 2: Health Assessment Cache in DividendStore

**Files:**
- Modify: `src/dividend_store.py`
- Test: `tests/test_dividend_store.py`

**Context:** `analysis_cache` table has `(ticker TEXT PRIMARY KEY, text TEXT, expires TEXT)`. We'll reuse it with key `"{ticker}:health"` to store a JSON blob `{"health_score": float, "fcf_payout_est": float, "rationale": str}`. This avoids a new table while keeping the 7-day TTL pattern.

**Step 1: Write the failing tests**

Add to `tests/test_dividend_store.py`:

```python
def test_save_and_get_health_assessment(tmp_path):
    """Health assessment round-trips through analysis_cache with :health key."""
    from src.dividend_store import DividendStore
    store = DividendStore(str(tmp_path / "test.db"))
    store.save_health_assessment("KMB", health_score=72.0, fcf_payout_est=55.0,
                                  rationale="KMB负净资产结构，FCF派息率约55%，实际安全")
    result = store.get_health_assessment("KMB")
    assert result is not None
    assert result["health_score"] == 72.0
    assert result["fcf_payout_est"] == 55.0
    assert "负净资产" in result["rationale"]

def test_health_assessment_cache_miss_returns_none(tmp_path):
    """Returns None when no cached health assessment exists."""
    from src.dividend_store import DividendStore
    store = DividendStore(str(tmp_path / "test.db"))
    assert store.get_health_assessment("UNKNOWN") is None
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_dividend_store.py::test_save_and_get_health_assessment \
       tests/test_dividend_store.py::test_health_assessment_cache_miss_returns_none -v
```
Expected: FAIL — methods don't exist.

**Step 3: Implement**

Add these two methods to `DividendStore` in `src/dividend_store.py` (after `save_analysis_text`):

```python
def get_health_assessment(self, ticker: str) -> Optional[Dict]:
    """Return cached LLM health assessment dict or None if missing/expired."""
    cursor = self.conn.cursor()
    cursor.execute(
        "SELECT text, expires FROM analysis_cache WHERE ticker=?", (f"{ticker}:health",)
    )
    row = cursor.fetchone()
    if not row:
        return None
    text, expires = row
    if expires < date.today().isoformat():
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

def save_health_assessment(self, ticker: str, health_score: float,
                            fcf_payout_est: float, rationale: str,
                            ttl_days: int = 7):
    """Persist LLM health assessment with TTL (default 7 days)."""
    expires = (date.today() + timedelta(days=ttl_days)).isoformat()
    payload = json.dumps({"health_score": health_score,
                          "fcf_payout_est": fcf_payout_est,
                          "rationale": rationale})
    cursor = self.conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO analysis_cache (ticker, text, expires) VALUES (?,?,?)",
        (f"{ticker}:health", payload, expires),
    )
    self.conn.commit()
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_dividend_store.py::test_save_and_get_health_assessment \
       tests/test_dividend_store.py::test_health_assessment_cache_miss_returns_none -v
```
Expected: PASS

**Step 5: Run full test suite**

```bash
pytest tests/test_dividend_store.py -v
```
Expected: All pass.

**Step 6: Commit**

```bash
git add src/dividend_store.py tests/test_dividend_store.py
git commit -m "feat: add health assessment cache methods to DividendStore"
```

---

### Task 3: LLM Health Assessment + Score Override

**Files:**
- Modify: `src/financial_service.py`
- Test: `tests/test_financial_service.py`

**Context:** `_get_defensiveness_score()` shows the LLM call pattern: `client.simple_chat(system, prompt, max_tokens=100)`, then parse JSON, then cache. We follow the same pattern. The override happens inside `_calculate_rule_based_score()`: after computing `health_score` by rules, if anomalous AND LLM key available, call `_get_health_assessment()`, replace `health_score`, replace `effective_payout_ratio` with `fcf_payout_est`, set `payout_type = "LLM"`, set `health_rationale`.

**Step 1: Write the failing tests**

Add to `tests/test_financial_service.py`:

```python
from unittest.mock import patch, MagicMock

def test_llm_health_assessment_overrides_rule_score():
    """For anomalous company, LLM health_score replaces rule-based value."""
    mock_store = MagicMock()
    mock_store.get_health_assessment.return_value = None  # no cache
    analyzer = FinancialServiceAnalyzer(enabled=True, api_key="fake-key", store=mock_store)
    fundamentals = {
        "consecutive_years": 11, "dividend_growth_5y": 7.0,
        "roe": 126.0, "debt_to_equity": 464.0,
        "payout_ratio": 103.7, "sector": "Consumer Defensive",
        "industry": "Household Products",
        "free_cash_flow": 2_000_000_000, "shares_outstanding": 340_000_000,
        "annual_dividend": 5.00,
    }
    mock_response = '{"health_score": 72.0, "fcf_payout_est": 55.0, "rationale": "KMB负净资产结构，FCF派息率约55%，实际安全"}'
    with patch.object(analyzer, '_get_client') as mock_get_client:
        mock_client = MagicMock()
        mock_client.simple_chat.return_value = mock_response
        mock_get_client.return_value = mock_client
        result = analyzer._calculate_rule_based_score("KMB", fundamentals)
    assert result.health_score == 72.0
    assert result.payout_type == "LLM"
    assert abs(result.effective_payout_ratio - 55.0) < 0.1
    assert "负净资产" in (result.health_rationale or "")

def test_llm_health_failure_falls_back_to_rules():
    """LLM failure leaves rule-based health_score intact."""
    mock_store = MagicMock()
    mock_store.get_health_assessment.return_value = None
    analyzer = FinancialServiceAnalyzer(enabled=True, api_key="fake-key", store=mock_store)
    fundamentals = {
        "consecutive_years": 11, "dividend_growth_5y": 7.0,
        "roe": 126.0, "debt_to_equity": 464.0,
        "payout_ratio": 103.7, "sector": "Consumer Defensive",
        "industry": "Household Products",
    }
    with patch.object(analyzer, '_get_client') as mock_get_client:
        mock_client = MagicMock()
        mock_client.simple_chat.side_effect = Exception("LLM error")
        mock_get_client.return_value = mock_client
        result = analyzer._calculate_rule_based_score("KMB", fundamentals)
    # Falls back: health_rationale is None, payout_type is GAAP, health_score is rule-based
    assert result.health_rationale is None
    assert result.payout_type == "GAAP"
    assert result.health_score >= 0  # rule-based value

def test_normal_company_skips_llm():
    """Normal company (D/E 50, payout 65%) does not call LLM."""
    mock_store = MagicMock()
    analyzer = FinancialServiceAnalyzer(enabled=True, api_key="fake-key", store=mock_store)
    fundamentals = {
        "consecutive_years": 8, "dividend_growth_5y": 5.0,
        "roe": 15.0, "debt_to_equity": 50.0, "payout_ratio": 65.0,
        "sector": "Consumer Defensive",
    }
    with patch.object(analyzer, '_get_client') as mock_get_client:
        analyzer._calculate_rule_based_score("KO", fundamentals)
        mock_get_client.assert_not_called()
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_financial_service.py::test_llm_health_assessment_overrides_rule_score \
       tests/test_financial_service.py::test_llm_health_failure_falls_back_to_rules \
       tests/test_financial_service.py::test_normal_company_skips_llm -v
```
Expected: FAIL — `_get_health_assessment` doesn't exist, no override logic.

**Step 3: Implement**

In `src/financial_service.py`, add `_get_health_assessment()` method (after `_get_defensiveness_score`):

```python
def _get_health_assessment(self, ticker: str, fundamentals: Dict[str, Any]) -> Optional[Dict]:
    """LLM health assessment for anomalous companies. Returns {health_score, fcf_payout_est, rationale} or None."""
    if self.store:
        cached = self.store.get_health_assessment(ticker)
        if cached is not None:
            logger.debug(f"Health assessment cache hit: {ticker}")
            return cached
    try:
        client = self._get_client()
        sector = fundamentals.get("sector") or ""
        industry = fundamentals.get("industry") or ""
        payout = fundamentals.get("payout_ratio") or 0.0
        de = fundamentals.get("debt_to_equity") or 0.0
        roe = fundamentals.get("roe") or 0.0
        consec = fundamentals.get("consecutive_years") or 0
        growth = fundamentals.get("dividend_growth_5y") or 0.0
        fcf = fundamentals.get("free_cash_flow")
        shares = fundamentals.get("shares_outstanding")
        annual_div = fundamentals.get("annual_dividend")

        fcf_info = ""
        if fcf and fcf > 0 and shares and annual_div:
            fcf_payout_real = (annual_div * shares / fcf) * 100
            fcf_info = f"自由现金流派息率（实际）: {fcf_payout_real:.1f}%\n"

        prompt = (
            f"股票: {ticker} | 行业: {sector}/{industry}\n"
            f"GAAP派息率: {payout:.1f}% | 资产负债率(D/E): {de:.0f}x | ROE: {roe:.1f}%\n"
            f"连续派息: {consec}年 | 股息5年CAGR: {growth:.1f}%\n"
            f"{fcf_info}"
            "注意：D/E极高或ROE异常通常表示负账面净资产（大量股票回购或并购摊销），GAAP派息率可能失真。\n"
            "请评估该公司真实的股息安全性，估算FCF派息率（若无数据则根据行业特征估算），给出综合财务健康分。\n"
            '返回严格JSON: {"health_score": float(0-100), "fcf_payout_est": float(%), "rationale": "1句中文说明"}'
        )
        raw = client.simple_chat(
            "你是专业股息分析师。只返回严格JSON，不加任何解释或markdown。",
            prompt,
            max_tokens=150,
        )
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        result = {
            "health_score": float(data["health_score"]),
            "fcf_payout_est": float(data["fcf_payout_est"]),
            "rationale": str(data.get("rationale", "")),
        }
        if self.store:
            self.store.save_health_assessment(
                ticker,
                health_score=result["health_score"],
                fcf_payout_est=result["fcf_payout_est"],
                rationale=result["rationale"],
            )
        logger.info(f"Health assessment: {ticker} → score={result['health_score']:.0f}, fcf_payout={result['fcf_payout_est']:.1f}% ({result['rationale']})")
        return result
    except Exception as e:
        logger.warning(f"Health assessment failed for {ticker} [{type(e).__name__}]: {e}, using rule-based")
        return None
```

Then in `_calculate_rule_based_score()`, after computing `health_score` and before computing `overall_score` (after the `# 3. 行业防御性评分` section), add:

```python
# 3b. LLM health override for anomalous companies (negative equity / GAAP distortion)
health_rationale = None
if self._is_anomalous(fundamentals) and self._has_llm_key():
    assessment = self._get_health_assessment(ticker, fundamentals)
    if assessment:
        health_score = float(assessment["health_score"])
        effective_payout_ratio = float(assessment["fcf_payout_est"])
        payout_type = "LLM"
        payout_score = 40.0 if effective_payout_ratio < 70 else 20.0
        health_rationale = assessment["rationale"]
        # Recompute health_score cap (LLM value is already 0-100)
        health_score = max(0.0, min(100.0, health_score))
```

Also update the `return DividendQualityScore(...)` call at the bottom of `_calculate_rule_based_score` to include:
```python
health_rationale=health_rationale,
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_financial_service.py::test_llm_health_assessment_overrides_rule_score \
       tests/test_financial_service.py::test_llm_health_failure_falls_back_to_rules \
       tests/test_financial_service.py::test_normal_company_skips_llm -v
```
Expected: PASS

**Step 5: Run full test suite**

```bash
pytest tests/test_financial_service.py -v
```
Expected: All pass.

**Step 6: Commit**

```bash
git add src/financial_service.py tests/test_financial_service.py
git commit -m "feat: LLM health assessment overrides rule score for anomalous companies"
```

---

### Task 4: DB Column + Store Propagation

**Files:**
- Modify: `src/dividend_store.py`
- Modify: `src/data_engine.py`
- Modify: `src/dividend_scanners.py`
- Test: `tests/test_dividend_store.py`

**Context:** Need to:
1. Add `health_rationale TEXT` column to `dividend_pool` via migration pattern in `_create_tables()`
2. Save it in `save_pool()` / read it in `get_pool_records()`
3. Add `health_rationale: Optional[str]` to `TickerData`
4. Pass it through in `scan_dividend_buy_signal`

**Step 1: Write the failing tests**

Add to `tests/test_dividend_store.py`:

```python
def test_save_and_get_pool_includes_health_rationale(tmp_path):
    """health_rationale is persisted and returned in get_pool_records."""
    from src.dividend_store import DividendStore
    from src.data_engine import TickerData
    from datetime import date
    store = DividendStore(str(tmp_path / "test.db"))
    td = TickerData(
        ticker="KMB", name="Kimberly-Clark", market="US",
        last_price=130.0, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=130.0,
        earnings_date=None, days_to_earnings=None,
        dividend_quality_score=77.0, consecutive_years=11,
        dividend_growth_5y=7.0, payout_ratio=55.0, payout_type="LLM",
        health_rationale="KMB负净资产结构，FCF派息率约55%，实际安全",
    )
    store.save_pool([td], version="2026-03-12")
    records = store.get_pool_records()
    assert len(records) == 1
    assert records[0]["health_rationale"] == "KMB负净资产结构，FCF派息率约55%，实际安全"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_dividend_store.py::test_save_and_get_pool_includes_health_rationale -v
```
Expected: FAIL — `health_rationale` attribute missing from `TickerData`.

**Step 3: Implement**

**3a. `src/data_engine.py`** — Add after `recommended_reason`:
```python
health_rationale: Optional[str] = None   # LLM health assessment explanation
```

**3b. `src/dividend_store.py`** — In `_create_tables()`, add to the migration loop:
```python
("health_rationale", "TEXT"),
```
(add to the existing `for col, col_type in [...]` list)

**3b. `src/dividend_store.py`** — In `save_pool()`, add `health_rationale` to INSERT:

Change the INSERT columns to include `health_rationale` and add `getattr(ticker, 'health_rationale', None)` to the values tuple. The full INSERT should be:
```python
cursor.execute("""
    INSERT INTO dividend_pool (
        ticker, version, name, market, quality_score,
        consecutive_years, dividend_growth_5y, payout_ratio,
        payout_type, dividend_yield, roe, debt_to_equity,
        industry, sector, added_date,
        quality_breakdown, analysis_text, forward_dividend_rate,
        max_yield_5y, data_version_date, sgov_yield, health_rationale
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    getattr(ticker, 'health_rationale', None),
))
```

**3c. `src/dividend_store.py`** — In `get_pool_records()`, add `health_rationale` to SELECT and cols list:
```python
# SELECT: add health_rationale after sgov_yield
SELECT ..., sgov_yield, health_rationale FROM dividend_pool ...

# cols list: add at end
cols = [..., "sgov_yield", "health_rationale"]
```

**3d. `src/dividend_scanners.py`** — In `scan_dividend_buy_signal`, where `TickerData` is constructed from pool record (around line 449), add:
```python
health_rationale=record.get("health_rationale"),
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_dividend_store.py::test_save_and_get_pool_includes_health_rationale -v
```
Expected: PASS

**Step 5: Run full test suite**

```bash
pytest tests/test_dividend_store.py tests/test_financial_service.py -v
```
Expected: All pass.

**Step 6: Commit**

```bash
git add src/data_engine.py src/dividend_store.py src/dividend_scanners.py tests/test_dividend_store.py
git commit -m "feat: propagate health_rationale through DB, TickerData, and signal payload"
```

---

### Task 5: Dashboard UI — `?` Button + Rationale Tooltip

**Files:**
- Modify: `agent/static/dashboard.html:1130-1148`

**Context:** The `payoutRiskRow` JS block currently:
- Computes `riskLbl` from raw GAAP `payout_ratio` thresholds
- Shows `ℹ` button with fixed tooltip text

New behavior:
- If signal has `health_rationale` (LLM-assessed): show `?` button, tooltip = rationale text; risk label uses `payout_ratio` (now overridden to `fcf_payout_est`)
- If no `health_rationale`: show `?` button, tooltip = existing fixed text
- Button symbol changes `ℹ` → `?` for all cases (consistent style)

The signal payload for dividend signals is in `p` (the pool record). `p.health_rationale` will be present when LLM assessed.

**Step 1: Write the failing test**

In `tests/test_financial_service.py`, add a UI contract test (checks rendered HTML):

```python
def test_payout_risk_row_uses_question_mark_button():
    """Dashboard payoutRiskRow uses ? button (not ℹ) for tooltip trigger."""
    import subprocess, re
    html_path = "agent/static/dashboard.html"
    with open(html_path) as f:
        content = f.read()
    # Find the payoutRiskRow JS block
    block_match = re.search(r'const payoutRiskRow[\s\S]{0,2000}?return `[\s\S]{0,500}?`;\s*\}\)\(\);', content)
    assert block_match, "payoutRiskRow block not found"
    block = block_match.group(0)
    assert "?" in block, "payoutRiskRow should use ? button"
    assert "ℹ" not in block, "payoutRiskRow should not use ℹ (replaced by ?)"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_financial_service.py::test_payout_risk_row_uses_question_mark_button -v
```
Expected: FAIL — current code uses `ℹ`.

**Step 3: Implement**

Replace the `payoutRiskRow` block in `agent/static/dashboard.html` (lines ~1130–1148):

```javascript
  // Payout risk row
  const payoutRiskRow = (() => {
    if (p.payout_ratio == null) return '';
    const pr       = p.payout_ratio;
    const pt       = p.payout_type || 'GAAP';
    const riskLbl  = pr > 100 ? '极高' : pr > 80 ? '偏高' : pr > 60 ? '中等' : '低';
    const riskSty  = pr > 100 ? 'color:var(--red)' : pr > 80 ? 'color:var(--amber)' : pr > 60 ? 'color:var(--amber)' : 'color:var(--green)';
    const rationale = p.health_rationale;
    const tooltip   = rationale
      ? rationale
      : pt === 'FCF' ? '能源/公用/REIT 使用自由现金流派息率'
      : pt === 'LLM' ? 'LLM综合评估：GAAP指标受负净资产或摊销影响，已校正'
      : '轻资产行业使用 GAAP 净利润派息率';
    return `<div class="card-row">
      <span class="row-label">派息切割风险</span>
      <span class="row-value" style="${riskSty}">${riskLbl} · ${pt} ${pr.toFixed(1)}%<span class="stab-info-btn" onclick="toggleDetail(this)">?</span><div style="display:none;font-size:11px;color:var(--text-3);margin-top:4px;font-family:'DM Sans',sans-serif;line-height:1.5">${tooltip}</div></span>
    </div>`;
  })();
```

Note: `<span class="stab-info-btn"...>?</span>` is placed immediately after the `%` text with no whitespace (紧接文字).

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_financial_service.py::test_payout_risk_row_uses_question_mark_button -v
```
Expected: PASS

**Step 5: Run full test suite**

```bash
pytest -x -q
```
Expected: All pass.

**Step 6: Commit**

```bash
git add agent/static/dashboard.html tests/test_financial_service.py
git commit -m "feat: replace ℹ with ? button in payoutRiskRow, show LLM health rationale in tooltip"
```

---

### Task 6: Update Spec + Push

**Files:**
- Modify: `docs/specs/dividend_scanners.md`

**Context:** Update the health scoring section to document the LLM layer. No tests needed for docs.

**Step 1: Update `docs/specs/dividend_scanners.md`**

Find the `health` scoring formula section and replace/extend with:

```markdown
### Health Score

**Rule-based (normal companies):**
```
health = min(roe, 30) + max(0, 30 - debt_to_equity × 20) + payout_score   [capped 0-100]
payout_score = 40 if effective_payout_ratio < 70 else 20
```

**LLM override (anomalous companies):**

Triggered when either:
- `debt_to_equity > 200` (negative book equity from buybacks/M&A)
- `payout_ratio > 100` AND `sector NOT IN {Energy, Utilities, Real Estate}`

LLM call returns `{health_score, fcf_payout_est, rationale}`. Overrides:
- `health_score` ← LLM value (0–100)
- `effective_payout_ratio` ← `fcf_payout_est`
- `payout_type` ← `"LLM"`
- `health_rationale` ← rationale string (shown in dashboard tooltip)

Fallback to rule-based if LLM unavailable or call fails.
```

**Step 2: Run full test suite one final time**

```bash
pytest -x -q
```
Expected: All pass.

**Step 3: Commit and push**

```bash
git add docs/specs/dividend_scanners.md
git commit -m "docs: update dividend_scanners spec with LLM health assessment layer"
git push origin main
```
