# HTML Design System Specification

**Applies to**: ALL HTML-generating modules in this project
`src/html_report.py`, `src/dividend_pool_page.py`, `src/portfolio_report.py`, and any future HTML output

**Reference implementation**: `src/portfolio_report.py` — this is the canonical example.
All other HTML pages must be migrated to match this spec.

---

## Design Language

**Style**: Apple 精炼金融终端 — 深色背景、精准排版、数字等宽、信息密度适中
**Theme**: Dark only
**Layout**: Mobile-first, 375px baseline, max-width 720px centered
**Grid**: Strict 8px multiples (8, 12, 16, 20, 24, 32, 40, 48)

---

## Color Tokens

All colors MUST be defined as CSS variables in `:root`. Never hardcode color values inline.

```css
:root {
  /* Background layers */
  --bg:        #080808;   /* page background, near-black */
  --surface:   #101010;   /* card body */
  --surface-2: #181818;   /* inset elements, code chips, inputs */

  /* Borders */
  --border:    rgba(255,255,255,0.08);  /* primary border */
  --border-2:  rgba(255,255,255,0.05); /* secondary divider */

  /* Text hierarchy */
  --text:   #ececec;                   /* primary text */
  --text-2: rgba(236,236,236,0.58);    /* secondary / descriptions — min 0.55 */
  --text-3: rgba(236,236,236,0.38);    /* labels / helpers — min 0.35 */

  /* Semantic colors */
  --red:   #ff453a;   /* error / danger — Apple iOS red */
  --amber: #ffb340;   /* warning — amber, not pure yellow */
  --green: #34c759;   /* success / safe — Apple iOS green */
  --blue:  #0a84ff;   /* accent / link — Apple iOS blue */

  /* Border radius scale */
  --r4:  4px;
  --r8:  8px;
  --r12: 12px;
  --r16: 16px;
  --r24: 24px;
}
```

### Small Text Contrast Rules (dark background)
- 11px auxiliary text: minimum `rgba(255,255,255,0.38)`, recommended `0.45+`
- 12px secondary text: minimum `rgba(255,255,255,0.50)`
- Never use below `0.25` opacity on `#000–#111` backgrounds

---

## Typography

Load Google Fonts via `<link>` with `preconnect` prewarming — always include all three families:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500&family=DM+Sans:opsz,wght@9..40,300..700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
```

### Font Role Assignments

| Font | Usage | CSS |
|------|-------|-----|
| `DM Sans` + `Noto Sans SC` (CJK) | Page titles, brand headings | `font-family: "DM Sans", "Noto Sans SC", -apple-system, sans-serif; font-weight: 600 (page title) / 500 (brand); font-style: normal; letter-spacing: -0.02em;` |
| `DM Sans` | Body text, labels, UI copy | `font-family: "DM Sans", -apple-system, "Helvetica Neue", sans-serif;` |
| `DM Mono` | All financial numbers, dates, tickers, codes, tech details | `font-family: "DM Mono", monospace;` |

### Type Scale
- Page title: `clamp(22px, 5.5vw, 32px)`, weight 600, letter-spacing `-0.02em`
- Brand title (sidebar): `18px`, weight 500, letter-spacing `-0.02em`
- Section labels: `10px`, weight 600, `letter-spacing: 0.1em`, `text-transform: uppercase`
- Body: `14px`, line-height `1.5`
- Secondary body: `13–14px`, `color: var(--text-2)`, line-height `1.65`
- Monospace numbers: `22px` (hero), `16px` (secondary), `11px` (chips)

### Prohibited Fonts
Never use: Inter, Roboto, Arial, SF Pro as primary font.
System fonts (`-apple-system`) are acceptable as fallback only.

---

## Layout Structure

Every HTML page must follow this structure:

```html
<body>
  <div class="container">

    <!-- 1. Page eyebrow: label left, date/meta right -->
    <div class="page-eyebrow">
      <span class="eyebrow-label">SECTION NAME</span>
      <span class="eyebrow-date">YYYY-MM-DD</span>
    </div>

    <!-- 2. Page title: DM Sans weight-600 -->
    <h1 class="page-title">Title</h1>

    <!-- 3. Status badges (optional) -->
    <div class="badges">...</div>

    <!-- 4. Summary card (optional, for dashboards) -->
    <div class="summary">...</div>

    <!-- 5. Section divider -->
    <div class="section-header">
      <span class="section-label">SECTION</span>
      <div class="section-rule"></div>
      <span class="section-label">N 条</span>
    </div>

    <!-- 6. Content cards -->

  </div>
</body>
```

### body
```css
body {
  background: var(--bg);
  color: var(--text);
  font-family: "DM Sans", -apple-system, "Helvetica Neue", sans-serif;
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  padding: 32px 16px 64px;
}
@media (min-width: 480px) { body { padding: 40px 24px 64px; } }
.container { max-width: 720px; margin: 0 auto; }
```

---

## Card Pattern

All content units are cards with this structure:

```css
.card, .alert-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r12);
  overflow: hidden;
  margin-bottom: 10px;
  transition: border-color 0.2s;
}
.card:hover { border-color: rgba(255,255,255,0.14); }
```

Cards have:
- **Header strip**: `padding: 10px 16px`, colored background for semantic states
- **Body**: `padding: 0 16px 16px`
- Maximum 2 primary actions per card, placed at bottom

---

## Semantic State Colors

Use these for colored card headers and badges:

```python
# In Python generators
_LEVEL_COLOR  = {"red": "#ff453a",              "yellow": "#ffb340"}
_LEVEL_BG     = {"red": "rgba(255,69,58,0.10)", "yellow": "rgba(255,179,64,0.09)"}
_LEVEL_BORDER = {"red": "rgba(255,69,58,0.22)", "yellow": "rgba(255,179,64,0.20)"}
```

---

## Badges

```css
.badge {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 12px; border-radius: 20px;
  font-size: 12px; font-weight: 500; border: 1px solid;
}
.badge-red    { color: var(--red);   background: rgba(255,69,58,0.10);  border-color: rgba(255,69,58,0.22); }
.badge-yellow { color: var(--amber); background: rgba(255,179,64,0.10); border-color: rgba(255,179,64,0.22); }
.badge-green  { color: var(--green); background: rgba(52,199,89,0.10);  border-color: rgba(52,199,89,0.22); }
.badge-blue   { color: var(--blue);  background: rgba(10,132,255,0.10); border-color: rgba(10,132,255,0.22); }
```

---

## Data Chips (Monospace Detail)

Technical values, tickers, and code strings use this chip pattern:

```css
.tech-detail {
  font-family: "DM Mono", monospace;
  font-size: 11px;
  color: var(--text-3);
  background: var(--surface-2);
  display: inline-block;
  padding: 4px 8px;
  border-radius: var(--r4);
  letter-spacing: 0.01em;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

---

## Animation

### Page Load — Staggered fadeUp (CSS-only)

```css
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}

.card { animation: fadeUp 0.4s ease both; }
.card:nth-child(1) { animation-delay: 0.06s; }
.card:nth-child(2) { animation-delay: 0.12s; }
.card:nth-child(3) { animation-delay: 0.18s; }
.card:nth-child(4) { animation-delay: 0.24s; }
.card:nth-child(5) { animation-delay: 0.30s; }
.card:nth-child(6) { animation-delay: 0.36s; }
.card:nth-child(n+7) { animation-delay: 0.40s; }
```

### Rules
- Enter animation runs once, no loop
- `translateY` displacement: 8–16px, never exceed 20px
- Hover: `transition: 0.2s`, not animation
- Never animate layout on data updates (causes jank)

---

## Section Divider

```html
<div class="section-header">
  <span class="section-label">风险预警</span>
  <div class="section-rule"></div>
  <span class="section-label">5 条</span>
</div>
```

```css
.section-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.section-label  { font-size: 10px; font-weight: 600; letter-spacing: 0.1em;
                  text-transform: uppercase; color: var(--text-3); white-space: nowrap; }
.section-rule   { flex: 1; height: 1px; background: var(--border-2); }
```

---

## Empty State

```html
<p class="empty-state">暂无数据 ✓</p>
```

```css
.empty-state { text-align: center; color: var(--text-3); font-size: 14px; padding: 48px 0; }
```

---

## Stat Block Pattern (for summary cards)

```css
.stat-label {
  font-size: 10px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--text-3); margin-bottom: 6px;
}
.stat-value {
  font-family: "DM Mono", monospace;
  font-size: 22px; font-weight: 500; letter-spacing: -0.02em;
  color: var(--text); line-height: 1; margin-bottom: 4px;
}
.stat-note { font-size: 11px; color: var(--text-2); line-height: 1.55; margin-top: 6px; }
```

---

## Migration Checklist

When updating an existing HTML-generating module to this spec:

1. Add Google Fonts `<link>` preconnect block to `<head>`
2. Replace all inline/hardcoded colors with CSS variable references
3. Replace body font with `DM Sans`
4. Replace all numeric/ticker displays with `DM Mono`
5. Replace page title font with `DM Sans` weight 600, `letter-spacing: -0.02em` (CJK fallback: `Noto Sans SC`)
6. Add staggered `fadeUp` animation to cards
7. Replace plain tables with card components where appropriate
8. Add section dividers between content groups
9. Verify small text meets minimum contrast (≥ 0.38 opacity on dark bg)

---

## Module Mapping

| HTML Module | Status | Notes |
|-------------|--------|-------|
| `src/portfolio_report.py` | Reference | Canonical implementation, fully compliant |
| `src/html_report.py` | Needs migration | Old table-based layout, no dark theme tokens |
| `src/dividend_pool_page.py` | Needs migration | Has partial CSS but not aligned with token system |
| Future HTML modules | Must comply | New modules must follow this spec from day one |
