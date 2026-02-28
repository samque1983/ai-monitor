# Reporting Specification

**Modules**: `src/report.py`, `src/html_report.py`

**Purpose**: 战报生成（文本 + HTML）

---

## Architecture

```
Scanner Results → Report Formatters → Output Files
                         ↓
                  report.txt + report.html
```

---

## Module: report.py (文本战报)

### format_report()

```python
def format_report(
    low_iv: List[TickerData],
    high_iv: List[TickerData],
    ma_bullish: List[TickerData],
    ma_bearish: List[TickerData],
    leaps: List[TickerData],
    sell_put: List[SellPutSignal],
    iv_momentum: List[TickerData],           # Phase 2
    earnings_gaps: List[EarningsGap],        # Phase 2
    earnings_gap_ticker_map: Dict[str, TickerData],  # Phase 2
    skipped: List[Tuple[str, str]],
    scan_time: float,
    data_source: str,
    total_tickers: int
) -> str
```

**输出格式**:
```
=======================================================
  量化扫描雷达 — YYYY-MM-DD (周X)
  数据源: yfinance | 标的数: 22
=======================================================

── 波动率极值监控 ─────────────────────────────────

▼ 低波动率 (IV Rank < 20%)
  AAPL     IV Rank: 15.2%  Price: $250.00  MA200: $245.00
          财报: 2026-05-01 (62天)

▲ 高波动率 (IV Rank > 80%)
  (无符合条件的标的)

── 趋势反转提醒 (MA200) ──────────────────────────

↑ 向上突破 MA200
  (无符合条件的标的)

↓ 向下跌破 MA200
  (无符合条件的标的)

── LEAPS 共振信号 ────────────────────────────────

  (无同时满足全部4项条件的标的)

── Sell Put 扫描 ─────────────────────────────────

  NVDA     Strike: $165  DTE: 48  Bid: $6.50  APY: 30.0%
          财报: 2026-05-21 (82天)

── 波动率异动雷达 (5日IV动量) ──────────────────────

  AAPL     IV动量: +35.2%  当前IV: 25.3%  5日前: 18.7%
          财报: 2026-05-01 (62天)

── 财报 Gap 预警 ─────────────────────────────────

  NVDA (财报: 2026-03-05, 5天后)
    2025-11-20: +8.5%  (Open $210.50, Prev $194.00)
    2025-08-28: -6.2%  (Open $112.00, Prev $119.50)
    ⚠️  高IV警告: 当前IV Rank 85% — 极端波动风险

── 跳过的标的 (Skipped Tickers) ────────────────────

  AVGO         无价格数据 (no price data)

=======================================================
  扫描耗时 220.1s │ 处理: 22 │ 跳过: 1
=======================================================
```

---

## Module: html_report.py (HTML 战报)

### format_html_report()

```python
def format_html_report(
    low_iv: List[TickerData],
    high_iv: List[TickerData],
    ma_bullish: List[TickerData],
    ma_bearish: List[TickerData],
    leaps: List[TickerData],
    sell_put: List[SellPutSignal],
    iv_momentum: List[TickerData],           # Phase 2
    earnings_gaps: List[EarningsGap],        # Phase 2
    earnings_gap_ticker_map: Dict[str, TickerData],  # Phase 2
    skipped: List[Tuple[str, str]],
    scan_time: float,
    data_source: str,
    total_tickers: int,
    report_date: str
) -> str
```

**设计风格**: Apple-style (SF Pro Text, 圆角, 精致阴影)

**CSS 类**:
```css
.container      { max-width: 720px; margin: auto; }
.card           { background: #fff; border-radius: 12px; }
.ticker         { font-weight: 600; }
.empty          { color: #86868b; font-style: italic; }
.earnings-warning { background: #fff0f0; color: #d00; }
.risk-badge     { background: #ff3b30; color: white; }
```

**响应式设计**:
```css
@media (max-width: 480px) {
    .container { padding: 20px 12px; }
    table { font-size: 13px; }
}
```

---

## Helper Functions

### format_earnings_tag()

```python
def format_earnings_tag(
    earnings_date: Optional[date],
    days_to_earnings: Optional[int]
) -> str
```

**输出**:
- `earnings_date` 存在 → `"财报: YYYY-MM-DD (X天)"`
- `earnings_date` 为 None → `"财报: --"`

---

## Report Philosophy (GLOBAL_MASTER.md 第 V 章)

### 战报哲学
1. **纯数据陈述**: 只输出客观指标值和触发条件
2. **禁止建议**: 不得出现 "适合买入"、"建议减仓" 等主观判断
3. **强制附加信息**: 所有标的必须包含财报日期和天数

### 空值处理
- 无符合条件的标的 → `"(无符合条件的标的)"`
- 禁止留空白区域

### 版本控制
- 不显示模块编号 (Module 1/2/3)
- 不显示版本号 (V1.9)
- 使用业务描述作为章节标题

---

## Integration Points

**← scanners.py**: 接收扫描结果
**→ main.py**: 生成文本和 HTML 报告文件

---

## Output Files

**文本报告**:
```
reports/YYYY-MM-DD_radar.txt
```

**HTML 报告**:
```
reports/YYYY-MM-DD_radar.html
```

---

## Configuration

**无需配置** - 报告格式完全由代码控制

---

## Testing

**Test Files**:
- `tests/test_report.py` (文本报告)
- `tests/test_html_report.py` (HTML 报告)

**Coverage**:
- 空值处理（无符合条件的标的）
- 财报风险警告
- Phase 2 新模块（IV 动量、财报 Gap）
- HTML 转义和特殊字符

---

## Design Principles

1. **冷峻理性**: 只陈述事实，零主观建议
2. **信息完整**: 所有标的必须包含财报信息
3. **用户体验**: Apple 风格设计，响应式布局
4. **可读性**: 中文输出，清晰的章节分隔
