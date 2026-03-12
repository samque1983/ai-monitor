# Sidebar Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a desktop sidebar with multi-dimensional filters (signal type + market), 2-column card grid on desktop, and dual horizontal chip rows on mobile — without touching any card logic, data, or backend.

**Architecture:** Pure frontend change in `agent/static/dashboard.html`. Two tasks: (1) HTML/CSS restructure — wrap page in `.layout`, add `.sidebar` shell, wire mobile chips; (2) JS filter refactor — replace single `currentCat` with a `FILTER_CONFIG`-driven multi-dimensional filter state. No Python code touched.

**Tech Stack:** Vanilla HTML/CSS/JS. Dark theme tokens already defined in `:root`. Fonts: DM Sans, DM Mono, Instrument Serif (already loaded).

**Safety:** Tag `v1.9-before-sidebar-redesign` already pushed. Rollback: `git checkout v1.9-before-sidebar-redesign -- agent/static/dashboard.html`

---

## Current Structure (reference)

```
<body>
  <div class="container">           ← max-width 760px centered
    page-eyebrow + h1
    .filter-row  [range btns]
    .filter-row  [cat btns: 全部/机会/风控]
    #section-header-row
    #cards-container
  </div>
</body>
```

JS state: `currentRange`, `currentCat` (single string).
Filter: `allSignals.filter(s => s.category === currentCat)`.

---

## Task 1: HTML + CSS — Sidebar layout, 2-col grid, mobile chips

**File:** `agent/static/dashboard.html`

No tests (pure CSS/HTML). Verify visually.

### Step 1: Replace `<body>` content with new layout shell

Replace the entire `<body>` content (lines 330–367) with:

```html
<body>
<div class="layout">

  <!-- ── Sidebar (desktop only) ── -->
  <aside class="sidebar">
    <div class="sidebar-brand">
      <span class="sidebar-eyebrow">Quant Radar</span>
      <span class="sidebar-meta" id="last-updated-sidebar"></span>
    </div>
    <div id="sidebar-filters"><!-- populated by JS --></div>
    <div class="sidebar-time">
      <div class="sidebar-group-label">时间范围</div>
      <button class="sidebar-time-btn active" data-range="24h">24小时</button>
      <button class="sidebar-time-btn" data-range="7d">最近一周</button>
      <button class="sidebar-time-btn" data-range="30d">最近一月</button>
    </div>
  </aside>

  <!-- ── Main content ── -->
  <div class="main-content">

    <div class="page-eyebrow">
      <span class="eyebrow-label">Quant Radar</span>
      <span class="eyebrow-meta" id="last-updated">正在加载...</span>
    </div>
    <h1 class="page-title">量化扫描雷达</h1>

    <!-- Mobile: time range (hidden on desktop) -->
    <div class="mobile-time-row" id="mobile-time-row">
      <button class="range-btn active" data-range="24h">24小时</button>
      <button class="range-btn" data-range="7d">最近一周</button>
      <button class="range-btn" data-range="30d">最近一月</button>
    </div>

    <!-- Mobile: filter chips (hidden on desktop) -->
    <div id="mobile-chips-container"></div>

    <div id="section-header-row" class="section-header" style="display:none">
      <span class="section-label" id="section-label-text">信号</span>
      <div class="section-rule"></div>
      <span class="section-label" id="section-count-text"></span>
    </div>

    <div id="cards-container">
      <div class="loading">加载中...</div>
    </div>

  </div><!-- /main-content -->
</div><!-- /layout -->
```

### Step 2: Add CSS for sidebar layout

Add these CSS blocks **after** the existing `.cat-btn.active .tab-count` rule (after line 91), replacing the old `.filter-row` / `.range-btn` / `.cat-btn` blocks (lines 74–91) with:

```css
/* ── Layout ── */
.layout {
  display: flex;
  min-height: 100vh;
}

/* ── Sidebar (hidden on mobile) ── */
.sidebar {
  display: none;
}

/* ── Main content ── */
.main-content {
  flex: 1;
  min-width: 0;
  padding: 28px 16px 64px;
  padding-bottom: max(64px, env(safe-area-inset-bottom, 64px));
}

/* ── Mobile time row ── */
.mobile-time-row {
  display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 10px;
}

/* ── Shared button base (mobile range + cat chips) ── */
.range-btn, .cat-btn, .chip-btn {
  padding: 7px 14px; border-radius: 20px; border: 1px solid var(--border);
  background: var(--surface); font-size: 13px; font-family: "DM Sans", sans-serif;
  color: var(--text-3); cursor: pointer;
  -webkit-tap-highlight-color: transparent; outline: none;
}
.range-btn.active, .cat-btn.active, .chip-btn.active {
  background: var(--surface-2); color: var(--text);
  border-color: rgba(255,255,255,0.18);
}
.tab-count {
  display: inline-block; background: var(--surface-2); color: var(--text-3);
  border-radius: 10px; padding: 0 6px; font-size: 11px; margin-left: 4px;
  font-family: "DM Mono", monospace;
}
.cat-btn.active .tab-count, .chip-btn.active .tab-count {
  background: rgba(255,255,255,0.10); color: var(--text-2);
}

/* ── Mobile chip rows ── */
.chip-row {
  display: flex; flex-wrap: nowrap; gap: 6px;
  overflow-x: auto; margin-bottom: 8px;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.chip-row::-webkit-scrollbar { display: none; }

/* ── Desktop sidebar ── */
@media (min-width: 1024px) {
  body { padding: 0; }

  .sidebar {
    display: flex; flex-direction: column; gap: 0;
    width: 220px; flex-shrink: 0;
    position: sticky; top: 0; height: 100vh;
    overflow-y: auto;
    border-right: 1px solid var(--border);
    padding: 32px 20px 32px;
    background: var(--surface);
  }

  .sidebar-brand {
    margin-bottom: 32px;
  }
  .sidebar-eyebrow {
    display: block;
    font-family: "DM Mono", monospace; font-size: 11px; font-weight: 500;
    letter-spacing: 0.1em; text-transform: uppercase;
    color: var(--amber); margin-bottom: 4px;
  }
  .sidebar-meta {
    display: block;
    font-family: "DM Mono", monospace; font-size: 11px;
    color: var(--text-3); line-height: 1.4;
  }

  .sidebar-group { margin-bottom: 24px; }
  .sidebar-group-label {
    font-size: 10px; font-weight: 600; letter-spacing: 0.1em;
    text-transform: uppercase; color: var(--text-3);
    margin-bottom: 8px;
  }
  .sidebar-filter-btn {
    display: flex; align-items: center; gap: 8px;
    width: 100%; padding: 8px 10px;
    border-radius: var(--r8); border: none;
    background: transparent; color: var(--text-2);
    font-size: 13px; font-family: "DM Sans", sans-serif;
    cursor: pointer; text-align: left;
    transition: background 0.15s, color 0.15s;
    position: relative;
  }
  .sidebar-filter-btn:hover { background: var(--surface-2); color: var(--text); }
  .sidebar-filter-btn.active {
    color: var(--text);
    background: var(--surface-2);
  }
  .sidebar-filter-btn.active::before {
    content: '';
    position: absolute; left: 0; top: 20%; bottom: 20%;
    width: 3px; border-radius: 2px;
    background: var(--amber);
  }
  .sidebar-filter-count {
    margin-left: auto;
    font-family: "DM Mono", monospace; font-size: 11px;
    color: var(--text-3); background: var(--surface);
    padding: 1px 6px; border-radius: 10px;
  }

  .sidebar-time { margin-top: auto; padding-top: 24px; border-top: 1px solid var(--border); }
  .sidebar-time-btn {
    display: block; width: 100%;
    padding: 7px 10px; border-radius: var(--r8);
    border: none; background: transparent;
    color: var(--text-3); font-size: 13px;
    font-family: "DM Sans", sans-serif;
    cursor: pointer; text-align: left;
    margin-bottom: 2px;
  }
  .sidebar-time-btn:hover { background: var(--surface-2); color: var(--text-2); }
  .sidebar-time-btn.active { color: var(--text); background: var(--surface-2); }

  .main-content {
    padding: 40px 40px 72px;
    max-width: 1200px;
  }

  /* 2-column card grid on desktop */
  .card-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
    align-items: start;
  }

  /* Mobile-only elements hidden on desktop */
  .mobile-time-row { display: none; }
  #mobile-chips-container { display: none; }
}

@media (min-width: 480px) and (max-width: 1023px) {
  .main-content { padding: 40px 24px 72px; }
}
```

### Step 3: Remove the old `.container` wrapper CSS

Find and remove:
```css
.container { max-width: 760px; margin: 0 auto; }
```

And the old body padding media query:
```css
@media (min-width: 480px) { body { padding: 40px 24px 72px; } }
```
(Both are now handled by the new CSS above.)

### Step 4: Visual check

Open dashboard in browser:
- **Mobile (<1024px):** Single column, mobile time row + chips at top (chips empty until Task 2 JS)
- **Desktop (≥1024px):** Sidebar visible on left, 2-column card grid on right
- Cards still render correctly, no layout breakage

### Step 5: Commit

```bash
cd /Users/q/code/ai-monitor
git add agent/static/dashboard.html
git commit -m "feat: sidebar layout shell — desktop 2-col grid, mobile chip rows"
```

---

## Task 2: JS — Multi-dimensional FILTER_CONFIG filter system

**File:** `agent/static/dashboard.html` (JS section, lines ~369–1071)

### Step 1: Replace filter state + add FILTER_CONFIG

Find at line ~372:
```js
let currentRange = '24h';
let currentCat   = 'all';
let allSignals   = [];
```

Replace with:
```js
let currentRange   = '24h';
let allSignals     = [];

// ── Filter config (add new dimensions here only) ──────────────────────────
const FILTER_CONFIG = [
  {
    id: 'type',
    label: '信号类型',
    options: [
      { value: 'all',         label: '全部' },
      { value: 'opportunity', label: '机会提醒' },
      { value: 'risk',        label: '市场风控' },
    ],
    match: (s, v) => v === 'all' || s.category === v,
  },
  {
    id: 'market',
    label: '市场',
    options: [
      { value: 'all', label: '全部' },
      { value: 'US',  label: '美股' },
      { value: 'HK',  label: '港股' },
      { value: 'CN',  label: 'A股'  },
    ],
    match: (s, v) => v === 'all' || (s.payload?.market || 'US') === v,
  },
];

// Active filter values, keyed by FILTER_CONFIG id
const currentFilters = Object.fromEntries(
  FILTER_CONFIG.map(f => [f.id, 'all'])
);
```

### Step 2: Add sidebar + mobile chips render functions

Add these functions **before** the `load()` function:

```js
// ── Sidebar filter render ─────────────────────────────────────────────────
function buildSidebarFilters() {
  return FILTER_CONFIG.map(f => {
    const btns = f.options.map(opt => {
      const active = currentFilters[f.id] === opt.value ? ' active' : '';
      const count = opt.value === 'all'
        ? allSignals.length
        : allSignals.filter(s => f.match(s, opt.value)).length;
      const countHtml = `<span class="sidebar-filter-count">${count}</span>`;
      return `<button class="sidebar-filter-btn${active}"
        data-filter-id="${f.id}" data-filter-value="${opt.value}">
        ${opt.label}${countHtml}
      </button>`;
    }).join('');
    return `<div class="sidebar-group">
      <div class="sidebar-group-label">${f.label}</div>
      ${btns}
    </div>`;
  }).join('');
}

// ── Mobile chip rows render ───────────────────────────────────────────────
function buildMobileChips() {
  return FILTER_CONFIG.map(f => {
    const chips = f.options.map(opt => {
      const active = currentFilters[f.id] === opt.value ? ' active' : '';
      return `<button class="chip-btn${active}"
        data-filter-id="${f.id}" data-filter-value="${opt.value}">
        ${opt.label}
      </button>`;
    }).join('');
    return `<div class="chip-row">${chips}</div>`;
  }).join('');
}

function renderFilterUI() {
  const sidebarEl = document.getElementById('sidebar-filters');
  if (sidebarEl) sidebarEl.innerHTML = buildSidebarFilters();
  const mobileEl = document.getElementById('mobile-chips-container');
  if (mobileEl) mobileEl.innerHTML = buildMobileChips();

  // Sync sidebar last-updated meta
  const sidebarMeta = document.getElementById('last-updated-sidebar');
  const mainMeta    = document.getElementById('last-updated');
  if (sidebarMeta && mainMeta) sidebarMeta.textContent = mainMeta.textContent;
}
```

### Step 3: Update `load()` function

Find the load function's success path:
```js
allSignals = data.signals || [];
document.getElementById('count-all').textContent  = data.count;
document.getElementById('count-opp').textContent  = data.opportunity_count;
document.getElementById('count-risk').textContent = data.risk_count;
document.getElementById('last-updated').textContent =
  `${rangeLabel(currentRange)} · ${data.count} 条`;
render();
```

Replace with:
```js
allSignals = data.signals || [];
document.getElementById('last-updated').textContent =
  `${rangeLabel(currentRange)} · ${data.count} 条`;
renderFilterUI();
render();
```

(The old count-all / count-opp / count-risk span IDs are gone — counts now live inside sidebar filter buttons.)

### Step 4: Update `render()` function

Find:
```js
function render() {
  const filtered = currentCat === 'all'
    ? allSignals
    : allSignals.filter(s => s.category === currentCat);

  const hdr = document.getElementById('section-header-row');
  if (!filtered.length) {
    hdr.style.display = 'none';
    document.getElementById('cards-container').innerHTML =
      '<div class="empty-state">该时间段内暂无信号</div>';
    return;
  }

  hdr.style.display = 'flex';
  document.getElementById('section-label-text').textContent =
    currentCat === 'opportunity' ? '机会提醒' : currentCat === 'risk' ? '市场风控' : '所有信号';
  document.getElementById('section-count-text').textContent = filtered.length + ' 条';

  document.getElementById('cards-container').innerHTML =
    `<div class="card-grid">${filtered.map(renderCard).join('')}</div>`;
  initWatchStates();
}
```

Replace with:
```js
function render() {
  const filtered = allSignals.filter(s =>
    FILTER_CONFIG.every(f => f.match(s, currentFilters[f.id]))
  );

  const hdr = document.getElementById('section-header-row');
  if (!filtered.length) {
    hdr.style.display = 'none';
    document.getElementById('cards-container').innerHTML =
      '<div class="empty-state">该时间段内暂无信号</div>';
    return;
  }

  hdr.style.display = 'flex';
  const typeFilter = currentFilters['type'];
  document.getElementById('section-label-text').textContent =
    typeFilter === 'opportunity' ? '机会提醒' : typeFilter === 'risk' ? '市场风控' : '所有信号';
  document.getElementById('section-count-text').textContent = filtered.length + ' 条';

  document.getElementById('cards-container').innerHTML =
    `<div class="card-grid">${filtered.map(renderCard).join('')}</div>`;
  initWatchStates();
}
```

### Step 5: Replace event bindings

Find the old event bindings section (lines ~1050–1067):
```js
document.querySelectorAll('.range-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentRange = btn.dataset.range;
    load();
  });
});

document.querySelectorAll('.cat-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentCat = btn.dataset.cat;
    render();
  });
});
```

Replace with:
```js
// Range buttons (mobile + sidebar — event delegation on document)
document.addEventListener('click', e => {
  // Time range (mobile range-btn or sidebar-time-btn)
  const rangeBtn = e.target.closest('[data-range]');
  if (rangeBtn) {
    currentRange = rangeBtn.dataset.range;
    // Sync active state across all range/time buttons
    document.querySelectorAll('[data-range]').forEach(b => {
      b.classList.toggle('active', b.dataset.range === currentRange);
    });
    load();
    return;
  }

  // Filter buttons (sidebar sidebar-filter-btn or mobile chip-btn)
  const filterBtn = e.target.closest('[data-filter-id]');
  if (filterBtn) {
    const { filterId, filterValue } = filterBtn.dataset;
    currentFilters[filterId] = filterValue;
    renderFilterUI();
    render();
    return;
  }
});
```

### Step 6: Verify filter works end-to-end

Check in browser:
- Desktop sidebar: clicking 机会提醒 filters cards to category === 'opportunity'
- Desktop sidebar: clicking 美股 filters to US market
- Both active simultaneously: AND filter (only 美股 机会)
- Mobile chips: same behavior on narrow screen
- Time range buttons in sidebar work (reload with new range)
- Counts in sidebar buttons update after load

### Step 7: Run Python tests (no regressions expected)

```bash
cd /Users/q/code/ai-monitor
pytest tests/ -x -q 2>&1 | tail -5
```

Expected: 443 passed.

### Step 8: Commit

```bash
git add agent/static/dashboard.html
git commit -m "feat: multi-dimensional FILTER_CONFIG filter — type + market, extensible"
```

---

## Final: push and deploy

```bash
git push
```

GitHub Actions deploys both agent and scanner automatically on push to main.
