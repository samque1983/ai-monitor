# Card UI Readability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix dashboard card readability — label/value rows too wide-spaced and text contrast too low on dark background.

**Architecture:** Pure CSS changes in `agent/static/dashboard.html`. No JS, no data, no logic touched. Two root causes: `justify-content: space-between` spreads label and value to opposite edges; `var(--text-3)` labels are too faint. Fix: fixed-width label column + better contrast + slightly larger fonts.

**Tech Stack:** CSS only, single file `agent/static/dashboard.html`

**Safety net:** Tag `v1.9-ui-before-redesign` already pushed — rollback with `git checkout v1.9-ui-before-redesign -- agent/static/dashboard.html`.

---

## Task 1: Fix card-row label/value layout and contrast

**File:** `agent/static/dashboard.html`

Exact lines to change (verified against current file):

| Line | Class | What changes |
|------|-------|-------------|
| 155 | `.card-row` | Remove `justify-content: space-between` |
| 160 | `.row-label` | `color: var(--text-3)` → `var(--text-2)`; `font-size: 13px` → `14px`; add `width: 120px` |
| 161-164 | `.row-value` | `font-size: 14px` → `15px`; `text-align: right` → `text-align: left` |
| 188 | `.entry-banner-label` | `color: var(--text-3)` → `var(--text-2)` |
| 198-202 | `.dc-group-title` | `color: rgba(236,236,236,0.85)` → `var(--text-2)`; `font-size: 11px` → `12px` |
| 313 | `.strategy-row` | Remove `justify-content: space-between` |
| 315 | `.strategy-row-label` | Add `width: 120px; flex-shrink: 0` |
| 316 | `.strategy-row-value` | `font-size: 13px` → `14px` |

### Step 1: Apply all CSS changes

In `agent/static/dashboard.html`, make these exact replacements:

**Change 1 — `.card-row`** (line 154–158):
```css
/* OLD */
.card-row {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding: 6px 0; border-bottom: 1px solid var(--border-2);
  min-height: 32px; gap: 12px;
}

/* NEW */
.card-row {
  display: flex; align-items: flex-start;
  padding: 6px 0; border-bottom: 1px solid var(--border-2);
  min-height: 32px; gap: 12px;
}
```

**Change 2 — `.row-label`** (line 160):
```css
/* OLD */
.row-label { color: var(--text-3); font-size: 13px; flex-shrink: 0; padding-top: 1px; }

/* NEW */
.row-label { color: var(--text-2); font-size: 14px; width: 120px; flex-shrink: 0; padding-top: 1px; }
```

**Change 3 — `.row-value`** (line 161–164):
```css
/* OLD */
.row-value {
  font-family: "DM Mono", monospace; font-size: 14px; font-weight: 500;
  color: var(--text); text-align: right; line-height: 1.4;
}

/* NEW */
.row-value {
  font-family: "DM Mono", monospace; font-size: 15px; font-weight: 500;
  color: var(--text); text-align: left; line-height: 1.4;
}
```

**Change 4 — `.entry-banner-label`** (line 188):
```css
/* OLD */
.entry-banner-label { color: var(--text-3); flex-shrink: 0; }

/* NEW */
.entry-banner-label { color: var(--text-2); flex-shrink: 0; }
```

**Change 5 — `.dc-group-title`** (line 198–202):
```css
/* OLD */
.dc-group-title {
  display: flex; align-items: center; gap: 6px;
  font-size: 11px; font-weight: 600; color: rgba(236,236,236,0.85);
  padding: 8px 0 5px; letter-spacing: 0.04em;
}

/* NEW */
.dc-group-title {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; font-weight: 600; color: var(--text-2);
  padding: 8px 0 5px; letter-spacing: 0.04em;
}
```

**Change 6 — `.strategy-row`** (line 313):
```css
/* OLD */
.strategy-row { display: flex; justify-content: space-between; align-items: baseline; padding: 5px 0; border-bottom: 1px solid var(--border-2); }

/* NEW */
.strategy-row { display: flex; align-items: baseline; padding: 5px 0; border-bottom: 1px solid var(--border-2); gap: 12px; }
```

**Change 7 — `.strategy-row-label`** (line 315):
```css
/* OLD */
.strategy-row-label { font-size: 12px; color: var(--text-2); }

/* NEW */
.strategy-row-label { font-size: 12px; color: var(--text-2); width: 120px; flex-shrink: 0; }
```

**Change 8 — `.strategy-row-value`** (line 316):
```css
/* OLD */
.strategy-row-value { font-family: 'DM Mono', monospace; font-size: 13px; color: var(--text); }

/* NEW */
.strategy-row-value { font-family: 'DM Mono', monospace; font-size: 14px; color: var(--text); }
```

### Step 2: Visual check

Open `agent/static/dashboard.html` in browser (or check deployed agent). Confirm:
- Label and value sit close together, no giant gap between them
- Labels are clearly legible (not washed-out gray)
- Group titles (基本面 / 风险 / 买入策略…) are readable
- No layout breakage on any card type (IV, MA200, Sell Put, Dividend)

### Step 3: Run Python tests to confirm no regressions

```bash
cd /Users/q/code/ai-monitor
pytest tests/ -x -q
```

Expected: all tests pass (no Python logic was changed).

### Step 4: Commit and push

```bash
git add agent/static/dashboard.html
git commit -m "style: fix card row readability — fixed label width, better contrast, larger font"
git push
```
