# Watchlist Seed from Default Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** When a user's watchlist is empty, automatically seed it with the default universe so they always operate in personal-editable mode.

**Architecture:** Add `seed_watchlist()` to `AgentDB`; call it in `watchlist_page` when items is empty; remove the dual-mode `is_default` branch from the template. One-time fork — seeded copy is independent of the default pool thereafter.

**Tech Stack:** Python, FastAPI, Jinja2, SQLite (via `AgentDB`), pytest

---

### Task 1: `AgentDB.seed_watchlist()` — DB layer

**Files:**
- Modify: `agent/db.py` (after `remove_from_watchlist`)
- Test: `tests/test_agent_db.py`

**Step 1: Write the failing tests**

Open `tests/test_agent_db.py`. Add at the end:

```python
def test_seed_watchlist(tmp_db):
    tmp_db.save_user("ALICE")
    items = [
        {"ticker": "AAPL", "name": "Apple", "group": "US Tech", "role": "core"},
        {"ticker": "TSM",  "name": "TSMC",  "group": "Semi",    "role": ""},
    ]
    tmp_db.seed_watchlist("ALICE", items)
    result = tmp_db._parse_watchlist(tmp_db.get_user("ALICE"))
    assert len(result) == 2
    assert result[0]["ticker"] == "AAPL"
    assert result[0]["name"] == "Apple"
    assert result[1]["ticker"] == "TSM"


def test_seed_watchlist_overwrites(tmp_db):
    tmp_db.save_user("ALICE")
    tmp_db.seed_watchlist("ALICE", [{"ticker": "MSFT"}])
    tmp_db.seed_watchlist("ALICE", [{"ticker": "NVDA"}, {"ticker": "AMD"}])
    result = tmp_db._parse_watchlist(tmp_db.get_user("ALICE"))
    tickers = [r["ticker"] for r in result]
    assert tickers == ["NVDA", "AMD"]
    assert "MSFT" not in tickers
```

Note: check how `tmp_db` fixture is defined in that file — it may be called `db` or use `tmp_path`. Match the existing fixture name.

**Step 2: Run tests to verify they fail**

```bash
cd /Users/q/code/ai-monitor
python -m pytest tests/test_agent_db.py::test_seed_watchlist tests/test_agent_db.py::test_seed_watchlist_overwrites -v
```

Expected: `FAILED` — `AgentDB has no attribute 'seed_watchlist'`

**Step 3: Implement `seed_watchlist` in `agent/db.py`**

Find `remove_from_watchlist` (around line 137). Add the new method immediately after it:

```python
def seed_watchlist(self, user_id: str, items: List[Dict]):
    """Write items directly to watchlist_json. Used for first-time seeding only.
    Overwrites any existing content. Caller is responsible for data quality."""
    self.conn.execute(
        "UPDATE users SET watchlist_json=? WHERE user_id=?",
        (json.dumps(items, ensure_ascii=False), user_id)
    )
    self.conn.commit()
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_agent_db.py::test_seed_watchlist tests/test_agent_db.py::test_seed_watchlist_overwrites -v
```

Expected: `PASSED`

**Step 5: Run full test suite to check no regressions**

```bash
python -m pytest tests/test_agent_db.py -v
```

Expected: all tests pass.

**Step 6: Commit**

```bash
git add agent/db.py tests/test_agent_db.py
git commit -m "feat(db): add seed_watchlist for first-time default pool copy"
```

---

### Task 2: Seed logic in `watchlist_page`

**Files:**
- Modify: `agent/dashboard.py` (function `watchlist_page`, lines ~125-150)
- Test: `tests/test_dashboard_routes.py`

**Step 1: Write the failing tests**

Open `tests/test_dashboard_routes.py`. Add:

```python
from unittest.mock import patch

FAKE_UNIVERSE = [
    {"ticker": "AAPL", "name": "Apple", "group": "US Tech", "role": "core",
     "floor": "150", "strike": "180", "note": ""},
    {"ticker": "MSFT", "name": "Microsoft", "group": "US Tech", "role": "core",
     "floor": "300", "strike": "350", "note": ""},
]


def test_watchlist_page_seeds_empty_user(client, db):
    """Empty watchlist → seeded from default universe on page load."""
    db.save_user("ALICE")
    with patch("agent.dashboard._get_default_universe", return_value=FAKE_UNIVERSE):
        resp = client.get("/watchlist")
    assert resp.status_code == 200
    user = db.get_user("ALICE")
    items = db._parse_watchlist(user)
    tickers = [i["ticker"] for i in items]
    assert "AAPL" in tickers
    assert "MSFT" in tickers


def test_watchlist_page_no_double_seed(client, db):
    """Non-empty watchlist → no re-seeding on subsequent visits."""
    db.save_user("ALICE")
    db.add_to_watchlist("ALICE", "TSLA")
    with patch("agent.dashboard._get_default_universe", return_value=FAKE_UNIVERSE) as mock_uni:
        client.get("/watchlist")
    # _get_default_universe should not be called at all (list already non-empty)
    mock_uni.assert_not_called()


def test_watchlist_page_no_seed_when_default_empty(client, db):
    """If default universe is empty (CSV not ready), do not seed — show empty state."""
    db.save_user("ALICE")
    with patch("agent.dashboard._get_default_universe", return_value=[]):
        resp = client.get("/watchlist")
    assert resp.status_code == 200
    user = db.get_user("ALICE")
    items = db._parse_watchlist(user)
    assert items == []
```

Note: check how `client` and `db` fixtures are defined in this file and match them. The `client` is typically a `TestClient` wrapping the FastAPI app.

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_dashboard_routes.py::test_watchlist_page_seeds_empty_user tests/test_dashboard_routes.py::test_watchlist_page_no_double_seed tests/test_dashboard_routes.py::test_watchlist_page_no_seed_when_default_empty -v
```

Expected: `FAILED` (seed logic not yet in `watchlist_page`)

**Step 3: Update `watchlist_page` in `agent/dashboard.py`**

Replace the current `watchlist_page` function body (lines ~125-150):

```python
@router.get("/watchlist")
async def watchlist_page(request: Request, db: AgentDB = Depends(get_db)):
    user = db.get_user("ALICE")
    items: list = db._parse_watchlist(user) if user else []

    if not items:
        defaults = _get_default_universe()
        if defaults:
            db.seed_watchlist("ALICE", defaults)
            user = db.get_user("ALICE")
            items = db._parse_watchlist(user)

    tag_index = _build_tag_index(db)
    ticker_rows = [{**item, "tags": tag_index.get(item["ticker"], [])} for item in items]

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

Key changes:
- Added seed block after `items` is fetched
- Removed `is_default` and `default_rows` from template context

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_dashboard_routes.py::test_watchlist_page_seeds_empty_user tests/test_dashboard_routes.py::test_watchlist_page_no_double_seed tests/test_dashboard_routes.py::test_watchlist_page_no_seed_when_default_empty -v
```

Expected: `PASSED`

**Step 5: Run full dashboard test suite**

```bash
python -m pytest tests/test_dashboard_routes.py -v
```

Expected: all pass. Fix any tests that break due to removal of `is_default`/`default_rows` from template context (they now get `None` or `KeyError` in template — template fix is Task 3).

**Step 6: Commit**

```bash
git add agent/dashboard.py tests/test_dashboard_routes.py
git commit -m "feat(dashboard): seed watchlist from default universe on first visit"
```

---

### Task 3: Simplify template — remove `is_default` branch

**Files:**
- Modify: `agent/templates/watchlist.html`

No new tests needed — covered by Task 2 integration tests confirming page renders correctly.

**Step 1: Edit `agent/templates/watchlist.html`**

Find the block starting at line ~142:
```jinja
{% if is_default %}
...
{% else %}
...
{% endif %}
```

Delete the entire `{% if is_default %}...{% else %}` section AND the closing `{% endif %}`, keeping only the content that was between `{% else %}` and `{% endif %}` (the personal view).

Also delete the banner div around line 144:
```html
<div style="font-size:12px; color:var(--text-3); background:var(--surface); ...">
  显示默认扫描标的池 · 添加标的后切换为个人自选
</div>
```

Also delete the CSS for `.default-row` variants that were only used in the default view (the `.default-row-left`, `.default-name`, `.default-role`, `.default-row-right`, `.default-price-label`, `.default-price`, `.default-note` styles can stay — they are also used in the personal view rows).

After edit, the `<!-- 我的自选 -->` section should look like:

```html
<div class="section-eyebrow">我的自选</div>

<div id="ticker-list">
  {% if ticker_rows %}
    {% for row in ticker_rows %}
    <div class="default-row" id="row-{{ row.ticker }}" style="animation-delay: {{ loop.index0 * 60 }}ms">
      ... (existing personal row markup, unchanged)
    </div>
    {% endfor %}
  {% else %}
    <div class="empty-state" id="empty-msg">暂无自选标的，在上方输入 ticker 添加。</div>
  {% endif %}
</div>
```

**Step 2: Verify page renders**

```bash
python -m pytest tests/test_dashboard_routes.py -v
```

Expected: all pass (template no longer references `is_default` or `default_rows`).

**Step 3: Commit**

```bash
git add agent/templates/watchlist.html
git commit -m "refactor(watchlist): remove read-only default view, always show personal list"
```

---

### Task 4: Full regression check

**Step 1: Run entire test suite**

```bash
python -m pytest --tb=short -q
```

Expected: all tests pass (or same count as before this feature).

**Step 2: Commit if clean, otherwise fix**

If all green:
```bash
# Nothing to commit — all changes already committed in Tasks 1-3
```

If any failures, fix the root cause (do not skip or suppress tests).
