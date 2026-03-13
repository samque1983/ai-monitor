# 自选池改造 + 策略详情页 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the `/watchlist` page with live add/remove ticker management + strategy coverage tags, and add a `/strategy/dividend` detail page showing the dividend strategy description and its latest scan pool with key metrics.

**Architecture:** Two new DB methods for watchlist mutation + one for strategy pool queries. Four new API routes wired into the existing FastAPI router. Two templates rewritten/created. Strategy registry in `dashboard.py` makes the design extensible to future strategies without code changes.

**Tech Stack:** FastAPI, Jinja2, SQLite (via AgentDB), existing design system (DM Sans / DM Mono / Instrument Serif, CSS variables, dark theme)

---

## Task 1: DB — add_to_watchlist, remove_from_watchlist, get_strategy_pool

**Files:**
- Modify: `agent/db.py`
- Create: `tests/test_agent_db.py`

### Step 1: Write the failing tests

```python
# tests/test_agent_db.py
import pytest, json, tempfile, os
from agent.db import AgentDB


@pytest.fixture
def db(tmp_path):
    return AgentDB(str(tmp_path / "test.db"))


def test_add_to_watchlist_creates_user_and_adds(db):
    result = db.add_to_watchlist("ALICE", "AAPL")
    assert "AAPL" in result


def test_add_to_watchlist_dedup(db):
    db.add_to_watchlist("ALICE", "AAPL")
    result = db.add_to_watchlist("ALICE", "AAPL")
    assert result.count("AAPL") == 1


def test_add_to_watchlist_uppercases(db):
    result = db.add_to_watchlist("ALICE", "aapl")
    assert "AAPL" in result
    assert "aapl" not in result


def test_remove_from_watchlist(db):
    db.add_to_watchlist("ALICE", "AAPL")
    db.add_to_watchlist("ALICE", "MSFT")
    result = db.remove_from_watchlist("ALICE", "AAPL")
    assert "AAPL" not in result
    assert "MSFT" in result


def test_remove_from_watchlist_missing_ticker(db):
    # Should not raise, just return current list
    result = db.remove_from_watchlist("ALICE", "NVDA")
    assert isinstance(result, list)


def test_get_strategy_pool_returns_latest_scan(db):
    import json
    from datetime import datetime
    # Insert two scan dates; latest should win
    db.conn.execute(
        "INSERT INTO signals (scan_date, scanned_at, signal_type, category, ticker, payload) VALUES (?,?,?,?,?,?)",
        ("2026-03-10", "2026-03-10T12:00:00", "dividend", "opportunity", "KO",
         json.dumps({"current_yield": 3.5, "last_price": 65.0, "quality_score": 85.0, "payout_ratio": 65.0}))
    )
    db.conn.execute(
        "INSERT INTO signals (scan_date, scanned_at, signal_type, category, ticker, payload) VALUES (?,?,?,?,?,?)",
        ("2026-03-12", "2026-03-12T12:00:00", "dividend", "opportunity", "ENB",
         json.dumps({"current_yield": 7.2, "last_price": 42.0, "quality_score": 78.0, "payout_ratio": 64.0}))
    )
    db.conn.execute(
        "INSERT INTO signals (scan_date, scanned_at, signal_type, category, ticker, payload) VALUES (?,?,?,?,?,?)",
        ("2026-03-12", "2026-03-12T12:00:00", "dividend", "opportunity", "T",
         json.dumps({"current_yield": 6.5, "last_price": 20.0, "quality_score": 72.0, "payout_ratio": 70.0}))
    )
    db.conn.commit()
    pool = db.get_strategy_pool("dividend")
    tickers = [r["ticker"] for r in pool]
    assert "ENB" in tickers
    assert "T" in tickers
    assert "KO" not in tickers  # older scan date, should not appear


def test_get_strategy_pool_empty(db):
    result = db.get_strategy_pool("dividend")
    assert result == []
```

### Step 2: Run tests to confirm RED

```bash
cd /Users/q/code/ai-monitor
python -m pytest tests/test_agent_db.py -v
```
Expected: FAIL — `add_to_watchlist`, `remove_from_watchlist`, `get_strategy_pool` not defined on `AgentDB`

### Step 3: Implement the three DB methods

Add to `agent/db.py` after the existing `update_watchlist` method:

```python
def add_to_watchlist(self, user_id: str, ticker: str) -> list:
    """Add ticker to watchlist (dedup, uppercase). Creates user if needed. Returns updated list."""
    ticker = ticker.upper().strip()
    user = self.get_user(user_id)
    if not user:
        self.save_user(user_id)
        user = self.get_user(user_id)
    tickers = json.loads(user["watchlist_json"]) if user.get("watchlist_json") else []
    if ticker not in tickers:
        tickers.append(ticker)
        self.update_watchlist(user_id, tickers)
    return tickers

def remove_from_watchlist(self, user_id: str, ticker: str) -> list:
    """Remove ticker from watchlist. No-op if not present. Returns updated list."""
    ticker = ticker.upper().strip()
    user = self.get_user(user_id)
    if not user:
        return []
    tickers = json.loads(user["watchlist_json"]) if user.get("watchlist_json") else []
    tickers = [t for t in tickers if t != ticker]
    self.update_watchlist(user_id, tickers)
    return tickers

def get_strategy_pool(self, signal_type: str) -> list:
    """Return all signals of given signal_type from the latest scan_date."""
    row = self.conn.execute(
        "SELECT MAX(scan_date) as latest FROM signals WHERE signal_type=?",
        (signal_type,)
    ).fetchone()
    if not row or not row["latest"]:
        return []
    rows = self.conn.execute(
        "SELECT ticker, payload FROM signals WHERE signal_type=? AND scan_date=?",
        (signal_type, row["latest"])
    ).fetchall()
    result = []
    for r in rows:
        entry = {"ticker": r["ticker"]}
        entry.update(json.loads(r["payload"]))
        result.append(entry)
    return result
```

### Step 4: Run tests to confirm GREEN

```bash
python -m pytest tests/test_agent_db.py -v
```
Expected: All 7 tests PASS

### Step 5: Commit

```bash
git add agent/db.py tests/test_agent_db.py
git commit -m "feat: add add/remove watchlist and get_strategy_pool to AgentDB"
```

---

## Task 2: API routes — POST /api/watchlist/add and /api/watchlist/remove

**Files:**
- Modify: `agent/dashboard.py`
- Modify: `tests/test_dashboard_routes.py`

### Step 1: Write the failing tests

Append to `tests/test_dashboard_routes.py`:

```python
def test_watchlist_add_ticker():
    client = get_client()
    resp = client.post("/api/watchlist/add", json={"ticker": "AAPL"})
    assert resp.status_code == 200
    data = resp.json()
    assert "AAPL" in data["tickers"]


def test_watchlist_add_ticker_dedup():
    client = get_client()
    client.post("/api/watchlist/add", json={"ticker": "AAPL"})
    resp = client.post("/api/watchlist/add", json={"ticker": "AAPL"})
    assert resp.json()["tickers"].count("AAPL") == 1


def test_watchlist_remove_ticker():
    client = get_client()
    client.post("/api/watchlist/add", json={"ticker": "NVDA"})
    resp = client.post("/api/watchlist/remove", json={"ticker": "NVDA"})
    assert resp.status_code == 200
    assert "NVDA" not in resp.json()["tickers"]


def test_watchlist_remove_nonexistent_ticker():
    client = get_client()
    resp = client.post("/api/watchlist/remove", json={"ticker": "ZZZZ"})
    assert resp.status_code == 200
    assert isinstance(resp.json()["tickers"], list)
```

### Step 2: Run tests to confirm RED

```bash
python -m pytest tests/test_dashboard_routes.py::test_watchlist_add_ticker -v
```
Expected: FAIL — 404 or method not found

### Step 3: Add routes to dashboard.py

Add these Pydantic models and routes to `agent/dashboard.py`:

```python
class WatchlistMutateRequest(BaseModel):
    ticker: str


@router.post("/api/watchlist/add")
async def watchlist_add(req: WatchlistMutateRequest, db: AgentDB = Depends(get_db)):
    tickers = db.add_to_watchlist("ALICE", req.ticker)
    return JSONResponse({"tickers": tickers})


@router.post("/api/watchlist/remove")
async def watchlist_remove(req: WatchlistMutateRequest, db: AgentDB = Depends(get_db)):
    tickers = db.remove_from_watchlist("ALICE", req.ticker)
    return JSONResponse({"tickers": tickers})
```

### Step 4: Run tests to confirm GREEN

```bash
python -m pytest tests/test_dashboard_routes.py -v
```
Expected: All existing + 4 new tests PASS

### Step 5: Commit

```bash
git add agent/dashboard.py tests/test_dashboard_routes.py
git commit -m "feat: add POST /api/watchlist/add and /remove routes"
```

---

## Task 3: Watchlist page — strategy tags + strategy discovery cards

**Files:**
- Modify: `agent/dashboard.py` (watchlist_page route)
- Modify: `agent/templates/watchlist.html`

### Step 1: Write the failing test

Append to `tests/test_dashboard_routes.py`:

```python
def test_watchlist_page_shows_strategy_section():
    client = get_client()
    resp = client.get("/watchlist")
    assert resp.status_code == 200
    assert "策略发现" in resp.text


def test_watchlist_page_shows_add_input():
    client = get_client()
    resp = client.get("/watchlist")
    assert "ticker-input" in resp.text or "add-ticker" in resp.text
```

### Step 2: Run tests to confirm RED

```bash
python -m pytest tests/test_dashboard_routes.py::test_watchlist_page_shows_strategy_section tests/test_dashboard_routes.py::test_watchlist_page_shows_add_input -v
```
Expected: FAIL

### Step 3: Update watchlist_page route in dashboard.py

Replace the `watchlist_page` function with:

```python
STRATEGY_REGISTRY = [
    {
        "slug": "dividend",
        "name": "高股息价值股",
        "description": "筛选连续派息 5 年以上、股息率处于历史高位的价值型标的",
        "signal_type": "dividend",
        "url": "/strategy/dividend",
    },
]


@router.get("/watchlist")
async def watchlist_page(request: Request, db: AgentDB = Depends(get_db)):
    user = db.get_user("ALICE")
    tickers = json.loads(user["watchlist_json"]) if user and user.get("watchlist_json") else []

    # Build strategy tag index: ticker -> list of strategy names
    strategy_tag_index: dict = {}
    for strategy in STRATEGY_REGISTRY:
        pool = db.get_strategy_pool(strategy["signal_type"])
        for item in pool:
            t = item["ticker"]
            strategy_tag_index.setdefault(t, []).append(strategy["name"])

    # Enrich ticker list with strategy tags
    ticker_rows = [
        {"ticker": t, "tags": strategy_tag_index.get(t, [])}
        for t in tickers
    ]

    # Build strategy cards with pool counts
    strategy_cards = []
    for strategy in STRATEGY_REGISTRY:
        pool = db.get_strategy_pool(strategy["signal_type"])
        strategy_cards.append({**strategy, "count": len(pool)})

    return templates.TemplateResponse(request, "watchlist.html", {
        "active_page": "watchlist",
        "ticker_rows": ticker_rows,
        "strategy_cards": strategy_cards,
    })
```

### Step 4: Rewrite watchlist.html

Replace the full contents of `agent/templates/watchlist.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>自选池 — AI 领航员</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Sans:opsz,wght@9..40,300..600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
:root {
  --bg: #111118; --surface: #1c1c2a; --surface-2: #262636;
  --border: rgba(255,255,255,0.12); --border-2: rgba(255,255,255,0.09);
  --text: #f0f0f8; --text-2: rgba(210,210,230,0.88); --text-3: rgba(210,210,230,0.75);
  --red: #f84960; --amber: #f7a600; --green: #02c076; --blue: #2e86de;
  --r4: 4px; --r8: 8px; --r12: 12px;
  --amber-dim: rgba(255,179,64,0.12);
}
html, body { height: 100%; }
body {
  font-family: "DM Sans", -apple-system, sans-serif;
  background: var(--bg); color: var(--text);
  font-size: 14px; line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
.page-title {
  font-family: "Instrument Serif", Georgia, serif; font-style: italic;
  font-size: clamp(24px, 6vw, 34px); font-weight: 400;
  color: var(--text); line-height: 1.1; margin-bottom: 4px;
}
.page-desc { font-size: 13px; color: var(--text-3); margin-bottom: 24px; }
.section-eyebrow {
  font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-3); margin-bottom: 10px;
  display: flex; align-items: center; gap: 8px;
}
.section-eyebrow::after { content: ''; flex: 1; height: 1px; background: var(--border-2); }

/* Add row */
.add-row {
  display: flex; gap: 8px; margin-bottom: 16px;
}
.add-input {
  flex: 1; background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r8); padding: 9px 14px;
  font-family: "DM Mono", monospace; font-size: 14px; color: var(--text);
  outline: none; text-transform: uppercase;
  transition: border-color 0.15s;
}
.add-input::placeholder { color: var(--text-3); text-transform: none; font-family: "DM Sans", sans-serif; }
.add-input:focus { border-color: var(--amber); }
.add-btn {
  background: var(--amber-dim); border: 1px solid rgba(255,179,64,0.3);
  color: var(--amber); border-radius: var(--r8); padding: 9px 16px;
  font-family: "DM Sans", sans-serif; font-size: 13px; font-weight: 500;
  cursor: pointer; white-space: nowrap;
  transition: background 0.15s, border-color 0.15s;
}
.add-btn:hover { background: rgba(255,179,64,0.2); border-color: rgba(255,179,64,0.5); }

/* Ticker rows */
.ticker-row {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; background: var(--surface);
  border: 1px solid var(--border); border-radius: var(--r8); margin-bottom: 6px;
  animation: fadeUp 0.3s ease both;
}
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.ticker-name { font-family: "DM Mono", monospace; font-size: 14px; font-weight: 600; letter-spacing: 0.03em; flex: 1; }
.ticker-tags { display: flex; gap: 5px; flex-wrap: wrap; }
.ticker-tag {
  font-family: "DM Mono", monospace; font-size: 10px; font-weight: 600;
  letter-spacing: 0.06em; padding: 2px 7px; border-radius: 10px;
  background: var(--amber-dim); color: var(--amber);
  border: 1px solid rgba(255,179,64,0.25);
}
.ticker-del {
  font-family: "DM Mono", monospace; font-size: 11px; color: var(--text-3);
  cursor: pointer; padding: 4px 6px; border-radius: var(--r4);
  border: none; background: transparent;
  transition: color 0.15s, background 0.15s;
}
.ticker-del:hover { color: var(--red); background: rgba(248,73,96,0.08); }
.empty-state {
  text-align: center; padding: 40px 20px;
  color: var(--text-3); font-size: 13px; line-height: 1.8;
}

/* Strategy cards */
.strategy-card {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 16px; background: var(--surface);
  border: 1px solid var(--border); border-radius: var(--r12); margin-bottom: 8px;
  text-decoration: none; color: inherit;
  transition: background 0.15s, border-color 0.15s;
}
.strategy-card:hover { background: var(--surface-2); border-color: rgba(255,255,255,0.18); }
.strategy-icon {
  width: 36px; height: 36px; border-radius: var(--r8);
  background: var(--amber-dim); display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.strategy-body { flex: 1; min-width: 0; }
.strategy-name { font-size: 14px; font-weight: 500; color: var(--text); }
.strategy-desc { font-size: 12px; color: var(--text-3); margin-top: 2px; line-height: 1.4; }
.strategy-meta { display: flex; flex-direction: column; align-items: flex-end; gap: 3px; flex-shrink: 0; }
.strategy-count { font-family: "DM Mono", monospace; font-size: 18px; font-weight: 500; color: var(--text-2); }
.strategy-count-label { font-family: "DM Mono", monospace; font-size: 10px; color: var(--text-3); }
.strategy-arrow { color: var(--text-3); margin-left: 8px; flex-shrink: 0; }
</style>
</head>
<body>
<div class="app-shell">
  {% include "_nav.html" %}
  <main class="main-content" style="padding: 24px 16px; max-width: 720px;">

    <div class="page-title">自选池</div>
    <div class="page-desc">管理关注标的 · 查看策略覆盖</div>

    <!-- Add ticker -->
    <div class="add-row">
      <input class="add-input" id="ticker-input" placeholder="输入 ticker，如 AAPL" maxlength="12">
      <button class="add-btn" onclick="addTicker()">+ 添加</button>
    </div>

    <div class="section-eyebrow">我的自选</div>
    <div id="ticker-list">
      {% if ticker_rows %}
        {% for row in ticker_rows %}
        <div class="ticker-row" id="row-{{ row.ticker }}" style="animation-delay: {{ loop.index0 * 60 }}ms">
          <span class="ticker-name">{{ row.ticker }}</span>
          <div class="ticker-tags">
            {% for tag in row.tags %}
            <span class="ticker-tag">{{ tag }}</span>
            {% endfor %}
          </div>
          <button class="ticker-del" onclick="removeTicker('{{ row.ticker }}')" title="移除">✕</button>
        </div>
        {% endfor %}
      {% else %}
        <div class="empty-state" id="empty-msg">暂无自选标的，在上方输入 ticker 添加。</div>
      {% endif %}
    </div>

    <!-- Strategy discovery -->
    <div class="section-eyebrow" style="margin-top: 32px;">策略发现</div>
    {% for card in strategy_cards %}
    <a class="strategy-card" href="{{ card.url }}">
      <div class="strategy-icon">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--amber)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
        </svg>
      </div>
      <div class="strategy-body">
        <div class="strategy-name">{{ card.name }}</div>
        <div class="strategy-desc">{{ card.description }}</div>
      </div>
      <div class="strategy-meta">
        <span class="strategy-count">{{ card.count }}</span>
        <span class="strategy-count-label">只标的</span>
      </div>
      <svg class="strategy-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="9 18 15 12 9 6"/>
      </svg>
    </a>
    {% endfor %}

  </main>
</div>

<script>
async function addTicker() {
  const input = document.getElementById('ticker-input');
  const ticker = input.value.trim().toUpperCase();
  if (!ticker) return;
  const resp = await fetch('/api/watchlist/add', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ticker})
  });
  if (!resp.ok) return;
  const {tickers} = await resp.json();
  input.value = '';
  renderTickerList(tickers);
}

async function removeTicker(ticker) {
  const resp = await fetch('/api/watchlist/remove', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ticker})
  });
  if (!resp.ok) return;
  const {tickers} = await resp.json();
  renderTickerList(tickers);
}

function renderTickerList(tickers) {
  const list = document.getElementById('ticker-list');
  if (!tickers.length) {
    list.innerHTML = '<div class="empty-state" id="empty-msg">暂无自选标的，在上方输入 ticker 添加。</div>';
    return;
  }
  list.innerHTML = tickers.map((t, i) => `
    <div class="ticker-row" id="row-${t}" style="animation-delay:${i*60}ms">
      <span class="ticker-name">${t}</span>
      <div class="ticker-tags"></div>
      <button class="ticker-del" onclick="removeTicker('${t}')" title="移除">✕</button>
    </div>`).join('');
}

document.getElementById('ticker-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') addTicker();
});
</script>
</body>
</html>
```

### Step 5: Run tests to confirm GREEN

```bash
python -m pytest tests/test_dashboard_routes.py -v
```
Expected: All tests PASS

### Step 6: Commit

```bash
git add agent/dashboard.py agent/templates/watchlist.html
git commit -m "feat: rebuild watchlist page with add/remove + strategy tags + strategy discovery cards"
```

---

## Task 4: Strategy detail page /strategy/dividend

**Files:**
- Modify: `agent/dashboard.py`
- Create: `agent/templates/strategy_dividend.html`
- Modify: `tests/test_dashboard_routes.py`

### Step 1: Write the failing tests

Append to `tests/test_dashboard_routes.py`:

```python
def test_strategy_dividend_page_returns_200():
    client = get_client()
    resp = client.get("/strategy/dividend")
    assert resp.status_code == 200


def test_strategy_dividend_page_has_strategy_name():
    client = get_client()
    resp = client.get("/strategy/dividend")
    assert "高股息" in resp.text


def test_strategy_dividend_page_has_nav():
    client = get_client()
    resp = client.get("/strategy/dividend")
    assert "/dashboard" in resp.text
    assert "/watchlist" in resp.text


def test_strategy_dividend_page_handles_empty_pool():
    # Should not crash when signals table has no dividend signals
    client = get_client()
    resp = client.get("/strategy/dividend")
    assert resp.status_code == 200
```

### Step 2: Run tests to confirm RED

```bash
python -m pytest tests/test_dashboard_routes.py::test_strategy_dividend_page_returns_200 -v
```
Expected: FAIL — 404

### Step 3: Add route to dashboard.py

Add after the `watchlist_page` route:

```python
@router.get("/strategy/dividend")
async def strategy_dividend_page(request: Request, db: AgentDB = Depends(get_db)):
    pool = db.get_strategy_pool("dividend")
    return templates.TemplateResponse(request, "strategy_dividend.html", {
        "active_page": "watchlist",
        "pool": pool,
    })
```

### Step 4: Create strategy_dividend.html

Create `agent/templates/strategy_dividend.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>高股息价值股策略 — AI 领航员</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Sans:opsz,wght@9..40,300..600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
:root {
  --bg: #111118; --surface: #1c1c2a; --surface-2: #262636;
  --border: rgba(255,255,255,0.12); --border-2: rgba(255,255,255,0.09);
  --text: #f0f0f8; --text-2: rgba(210,210,230,0.88); --text-3: rgba(210,210,230,0.75);
  --red: #f84960; --amber: #f7a600; --green: #02c076; --blue: #2e86de;
  --r4: 4px; --r8: 8px; --r12: 12px;
  --amber-dim: rgba(255,179,64,0.12);
}
html, body { height: 100%; }
body {
  font-family: "DM Sans", -apple-system, sans-serif;
  background: var(--bg); color: var(--text);
  font-size: 14px; line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
.back-link {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 13px; color: var(--text-3); text-decoration: none;
  margin-bottom: 16px;
  transition: color 0.15s;
}
.back-link:hover { color: var(--text); }
.page-title {
  font-family: "Instrument Serif", Georgia, serif; font-style: italic;
  font-size: clamp(24px, 6vw, 34px); font-weight: 400;
  color: var(--text); line-height: 1.1; margin-bottom: 4px;
}
.page-desc { font-size: 13px; color: var(--text-3); margin-bottom: 24px; }
.section-eyebrow {
  font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-3); margin-bottom: 10px;
  display: flex; align-items: center; gap: 8px;
}
.section-eyebrow::after { content: ''; flex: 1; height: 1px; background: var(--border-2); }

/* Doc card */
.doc-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r12); padding: 20px; margin-bottom: 24px;
}
.doc-criteria { display: flex; flex-direction: column; gap: 8px; }
.criterion {
  display: flex; align-items: flex-start; gap: 10px;
  font-size: 13px; color: var(--text-2); line-height: 1.5;
}
.criterion-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--amber); margin-top: 6px; flex-shrink: 0;
}
.doc-note {
  font-size: 12px; color: var(--text-3); margin-top: 14px;
  padding-top: 14px; border-top: 1px solid var(--border-2);
  line-height: 1.6;
}

/* Pool table — desktop */
.pool-table {
  width: 100%; border-collapse: collapse; display: none;
}
.pool-table th {
  font-family: "DM Mono", monospace; font-size: 10px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--text-3); padding: 8px 12px; text-align: left;
  border-bottom: 1px solid var(--border);
}
.pool-table th:not(:first-child) { text-align: right; }
.pool-table td {
  padding: 10px 12px; font-size: 13px; color: var(--text-2);
  border-bottom: 1px solid var(--border-2);
}
.pool-table td:not(:first-child) { text-align: right; font-family: "DM Mono", monospace; }
.pool-table tr:last-child td { border-bottom: none; }
.pool-table tbody tr:hover td { background: var(--surface-2); }
.ticker-cell { font-family: "DM Mono", monospace; font-size: 14px; font-weight: 600; color: var(--text); }
.yield-val { color: var(--green); }
.payout-badge {
  font-family: "DM Mono", monospace; font-size: 10px; font-weight: 600;
  padding: 2px 6px; border-radius: 10px;
  background: var(--surface-2); color: var(--text-3);
  border: 1px solid var(--border-2);
}

/* Pool cards — mobile */
.pool-cards { display: flex; flex-direction: column; gap: 8px; }
.pool-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r12); padding: 14px 16px;
  animation: fadeUp 0.3s ease both;
}
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.pool-card-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.pool-card-ticker { font-family: "DM Mono", monospace; font-size: 16px; font-weight: 600; flex: 1; }
.pool-card-yield { font-family: "DM Mono", monospace; font-size: 18px; font-weight: 500; color: var(--green); }
.pool-card-metrics { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
.metric-block { }
.metric-label { font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-3); }
.metric-value { font-family: "DM Mono", monospace; font-size: 13px; color: var(--text-2); margin-top: 2px; }
.empty-state {
  text-align: center; padding: 40px 20px;
  color: var(--text-3); font-size: 13px; line-height: 1.8;
}

@media (min-width: 640px) {
  .pool-table { display: table; }
  .pool-cards { display: none; }
}
</style>
</head>
<body>
<div class="app-shell">
  {% include "_nav.html" %}
  <main class="main-content" style="padding: 24px 16px; max-width: 720px;">

    <a class="back-link" href="/watchlist">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
      自选池
    </a>

    <div class="page-title">高股息价值股</div>
    <div class="page-desc">连续派息 · 股息率历史高位 · 质量评分筛选</div>

    <!-- Strategy description -->
    <div class="section-eyebrow">策略逻辑</div>
    <div class="doc-card">
      <div class="doc-criteria">
        <div class="criterion"><span class="criterion-dot"></span><span>连续派息 ≥ 5 年，5 年股息增长率 ≥ 0%（排除削减股息的标的）</span></div>
        <div class="criterion"><span class="criterion-dot"></span><span>当前股息率 ≥ 2%，派息率 ≤ 100%（FCF 或 GAAP 盈利支撑）</span></div>
        <div class="criterion"><span class="criterion-dot"></span><span>LLM 质量评分 ≥ 70 分（综合 ROE、负债率、FCF 稳定性、行业竞争力）</span></div>
        <div class="criterion"><span class="criterion-dot"></span><span>每日监控买入时机：当前股息率 ≥ 4% 或处于 5 年历史分位数 ≥ 90%</span></div>
        <div class="criterion"><span class="criterion-dot"></span><span>美股标的：评估 Sell Put 策略增强收益（综合年化 = 期权收益 + 股息率）</span></div>
      </div>
      <div class="doc-note">
        股票池每周刷新一次。买入信号每日扫描，以价格低位（高股息率）为核心触发条件。<br>
        此处展示当日触发买入信号的标的，非完整股票池。
      </div>
    </div>

    <!-- Current pool -->
    <div class="section-eyebrow">当前买入信号池（{{ pool | length }} 只）</div>

    {% if pool %}
      <!-- Desktop table -->
      <table class="pool-table">
        <thead>
          <tr>
            <th>标的</th>
            <th>当前股息率</th>
            <th>最新价</th>
            <th>质量分</th>
            <th>派息率</th>
            <th>类型</th>
          </tr>
        </thead>
        <tbody>
          {% for item in pool %}
          <tr>
            <td class="ticker-cell">{{ item.ticker }}</td>
            <td><span class="yield-val">{{ "%.1f"|format(item.current_yield) }}%</span></td>
            <td>{{ "%.2f"|format(item.last_price) if item.last_price else "—" }}</td>
            <td>{{ item.quality_score | int if item.quality_score else "—" }}</td>
            <td>{{ "%.0f"|format(item.payout_ratio) ~ "%" if item.payout_ratio else "—" }}</td>
            <td><span class="payout-badge">{{ item.payout_type or "GAAP" }}</span></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>

      <!-- Mobile cards -->
      <div class="pool-cards">
        {% for item in pool %}
        <div class="pool-card" style="animation-delay: {{ loop.index0 * 60 }}ms">
          <div class="pool-card-header">
            <span class="pool-card-ticker">{{ item.ticker }}</span>
            <span class="pool-card-yield">{{ "%.1f"|format(item.current_yield) }}%</span>
          </div>
          <div class="pool-card-metrics">
            <div class="metric-block">
              <div class="metric-label">最新价</div>
              <div class="metric-value">{{ "%.2f"|format(item.last_price) if item.last_price else "—" }}</div>
            </div>
            <div class="metric-block">
              <div class="metric-label">质量分</div>
              <div class="metric-value">{{ item.quality_score | int if item.quality_score else "—" }}</div>
            </div>
            <div class="metric-block">
              <div class="metric-label">派息率</div>
              <div class="metric-value">{{ "%.0f"|format(item.payout_ratio) ~ "%" if item.payout_ratio else "—" }}</div>
            </div>
          </div>
        </div>
        {% endfor %}
      </div>

    {% else %}
      <div class="empty-state">暂无买入信号。<br>当股息率处于历史高位时，标的将出现在此处。</div>
    {% endif %}

  </main>
</div>
</body>
</html>
```

### Step 5: Run tests to confirm GREEN

```bash
python -m pytest tests/test_dashboard_routes.py -v
```
Expected: All tests PASS

### Step 6: Run full test suite

```bash
python -m pytest --tb=short -q
```
Expected: All existing tests still PASS

### Step 7: Commit

```bash
git add agent/dashboard.py agent/templates/strategy_dividend.html tests/test_dashboard_routes.py
git commit -m "feat: add /strategy/dividend page with strategy docs and live pool"
```

---

## Final Verification

```bash
python -m pytest --tb=short -q
```
All tests pass. Manually verify:
- `/watchlist` — input box works, add/remove via browser
- `/strategy/dividend` — loads, shows empty state if no signals
- Mobile layout: resize browser < 640px, cards render instead of table
