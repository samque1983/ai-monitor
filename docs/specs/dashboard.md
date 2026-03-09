# Dashboard MVP Spec

**Source modules:**
- `agent/db.py` — signals table schema + save/query methods
- `agent/deps.py` — DB dependency injection
- `agent/dashboard.py` — HTTP endpoints
- `agent/static/dashboard.html` — frontend (static file)
- `agent/main.py` — scan_results push wiring
- `src/main.py` — `_build_agent_payload()`

---

## Data Layer (`agent/db.py`)

### signals table schema

```sql
CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date   DATE NOT NULL,
    scanned_at  TIMESTAMP NOT NULL,
    signal_type TEXT NOT NULL,
    category    TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_scanned_at ON signals(scanned_at);
```

### `_CATEGORY_MAP`

Class-level dict mapping `signal_type` → `category`:

| signal_type | category |
|---|---|
| `sell_put` | `opportunity` |
| `iv_low` | `opportunity` |
| `leaps` | `opportunity` |
| `dividend` | `opportunity` |
| `ma200_bullish` | `opportunity` |
| `iv_high` | `risk` |
| `ma200_bearish` | `risk` |
| `earnings_gap` | `risk` |
| `sell_put_earnings_risk` | `risk` |
| `iv_momentum` | `risk` |

Unknown `signal_type` values are categorized as `"unknown"` with a warning log.

### `save_signals(scan_date: str, signals: List[Dict]) -> int`

Idempotent write: deletes all existing rows for `scan_date` before inserting new ones.

`scanned_at` is set to noon (`12:00:00`) of `scan_date` so that time-range filters work correctly for historical dates. Falls back to `datetime.now()` if `scan_date` is not a valid ISO date.

`payload` stores all signal fields except `signal_type` and `ticker`, serialized as JSON.

Returns the number of rows inserted.

### `get_signals(time_range: str = "24h", category: Optional[str] = None) -> List[Dict]`

`time_range` values and their cutoff windows:

| value | hours |
|---|---|
| `"24h"` | 24 |
| `"7d"` | 168 |
| `"30d"` | 720 |

Unknown values default to 24h. Filters `scanned_at >= cutoff`.

`category` filter is applied only when not `None` (the API layer converts `"all"` → `None`).

Returns rows ordered by `scanned_at DESC`. Each dict has `payload` parsed back to a Python dict (not a JSON string).

---

## Dependency Injection (`agent/deps.py`)

### `get_db() -> AgentDB`

Module-level lazy singleton. Reads `AGENT_DB_PATH` env var (default: `"data/agent.db"`) on every call and re-creates the instance if the path has changed. This path-change detection enables test isolation: tests set a different `AGENT_DB_PATH` and get a fresh DB instance automatically.

---

## API Layer (`agent/dashboard.py`)

### `GET /dashboard`

Returns `agent/static/dashboard.html` as a `FileResponse`. No authentication.

### `GET /api/signals`

Query params:
- `time_range`: `Literal["24h", "7d", "30d"]`, default `"24h"`
- `category`: `str`, default `"all"` (passed as `None` to `get_signals` when `"all"`)

Response shape (JSON):
```json
{
  "range": "24h",
  "count": 12,
  "opportunity_count": 7,
  "risk_count": 5,
  "signals": [
    {
      "id": 1,
      "scan_date": "2026-03-09",
      "scanned_at": "2026-03-09T12:00:00",
      "signal_type": "sell_put",
      "category": "opportunity",
      "ticker": "AAPL",
      "payload": {"strike": 170.0, "dte": 21, "bid": 1.5, "apy": 18.3}
    }
  ]
}
```

`opportunity_count` and `risk_count` are computed server-side from the returned signals (not a separate DB query). They reflect the filtered result set, not global totals.

---

## Scan Push Wiring (`agent/main.py`)

### `POST /api/scan_results`

Existing endpoint extended with dual-write. After saving to `scan_results` (raw blob), it now also calls `db.save_signals(scan_date, results)`. Both writes happen in the same request handler; a failure in `save_signals` would propagate as a 500.

The `dashboard_router` from `agent/dashboard.py` is registered via `app.include_router(dashboard_router)` during app construction.

---

## Signal Builder (`src/main.py`)

### `_build_agent_payload(...) -> list`

Converts scanner outputs into a flat list of signal dicts for the agent API. All 10 signal types:

| signal_type | key fields |
|---|---|
| `sell_put` | `strike`, `dte`, `bid`, `apy` |
| `sell_put_earnings_risk` | same as `sell_put` — emitted as a second entry when `signal.earnings_risk` is true |
| `iv_low` | `iv_rank` |
| `iv_high` | `iv_rank` |
| `ma200_bullish` | `last_price`, `ma200`, `pct` |
| `ma200_bearish` | `last_price`, `ma200`, `pct` |
| `leaps` | `last_price`, `rsi14`, `iv_rank` |
| `earnings_gap` | `avg_gap`, `up_ratio`, `max_gap`, `days_to_earnings`, `iv_rank` |
| `iv_momentum` | `iv_momentum`, `iv_rank` |
| `dividend` | ticker only (no extra fields) |

Numeric fields are rounded: `apy` to 1 dp, prices to 2 dp, ratios/ranks to 1 dp. `None` is preserved for missing optional fields (e.g. `iv_rank` when not computed).

`earnings_gap` enrichment: `days_to_earnings` and `iv_rank` are looked up from `earnings_gap_ticker_map` (a `{ticker: TickerData}` dict built from `all_data`).

---

## Tests

- `tests/agent/test_db.py` — signals table: save/get, idempotency, time-range filtering, category filter, unknown signal_type handling
- `tests/agent/test_dashboard.py` — HTTP endpoints: `GET /dashboard` returns 200, `GET /api/signals` returns correct shape, category and time_range params, empty state
- `tests/agent/test_scan_push.py` — `POST /api/scan_results` dual-write: verifies signals are persisted alongside raw scan_results
- `tests/test_integration.py` — `_build_agent_payload`: verifies all 10 signal types, earnings_risk branching, None handling
