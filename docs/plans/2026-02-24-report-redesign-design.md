# Report Redesign: Chinese + Apple-Style HTML

## Goal

Redesign the report output: (1) convert TXT report to Chinese, (2) add an Apple-style HTML report, (3) remove "Module X" labels and version numbers.

## Architecture

Dual renderer approach — keep `report.py` for TXT (rewritten in Chinese), add `html_report.py` for HTML. Both accept the same data parameters. `main.py` calls both and saves `.txt` + `.html`.

## Decisions

| Decision | Choice |
|----------|--------|
| HTML deployment | Self-contained static `.html` file (inline CSS, no external deps) |
| TXT report | Keep, rewrite in Chinese |
| Design style | Apple.com: white background, large whitespace, SF Pro font stack, card layout |
| Chinese level | Mixed: titles/descriptions in Chinese, financial terms (IV Rank, MA200, RSI, APY, DTE) stay English |
| Module titles | Rule name only, no "Module X", no version |

## Section 1: TXT Report Chinese Rewrite (`report.py`)

### Header
- Before: `V1.9 QUANT RADAR — 2026-02-24 (Mon)`
- After: `量化扫描雷达 — 2026-02-24 (周一)`
- `Data Source:` → `数据源:`, `Universe:` → `标的数:`

### Module Titles
| Before | After |
|--------|-------|
| `── MODULE 2: IV EXTREMES` | `── 波动率极值监控` |
| `── MODULE 3: MA200 CROSSOVER` | `── 趋势反转提醒 (MA200)` |
| `── MODULE 4: LEAPS SETUP (V1.9 共振)` | `── LEAPS 共振信号` |
| `── MODULE 5: SELL PUT SCANNER` | `── Sell Put 扫描` |

### Sub-labels
| Before | After |
|--------|-------|
| `▼ LOW IV (IV Rank < 20%)` | `▼ 低波动率 (IV Rank < 20%)` |
| `▲ HIGH IV (IV Rank > 80%)` | `▲ 高波动率 (IV Rank > 80%)` |
| `↑ BULLISH CROSS (Price > MA200)` | `↑ 向上突破 MA200` |
| `↓ BEARISH CROSS (Price < MA200)` | `↓ 向下跌破 MA200` |

### Empty Results
| Before | After |
|--------|-------|
| `(none)` | `(无符合条件的标的)` |
| `(no tickers meet all 4 conditions)` | `(无同时满足全部4项条件的标的)` |

### Earnings Tag
- Before: `Earnings: 2026-04-25 (64d)`
- After: `财报: 2026-04-25 (64天)`

### Footer
- `Scan completed in` → `扫描耗时`
- `Processed:` → `处理:`
- `Skipped:` → `跳过:`

## Section 2: HTML Report (`html_report.py`)

### Design Specs
- **Colors**: White `#fff` background, text `#1d1d1f`, secondary `#86868b`, dividers `#d2d2d7`
- **Font stack**: `-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif`
- **Layout**: Max-width 720px centered, padding 40px+
- **Cards**: Each module in a rounded card (border-radius: 12px, subtle box-shadow)
- **Responsive**: Works on mobile screens

### Page Structure
```
Header: 量化扫描雷达 + date + data source + universe count
Card: 波动率极值监控 (low/high IV tables)
Card: 趋势反转提醒 (bullish/bearish MA200)
Card: LEAPS 共振信号 (4-condition results)
Card: Sell Put 扫描 (signals with earnings warnings)
Card: 跳过的标的 (if any)
Footer: scan time + processed/skipped counts
```

### Special Rendering
- Earnings warning `🚨` → red highlight background
- Empty results → gray italic "(无符合条件的标的)"
- All CSS inline in `<style>` tag, no external files
- Chinese text throughout, financial terms in English

## Section 3: Integration

### main.py Changes
- Import `format_html_report` from `src.html_report`
- Call both renderers with same data
- Save `{date}_radar.txt` and `{date}_radar.html`
- Print TXT to terminal

### Test Strategy
- `tests/test_report.py` — Update assertions for Chinese text
- `tests/test_html_report.py` — New: verify HTML structure, Chinese labels, empty states, earnings warning
- `tests/test_integration.py` — Update assertions for Chinese text
