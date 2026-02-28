# Scanners Specification

**Module**: `src/scanners.py`

**Purpose**: 扫描器逻辑规则（Phase 1 + Phase 2）

---

## Architecture

```
List[TickerData] → Scanner Functions → Filtered Results
                         ↓
                  纯函数设计（无副作用）
```

---

## Phase 1 Scanners

### 1. scan_iv_extremes()

```python
def scan_iv_extremes(
    data: List[TickerData],
    low_threshold: float = 20.0,
    high_threshold: float = 80.0
) -> Tuple[List[TickerData], List[TickerData]]
```

**逻辑**:
- **低波动率**: IV Rank < 20%
- **高波动率**: IV Rank > 80%

**返回**: `(low_iv_list, high_iv_list)`

**排序**: 低 IV 升序，高 IV 降序

**边界条件**:
- `iv_rank is None` → 跳过

---

### 2. scan_ma200_crossover()

```python
def scan_ma200_crossover(
    data: List[TickerData],
    tolerance: float = 0.01
) -> Tuple[List[TickerData], List[TickerData]]
```

**逻辑**:
- **向上突破**: MA200 ≤ Last Price ≤ MA200 × 1.01
- **向下跌破**: MA200 × 0.99 ≤ Last Price ≤ MA200

**返回**: `(bullish_list, bearish_list)`

**排序**: 按 ticker 字母序

**边界条件**:
- `ma200 is None` → 跳过

---

### 3. scan_leaps_setup()

```python
def scan_leaps_setup(
    data: List[TickerData]
) -> List[TickerData]
```

**逻辑** (4 个条件全部满足):
1. Price > MA200 (上升趋势)
2. |Price - MA50w| / MA50w < 10% (接近周线 MA)
3. RSI14 < 70 (未超买)
4. IV Rank < 50 (波动率不高)

**排序**: 按 ticker 字母序

**边界条件**:
- 任一指标为 `None` → 跳过

---

### 4. scan_sell_put()

```python
@dataclass
class SellPutSignal:
    ticker_data: TickerData
    strike: float
    dte: int
    bid: float
    apy: float
    earnings_risk: bool

def scan_sell_put(
    ticker_data: TickerData,
    provider: MarketDataProvider,
    target_dte: int = 45,
    min_apy: float = 15.0
) -> Optional[SellPutSignal]
```

**逻辑**:
1. 获取期权链（ATM 附近，DTE ≈ 45 天）
2. 选择最接近当前价 0.9 倍的行权价
3. 计算 APY: `(Bid / Strike) × (365 / DTE) × 100`
4. 检查财报风险: `earnings_date` 在 DTE 窗口内

**返回**: 单个最优信号 或 `None`

**财报风险标记**:
- `days_to_earnings ≤ dte` → `earnings_risk = True`

**边界条件**:
- 期权链为空 → 返回 `None`
- APY < min_apy → 返回 `None`
- CN/HK 市场 → 跳过（无期权）

---

## Phase 2 Scanners

### 5. scan_iv_momentum()

```python
def scan_iv_momentum(
    data: List[TickerData],
    threshold: float = 30.0
) -> List[TickerData]
```

**逻辑**:
- IV 动量 > 30% (5 日 IV 上升超过 30%)

**公式**:
```
IV_Momentum = (Current_IV - IV_5d_ago) / IV_5d_ago × 100
```

**排序**: 按 IV 动量降序

**边界条件**:
- `iv_momentum is None` → 跳过

---

### 6. scan_earnings_gap()

```python
def scan_earnings_gap(
    data: List[TickerData],
    provider: MarketDataProvider,
    days_threshold: int = 3,
    lookback: int = 8
) -> List[EarningsGap]
```

**逻辑**:
1. 筛选 `days_to_earnings ≤ 3` 的标的
2. 获取历史 8 次财报日期
3. 计算每次财报的 Gap%
4. 返回所有 Gap 数据

**排序**: 按财报日期降序（最新在前）

**边界条件**:
- `earnings_date is None` → 跳过
- CN 市场 → 跳过（无可靠财报数据）

---

## Integration Points

**← data_engine.py**: 接收 `List[TickerData]`
**← market_data.py**: 获取期权链数据（Sell Put）
**→ report.py**: 提供扫描结果用于战报生成
**→ main.py**: 统一调度所有扫描器

---

## Configuration (config.yaml)

```yaml
scanners:
  iv_low_threshold: 20
  iv_high_threshold: 80
  ma200_tolerance: 0.01
  sell_put_target_dte: 45
  sell_put_min_apy: 15
  iv_momentum_threshold: 30      # Phase 2
  earnings_gap_days: 3           # Phase 2
  earnings_lookback: 8           # Phase 2
```

---

## Testing

**Test File**: `tests/test_scanners.py`

**Coverage**:
- 边界条件（None 值处理）
- 排序逻辑
- 财报风险标记
- 阈值可配置性
- Phase 2 新扫描器

---

## Design Principles

1. **纯函数**: 所有扫描器无副作用
2. **防御性**: 处理所有 `None` 值
3. **可测试**: 无外部依赖（除 MarketDataProvider）
4. **可配置**: 所有阈值通过参数传入
