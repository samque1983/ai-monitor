# Financial Health LLM Assessment Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace distorted GAAP-based health scoring for negative-equity / high-payout companies with LLM assessment, while keeping rule-based scoring for normal companies.

**Architecture:** Two-layer approach — rule-based anomaly detection gates LLM calls; LLM returns structured JSON (health_score + fcf_payout_est + risk_level + rationale); rationale stored in DB and surfaced in dashboard tooltip.

**Tech Stack:** Python, SQLite, Anthropic/DeepSeek LLM via existing `FinancialServiceAnalyzer`, FastAPI agent, dashboard.html

---

## Problem Statement

Current `health_score` uses GAAP metrics that break for buyback-heavy companies:

| Ticker | GAAP Payout | D/E | ROE | Root Cause |
|--------|-------------|-----|-----|------------|
| ABBV   | 276.79%     | —   | 6225% | M&A intangible amortization crushes GAAP EPS |
| CL     | 78.3%       | 2343x | 497% | Negative book equity from decades of buybacks |
| HD     | 64.6%       | 510x | 145% | Same — negative equity |
| KMB    | 103.7%      | 464x | 126% | Same — negative equity |
| MO     | 101%        | —   | —   | Non-recurring impairments depress GAAP EPS |

These companies are Dividend Kings/Aristocrats with 10–60+ years of unbroken dividend growth. Flagging them as "极高风险" is misleading.

---

## Design

### Layer 1: Anomaly Detection (Rules)

Trigger LLM assessment when **any** of:
- `debt_to_equity > 200` — negative book equity signal
- `payout_ratio > 100` AND `sector NOT IN FCF_PAYOUT_SECTORS` — GAAP EPS distortion

Normal companies (neither condition met) continue with existing rule-based `health_score`. No extra API calls.

### Layer 2: LLM Health Assessment

New method `_get_health_assessment()` in `FinancialServiceAnalyzer`.

**Input** (passed as structured prompt):
```
ticker, sector, industry, consecutive_years, dividend_growth_5y,
payout_ratio (GAAP), roe, debt_to_equity,
free_cash_flow, shares_outstanding, annual_dividend
```

**LLM prompt** (Chinese, system role = "专业股息分析师"):
- Explain that GAAP metrics may be distorted (negative equity / amortization)
- Ask to estimate FCF-based payout ratio
- Ask to assess true dividend cut risk
- Return strict JSON only

**Output JSON schema**:
```json
{
  "health_score": 72.0,
  "fcf_payout_est": 55.0,
  "risk_level": "low",
  "rationale": "KMB负净资产结构由大量股票回购导致，FCF派息率约55%，连续51年增息，实际派息安全"
}
```

- `health_score`: 0–100, replaces rule-based value
- `fcf_payout_est`: estimated FCF payout %, used to recompute `payout_score`
- `risk_level`: `"low"` | `"medium"` | `"high"` — drives dashboard risk label
- `rationale`: 1–2 sentences in Chinese, shown in dashboard tooltip

**Caching**: stored in existing `analysis_cache` table with `cache_type = "health"`, key = ticker, 7-day TTL (same as `analysis_text`).

### Layer 3: Score Override

In `_calculate_rule_based_score()`:
1. Detect anomaly (D/E > 200 or GAAP payout > 100 outside FCF sectors)
2. If anomalous AND LLM key available: call `_get_health_assessment()`
3. Override `health_score` with LLM value
4. Override `payout_score` component using `fcf_payout_est` (< 70% → 40pts, else 20pts)
5. Recompute `overall_score` with corrected health

### Layer 4: DB Storage

Add `health_rationale TEXT` column to `dividend_pool` table (migration: `ALTER TABLE dividend_pool ADD COLUMN health_rationale TEXT`).

Populated from `rationale` field of LLM response during weekly scan.

### Layer 5: Dashboard UI

**"派息切割风险" row changes:**

For anomalous companies with LLM assessment:
- Risk label driven by `risk_level`: `low` → 低(绿), `medium` → 中等(amber), `high` → 高/极高(red)
- Payout display shows `fcf_payout_est` (estimated FCF%) instead of raw GAAP%
- Adds `· LLM` suffix to payout_type display

For all companies:
- Replace `ℹ` button with `?` pill button (same `stab-info-btn` CSS class)
- Button placed immediately after risk label text (no space-between)
- Click toggles detail div showing:
  - If `health_rationale` present: LLM rationale text
  - Else: existing fixed tooltip text ("轻资产行业使用 GAAP 净利润" / "FCF派息率")

**Button style** (inherits existing `stab-info-btn`):
```css
/* no new CSS needed — reuse stab-info-btn */
```

---

## Affected Files

| File | Change |
|------|--------|
| `src/financial_service.py` | Add `_get_health_assessment()`, anomaly detection, score override in `_calculate_rule_based_score()` |
| `src/dividend_store.py` | Add `health_rationale` column migration + save/get in `save_pool()` |
| `agent/static/dashboard.html` | Update `payoutRiskRow` JS — `?` button, LLM rationale, risk_level-driven label |
| `tests/test_financial_service.py` | Tests for anomaly detection, LLM override, fallback when no key |
| `docs/specs/dividend_scanners.md` | Update health scoring section to document LLM layer |

---

## Error Handling

- LLM call fails → fall back to rule-based score silently (log warning)
- LLM returns invalid JSON → same fallback
- No LLM key → anomaly detected but no LLM call, rule-based score used as-is (existing behavior)
- `fcf_payout_est` missing from response → use GAAP payout for payout_score only

---

## Test Plan

1. `test_anomaly_detection_triggers_for_high_de` — D/E 300 triggers LLM path
2. `test_anomaly_detection_triggers_for_gaap_payout_over_100` — payout 103% non-FCF-sector triggers
3. `test_normal_company_skips_llm` — D/E 50, payout 65% does NOT trigger
4. `test_llm_health_override_replaces_rule_score` — mock LLM response, verify health_score replaced
5. `test_llm_failure_falls_back_to_rules` — LLM throws, rule score used
6. `test_health_rationale_stored_in_pool` — rationale saved to DB
7. `test_dashboard_shows_question_mark_button` — `?` present in payoutRiskRow HTML
