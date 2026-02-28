# Technical Indicators Specification

**Module**: `src/data_engine.py`

**Purpose**: 技术指标计算引擎（MA, RSI, IV Rank, Earnings Gap）

---

## Architecture

```
MarketDataProvider → data_engine → TickerData
                         ↓
                  独立指标函数（纯函数设计）
```

---

## Core Data Model

### TickerData (Central Data Class)

```python
@dataclass
class TickerData:
    ticker: str
    name: str
    market: str                    # "US" | "HK" | "CN"
    last_price: float
    ma200: Optional[float]
    ma50w: Optional[float]
    rsi14: Optional[float]
    iv_rank: Optional[float]
    prev_close: float
    earnings_date: Optional[date]
    days_to_earnings: Optional[int]
    iv_momentum: Optional[float]   # Phase 2
```

**扩展规则**（GLOBAL_MASTER.md 第 I.2 章）:
- 新字段必须是 `Optional` 类型
- 禁止修改现有字段类型
- 所有新增字段追加到末尾

---

## Indicator Functions

### 1. compute_ma200()

```python
def compute_ma200(daily_df: pd.DataFrame) -> Optional[float]
```

**算法**:
- 输入: 日线 OHLCV DataFrame
- 输出: 200 日简单移动平均（SMA）
- 使用 `Adj Close` 列（复权价格）

**边界条件**:
- 数据不足 200 天 → 返回 `None`
- DataFrame 为空 → 返回 `None`

---

### 2. compute_ma50w()

```python
def compute_ma50w(weekly_df: pd.DataFrame) -> Optional[float]
```

**算法**:
- 输入: 周线 OHLCV DataFrame
- 输出: 50 周简单移动平均（SMA）
- 使用 `Adj Close` 列

**边界条件**:
- 数据不足 50 周 → 返回 `None`

---

### 3. compute_rsi14()

```python
def compute_rsi14(daily_df: pd.DataFrame) -> Optional[float]
```

**算法** (Wilder's RSI):
```
1. 计算每日价格变化: ΔP = Close[i] - Close[i-1]
2. 分离涨幅和跌幅:
   - Gain = ΔP if ΔP > 0 else 0
   - Loss = -ΔP if ΔP < 0 else 0
3. 计算 14 日平均涨幅/跌幅（指数移动平均）
4. RS = Avg_Gain / Avg_Loss
5. RSI = 100 - (100 / (1 + RS))
```

**边界条件**:
- 数据不足 14 天 → 返回 `None`
- 全部上涨（Loss=0）→ RSI = 100
- 全部下跌（Gain=0）→ RSI = 0

---

### 4. validate_price_df()

```python
def validate_price_df(df: pd.DataFrame) -> None
```

**数据质量检查**（GLOBAL_MASTER.md 第 III.3 章）:

1. **必需列**: `Open`, `High`, `Low`, `Close`, `Adj Close`
2. **价格合法性**: Close/Open > 0
3. **缺失值比例**: NaN < 5%

**行为**:
- 验证失败 → 抛出 `ValueError`
- 在 `build_ticker_data()` 入口调用

---

### 5. compute_earnings_gaps() (Phase 2)

```python
@dataclass
class EarningsGap:
    ticker: str
    earnings_date: date
    gap_pct: float
    prev_close: float
    earnings_open: float

def compute_earnings_gaps(
    ticker: str,
    earnings_dates: List[date],
    provider: MarketDataProvider
) -> List[EarningsGap]
```

**算法**:
```
Gap% = (Earnings_Day_Open - Prev_Day_Close) / Prev_Day_Close × 100
```

**边界条件**:
- 财报日价格数据缺失 → 跳过该日期
- Open = 0 → 跳过
- 返回按日期降序排列

---

## Main Orchestrator

### build_ticker_data()

```python
def build_ticker_data(
    ticker: str,
    provider: MarketDataProvider
) -> Optional[TickerData]
```

**流程**:
1. 获取价格数据（日线 + 周线）
2. `validate_price_df()` 验证数据质量
3. 计算所有指标（MA200, MA50w, RSI14）
4. 获取 IV Rank, Earnings Date
5. 计算 IV Momentum (Phase 2)
6. 构造 `TickerData` 对象

**错误隔离**:
- 单个指标失败 → 该字段为 `None`，其他指标继续计算
- 价格数据获取失败 → 返回 `None`（整个 ticker 跳过）

---

## Integration Points

**← market_data.py**: 接收原始价格/IV 数据
**→ scanners.py**: 提供完整 TickerData 用于扫描逻辑
**→ report.py**: 提供格式化数据用于战报生成

---

## Testing

**Test File**: `tests/test_data_engine.py`

**Coverage**:
- MA200/MA50w/RSI14 边界条件
- `validate_price_df()` 各类异常数据
- `compute_earnings_gaps()` 完整流程
- `build_ticker_data()` 错误隔离

---

## Design Principles

1. **纯函数设计**: 所有指标函数无副作用
2. **防御性编程**: 所有函数返回 `Optional[T]`
3. **单一职责**: 每个函数只计算一个指标
4. **数据验证**: 入口处强制验证数据质量
