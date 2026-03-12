# IB Gateway Poller → Cloud Risk Pipeline Design

**Date:** 2026-03-12
**Status:** Approved
**Scope:** Local IB Gateway poller + cloud `/api/positions` endpoint + dashboard risk report page

---

## Goal

Replace Flex Query as the positions data source with a direct IB Gateway connection.
Local machine runs a lightweight poller that POSTs live account positions to the cloud,
which enriches Greeks via existing MarketDataProvider and auto-triggers the risk pipeline.

---

## Architecture

```
本地 (live IB Gateway :4001)
────────────────────────────────
ibapi
  └─ local/ibgateway_poller.py
       │  持仓 + 账户摘要 (无 Greeks)
       ↓  POST /api/positions
       │  Header: X-API-Key: <secret>

云端 (Fly.io Docker Compose)
────────────────────────────────
POST /api/positions  (agent/main.py)
  ↓ 验证 API Key
  ↓ 反序列化 → PositionRecord[] + AccountSummary
  ↓ MarketDataProvider.get_option_greeks()
    IB Gateway (paper :4003) → Tradier → Polygon → Black-Scholes
  ↓ OptionStrategyRecognizer
  ↓ StrategyRiskEngine + LLM suggestions
  ↓ generate_html_report()
  ↓ 存入 risk_reports 表
  ↓ 返回 { status: ok, report_date }

GET /risk-report  (agent/main.py)
  ↓ 查最新报告 (或按 ?date= 参数查历史)
  ↓ 渲染 dashboard 页面，内嵌 HTML 报告内容
```

---

## Components

### 1. Local Poller (`local/ibgateway_poller.py`)

Standalone script, no dependency on cloud code.

**Flow:**
1. Connect to IB Gateway at `IB_GATEWAY_HOST:IB_GATEWAY_PORT` with a unique `client_id`
2. `reqAccountSummary()` → NLV, margin, cushion, excess liquidity
3. `reqPositions()` → all positions (STK + OPT), with `avgCost` and `position`
4. Wait for `accountSummaryEnd` + `positionEnd` callbacks via `threading.Event`
5. Serialize to JSON payload (no Greeks — cloud fills these)
6. POST to `CLOUD_API_URL` with `X-API-Key` header
7. Print result and exit

**JSON Payload:**
```json
{
  "account_key": "ALICE",
  "ib_account_id": "U9376705",
  "positions": [
    {
      "symbol": "AVGO  260515P00260000",
      "asset_category": "OPT",
      "put_call": "P",
      "strike": 260.0,
      "expiry": "20260515",
      "multiplier": 100,
      "position": -6,
      "cost_basis_price": 8.93,
      "mark_price": 4.93,
      "unrealized_pnl": 2400.0,
      "delta": 0.0,
      "gamma": 0.0,
      "theta": 0.0,
      "vega": 0.0,
      "underlying_symbol": "AVGO",
      "currency": "USD"
    }
  ],
  "account_summary": {
    "net_liquidation": 820000.0,
    "gross_position_value": 750000.0,
    "init_margin_req": 45000.0,
    "maint_margin_req": 38000.0,
    "excess_liquidity": 240000.0,
    "available_funds": 240000.0,
    "cushion": 0.29
  }
}
```

**Files:**
```
local/
  ibgateway_poller.py
  requirements.txt          # ibapi, requests, python-dotenv
  .env.example
  README.md
```

---

### 2. Cloud Endpoint (`POST /api/positions`)

New route in `agent/main.py`.

**Steps:**
1. Validate `X-API-Key` header against `POSITIONS_API_KEY` env var
2. Parse JSON body → `List[PositionRecord]` + `AccountSummary`
3. Call `src/risk_pipeline.run_pipeline(positions, account_summary, account_key)`
4. `risk_pipeline` enriches Greeks via `MarketDataProvider` for OPT positions with delta=0
5. Runs `OptionStrategyRecognizer → StrategyRiskEngine → generate_html_report()`
6. Saves HTML to `risk_reports` table (upsert by account_id + report_date)
7. Returns `{"status": "ok", "report_date": "2026-03-12", "alerts": {"red": 1, "yellow": 0}}`

**New file:** `src/risk_pipeline.py`
- Extracts the pipeline logic currently in `main.py:run_risk_report()`
- Accepts `List[PositionRecord]` directly (no FlexClient dependency)
- Returns `StrategyRiskReport`

---

### 3. Greeks Enrichment

In `risk_pipeline.py`, after deserializing positions:

```python
for p in positions:
    if p.asset_category == "OPT" and p.delta == 0.0:
        greeks = market_data.get_option_greeks(p.underlying_symbol, p.put_call,
                                                p.strike, p.expiry)
        if greeks:
            p.delta = greeks.get("delta", 0.0)
            p.gamma = greeks.get("gamma", 0.0)
            p.theta = greeks.get("theta", 0.0)
            p.vega  = greeks.get("vega",  0.0)
```

Routing (existing MarketDataProvider priority):
```
IB Gateway (paper, cloud :4003) → Tradier → Polygon → 0.0 (skip)
```

---

### 4. Database

New table in agent's SQLite DB:

```sql
CREATE TABLE IF NOT EXISTS risk_reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   TEXT NOT NULL,
    report_date  TEXT NOT NULL,          -- YYYY-MM-DD
    html_content TEXT NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, report_date)      -- upsert: same day overwrites
);
```

---

### 5. Dashboard (`GET /risk-report`)

New route in `agent/main.py`.

- Left sidebar: add "仓位风险报告" link
- Default: load latest report for default account
- Query params: `?account=ALICE&date=2026-03-12`
- Date picker: dropdown populated from `SELECT DISTINCT report_date ... ORDER BY DESC`
- Rendering: inline HTML (not iframe) — inject `html_content` directly into page template
- If no report exists: show "尚无报告，请运行本地 poller"

---

### 6. Config Redesign

**Cloud (Fly.io secrets) — additions:**
```env
POSITIONS_API_KEY=<random-64-char-secret>   # poller authentication

# New-style account config (IB Gateway path)
ACCOUNT_ALICE_IB_ACCOUNT_ID=U9376705

# Legacy Flex config retained during transition
ACCOUNT_ALICE_FLEX_TOKEN=...
ACCOUNT_ALICE_FLEX_QUERY_ID=...
```

**Local poller (.env):**
```env
IB_GATEWAY_HOST=127.0.0.1
IB_GATEWAY_PORT=4001          # live: 4001, paper: 4002
IB_CLIENT_ID=10               # must be unique, not used by TWS/other clients
IB_ACCOUNT_ID=U9376705

CLOUD_API_URL=https://xxx.fly.dev/api/positions
CLOUD_API_KEY=<same-as-POSITIONS_API_KEY>
ACCOUNT_KEY=ALICE
```

**`load_account_configs()` updated:** supports both `IB_ACCOUNT_ID` (new) and `FLEX_TOKEN` (legacy).
Both paths produce the same `AccountConfig`; the caller decides which data source to use.

---

## File Changes Summary

| File | Change |
|------|--------|
| `local/ibgateway_poller.py` | NEW — local IB Gateway poller |
| `local/requirements.txt` | NEW |
| `local/.env.example` | NEW |
| `src/risk_pipeline.py` | NEW — pipeline logic extracted from main.py |
| `agent/main.py` | ADD routes: POST /api/positions, GET /risk-report |
| `agent/db.py` | ADD risk_reports table |
| `src/risk_utils.py` | UPDATE load_account_configs() for IB_ACCOUNT_ID |

**Not changed:** `option_strategies.py`, `strategy_risk.py`, `portfolio_report.py`, `flex_client.py`

---

## Out of Scope

- Real-time WebSocket push on position change
- Multi-account dashboard (single account per view for now)
- Scheduling / cron setup (user runs poller manually or via cron)
- Greeks via `reqMktData()` in local poller (cloud handles enrichment)
