# Sell Put Liquidity + Dividend Card Dim 1/2 Redesign

**Goal:** Add bid-ask spread liquidity assessment to Sell Put signals; restructure dividend card Dim 1 as business valuation narrative and Dim 2 as risk-only.

**Architecture:** Scanner-level spread filter → payload enrichment → dashboard display.

**Tech Stack:** Python (scanners.py, dividend_scanners.py, market_data.py, main.py), Vanilla JS (dashboard.html), LLM prompt update (financial_service.py)

---

## Change 1: Dividend Card Dim 1 — Business Valuation Narrative

### Before
Dim 1 showed: business type label + yield percentile + analysis_text + stability score + risk flags.

### After
Dim 1 shows only: business type label + LLM analysis structured as 确定性业务 + 增量新业务 + estimated value range.

- Yield percentile stays only in the header subtitle (already there), not repeated in Dim 1.
- `analysis_text` must output in Chinese (for now; i18n later).
- If `analysis_text` is empty: show "业务分析暂缺，配置 DeepSeek/OpenAI key 后自动生成".
- Stability score (综合评分) + risk flags move to Dim 2 only.

### LLM Prompt Update (`financial_service.py`)
Change `analyze_dividend_quality()` prompt to output `analysis_text` in this structure:

```
确定性业务：[核心业务描述，稳定现金流来源，1句话]
增量新业务：[增长方向或新业务风险，1句话]
估值区间：[大概值多少钱的逻辑，结合股息率定价或PE区间，1句话]
```

Language: Chinese. Future: detect user locale and switch.

---

## Change 2: Dividend Card Dim 2 — Risk Classification Only

### Before
Dim 2 showed: 价格下行风险 + 派息切割风险 + 综合质量风险.

### After
Remove 价格下行风险 (already in Dim 5 floor price analysis). Keep:

- **派息切割风险**: payout ratio graded Low/Mid/High/Extreme + plain-language explanation
- **综合质量风险**: quality score graded + note that it covers 5 dimensions

---

## Change 3: Sell Put Liquidity Assessment

### Data Layer — `market_data.py`

`get_options_chain()` currently fetches `["strike", "bid", "impliedVolatility"]`.
Add `"ask"` to the column selection so spread can be computed downstream.

```python
puts = chain.puts[["strike", "bid", "ask", "impliedVolatility"]].copy()
```

Also add `"ask"` to IBKR and Tradier provider options chains for consistency.

### Scanner Layer — `scanners.py` `scan_sell_put()`

After selecting `best` option row:

```python
ask = float(best.get("ask", 0))
bid = float(best["bid"])
mid = (bid + ask) / 2 if ask > 0 else bid
spread_pct = ((ask - bid) / mid * 100) if mid > 0 and ask > 0 else 0.0

# Hard filter: spread > 30% → no signal for pure sell put
if spread_pct > 30:
    return None

# APY uses midpoint
apy = (mid / strike) * (365 / dte) * 100

# Liquidity flag
liquidity_warn = spread_pct > 20
```

Extend `SellPutSignal` dataclass with:
- `ask: float`
- `mid: float`
- `spread_pct: float`
- `liquidity_warn: bool`

### Scanner Layer — `dividend_scanners.py` `scan_dividend_sell_put()`

Same spread calculation. Different behavior at > 30%:
- **Do NOT return None** — return a dict with `sell_put_illiquid=True` flag instead
- Dim 4 in dashboard uses this flag to show "流动性差，不建议 Sell Put（价差 X%）"

```python
ask = float(row.get("ask", 0))
mid = (bid + ask) / 2 if ask > 0 else bid
spread_pct = ((ask - bid) / mid * 100) if mid > 0 and ask > 0 else 0.0

if spread_pct > 30:
    return {"sell_put_illiquid": True, "spread_pct": round(spread_pct, 1)}

apy = (mid / strike) * (365 / dte) * 100
liquidity_warn = spread_pct > 20

return {
    "strike": strike, "bid": bid, "ask": ask, "mid": mid,
    "dte": dte, "apy": round(apy, 2),
    "spread_pct": round(spread_pct, 1),
    "liquidity_warn": liquidity_warn,
    "sell_put_illiquid": False,
}
```

### Payload Layer — `main.py` `_build_agent_payload()`

**Sell Put signal** — add fields:
```python
"ask": round(float(signal.ask), 2),
"mid": round(float(signal.mid), 2),
"spread_pct": round(float(signal.spread_pct), 1),
"liquidity_warn": signal.liquidity_warn,
```

**Dividend signal** — option_details already passed through; add fields from it:
```python
"option_ask": round(float(opt["ask"]), 2) if opt and not opt.get("sell_put_illiquid") else None,
"option_mid": round(float(opt["mid"]), 2) if opt and not opt.get("sell_put_illiquid") else None,
"option_spread_pct": round(float(opt["spread_pct"]), 1) if opt else None,
"option_liquidity_warn": opt.get("liquidity_warn", False) if opt else False,
"option_illiquid": opt.get("sell_put_illiquid", False) if opt else False,
```

### Dashboard — `dashboard.html`

#### Sell Put card (`cardSellPut`)

Replace `bid` display with midpoint APY + liquidity note:

```
APY: ${mid_apy}%
[if liquidity_warn]: ⚠️ 流动性偏差 (价差 ${spread_pct}%)
行权价: $${strike}
到期天数: ${dte} 天
权利金: $${mid} (bid $${bid} / ask $${ask})  ← small text
按中间价估算，实际成交可能略低  ← 11px hint
[ℹ️ tooltip]: 流动性规则：价差 ≤ 20% 正常；20–30% 提示；> 30% 纯策略不展示，股息卡提示不建议操作。收益按 (bid+ask)÷2 估算。
```

#### Dividend Dim 4

```
[if option_illiquid]:
  📊 Sell Put $${strike} — 流动性太差，不建议操作（价差 ${spread_pct}%）
  ℹ️ 价差超过30%，买卖成本过高，建议仅做现货买入

[else]:
  📈 现货买入: $${price} (股息率 ${yield}%)
  📊 Sell Put $${strike} (${dte}DTE) [if liquidity_warn: ⚠️]
  Premium: $${mid} → 年化 ${apy}%
  [small]: 按中间价估算 (bid $${bid} / ask $${ask})
  综合年化: ${combined_apy}%
```

---

## Liquidity Rule Summary (for ℹ️ tooltip)

> **流动性规则**：期权买卖价差 = (卖价 - 买价) ÷ 中间价。
> - ≤ 20%：流动性正常，按中间价估算收益
> - 20–30%：流动性偏差，仍可操作，但实际成交价可能低于估算
> - > 30%：流动性过差。纯 Sell Put 策略不展示；股息策略提示不建议 Sell Put

---

## Files Touched

| File | Change |
|------|--------|
| `src/market_data.py` | Add `ask` column to yfinance options chain fetch |
| `src/scanners.py` | `SellPutSignal` new fields; spread calc; midpoint APY; >30% filter |
| `src/dividend_scanners.py` | `scan_dividend_sell_put()` spread calc; illiquid flag instead of None |
| `src/main.py` | `_build_agent_payload()` new liquidity fields for both signal types |
| `src/financial_service.py` | Update LLM prompt to output Chinese 确定性/增量/估值区间 structure |
| `agent/static/dashboard.html` | Dim 1 business narrative; Dim 2 risk-only; Sell Put card liquidity |

## Not In Scope
- i18n / locale detection (future)
- Volume / open interest display (future enhancement)
- IBKR / Tradier provider `ask` column (deferred; yfinance path only for now)
