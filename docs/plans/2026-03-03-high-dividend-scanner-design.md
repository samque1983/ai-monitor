# 高股息防御双打 - 设计文档

**Feature**: Phase 2 - 高股息防御双打扫描器
**Date**: 2026-03-03
**Status**: Design Approved
**Approach**: Financial Service深度集成方案

---

## 1. 产品目标

实现"场景4：高股息防御双打"策略，提供**现货底仓 + 卖浅虚值Put**的组合机会监控。

**核心价值**：
- 每周筛选高质量股息股票池（评估稳定性、永续性）
- 每日监控池中标的的买入时机（股息率历史高点触发）
- 双重现金流：股息收入 + 期权权利金（综合年化目标11.7%）

**风险控制**：
- 派息率 > 100% 时AI立即报警（硬性止损规则）
- 六维度评估卡片，30秒看懂完整风险

---

## 2. 架构设计

### 2.1 模块层级（遵循GLOBAL_MASTER依赖规则）

```
main.py
  ↓
dividend_report.py (新增，HTML卡片渲染) 或扩展 html_report.py
  ↓
dividend_scanners.py (新增，两个扫描器)
  ↓
financial_service.py (新增，封装Financial Analysis)
  ↓
dividend_store.py (新增，SQLite存储池子)
  ↓
market_data.py (扩展，获取股息历史数据)
```

**依赖关系**：
- 上层可导入下层，下层禁止导入上层
- 同层模块禁止互相导入
- 使用`TYPE_CHECKING`解决类型提示的循环依赖

### 2.2 核心新增模块

#### financial_service.py
**职责**：封装Claude Financial Analysis能力，提供专业级基本面分析

**核心接口**：
```python
@dataclass
class DividendQualityScore:
    overall_score: float         # 综合评分 (0-100)
    stability_score: float       # 派息稳定性 (连续性 + 增长率)
    health_score: float          # 财务健康度 (ROE + 负债 + FCF)
    defensiveness_score: float   # 行业防御性 (公用事业/消费/医疗优先)
    risk_flags: List[str]        # 风险标记 ["HIGH_PAYOUT_RISK", ...]

class FinancialServiceAnalyzer:
    def analyze_dividend_quality(
        self,
        ticker: str,
        fundamentals: Dict[str, Any]
    ) -> DividendQualityScore:
        """
        使用Claude Financial Service分析股息质量

        输入fundamentals包含:
        - dividend_history: List[{date, amount}]
        - payout_ratio, roe, debt_to_equity
        - industry, sector
        - free_cash_flow

        输出:
        - 三维评分（稳定性、财务健康、行业防御性）
        - 综合评分（加权平均）
        - 风险标记
        """
```

**降级策略**（Financial Service不可用时）：
```python
def _calculate_rule_based_score(fundamentals) -> DividendQualityScore:
    """规则化评分降级方案"""
    stability_score = f(consecutive_years, dividend_growth)
    health_score = f(roe, debt_to_equity, payout_ratio)
    defensiveness_score = 50  # 无行业分析时固定50分
```

---

#### dividend_store.py
**职责**：SQLite存储股票池、历史股息数据、筛选版本

**表结构**：

```sql
-- 股票池表（每周更新）
CREATE TABLE dividend_pool (
    ticker TEXT PRIMARY KEY,
    name TEXT,
    market TEXT,
    quality_score REAL,
    consecutive_years INTEGER,
    dividend_growth_5y REAL,
    payout_ratio REAL,
    roe REAL,
    debt_to_equity REAL,
    industry TEXT,
    added_date DATE,
    version TEXT  -- 'weekly_2026-03-03'
);

-- 历史股息表（用于计算分位数）
CREATE TABLE dividend_history (
    ticker TEXT,
    date DATE,
    dividend_yield REAL,
    annual_dividend REAL,
    price REAL,
    PRIMARY KEY (ticker, date)
);

-- 筛选版本表（版本管理）
CREATE TABLE screening_versions (
    version TEXT PRIMARY KEY,
    created_at TIMESTAMP,
    tickers_count INTEGER,
    avg_quality_score REAL
);
```

**核心接口**：
```python
class DividendStore:
    def save_pool(self, tickers: List[TickerData], version: str)
    def get_current_pool(self) -> List[str]
    def save_dividend_history(self, ticker: str, date: date, yield: float, ...)
    def get_yield_percentile(self, ticker: str, current_yield: float) -> float
    def get_pool_summary(self) -> Dict[str, Any]  # UI概览数据
```

---

#### dividend_scanners.py
**职责**：实现两个核心扫描器（每周筛选 + 每日监控）

**扫描器1：每周筛选**
```python
def scan_dividend_pool_weekly(
    universe: List[str],
    provider: MarketDataProvider,
    financial_service: FinancialServiceAnalyzer,
    config: Dict
) -> List[TickerData]:
    """
    每周筛选高质量股息股票池

    流程:
    1. 遍历universe，获取基本面数据（5年股息历史、财务指标）
    2. 调用Financial Service分析股息质量
    3. 应用筛选规则:
       - quality_score >= 70
       - consecutive_years >= 5
       - payout_ratio < 100 (硬性上限)
       - roe >= 10, debt_to_equity <= 1.5
    4. 返回符合条件的TickerData列表

    返回:
        符合条件的TickerData列表（扩展字段已填充）
    """
```

**扫描器2：每日监控**
```python
@dataclass
class DividendBuySignal:
    ticker_data: TickerData
    signal_type: str  # "STOCK" | "OPTION"
    current_yield: float
    yield_percentile: float  # 5年历史分位数
    option_details: Optional[SellPutSignal]  # 期权策略详情

def scan_dividend_buy_signal(
    pool: List[str],
    provider: MarketDataProvider,
    store: DividendStore,
    config: Dict
) -> List[DividendBuySignal]:
    """
    每日监控买入时机

    流程:
    1. 从DividendStore读取当前池子
    2. 获取实时价格和股息率
    3. 计算5年历史分位数
    4. 判断触发条件:
       现货信号:
         - dividend_yield >= 4%
         - dividend_yield_5y_percentile >= 90% (前10%最高)

       期权信号（仅US市场）:
         - 调用scan_dividend_sell_put()
         - strike选择让股息率达到90th percentile
         - DTE: 45-90天
    5. 返回买入信号列表
    """
```

**期权策略扫描器**（独立新策略）：
```python
def scan_dividend_sell_put(
    ticker_data: TickerData,
    provider: MarketDataProvider,
    target_yield_percentile: float,
    min_dte: int = 45,
    max_dte: int = 90
) -> Optional[SellPutSignal]:
    """
    高股息场景的Sell Put策略（独立于现有scan_sell_put）

    核心差异:
    - strike选择逻辑: 选择能让股息率达到target_yield_percentile的strike
    - 不关注APY阈值，关注股息率历史分位数

    示例:
        当前价$34.5, 年股息$2.35, 当前股息率6.8%
        目标: 股息率达到7.3% (90th percentile)
        反推strike: $2.35 / 0.073 = $32.19
        选择最接近的期权: $32 Put, 60DTE, Bid $0.45
    """
```

---

#### dividend_report.py（或扩展html_report.py）
**职责**：渲染六维度评估卡片，集成到现有HTML报告

**核心功能**：
- 池子概览（当前标的数、最近更新时间）
- 买入信号卡片（六维度评估）
- 完整池子查看功能

---

### 2.3 TickerData扩展

```python
@dataclass
class TickerData:
    # ... 现有字段 ...

    # Phase 2 高股息新增字段（全部Optional）
    dividend_yield: Optional[float]                # 当前股息率
    dividend_yield_5y_percentile: Optional[float]  # 5年历史分位数
    dividend_quality_score: Optional[float]        # 综合评分 (0-100)
    consecutive_years: Optional[int]               # 连续派息年限
    dividend_growth_5y: Optional[float]            # 5年股息复合增长率 (CAGR)
    payout_ratio: Optional[float]                  # 派息率 (%)
    roe: Optional[float]                           # ROE (%)
    debt_to_equity: Optional[float]                # 负债率
    industry: Optional[str]                        # 行业分类
    sector: Optional[str]                          # 行业板块
    free_cash_flow: Optional[float]                # 自由现金流
```

**扩展规则**（遵循GLOBAL_MASTER）：
- 所有新增字段必须是`Optional`类型
- 更新后同步修改所有测试的`make_ticker()` helper

---

## 3. 数据流设计

### 3.1 每周筛选流程

```
Universe CSV → data_loader.load_universe()
  ↓
MarketDataProvider.get_fundamentals(ticker)
  ├─ yfinance.Ticker.dividends (5年历史)
  ├─ yfinance.Ticker.info (payoutRatio, trailingROE, debtToEquity, industry)
  └─ 计算: consecutive_years, dividend_growth_5y
  ↓
FinancialServiceAnalyzer.analyze_dividend_quality()
  输入: {ticker, fundamentals_json}
  输出: DividendQualityScore {overall: 85, stability: 90, health: 80, defensiveness: 85}
  ↓
应用筛选规则:
  ✓ quality_score >= 70
  ✓ consecutive_years >= 5
  ✓ payout_ratio < 100 (硬性)
  ✓ roe >= 10
  ✓ debt_to_equity <= 1.5
  ↓
DividendStore.save_pool(filtered_tickers, version='weekly_2026-03-03')
  ├─ 更新dividend_pool表
  ├─ 记录screening_versions
  └─ 保存dividend_history（用于分位数计算）
```

### 3.2 每日监控流程

```
DividendStore.get_current_pool() → List[ticker]
  ↓
For each ticker:
  MarketDataProvider.get_price_data() → last_price
  计算: current_yield = annual_dividend / last_price
  ↓
  DividendStore.get_yield_percentile(ticker, current_yield)
    → 从dividend_history表计算分位数
  ↓
  判断触发条件:
    现货信号:
      current_yield >= 4% AND yield_percentile >= 90%

    期权信号 (仅US市场):
      调用scan_dividend_sell_put(ticker, target_percentile=90)
      → 返回SellPutSignal (strike, dte, bid, apy)
  ↓
返回 List[DividendBuySignal]
  ↓
HTML Report渲染六维度卡片
```

---

## 4. 错误处理与韧性

### 4.1 Financial Service调用失败

**策略**：降级到规则化评分

```python
try:
    quality_score = financial_service.analyze_dividend_quality(ticker, fundamentals)
except FinancialServiceError as e:
    logger.warning(f"{ticker}: Financial Service unavailable, using fallback scoring")
    quality_score = _calculate_rule_based_score(fundamentals)
```

**降级评分规则**：
```python
def _calculate_rule_based_score(fundamentals):
    stability_score = (
        consecutive_years * 10 +  # 每年+10分
        min(dividend_growth_5y * 2, 30)  # 增长率，最多30分
    )

    health_score = (
        min(roe, 30) +  # ROE最多30分
        max(0, 30 - debt_to_equity * 20) +  # 负债率惩罚
        (40 if payout_ratio < 70 else 20)  # 派息率健康度
    )

    defensiveness_score = 50  # 无行业分析，固定50分

    overall = (stability_score * 0.4 + health_score * 0.4 + defensiveness_score * 0.2)
```

### 4.2 数据获取失败隔离

**yfinance股息数据缺失**：
```python
dividend_history = ticker.dividends
if dividend_history is None or len(dividend_history) < 12:  # <1年数据
    logger.warning(f"{ticker}: Insufficient dividend history (<1 year), skip")
    return None  # 不加入池子
```

**财务指标部分缺失**：
- `payout_ratio`缺失 → 使用`dividend / EPS`估算
- `roe`缺失 → health_score降权（仅用负债率 + payout_ratio）
- 超过2个核心指标缺失 → 跳过该ticker

### 4.3 派息率风险预警（硬性规则）

```python
if payout_ratio > 100:
    logger.error(f"⚠️ {ticker}: Payout Ratio {payout_ratio}% > 100%, EXCLUDE FROM POOL")
    return None  # 立即排除

if payout_ratio > 80:
    # 加入池子但标记高风险
    risk_flags.append("HIGH_PAYOUT_RISK")
    logger.warning(f"{ticker}: Payout Ratio {payout_ratio}% > 80%, flagged as high risk")
```

### 4.4 市场差异化处理

**CN/HK市场（无期权）**：
```python
if market_data.should_skip_options(ticker):
    # 仅生成现货买入信号
    option_signal = None
else:
    # US市场生成期权信号
    option_signal = scan_dividend_sell_put(ticker_data, provider, config)
```

---

## 5. UI设计：六维度评估卡片

### 5.1 HTML报告集成

**新增章节**（在`html_report.py`或新建`dividend_report.py`）：

```html
<section class="dividend-defense">
    <h2>高股息防御双打</h2>

    <!-- 池子概览 -->
    <div class="pool-summary">
        <p>当前池子: <strong>23只标的</strong> | 最近更新: <strong>2026-03-03</strong></p>
        <button onclick="showFullPool()">查看完整池子</button>
    </div>

    <!-- 买入信号卡片列表 -->
    <div class="buy-signals">
        <!-- 每个信号一张卡片 -->
    </div>
</section>
```

### 5.2 单卡片结构（六维度）

**设计原则**：30秒看懂，信息一次性整合

```
┌─────────────────────────────────────────────────┐
│ ENB (安桥能源)                     🛡️ 防御型     │
│ 当前股息率: 6.8% (5年历史前10%最高分位)          │
├─────────────────────────────────────────────────┤
│ 1️⃣ 基本面估值                                    │
│   铁底区间: $32-35  |  公允价: $38-42            │
│   当前价: $34.5 ✓ 接近铁底                       │
├─────────────────────────────────────────────────┤
│ 2️⃣ 风险分级 ★★☆☆☆ (综合评分: 85/100)            │
│   业务风险: 低 (管道垄断，稳定现金流)            │
│   地缘风险: 中 (美加政策影响)                    │
│   竞争风险: 低 (高准入壁垒)                      │
│   ⚠️ 派息率: 78% (接近80%警戒线)                 │
├─────────────────────────────────────────────────┤
│ 3️⃣ 关键事件                                      │
│   下次财报: 2026-05-12 (69天后)                 │
│   历史财报跳空: ±3% (温和波动)                   │
├─────────────────────────────────────────────────┤
│ 4️⃣ 建议操作                                      │
│   📈 现货买入: $34.5 (股息率6.8%)                │
│   📊 期权策略: Sell Put $33 Strike (60DTE)      │
│       Premium: $0.45 → 年化8.2%                 │
│       综合年化收益: 15.0% (股息6.8% + 期权8.2%)  │
├─────────────────────────────────────────────────┤
│ 5️⃣ 最坏情景测算                                  │
│   期权被行权成本: $32.55 ($33 - $0.45)          │
│   此时股息率: 7.3% (历史前5%最高)                │
│   最大亏损触发点: 需跌破$30 (-13%)               │
│   仓位建议: 不超过总仓位10%                      │
├─────────────────────────────────────────────────┤
│ 6️⃣ AI监控承诺                                    │
│   ✓ 派息率>100%时立即预警                        │
│   ✓ 财报前7天提醒                                │
│   ✓ 股息率回落至中位数时提示                     │
│   ✓ 期权到期前5天通知                            │
└─────────────────────────────────────────────────┘
```

### 5.3 数据来源映射

| 卡片维度 | 数据来源 | 实现方式 |
|---------|---------|---------|
| 基本面估值 | Financial Service | DCF/Comps分析（调用financial-analysis技能） |
| 风险分级 | Financial Service + 手动配置 | 行业分析 + quality_score分解展示 + risk_flags |
| 关键事件 | earnings_date (现有) | 复用现有数据 + 历史Gap统计 |
| 建议操作 | scan_dividend_buy_signal() | 输出DividendBuySignal结构 |
| 最坏情景 | 计算逻辑 | strike - premium, 股息率回测 |
| AI监控 | 配置化规则 | config.yaml定义监控规则列表 |

### 5.4 Apple风格CSS

```css
.dividend-defense .buy-signals {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
    gap: 20px;
}

.dividend-card {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    border-radius: 16px;
    padding: 24px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.2);
}

.dividend-card .dimension {
    margin: 16px 0;
    padding: 12px;
    background: rgba(255,255,255,0.1);
    border-radius: 8px;
}
```

---

## 6. 配置扩展（config.yaml）

```yaml
scanners:
  # ... 现有配置 ...

  # 高股息防御双打配置
  dividend:
    enabled: true  # 总开关

    # 每周筛选标准
    screening:
      min_quality_score: 70
      min_consecutive_years: 5
      max_payout_ratio: 100  # 硬性上限
      min_roe: 10
      max_debt_to_equity: 1.5

    # 每日监控触发条件
    buy_signal:
      min_yield: 4.0  # 最低股息率4%
      min_yield_percentile: 90  # 5年历史前10%

      # 期权策略（仅US市场）
      option:
        min_dte: 45
        max_dte: 90
        target_strike_percentile: 90  # strike对应股息率分位数

    # 风险预警阈值
    alerts:
      payout_ratio_warning: 80   # 黄色警告
      payout_ratio_critical: 100 # 红色警告，排除池子

data:
  # ... 现有配置 ...
  dividend_db_path: "data/dividend_pool.db"

  # Financial Service配置
  financial_service:
    enabled: true
    fallback_to_rules: true  # 服务不可用时降级到规则评分
    timeout: 30  # API超时（秒）
```

---

## 7. 测试策略

### 7.1 Mirror Testing（遵循GLOBAL_MASTER规范）

**新增测试文件**：
- `tests/test_financial_service.py` ← Financial Service集成测试
- `tests/test_dividend_store.py` ← SQLite存储测试
- `tests/test_dividend_scanners.py` ← 两个扫描器逻辑测试
- `tests/test_dividend_report.py` ← HTML卡片渲染测试

### 7.2 Mock策略

**Mock Financial Service**：
```python
@patch('src.financial_service.FinancialServiceAnalyzer')
def test_weekly_scan_with_mocked_service(mock_service):
    mock_service.analyze_dividend_quality.return_value = DividendQualityScore(
        overall_score=85,
        stability_score=90,
        health_score=80,
        defensiveness_score=85,
        risk_flags=[]
    )
    # 测试筛选逻辑
    result = scan_dividend_pool_weekly(universe, provider, mock_service, config)
    assert len(result) > 0
```

**Mock yfinance股息数据**：
```python
@patch('yfinance.Ticker')
def test_dividend_history_fetch(mock_ticker):
    mock_ticker.return_value.dividends = pd.Series({
        pd.Timestamp('2020-03-01'): 0.50,
        pd.Timestamp('2021-03-01'): 0.52,
        pd.Timestamp('2022-03-01'): 0.54,
        pd.Timestamp('2023-03-01'): 0.57,
        pd.Timestamp('2024-03-01'): 0.60,
        pd.Timestamp('2025-03-01'): 0.63,
    })
    # 测试consecutive_years和dividend_growth计算
```

### 7.3 TDD关键测试用例

**测试优先级**（必须RED → GREEN）：

1. **派息率>100%硬性排除**
   ```python
   def test_payout_ratio_over_100_excluded():
       ticker_data = make_ticker(payout_ratio=105)
       result = scan_dividend_pool_weekly([ticker_data], ...)
       assert ticker_data.ticker not in result
   ```

2. **5年历史分位数计算准确性**
   ```python
   def test_yield_percentile_calculation():
       # 准备5年数据: yields = [3%, 4%, 5%, 6%, 7%]
       store.save_dividend_history(...)
       percentile = store.get_yield_percentile('AAPL', current_yield=6.8)
       assert percentile >= 90  # 6.8%应该在前10%
   ```

3. **Financial Service降级逻辑**
   ```python
   def test_fallback_when_service_unavailable():
       with patch('financial_service.analyze_dividend_quality', side_effect=Exception):
           result = scan_dividend_pool_weekly(...)
           # 应该使用规则评分，不应该crash
           assert result is not None
   ```

4. **CN/HK市场跳过期权信号**
   ```python
   def test_hk_market_no_option_signal():
       ticker_data = make_ticker(ticker='00700', market='HK')
       signals = scan_dividend_buy_signal([ticker_data], ...)
       assert all(s.option_details is None for s in signals)
   ```

5. **DividendStore版本管理**
   ```python
   def test_weekly_version_not_overwrite():
       store.save_pool(tickers_v1, version='weekly_2026-03-03')
       store.save_pool(tickers_v2, version='weekly_2026-03-10')
       # 两个版本都应该存在
       versions = store.get_all_versions()
       assert len(versions) == 2
   ```

---

## 8. 工作流触发方式

**配置化手动运行**（用户选择）：

```python
# main.py 扩展
def main():
    config = load_config()

    if config['scanners']['dividend']['enabled']:
        # 每周筛选（手动运行）
        if args.mode == 'dividend_screening':
            logger.info("Running weekly dividend pool screening...")
            pool = scan_dividend_pool_weekly(universe, provider, financial_service, config)
            store.save_pool(pool, version=f"weekly_{date.today()}")

        # 每日监控（手动运行）
        if args.mode == 'dividend_monitor':
            logger.info("Monitoring dividend buy signals...")
            signals = scan_dividend_buy_signal(store.get_current_pool(), provider, store, config)
            # 添加到HTML报告
```

**命令行参数**：
```bash
# 每周筛选池子
python -m src.main --mode dividend_screening

# 每日监控买入机会
python -m src.main --mode dividend_monitor

# 完整运行（现有扫描器 + 股息监控）
python -m src.main --mode all
```

---

## 9. 实施路线图

### Phase 1: 数据基础设施（Week 1）
- [ ] `market_data.py`扩展：获取股息历史、财务指标
- [ ] `dividend_store.py`：SQLite表结构、核心CRUD
- [ ] 单元测试：Mock yfinance数据

### Phase 2: Financial Service集成（Week 2）
- [ ] `financial_service.py`：封装Financial Analysis调用
- [ ] 降级逻辑：规则化评分
- [ ] 单元测试：Mock Financial Service

### Phase 3: 扫描器逻辑（Week 3）
- [ ] `dividend_scanners.py`：两个扫描器实现
- [ ] `scan_dividend_sell_put()`：期权策略
- [ ] 单元测试：筛选规则、分位数计算

### Phase 4: UI集成（Week 4）
- [ ] `dividend_report.py`或扩展`html_report.py`
- [ ] 六维度卡片渲染
- [ ] CSS样式（Apple风格）

### Phase 5: 集成测试与文档（Week 5）
- [ ] `main.py`集成
- [ ] 端到端测试
- [ ] 更新`docs/specs/scanners.md`
- [ ] 删除本plan文档

---

## 10. 风险与依赖

**技术风险**：
- Financial Service API稳定性 → 已设计降级方案
- yfinance股息数据质量 → 需验证A股/港股数据充分性

**数据依赖**：
- yfinance提供5年股息历史（US/HK可靠，CN需验证）
- yfinance财务指标（payoutRatio, trailingROE, debtToEquity）

**外部依赖**：
- Claude Financial Service Plugin（financial-analysis技能组）

---

## 11. 成功标准

**功能完整性**：
- ✅ 每周筛选输出20-30只高质量股息股
- ✅ 每日监控触发3-5个买入信号（股息率历史高点）
- ✅ CN/HK市场正确跳过期权信号
- ✅ 派息率>100%立即排除并报警

**用户体验**：
- ✅ HTML卡片30秒内看懂所有关键信息
- ✅ 六维度评估数据完整、准确
- ✅ Apple风格美观、易读

**代码质量**：
- ✅ 所有测试100%通过（pytest）
- ✅ 遵循GLOBAL_MASTER架构规则
- ✅ Mirror Testing覆盖所有新模块

---

**设计文档结束** | 待实施
