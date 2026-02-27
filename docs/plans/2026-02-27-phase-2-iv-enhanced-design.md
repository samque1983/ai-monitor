# Phase 2 IV Enhanced — Design Document

**Version**: 2.0 (Enhanced Resilience)
**Date**: 2026-02-27
**Status**: Approved for Implementation
**Approach**: 方案 B — 增强韧性版

---

## 设计原则遵守

本设计遵循以下规范:
- ✅ `req/GLOBAL_MASTER.md` — 架构约束、数据完整性、TDD 协议
- ✅ `req/phase_2_iv.md` — PRD 功能需求
- ✅ `.clauderc` (项目) — Financial Service Skill、data-explorer 验证
- ✅ `.clauderc` (上级) — 文档层级、镜像测试规则

---

## 一、边界审查总结

### 已识别的关键边界情况

| 模块 | 边界情况 | 风险等级 | 处理策略 |
|------|---------|---------|---------|
| IV Store | 冷启动数据不足 | 🟡 中 | `get_data_sufficiency()` 检查,不足时返回 None |
| IV Momentum | 交易日 vs 自然日偏差 | 🟢 低 | 允许 [n, n+3] 天窗口容差 |
| ATM 识别 | Strike 网格缺失 | 🟡 中 | 使用 `abs(strike - price).idxmin()` |
| Gap 计算 | 盘前/盘后时间未知 | 🔴 高 | MVP 简化假设,本地 CSV 预留 `time_type` 字段 |
| Gap 计算 | K 线数据缺失 | 🟡 中 | 跳过缺失日期,`min_samples=2` 规则 |
| yfinance API | 财报日期接口熔断 | 🔴 高 | yfinance → CSV Fallback 链路 |
| 除零错误 | `prev_close = 0` | 🟢 低 | `if prev_close == 0: continue` |
| 输出格式 | None 值占位符 | 🟢 低 | `f"{value:.1f}%" if value else "N/A"` |

---

## 二、系统架构

### 2.1 模块改动清单

| 文件 | 改动类型 | 核心职责 |
|------|---------|---------|
| **数据层** |
| `src/iv_store.py` | 🔧 扩展 | +`get_iv_n_days_ago()` 历史 IV 查询<br>+`get_data_sufficiency()` 数据质量检查 |
| `src/market_data.py` | 🔧 扩展 | +`get_historical_earnings_dates()` 带 CSV fallback<br>+`get_iv_momentum()` 5日动量计算<br>+`_load_earnings_from_csv()` 本地降级 |
| `data/earnings_calendar.csv` | ✨ 新增 | 本地财报日历兜底数据 (初期可为空) |
| **计算引擎** |
| `src/data_engine.py` | 🔧 扩展 | +`TickerData.iv_momentum` 字段<br>+`EarningsGap` dataclass<br>+`compute_earnings_gaps()` 函数<br>+`validate_price_df()` 验证函数 |
| **扫描器** |
| `src/scanners.py` | 🔧 扩展 | +`scan_iv_momentum()` 高动量扫描<br>+`scan_earnings_gap()` 财报 Gap 分析 |
| **报告** |
| `src/report.py` | 🔧 扩展 | +Section: "波动率异动雷达"<br>+Section: "财报 Gap 预警" |
| `src/html_report.py` | 🔧 扩展 | +对应 HTML 卡片 + 风险标注样式 |
| **配置** |
| `config.yaml` | 🔧 扩展 | +`data.earnings_csv_path`<br>+`scanners.iv_momentum_threshold`<br>+`scanners.earnings_gap_days`<br>+`scanners.earnings_lookback` |
| **测试** |
| `tests/test_*.py` | 🔧 扩展 | 所有改动模块的镜像测试 |

### 2.2 数据流向

```
[Google Sheets CSV]
        ↓
   data_loader (classify_market)
        ↓
┌──────────────────────────────────┐
│  main.py (调度中心)                │
│  ├─ 读取 config.yaml              │
│  ├─ 加载 ticker 池                │
│  └─ 初始化 MarketDataProvider     │
└──────────────────────────────────┘
        ↓
┌──────────────────────────────────┐
│  market_data.py (数据获取层)       │
│  ├─ yfinance API (一级数据源)     │
│  ├─ IVStore (SQLite 历史)         │
│  └─ earnings_calendar.csv (二级)  │
└──────────────────────────────────┘
        ↓
┌──────────────────────────────────┐
│  data_engine.py (计算引擎)         │
│  ├─ validate_price_df() ← 新增    │
│  ├─ build_ticker_data()           │
│  │   └─ +iv_momentum 计算         │
│  └─ compute_earnings_gaps() ← 新增│
└──────────────────────────────────┘
        ↓
┌──────────────────────────────────┐
│  scanners.py (规则引擎)            │
│  ├─ Phase 1 扫描器                │
│  ├─ scan_iv_momentum() ← 新增     │
│  └─ scan_earnings_gap() ← 新增    │
└──────────────────────────────────┘
        ↓
┌──────────────────────────────────┐
│  report.py + html_report.py       │
│  └─ 战报生成 (TXT + HTML)         │
└──────────────────────────────────┘
```

### 2.3 导入方向遵守

严格遵循 `GLOBAL_MASTER.md` 定义:
```
main → scanners/report → data_engine → market_data → data_loader/iv_store
```

**循环依赖预防**:
- `scanners.py` 导入 `MarketDataProvider` 用于类型提示
- 使用 `TYPE_CHECKING` 避免运行时循环导入

---

## 三、核心组件详细设计

### 3.1 IVStore 扩展 (`src/iv_store.py`)

#### 方法 1: `get_iv_n_days_ago()`

**函数签名**:
```python
def get_iv_n_days_ago(
    self,
    ticker: str,
    n: int = 5,
    reference_date: Optional[date] = None
) -> Optional[float]
```

**逻辑**:
- 查询窗口: `[reference_date - n - 3, reference_date - n]`
- 返回窗口内最近的一条记录
- 无数据时返回 `None`

**边界处理**:
- 节假日/周末: 自动回溯到最近交易日
- 数据不足: 返回 `None` (调用方负责判断)

**SQL 查询**:
```sql
SELECT iv FROM iv_history
WHERE ticker = ? AND date >= ? AND date <= ?
ORDER BY date DESC LIMIT 1
```

#### 方法 2: `get_data_sufficiency()`

**返回值**:
```python
{
    "total_days": int,
    "sufficient_for_ivp": bool,      # >= 30 天
    "sufficient_for_momentum": bool  # >= 5 天
}
```

**用途**:
- 在计算 IV Momentum 前检查数据充足性
- 日志记录数据积累进度

---

### 3.2 MarketDataProvider 扩展 (`src/market_data.py`)

#### 方法 1: `get_historical_earnings_dates()`

**Fallback 链路**:
```
yfinance Ticker.earnings_dates
    ↓ (失败/超时)
_load_earnings_from_csv()
    ↓ (CSV 不存在或无数据)
返回 []
```

**CSV 格式** (`data/earnings_calendar.csv`):
```csv
ticker,date,time_type
AAPL,2026-01-30,AMC
AAPL,2025-10-31,AMC
MSFT,2026-01-28,BMO
```

**列说明**:
- `time_type`: AMC (盘后) / BMO (盘前), 可选字段, MVP 阶段不使用

#### 方法 2: `get_iv_momentum()`

**计算公式**:
```python
iv_momentum = (current_iv - iv_5d_ago) / iv_5d_ago * 100
```

**流程**:
1. 检查数据充足性 (`get_data_sufficiency()`)
2. 获取当前 ATM IV
3. 查询 5 天前 IV (`iv_store.get_iv_n_days_ago()`)
4. 计算百分比变化

**返回值**:
- `float`: 动量百分比 (如 `+45.2`)
- `None`: CN/HK 市场、数据不足、API 失败

---

### 3.3 DataEngine 扩展 (`src/data_engine.py`)

#### 新增 dataclass: `EarningsGap`

```python
@dataclass
class EarningsGap:
    ticker: str
    avg_gap: float       # 平均跳空幅度 (%)
    up_ratio: float      # 上涨概率 (%)
    max_gap: float       # 最大跳空 (保留符号)
    sample_count: int    # 样本数量
```

#### 新增函数: `validate_price_df()`

**验证项 (Data-Explorer 思路)**:
- ✅ 必须包含 `Open`, `Close` 列
- ✅ 价格值 > 0
- ✅ NaN 占比 < 5%
- ✅ Index 为 DatetimeIndex

**返回值**:
- `True`: 数据合格,可进入计算
- `False`: 数据异常,拒绝处理

#### 新增函数: `compute_earnings_gaps()`

**Gap 计算公式 (MVP 简化版)**:
```python
gap = (财报日 Open - 前一交易日 Close) / 前一交易日 Close * 100
```

**注意事项**:
- 盘后财报: 次日 Open 才反映 Gap (本算法会滞后一天)
- 盘前财报: 当日 Open 反映 Gap (准确)
- MVP 阶段: 统一使用此公式,未来可根据 `time_type` 调整

**边界处理**:
- 财报日不在 `price_df.index`: 跳过该事件
- `prev_close = 0`: 跳过该事件
- `len(gaps) < min_samples`: 返回 `None`

**统计计算**:
```python
avg_gap = mean(|gap_1|, |gap_2|, ...)
up_ratio = count(gap > 0) / total_count * 100
max_gap = max(gaps, key=abs)  # 保留符号
```

#### TickerData 扩展

```python
@dataclass
class TickerData:
    # ... 现有字段 ...
    iv_momentum: Optional[float]  # 新增: 5日IV动量 (%)
```

**测试更新要求**:
- 所有使用 `make_ticker()` 的测试文件必须添加 `iv_momentum=None` 默认值

---

### 3.4 Scanners 扩展 (`src/scanners.py`)

#### 扫描器 1: `scan_iv_momentum()`

**函数签名**:
```python
def scan_iv_momentum(
    data: List[TickerData],
    threshold: float = 30.0
) -> List[TickerData]
```

**筛选条件**:
```python
t.iv_momentum is not None and t.iv_momentum > threshold
```

**输出排序**: 按 `iv_momentum` 降序

**边界规则**:
- `iv_momentum = None`: 跳过
- `iv_momentum = 30.0` (边界值): 不触发 (必须 >)

#### 扫描器 2: `scan_earnings_gap()`

**函数签名**:
```python
def scan_earnings_gap(
    data: List[TickerData],
    provider: MarketDataProvider,
    days_threshold: int = 3,
) -> List[EarningsGap]
```

**触发条件**:
```python
t.days_to_earnings is not None and t.days_to_earnings <= days_threshold
```

**流程**:
1. 筛选临近财报的标的
2. 跳过 CN/HK 市场 (`should_skip_options()`)
3. 获取历史财报日期 (带 fallback)
4. 抓取历史价格 (3年数据)
5. 验证价格数据质量
6. 计算 Gap 统计

**错误隔离**:
- 单个 ticker 失败: `try-except` 捕获,记录 warning,继续下一个

---

### 3.5 报告输出 (`src/report.py` + `src/html_report.py`)

#### Text Report 新增 Section

**Section 1: 波动率异动雷达**
```
── 波动率异动雷达 (5日IV动量) ──────────────────────

  NVDA     IV动量: +45.2%  IV Rank: 72.3%  │ 财报: 2天
  TSLA     IV动量: +38.1%  IV Rank: 68.5%  │ 财报: 无

```

**Section 2: 财报 Gap 预警**
```
── 财报 Gap 预警 ─────────────────────────────────

  ⚠️ AAPL 财报还有 2天
     历史平均 Gap ±4.2%  |  上涨概率 62.5%  |  历史最大跳空 -8.1%
     当前 IV Rank: 85.3%  (样本数: 6)
     🔥 高 IV (85.3%) + 临近财报 → IV Crush 风险!

```

**风险标注逻辑**:
```python
if iv_rank > 70 and days_to_earnings <= 3:
    print("🔥 高 IV + 临近财报 → IV Crush 风险!")
```

#### HTML Report 新增卡片

**IV Momentum Card**:
- 表格: Ticker | IV动量 | IV Rank | 财报
- 样式: 沿用现有 Apple 风格

**Earnings Gap Card**:
- 表格: Ticker | Gap统计 | 最大跳空 | IV Rank
- 风险标注: `<span class="risk-badge">高IV风险</span>`

**CSS 新增**:
```css
.risk-badge {
    background: #ff3b30;
    color: white;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.85em;
}
```

---

### 3.6 配置扩展 (`config.yaml`)

```yaml
data:
  iv_history_db: "data/iv_history.db"
  price_period: "1y"
  earnings_csv_path: "data/earnings_calendar.csv"  # 新增

scanners:
  iv_momentum_threshold: 30     # 新增: 5日IV涨幅触发阈值(%)
  earnings_gap_days: 3          # 新增: 距财报N天内触发Gap分析
  earnings_lookback: 8          # 新增: 历史财报回溯次数
```

---

## 四、错误处理策略

### 4.1 分层错误隔离

**Level 1: Ticker 级别**
- 单个 ticker 失败不影响整体扫描
- 失败原因记录到 `skipped: List[Tuple[ticker, reason]]`

**Level 2: 指标级别**
- `iv_momentum` 计算失败 → 设为 `None`, TickerData 仍返回
- 其他指标不受影响

**Level 3: 数据源降级**
- yfinance 失败 → 本地 CSV
- 本地 CSV 失败 → 返回空列表

### 4.2 数据质量门控

**Gate 1: 价格数据验证**
```python
if not validate_price_df(price_df, ticker):
    return None  # 拒绝脏数据
```

**Gate 2: IV 数据充足性**
```python
sufficiency = iv_store.get_data_sufficiency(ticker)
if not sufficiency["sufficient_for_momentum"]:
    return None
```

**Gate 3: 样本数阈值**
```python
if len(gaps) < min_samples:
    return None
```

### 4.3 超时策略

- yfinance 调用设置 `timeout=10` 秒
- 单次失败直接降级,不重试 (避免阻塞定时任务)

---

## 五、TDD 测试策略

### 5.1 测试覆盖要求

| 模块 | 测试文件 | 最低用例数 |
|------|---------|-----------|
| `iv_store.py` | `test_iv_store.py` | +6 (新方法) |
| `data_engine.py` | `test_data_engine.py` | +10 (验证+Gap计算) |
| `market_data.py` | `test_market_data.py` | +4 (fallback+momentum) |
| `scanners.py` | `test_scanners.py` | +6 (两个扫描器) |
| `report.py` | `test_report.py` | +4 (两个section) |
| `main.py` | `test_integration.py` | +1 (端到端) |

### 5.2 关键测试用例

**`test_iv_store.py`**:
- ✅ 精确匹配 5 天前数据
- ✅ 窗口容差 (5-8 天)
- ✅ 无数据返回 None
- ✅ 数据太新返回 None
- ✅ 充足性检查 (30天/5天阈值)

**`test_data_engine.py`**:
- ✅ `validate_price_df()`: 正常数据通过
- ✅ `validate_price_df()`: 空 DataFrame 拒绝
- ✅ `validate_price_df()`: 负价格拒绝
- ✅ `validate_price_df()`: 高 NaN 占比拒绝
- ✅ `compute_earnings_gaps()`: 基础 Gap 计算
- ✅ `compute_earnings_gaps()`: 样本不足返回 None
- ✅ `compute_earnings_gaps()`: 跳过缺失日期

**`test_scanners.py`**:
- ✅ `scan_iv_momentum()`: 高动量被筛选
- ✅ `scan_iv_momentum()`: 边界值不触发
- ✅ `scan_iv_momentum()`: None 被跳过
- ✅ `scan_iv_momentum()`: 降序排列
- ✅ `scan_earnings_gap()`: 临近财报触发
- ✅ `scan_earnings_gap()`: 超过阈值跳过

### 5.3 Mock 策略

- **yfinance API**: 使用 `@patch("src.market_data.yf.Ticker")`
- **IVStore**: 使用 `MagicMock()` 模拟数据库
- **时间敏感逻辑**: 通过 `reference_date` 参数注入固定日期

### 5.4 TDD 工作流

```
RED (测试失败) → GREEN (最小实现) → REFACTOR (重构) → COMMIT
```

**强制规则**:
- ❌ 禁止在 RED 状态下写实现代码
- ❌ 禁止在测试未通过时提交
- ✅ 每个新功能必须先有失败的测试

---

## 六、金融数据完整性处理

### 6.1 复权调整 (Adjusted Prices)

**现状**: yfinance 默认返回复权后价格 (Adjusted Close)

**验证**:
- MA200/RSI 计算基于 `df["Close"]` (已复权)
- Gap 计算使用 `df["Open"]` / `df["Close"]` (已复权)

**无需额外处理**: yfinance 自动处理分红/拆股调整

### 6.2 多市场时差

**处理策略**:
- 财报日期统一使用 `date` 类型 (不含时区)
- Gap 计算使用自然日差值,不涉及时区转换
- US/HK/CN 市场的价格数据来自各自交易所,无需时区调整

### 6.3 股息影响

**已处理**:
- 技术指标 (MA/RSI): 基于复权价,已包含股息影响
- IV Rank: 期权隐含波动率,不受股息影响

**未来扩展**:
- 如需 Total Return 计算,需显式处理分红再投资

---

## 七、实施计划入口

完成本设计文档后,将调用 `superpowers:writing-plans` 技能,生成详细的 TDD 实施计划。

**预计任务数**: 10-12 个任务
**预计工期**: 4-5 天
**验收标准**: 所有测试 100% 通过,报告输出正确

---

## 八、未来扩展路径 (Phase 2.2+)

本设计为未来升级预留了扩展点:

1. **盘前/盘后精细化 Gap 计算**:
   - `earnings_calendar.csv` 已预留 `time_type` 字段
   - 可根据 AMC/BMO 调整计算公式

2. **多源财报数据聚合**:
   - 增加 SEC Calendar 爬虫
   - 三源融合: yfinance + CSV + SEC

3. **IV 数据质量评分**:
   - 评估历史 IV 的连续性
   - 标注"高质量"vs"低质量"数据

4. **自适应阈值**:
   - 根据市场整体波动率动态调整 `iv_momentum_threshold`

---

**设计完成日期**: 2026-02-27
**下一步**: 生成实施计划 (TDD Task List)
