# Design: Watchlist Seed from Default Universe

**Date:** 2026-03-14
**Status:** Approved

## Problem

When a user's watchlist is empty, the `/watchlist` page currently shows a read-only "default universe" view. The moment the user adds any ticker, it switches to a personal editable view. This two-mode design is confusing — users lose sight of the default pool entirely, and there is no easy way to start from the defaults.

## Solution

On first visit to `/watchlist` with an empty watchlist, automatically copy the default universe into the user's `watchlist_json`. After seeding, the user is always in personal watchlist mode — their copy is fully editable and independent of the default pool.

## Behavior

```
First visit (watchlist_json = [])
  → detect empty
  → seed from _get_default_universe()
  → watchlist_json = [{ticker, name, role, ...}, ...]
  → render personal view (editable, with delete buttons)

Subsequent visits (watchlist_json non-empty)
  → render personal view directly, no seeding
```

The seed is a one-time fork. The user's copy is fully independent — future changes to the default pool do not affect already-seeded users.

## Changes

### 1. `agent/db.py` — add `seed_watchlist`

New method alongside existing `add_to_watchlist` / `remove_from_watchlist`:

```python
def seed_watchlist(self, user_id: str, items: List[Dict]):
    """Write a list of dicts directly to watchlist_json. Used for first-time seeding only."""
    self.conn.execute(
        "UPDATE users SET watchlist_json=? WHERE user_id=?",
        (json.dumps(items, ensure_ascii=False), user_id)
    )
    self.conn.commit()
```

- Does not dedup or merge — caller is responsible for passing clean data.
- `items` are full row dicts from `_get_default_universe()` (fields: `ticker`, `name`, `group`, `role`, `floor`, `strike`, `note`).

### 2. `agent/dashboard.py` — `watchlist_page` seed logic

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
    # ... rest unchanged
```

- Remove `is_default` and `default_rows` from template context.
- If `_get_default_universe()` returns empty (CSV not ready), fall through to empty personal view with no seed.

### 3. `agent/templates/watchlist.html` — remove default universe branch

- Delete the `{% if is_default %}...{% else %}...{% endif %}` block.
- Keep only the personal view (currently the `{% else %}` branch).
- Delete the banner: `显示默认扫描标的池 · 添加标的后切换为个人自选`.
- The empty state message `暂无自选标的，在上方输入 ticker 添加。` is kept for the edge case where the default universe CSV is also empty.

## Tests

| File | Test | Assertion |
|------|------|-----------|
| `tests/test_agent_db.py` | `test_seed_watchlist` | After `seed_watchlist`, `_parse_watchlist` returns the seeded items with correct fields |
| `tests/test_agent_db.py` | `test_seed_watchlist_overwrites` | Calling `seed_watchlist` again replaces previous data |
| `tests/test_dashboard_routes.py` | `test_watchlist_page_seeds_empty_user` | Mock `_get_default_universe`, GET `/watchlist` with empty user → DB is seeded, response contains ticker rows |
| `tests/test_dashboard_routes.py` | `test_watchlist_page_no_double_seed` | Mock `_get_default_universe`, GET `/watchlist` twice → seed called only once (second call skips because non-empty) |
| `tests/test_dashboard_routes.py` | `test_watchlist_page_no_seed_when_default_empty` | Mock `_get_default_universe` returns `[]` → no seed, empty state rendered |

## Out of Scope

- Multi-user support (currently hardcoded to `ALICE`)
- Sync/merge when default pool updates after seeding
- "Reset to defaults" button (could be a future feature)
