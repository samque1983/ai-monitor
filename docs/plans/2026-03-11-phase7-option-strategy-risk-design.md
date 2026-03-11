# Phase 7: Option Strategy Risk — Design Doc

**Date:** 2026-03-11
**Status:** Approved
**Scope:** Complete replacement of per-leg risk analysis with a strategy-aware three-layer pipeline

---

## Goal

Every day, identify the main risks in the account and suggest what to do. When multiple options exist, show pros/cons and a recommendation. Analysis must be understandable by non-experts.

---

## Architecture: Three-Layer Pipeline

```
FlexClient (existing)
    │  List[PositionRecord]
    ▼
OptionStrategyRecognizer          src/option_strategies.py  (NEW)
    │  List[StrategyGroup]
    ▼
StrategyRiskEngine                src/strategy_risk.py      (NEW)
    │  RiskAssessment
    ▼
RecommendationBuilder             (within strategy_risk.py)
    │  ranked alerts + LLM suggestions
    ▼
generate_html_report              src/portfolio_report.py   (REWRITE)
```

**Deleted:** `src/portfolio_risk.py` (10-dim per-leg analysis fully replaced)

---

## Layer 1: OptionStrategyRecognizer

### Grouping

All positions grouped by underlying ticker:
- OPT positions: use `underlying_symbol` field
- STK positions: use `symbol`
- Each underlying becomes one `StrategyGroup` candidate

### Three-Step Recognition

**Step 1 — Match core structure** (priority order, most complex first):

| Priority | Strategy | Match Condition |
|----------|----------|-----------------|
| 1 | Iron Condor | Short Call + Long Call (higher) + Short Put + Long Put (lower), same expiry |
| 2 | Iron Butterfly | Same as Iron Condor, Short Call/Put share strike |
| 3 | Collar | STK + Short Call + Long Put, same expiry |
| 4 | Covered Call | STK + Short Call |
| 5 | Protective Put | STK + Long Put |
| 6 | Bull Put Spread | Short Put (higher strike) + Long Put (lower strike), same expiry |
| 7 | Bear Call Spread | Short Call (lower strike) + Long Call (higher strike), same expiry |
| 8 | Bull Call Spread | Long Call (lower) + Short Call (higher), same expiry |
| 9 | Bear Put Spread | Long Put (higher) + Short Put (lower), same expiry |
| 10 | Straddle | Long or Short Call + Put at same strike, same expiry |
| 11 | Strangle | Long or Short Call + Put at different strikes, same expiry |
| 12 | Calendar Spread | Same strike, different expiry |
| 13 | Diagonal Spread | Different strike + different expiry |
| 14 | Naked Put | Short Put, no stock or hedge |
| 15 | Cash-Secured Put | Short Put, account has sufficient cash |
| 16 | Naked Call | Short Call, no stock |
| 17 | Long Put | Long Put alone |
| 18 | Long Call | Long Call alone |
| 19 | Long Stock | STK only, no options matched |
| 20 | Short Stock | Short STK only |

**Step 2 — Attach protective modifiers**

Remaining unmatched Long Put/Call legs on same underlying → tagged as `tail_hedge` or `extra_protection` modifier on the matched strategy. Changes max_loss calculation: capped at spread width.

**Step 3 — Intent classification**

| Intent | Strategies |
|--------|-----------|
| `income` | Naked Put, CSP, Covered Call, Bull Put Spread, Bear Call Spread, Iron Condor, Iron Butterfly |
| `hedge` | Protective Put, Collar, Long Put/Call as modifier |
| `directional` | Bull/Bear Call/Put Spread (debit), Long Stock, Short Stock |
| `speculation` | Straddle, Strangle, Long Put/Call standalone |
| `mixed` | Collar (income + hedge), Calendar (income + directional) |

### StrategyGroup Dataclass

```python
@dataclass
class StrategyGroup:
    underlying: str
    strategy_type: str        # "Iron Condor", "Bull Put Spread", ...
    intent: str               # "income" | "hedge" | "directional" | "speculation" | "mixed"
    legs: List[PositionRecord]
    stock_leg: Optional[PositionRecord]
    modifiers: List[PositionRecord]   # protective add-ons
    net_delta: float
    net_theta: float
    net_vega: float
    net_gamma: float
    max_profit: Optional[float]       # None = unlimited
    max_loss: Optional[float]         # None = unlimited (naked)
    breakevens: List[float]           # 1 for spreads, 2 for condors/straddles
    expiry: str                       # primary leg expiry YYYYMMDD
    dte: int
    net_pnl: float                    # sum of unrealized_pnl across legs
    net_credit: float                 # premium collected (income) or paid (debit)
    currency: str
```

---

## Layer 2: StrategyRiskEngine

### Four Analysis Dimensions (per strategy)

**A — Greeks (plain language)**
```
净方向敞口：标的每跌1%，此策略盈亏约 $X
时间价值：每天自然流逝 +/-$Y（正=收租，负=付租）
波动率敏感度：IV每上升1%，此策略盈亏约 $Z
```

**B — Scenario Analysis**
Payoff at: underlying ±5%, ±10%, ±15%; IV ±20%, ±50%; time decay 7d/14d/30d.

**C — Stress Test**
- SPY -10% (beta-weighted, cash-like = beta 0)
- VIX +50% (vega-weighted)
- Earnings gap ±8% (for strategies with earnings crossing expiry)

**D — Concentration & Margin**
- Strategy notional as % of NLV (signed: short adds, long subtracts)
- Margin usage per strategy
- Portfolio-level aggregates

### Rule Engine — 20 Core Rules

**Red (立即处理):**
1. Short leg DTE ≤ 7 AND ITM > 2% → assignment imminent
2. Short leg DTE ≤ 14 AND earnings before expiry → earnings crossing, unavoidable
3. Iron Condor: either breakeven breached → one side losing, limited protection remains
4. Account cushion < 10% → margin call risk
5. Single underlying net risk > 40% NLV → dangerous concentration
6. Naked short: no protective modifier AND DTE ≤ 14 AND ITM → full exposure near expiry

**Yellow (本周评估):**
7. Income strategy realized profit > 75% → risk/reward no longer favourable
8. Protective Put/Collar DTE ≤ 21 → hedge expiring, downside soon unprotected
9. Protective Put delta coverage < 50% of stock delta → insufficient hedge
10. Single underlying net risk > 20% NLV → concentration building
11. Stress loss (SPY -10%) > 15% NLV → tail risk elevated
12. Calendar: near leg DTE ≤ 7 → near-month expiring, structure breaks
13. Straddle/Strangle: IV rank < 30% → selling vol cheap, unfavourable entry
14. Account cushion < 20% → margin tightening

**Watch (持续观察):**
15. Portfolio net delta > 80% NLV → directional exposure elevated
16. Portfolio net vega < threshold → short vol, IV spike will hurt overall
17. Long Put/Call standalone with DTE ≤ 21 → hedge depreciating quickly
18. Diagonal: near leg < 14 DTE, roll candidate
19. Iron Condor within 21 DTE → enter management zone
20. Any strategy with unrealised loss > 2× initial max_profit target → exceeded loss tolerance

### Plain Language Layer

Every rule trigger generates two texts:
1. **Technical:** "AAPL Bull Put Spread 180/170 — DTE 8, 已实值 3.2%，已实现收益 82%"
2. **Plain:** "你的 AAPL 价差期权快到期了，而且已经进入亏损区间。现在的风险比剩余可赚的权利金大很多。"

### Portfolio-Level Aggregation

After per-strategy analysis, aggregate:
- Net portfolio delta, theta, vega
- Total stress loss at SPY -10%
- Margin usage breakdown by strategy
- Concentration map by underlying

---

## Layer 3: RecommendationBuilder

### Priority Sorting

Rules produce `RiskAlert` objects with:
- `severity`: red / yellow / watch
- `urgency_dims`: {4=margin, 6=earnings, 7=expiry, 9=gamma} → sorts before others at same level
- `strategy_ref`: which StrategyGroup triggered this

Sort: red+urgent → red → yellow+urgent → yellow → watch

### LLM Calls

Top 3–5 red alerts → one LLM call per alert:

```
Prompt template:
  策略：{strategy_type} on {underlying}
  结构：{legs summary}
  触发规则：{rule description}
  当前数据：{relevant metrics}

  请用80-120字中文分析：
  当前处境 → 选项A/B/C/D的利弊 → 推荐选项及理由
  只陈述条件和逻辑，末尾注明推荐选项。
```

Remaining alerts → rule fallback text from `_RULE_FALLBACKS` dict.

### Portfolio Summary

One additional LLM call for the portfolio-level narrative (top 12 alerts as context) → 80-120 char summary for the report header.

### Today's Action List (今日操作清单)

Top 5 red alerts formatted as:
> 🔴 AAPL Bull Put Spread — 快到期且实值，建议今天 Roll → 推荐 C

---

## Report Redesign (portfolio_report.py)

### Layout

```
[Header] Account · Date · NLV · Cushion · Stress Loss
[Portfolio Summary] AI narrative
[今日操作清单] Top 5 actionable items
─── 立即处理 ──────────────────────
[Strategy Card × N]
─── 本周评估 ──────────────────────
[Strategy Card × N]
─── 持续观察 ─────────────────────
[Strategy Card × N]
```

### Strategy Card Structure

```
┌─ [Strategy Name] [Underlying] [DTE] [Intent badge] ─────────────┐
│  Tech detail: legs summary                                        │
│  Plain text: AI suggestion or rule fallback                       │
│  ─────────────────────────────────────────────────────────────── │
│  Greeks row: Δ $X/1%  Θ +$Y/d  V $Z/1%IV                        │
│  Scenarios: -10% → $△  +10% → $△  IV+30% → $△                  │
│  Options: [A] [B★] [C] [D]  (★ = recommended)                   │
└───────────────────────────────────────────────────────────────────┘
```

---

## Files Changed

| File | Action |
|------|--------|
| `src/option_strategies.py` | NEW — StrategyGroup dataclass + OptionStrategyRecognizer |
| `src/strategy_risk.py` | NEW — StrategyRiskEngine + RecommendationBuilder |
| `src/portfolio_report.py` | REWRITE — strategy-card layout |
| `src/portfolio_risk.py` | DELETE |
| `src/main.py` | UPDATE — wire new pipeline, remove old pipeline |
| `tests/test_option_strategies.py` | NEW |
| `tests/test_strategy_risk.py` | NEW |
| `tests/test_portfolio_risk.py` | DELETE |

---

## Out of Scope (Phase 7)

- Real-time intraday updates (Flex is end-of-day)
- Options Greeks calculation from scratch (use Flex-reported values)
- Multi-account aggregation (single account per report)
- Historical strategy performance tracking
