# Sell Put Liquidity + Dividend Card Dim 1/2 Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add bid-ask spread liquidity assessment to both Sell Put scanners, use midpoint APY, and restructure the dividend card Dim 1 (business narrative) and Dim 2 (risk-only).

**Architecture:** Four layers in order — data (add `ask` column) → scanner (spread calc + filter) → payload (new fields) → dashboard (new card UI). LLM prompt updated separately to produce structured Chinese business narrative.

**Tech Stack:** Python dataclasses, pandas DataFrame, yfinance options chain, Vanilla JS dashboard.

---

### Task 1: Add `ask` column to yfinance options chain

**Files:**
- Modify: `src/market_data.py:440`
- Test: `tests/test_market_data.py`

**Context:** `get_options_chain()` currently fetches `["strike", "bid", "impliedVolatility"]`. yfinance `chain.puts` also has `ask`. We just need to add it to the column selection.

**Step 1: Write the failing test**

In `tests/test_market_data.py`, add to the existing options chain test section:

```python
def test_get_options_chain_includes_ask_column(mock_provider):
    """Options chain DataFrame must include ask column."""
    with patch("yfinance.Ticker") as mock_yf:
        mock_ticker = MagicMock()
        mock_yf.return_value = mock_ticker
        mock_ticker.options = ["2026-05-16"]
        chain = MagicMock()
        chain.puts = pd.DataFrame({
            "strike": [50.0, 55.0],
            "bid": [1.0, 1.5],
            "ask": [1.2, 1.8],
            "impliedVolatility": [0.3, 0.35],
        })
        mock_ticker.option_chain.return_value = chain
        result = mock_provider.get_options_chain("AAPL", dte_min=30, dte_max=90)
        assert "ask" in result.columns
```

**Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_market_data.py::test_get_options_chain_includes_ask_column -v
```
Expected: FAIL — `ask` not in columns.

**Step 3: Implement**

In `src/market_data.py` line 440, change:
```python
puts = chain.puts[["strike", "bid", "impliedVolatility"]].copy()
```
to:
```python
available = [c for c in ["strike", "bid", "ask", "impliedVolatility"] if c in chain.puts.columns]
puts = chain.puts[available].copy()
if "ask" not in puts.columns:
    puts["ask"] = 0.0
```

**Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_market_data.py::test_get_options_chain_includes_ask_column -v
```
Expected: PASS.

**Step 5: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: add ask column to options chain fetch"
```

---

### Task 2: Update `SellPutSignal` and `scan_sell_put` with liquidity logic

**Files:**
- Modify: `src/scanners.py:94-152`
- Test: `tests/test_scanners.py`

**Context:** `SellPutSignal` has fields `ticker, strike, bid, dte, expiration, apy, earnings_risk`. We need to add `ask, mid, spread_pct, liquidity_warn`. The APY must switch to midpoint. Spread > 30% → return None.

**Step 1: Write failing tests**

In `tests/test_scanners.py`, add:

```python
def test_scan_sell_put_uses_midpoint_apy(sample_ticker_data):
    """APY should be calculated from midpoint (bid+ask)/2, not bid."""
    options_df = pd.DataFrame({
        "strike": [95.0], "bid": [1.0], "ask": [1.4],
        "dte": [60], "expiration": [date.today() + timedelta(days=60)],
    })
    result = scan_sell_put(sample_ticker_data, 100.0, options_df, min_apy=0.0)
    mid = (1.0 + 1.4) / 2  # 1.2
    expected_apy = round((mid / 95.0) * (365 / 60) * 100, 2)
    assert result is not None
    assert result.mid == pytest.approx(1.2)
    assert result.apy == pytest.approx(expected_apy)

def test_scan_sell_put_rejects_spread_over_30pct(sample_ticker_data):
    """Spread > 30% should return None."""
    # mid = (1.0 + 1.6) / 2 = 1.3; spread = 0.6/1.3 = 46% > 30%
    options_df = pd.DataFrame({
        "strike": [95.0], "bid": [1.0], "ask": [1.6],
        "dte": [60], "expiration": [date.today() + timedelta(days=60)],
    })
    result = scan_sell_put(sample_ticker_data, 100.0, options_df, min_apy=0.0)
    assert result is None

def test_scan_sell_put_warns_spread_20_to_30pct(sample_ticker_data):
    """Spread 20-30% should generate signal with liquidity_warn=True."""
    # mid = (1.0 + 1.3) / 2 = 1.15; spread = 0.3/1.15 = 26%
    options_df = pd.DataFrame({
        "strike": [95.0], "bid": [1.0], "ask": [1.3],
        "dte": [60], "expiration": [date.today() + timedelta(days=60)],
    })
    result = scan_sell_put(sample_ticker_data, 100.0, options_df, min_apy=0.0)
    assert result is not None
    assert result.liquidity_warn is True
    assert result.spread_pct == pytest.approx(26.1, abs=0.5)

def test_scan_sell_put_no_ask_falls_back_to_bid(sample_ticker_data):
    """When ask column is missing (0.0), use bid as midpoint."""
    options_df = pd.DataFrame({
        "strike": [95.0], "bid": [1.2], "ask": [0.0],
        "dte": [60], "expiration": [date.today() + timedelta(days=60)],
    })
    result = scan_sell_put(sample_ticker_data, 100.0, options_df, min_apy=0.0)
    assert result is not None
    assert result.mid == pytest.approx(1.2)
    assert result.liquidity_warn is False
```

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_scanners.py::test_scan_sell_put_uses_midpoint_apy tests/test_scanners.py::test_scan_sell_put_rejects_spread_over_30pct -v
```
Expected: FAIL.

**Step 3: Implement**

In `src/scanners.py`, replace `SellPutSignal` dataclass (lines 94-102):

```python
@dataclass
class SellPutSignal:
    ticker: str
    strike: float
    bid: float
    ask: float
    mid: float
    spread_pct: float
    dte: int
    expiration: date
    apy: float           # percentage, based on midpoint
    earnings_risk: bool
    liquidity_warn: bool  # True if spread 20-30%
```

Replace the body of `scan_sell_put` after selecting `best` (lines 126-152):

```python
    strike = float(best["strike"])
    bid = float(best["bid"])
    ask = float(best.get("ask", 0) or 0)
    dte = int(best["dte"])
    expiration = best["expiration"]

    if strike == 0 or dte == 0:
        return None

    # Liquidity: compute spread
    mid = (bid + ask) / 2 if ask > 0 else bid
    spread_pct = ((ask - bid) / mid * 100) if mid > 0 and ask > 0 else 0.0

    # Hard filter: spread > 30% → no signal for standalone sell put
    if spread_pct > 30:
        return None

    liquidity_warn = spread_pct > 20

    apy = (mid / strike) * (365 / dte) * 100

    if apy < min_apy:
        return None

    earnings_risk = False
    if ticker_data.earnings_date and ticker_data.days_to_earnings is not None:
        if ticker_data.days_to_earnings <= dte:
            earnings_risk = True

    return SellPutSignal(
        ticker=ticker_data.ticker,
        strike=strike,
        bid=bid,
        ask=ask,
        mid=mid,
        spread_pct=round(spread_pct, 1),
        dte=dte,
        expiration=expiration if isinstance(expiration, date) else expiration,
        apy=round(apy, 2),
        earnings_risk=earnings_risk,
        liquidity_warn=liquidity_warn,
    )
```

**Step 4: Run all scanner tests**

```bash
python3 -m pytest tests/test_scanners.py -v
```
Expected: all PASS.

**Step 5: Commit**

```bash
git add src/scanners.py tests/test_scanners.py
git commit -m "feat: add liquidity check to scan_sell_put (midpoint APY, spread filter)"
```

---

### Task 3: Update `scan_dividend_sell_put` with liquidity logic

**Files:**
- Modify: `src/dividend_scanners.py:466-566`
- Test: `tests/test_dividend_scanners.py`

**Context:** Unlike `scan_sell_put`, spread > 30% here does NOT return None — it returns a dict with `sell_put_illiquid=True` so Dim 4 can show a warning instead of an action.

**Step 1: Write failing tests**

In `tests/test_dividend_scanners.py`, add:

```python
def test_scan_dividend_sell_put_uses_midpoint_apy(mock_provider, sample_ticker_data):
    """APY uses midpoint, not bid."""
    options_df = pd.DataFrame({
        "strike": [30.0], "bid": [0.80], "ask": [1.00],
        "dte": [60], "expiration": [date.today() + timedelta(days=60)],
    })
    mock_provider.get_options_chain.return_value = options_df
    mock_provider.should_skip_options.return_value = False
    result = scan_dividend_sell_put(sample_ticker_data, mock_provider,
                                    annual_dividend=1.72, target_yield_percentile=90,
                                    target_yield=5.5)
    assert result is not None
    assert result.get("sell_put_illiquid") is False
    mid = (0.80 + 1.00) / 2
    expected_apy = round((mid / 30.0) * (365 / 60) * 100, 2)
    assert result["apy"] == pytest.approx(expected_apy, abs=0.1)

def test_scan_dividend_sell_put_illiquid_flag_over_30pct(mock_provider, sample_ticker_data):
    """Spread > 30% returns illiquid dict, not None."""
    # mid=1.3, spread=(1.6-1.0)/1.3=46%
    options_df = pd.DataFrame({
        "strike": [30.0], "bid": [1.0], "ask": [1.6],
        "dte": [60], "expiration": [date.today() + timedelta(days=60)],
    })
    mock_provider.get_options_chain.return_value = options_df
    mock_provider.should_skip_options.return_value = False
    result = scan_dividend_sell_put(sample_ticker_data, mock_provider,
                                    annual_dividend=1.72, target_yield_percentile=90,
                                    target_yield=5.5)
    assert result is not None
    assert result["sell_put_illiquid"] is True
    assert result["spread_pct"] > 30
```

**Step 2: Run to verify fail**

```bash
python3 -m pytest tests/test_dividend_scanners.py::test_scan_dividend_sell_put_uses_midpoint_apy tests/test_dividend_scanners.py::test_scan_dividend_sell_put_illiquid_flag_over_30pct -v
```
Expected: FAIL.

**Step 3: Implement**

In `src/dividend_scanners.py`, replace lines 541-562 (after selecting `closest_option`):

```python
        strike = float(closest_option['strike'])
        bid = float(closest_option['bid'])
        ask = float(closest_option.get('ask', 0) or 0)
        dte = int(closest_option['dte'])
        expiration = closest_option['expiration']

        # Liquidity assessment
        mid = (bid + ask) / 2 if ask > 0 else bid
        spread_pct = ((ask - bid) / mid * 100) if mid > 0 and ask > 0 else 0.0

        # Spread > 30%: return illiquid flag (don't discard — Dim 4 will warn)
        if spread_pct > 30:
            logger.info(f"{ticker}: Sell Put illiquid - spread={spread_pct:.1f}%, strike=${strike:.2f}")
            return {"sell_put_illiquid": True, "strike": strike, "dte": dte, "spread_pct": round(spread_pct, 1)}

        liquidity_warn = spread_pct > 20

        # APY uses midpoint
        apy = (mid / strike) * (365 / dte) * 100

        result = {
            'strike': strike,
            'bid': bid,
            'ask': ask,
            'mid': mid,
            'spread_pct': round(spread_pct, 1),
            'liquidity_warn': liquidity_warn,
            'sell_put_illiquid': False,
            'dte': dte,
            'expiration': expiration,
            'apy': round(apy, 2),
        }

        logger.info(
            f"{ticker}: Sell Put selected - strike=${strike:.2f}, mid=${mid:.2f}, "
            f"dte={dte}, apy={apy:.2f}% spread={spread_pct:.1f}% (target_strike=${target_strike:.2f})"
        )

        return result
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_dividend_scanners.py -v
```
Expected: all PASS.

**Step 5: Commit**

```bash
git add src/dividend_scanners.py tests/test_dividend_scanners.py
git commit -m "feat: add liquidity check to scan_dividend_sell_put (illiquid flag, midpoint APY)"
```

---

### Task 4: Update `_build_agent_payload` with new liquidity fields

**Files:**
- Modify: `src/main.py:39-53` (sell_put section), `src/main.py:139-162` (dividend section)
- Test: `tests/test_integration.py`

**Context:** Payload must pass `ask`, `mid`, `spread_pct`, `liquidity_warn` for sell put; `option_ask`, `option_mid`, `option_spread_pct`, `option_liquidity_warn`, `option_illiquid` for dividend.

**Step 1: Write failing test**

In `tests/test_integration.py`, find or add a payload test:

```python
def test_build_agent_payload_sell_put_has_liquidity_fields():
    signal = SellPutSignal(
        ticker="AAPL", strike=150.0, bid=1.0, ask=1.2, mid=1.1,
        spread_pct=18.2, dte=45,
        expiration=date.today() + timedelta(days=45),
        apy=5.9, earnings_risk=False, liquidity_warn=False,
    )
    td = make_ticker_data("AAPL")
    payload = _build_agent_payload(
        sell_puts=[(signal, td)], iv_low=[], iv_high=[], ma200_bull=[],
        ma200_bear=[], leaps=[], earnings_gaps=[], earnings_gap_ticker_map={},
        iv_momentum=[], dividend_signals=[],
    )
    sp = next(p for p in payload if p["signal_type"] == "sell_put")
    assert sp["ask"] == 1.2
    assert sp["mid"] == 1.1
    assert sp["spread_pct"] == 18.2
    assert sp["liquidity_warn"] is False

def test_build_agent_payload_dividend_illiquid_option():
    """Dividend signal with illiquid option should have option_illiquid=True."""
    opt = {"sell_put_illiquid": True, "strike": 50.0, "dte": 60, "spread_pct": 45.0}
    signal = make_dividend_signal(option_details=opt)
    payload = _build_agent_payload(..., dividend_signals=[signal])
    div = next(p for p in payload if p["signal_type"] == "dividend")
    assert div["option_illiquid"] is True
    assert div["option_spread_pct"] == 45.0
```

**Step 2: Run to verify fail**

```bash
python3 -m pytest tests/test_integration.py -k "liquidity" -v
```
Expected: FAIL — missing fields.

**Step 3: Implement**

In `src/main.py`, sell_put section of `_build_agent_payload` (around line 39-52):
Add after `"apy"` line:
```python
            "ask": round(float(signal.ask), 2),
            "mid": round(float(signal.mid), 2),
            "spread_pct": round(float(signal.spread_pct), 1),
            "liquidity_warn": bool(signal.liquidity_warn),
```

In the dividend section (around line 149-162), update option fields:
```python
            "option_strike": round(float(opt["strike"]), 0) if opt and not opt.get("sell_put_illiquid") else (round(float(opt["strike"]), 0) if opt else None),
            "option_dte": opt["dte"] if opt else None,
            "option_bid": round(float(opt["bid"]), 2) if opt and not opt.get("sell_put_illiquid") else None,
            "option_ask": round(float(opt["ask"]), 2) if opt and not opt.get("sell_put_illiquid") else None,
            "option_mid": round(float(opt["mid"]), 2) if opt and not opt.get("sell_put_illiquid") else None,
            "option_apy": round(float(opt["apy"]), 1) if opt and not opt.get("sell_put_illiquid") else None,
            "option_spread_pct": round(float(opt["spread_pct"]), 1) if opt else None,
            "option_liquidity_warn": bool(opt.get("liquidity_warn", False)) if opt else False,
            "option_illiquid": bool(opt.get("sell_put_illiquid", False)) if opt else False,
            "combined_apy": round(float(s.current_yield) + float(opt["apy"]), 1) if opt and not opt.get("sell_put_illiquid") else None,
```

**Step 4: Run full test suite**

```bash
python3 -m pytest tests/ -q
```
Expected: all PASS.

**Step 5: Commit**

```bash
git add src/main.py tests/test_integration.py
git commit -m "feat: add liquidity fields to agent payload for sell put and dividend signals"
```

---

### Task 5: Update LLM prompt to output structured Chinese business narrative

**Files:**
- Modify: `src/financial_service.py:161-174`
- Test: `tests/test_financial_service.py`

**Context:** `_get_analysis_text()` currently asks for "2-3句中文描述业务稳定性". Change to output three labeled lines: 确定性业务 / 增量新业务 / 估值区间.

**Step 1: Write failing test**

In `tests/test_financial_service.py`, add:

```python
def test_analysis_text_prompt_includes_business_structure(mock_llm_client):
    """LLM prompt must request 确定性业务/增量新业务/估值区间 structure."""
    analyzer = FinancialServiceAnalyzer(enabled=True, fallback_to_rules=True, api_key="test")
    with patch.object(analyzer, '_get_client', return_value=mock_llm_client):
        with patch.object(analyzer, '_has_llm_key', return_value=True):
            mock_llm_client.simple_chat.return_value = "确定性业务：稳定分红。增量新业务：无。估值区间：合理。"
            result = analyzer._get_analysis_text("KO", "Consumer Staples", "Beverages", MagicMock())
    call_args = mock_llm_client.simple_chat.call_args
    prompt_text = call_args[0][1]  # user message
    assert "确定性业务" in prompt_text
    assert "增量新业务" in prompt_text
    assert "估值区间" in prompt_text
```

**Step 2: Run to verify fail**

```bash
python3 -m pytest tests/test_financial_service.py::test_analysis_text_prompt_includes_business_structure -v
```
Expected: FAIL — prompt doesn't contain those keywords.

**Step 3: Implement**

In `src/financial_service.py` lines 161-174, replace the prompt string:

```python
            prompt = (
                f"股票: {ticker}\n"
                f"行业: {sector} / {industry}\n"
                f"综合质量评分: {quality_result.overall_score:.0f}/100\n"
                f"稳定性: {quality_result.stability_score:.0f}, "
                f"财务健康: {quality_result.health_score:.0f}, "
                f"防御性: {quality_result.defensiveness_score:.0f}\n\n"
                "请用中文按以下格式输出，每项一句话：\n"
                "确定性业务：[核心业务描述，稳定现金流来源]\n"
                "增量新业务：[增长方向或新业务风险，若无则写"暂无明显增量业务"]\n"
                "估值区间：[结合股息率定价或PE区间说明大概值多少钱的逻辑]"
            )
```

Also update `max_tokens=300` (was 200) to allow for the structured format.

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_financial_service.py -v
```
Expected: all PASS.

**Step 5: Commit**

```bash
git add src/financial_service.py tests/test_financial_service.py
git commit -m "feat: update LLM prompt to output structured business narrative (确定性/增量/估值区间)"
```

---

### Task 6: Update dashboard — Sell Put card liquidity display

**Files:**
- Modify: `agent/static/dashboard.html` — `cardSellPut()` and `cardSellPutRisk()`

**Context:** Replace `bid` with `mid` APY display, add liquidity warning row, add ℹ️ tooltip explaining the rule. No backend test needed — visual only.

**Step 1: Update `cardSellPut()`**

Find `function cardSellPut(s)` and replace the card body:

```js
function cardSellPut(s) {
  const p = s.payload;
  const earningsRow = p.days_to_earnings != null
    ? `<div class="row"><span class="label">财报</span><span class="value">${p.earnings_date} (${p.days_to_earnings}天)</span></div>`
    : '';
  const liquidityRow = p.liquidity_warn
    ? `<div class="row"><span class="label" style="color:#ff9f43">流动性</span><span class="value" style="color:#ff9f43">⚠️ 偏差 (价差${p.spread_pct}%)</span></div>`
    : '';
  const liquidityHint = p.mid != null
    ? `<p style="font-size:11px;color:#8080a0;margin-top:4px">按中间价估算 (bid $${p.bid} / ask $${p.ask})，实际成交可能略低
       <span class="stab-info-btn" onclick="toggleStabilityDetail(this)">ℹ️</span>
       <span class="stability-detail" style="display:none;font-size:11px;color:#a0a0c0">
         流动性规则：价差 ≤ 20% 正常；20–30% 提示流动性差；> 30% 不展示此卡片。收益按 (bid+ask)÷2 估算。
       </span></p>`
    : '';
  return `<div class="card">
    <div class="card-header">
      <span class="ticker">${s.ticker}</span>
      <span class="type-badge badge-opportunity">Sell Put</span>
    </div>
    <div class="card-body">
      <div class="apy">${p.apy}% APY</div>
      <div class="row"><span class="label">行权价</span><span class="value">$${p.strike}</span></div>
      <div class="row"><span class="label">到期天数</span><span class="value">${p.dte} 天</span></div>
      <div class="row"><span class="label">权利金</span><span class="value">$${p.mid ?? p.bid}</span></div>
      ${liquidityRow}
      ${earningsRow}
      ${liquidityHint}
    </div>
    <div class="card-time">${fmtTime(s.scanned_at)}</div>
  </div>`;
}
```

**Step 2: Verify visually**

Open `https://ai-monitor.fly.dev` after deploy — check that sell put cards show mid-based APY and hint text.

**Step 3: Commit**

```bash
git add agent/static/dashboard.html
git commit -m "feat: sell put card shows midpoint APY, liquidity warning, and rule tooltip"
```

---

### Task 7: Update dashboard — Dividend Dim 1, Dim 2, Dim 4 liquidity

**Files:**
- Modify: `agent/static/dashboard.html` — `cardDividend()`

**Context:** Three changes in one card function:
1. Dim 1: remove stability score (move to Dim 2), show `analysis_text` with 确定性/增量/估值区间 structure
2. Dim 2: remove 价格下行风险 (already in Dim 5), keep 派息风险 + 综合质量风险
3. Dim 4: handle `option_illiquid=True` case

**Step 1: Dim 1 update** in `cardDividend()`:

Replace the Dim 1 div:
```js
    <div class="dc-dim">
      <h4>1️⃣ 基本面估值</h4>
      ${biz ? `<p style="margin-bottom:4px"><strong>${biz.tag}</strong> <span style="color:#a0a0c0;font-size:12px">— ${biz.hint}</span></p>` : ''}
      ${p.analysis_text
        ? `<p class="analysis-text" style="margin-top:6px;white-space:pre-line">${esc(p.analysis_text)}</p>`
        : '<p style="font-size:12px;color:#8080a0">业务分析暂缺，配置 DeepSeek/OpenAI key 后自动生成</p>'}
    </div>
```
(Remove `pctLine`, stability score, `riskFlags` from Dim 1 — these go to Dim 2.)

**Step 2: Dim 2 update** — remove price downside, keep payout + quality + add stability:

```js
    <div class="dc-dim">
      <h4>2️⃣ 风险分级</h4>
      ${/* payout risk row — same as before */}
      ${/* quality risk row — same as before */}
      ${stab ? `<p style="margin-top:6px">${stab} ${stabDetail}</p>` : ''}
      ${riskFlags}
    </div>
```
Remove the 价格下行风险 block entirely.

**Step 3: Dim 4 illiquid handling**:

In the `optSection` template, add illiquid branch:
```js
  const optSection = (() => {
    if (!p.option_strike) return `
      <div class="dc-dim"><h4>4️⃣ 建议操作</h4>
        <p>📈 现货买入: $${p.last_price} (股息率${p.current_yield}%)</p>
      </div>
      <div class="dc-dim"><h4>5️⃣ 最坏情景</h4>${floorSection}</div>`;

    if (p.option_illiquid) return `
      <div class="dc-dim"><h4>4️⃣ 建议操作</h4>
        <p>📈 现货买入: $${p.last_price} (股息率${p.current_yield}%)</p>
        <p style="color:#ff9f43;margin-top:6px">⚠️ Sell Put 流动性太差，不建议操作（价差 ${p.option_spread_pct}%）</p>
        <p style="font-size:11px;color:#8080a0">价差超过30%，买卖成本过高，建议仅做现货买入</p>
      </div>
      <div class="dc-dim"><h4>5️⃣ 最坏情景</h4>${floorSection}</div>`;

    const liqWarn = p.option_liquidity_warn
      ? `<p style="color:#ff9f43;font-size:12px">⚠️ 流动性偏差 (价差${p.option_spread_pct}%)</p>` : '';
    const liqHint = `<p style="font-size:11px;color:#8080a0">按中间价估算 (bid $${p.option_bid} / ask $${p.option_ask})，实际成交可能略低</p>`;
    return `
      <div class="dc-dim"><h4>4️⃣ 建议操作</h4>
        <p>📈 现货买入: $${p.last_price} (股息率${p.current_yield}%)</p>
        <p>📊 Sell Put $${p.option_strike} Strike (${p.option_dte}DTE)</p>
        ${liqWarn}
        <p>权利金: $${p.option_mid} → 年化${p.option_apy}%</p>
        ${liqHint}
        <p class="dc-combined">综合年化: ${p.combined_apy}%</p>
      </div>
      <div class="dc-dim"><h4>5️⃣ 最坏情景</h4>${floorSection}</div>`;
  })();
```

**Step 4: Run full test suite**

```bash
python3 -m pytest tests/ -q
```
Expected: all PASS (dashboard changes are JS-only).

**Step 5: Commit**

```bash
git add agent/static/dashboard.html
git commit -m "redesign: dividend card Dim 1 business narrative, Dim 2 risk-only, Dim 4 liquidity"
```

---

### Task 8: Final verification + rescan reminder

**Step 1: Run full test suite**

```bash
python3 -m pytest tests/ -q
```
Expected: all PASS, no regressions.

**Step 2: Push and wait for deploy**

```bash
git push
```
Wait for both `Deploy to Fly.io` and `Deploy Scanner to Fly` GitHub Actions to complete.

**Step 3: Force weekly pool rescan**

Because the pool was built before the LLM prompt change, `analysis_text` in DB is either empty or old format. To regenerate:

The weekly scan triggers when `last_scan_date` is None or >= 7 days ago. To force it now, either:
- Wait for next week, OR
- Trigger a rescan via the approach discussed (reset last_scan in Fly DB)

**Step 4: Trigger Daily Quant Scan**

```bash
gh workflow run "Daily Quant Scan" --ref main
```
Verify in Fly logs:
- `Pushed X signals to agent` (no flycast error)
- `Bootstrapped X historical yield points` (from yield bootstrap)
- APY values reflect midpoint
- No spread-related errors
