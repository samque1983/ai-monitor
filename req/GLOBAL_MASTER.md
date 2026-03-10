# AI Options Monitor — Global Master Constitution

**Project**: AI Options Monitor (V1.9+ Quant Radar)
**Purpose**: 定时扫描期权市场,输出纯数据战报,规避人工盯盘风险
**Philosophy**: 冷峻理性、只陈述事实、零主观建议

---

## I. 架构铁律 (Architecture Rules)

### 1.1 模块依赖层级 (Import Direction)
严格单向依赖,禁止循环导入:

```
main.py
  ↓
scanners.py, report.py, html_report.py
  ↓
data_engine.py
  ↓
market_data.py
  ↓
data_loader.py, iv_store.py
```

**规则**:
- 上层可导入下层,下层禁止导入上层
- 同层模块禁止互相导入
- 使用 TYPE_CHECKING 解决类型提示的循环依赖

### 1.2 中心数据模型 (Central Data Model)
所有 Phase 必须共用 `TickerData` dataclass:

```python
@dataclass
class TickerData:
    ticker: str
    name: str
    market: str              # "US" | "HK" | "CN"
    last_price: float
    ma200: Optional[float]
    ma50w: Optional[float]
    rsi14: Optional[float]
    iv_rank: Optional[float]
    prev_close: float
    earnings_date: Optional[date]
    days_to_earnings: Optional[int]
    # Phase 2+: 新增字段追加在此
```

**扩展规则**:
- 新 Phase 可追加字段,但禁止修改现有字段类型
- 所有新增字段必须是 `Optional` 类型
- 更新后必须同步修改所有测试的 `make_ticker()` helper

### 1.3 配置权威 (Config Authority)
- **唯一配置源**: `config.yaml`
- **加载入口**: `src/config.py` 的 `load_config()` 函数
- **使用规范**:
  - 所有模块通过参数传递配置,禁止直接导入 config
  - `main.py` 负责解析 config 并分发给各模块
  - 新 Phase 的配置项追加到 `scanners:` 或 `data:` section

---

## II. 数据获取协议 (Data Acquisition Rules)

### 2.1 多市场分类 (Market Classification)
- **市场划分**: US, HK, CN (由 `data_loader.classify_market()` 判断)
- **期权限制**: CN 和 HK 市场无期权数据,所有 IV 相关指标必须返回 `None`
- **跳过策略**: `MarketDataProvider.should_skip_options(ticker)` 统一判断

### 2.2 API 调用策略 (API Fallback Chain)
优先级: **IBKR Gateway → yfinance → 本地缓存/CSV**

**规则**:
- 所有 API 调用必须包裹在 `try-except` 中
- 单个 ticker 失败时记录 warning,继续处理下一个
- 关键数据(如财报日期、历史价格)必须设计本地 Fallback 机制

### 2.3 金融数据完整性要求 (Financial Data Integrity)

**复权调整 (Adjusted Prices)**:
- 所有技术指标计算必须使用复权后价格 (Adjusted Close)
- yfinance 默认返回复权数据,无需额外处理
- IBKR 数据需验证是否为复权数据

**多市场时差处理**:
- US 市场: Eastern Time (ET)
- HK 市场: Hong Kong Time (HKT, UTC+8)
- CN 市场: China Standard Time (CST, UTC+8)
- 财报日期统一使用 `date` 类型,不处理具体时刻
- Gap 计算使用自然日差值,不涉及时区转换

**股息影响 (Dividend Impact)**:
- MA/RSI 等技术指标基于复权价,已包含股息影响
- IV Rank 不受股息影响(期权隐含波动率)
- 未来如需 Total Return 计算,需显式处理分红再投资

---

## III. 错误隔离与韧性 (Error Isolation & Resilience)

### 3.1 单点故障隔离
**原则**: 一只股票的数据获取失败,不得中断整个扫描流程。

**实现**:
- `build_ticker_data()` 返回 `Optional[TickerData]`,失败时返回 `None`
- 主循环过滤掉 `None` 结果
- 所有失败记录到 `skipped: List[Tuple[ticker, reason]]`

### 3.2 API 熔断与降级
- yfinance 超时: 设置 `timeout` 参数,捕获 `Timeout` 异常
- 期权链为空: 返回 `None`,跳过该 ticker 的 IV 计算
- 财报日期缺失: 返回 `None`,不影响其他指标

### 3.3 数据验证 (Data Validation with data-explorer)
在进入业务逻辑前,必须执行以下验证:
- **价格合法性**: Close/Open > 0
- **时间序列完整性**: 检查 DataFrame index 是否连续
- **异常值检测**: MA/RSI 是否在合理范围 (0-100% for RSI, > 0 for MA)
- **缺失值处理**: 使用 `dropna()` 或 `fillna()`,禁止直接计算含 NaN 的数据

---

## IV. 测试驱动开发 (TDD Protocol)

### 4.1 镜像测试规则 (Mirror Testing)
每个源文件必须有对应测试文件:

| Source File | Test File |
|-------------|-----------|
| `src/data_engine.py` | `tests/test_data_engine.py` |
| `src/market_data.py` | `tests/test_market_data.py` |
| `src/scanners.py` | `tests/test_scanners.py` |

### 4.2 TDD 执行流程
1. **写测试**: 针对新功能写 pytest 用例,运行确认 FAIL (RED)
2. **写实现**: 编写最小实现代码
3. **验证通过**: 运行测试确认 PASS (GREEN)
4. **重构**: 仅在 GREEN 状态下重构
5. **提交**: 所有测试 100% 通过才允许 commit

### 4.3 Mock 策略
- **外部 API**: 使用 `unittest.mock.patch` Mock yfinance/IBKR
- **时间敏感逻辑**: 通过 `reference_date` 参数注入固定日期
- **数据库**: 使用 `:memory:` SQLite 数据库 (iv_store)

---

## V. 输出规范 (Output Standards)

### 5.1 战报哲学
- **纯数据陈述**: 只输出客观指标值和触发条件
- **禁止建议**: 不得出现"适合买入"、"建议减仓"等主观判断
- **强制附加信息**: 所有输出标的必须包含:
  - Next Earnings Date (YYYY-MM-DD)
  - Days to Earnings (自然日)

### 5.2 报告格式
- **文本报告**: `src/report.py` 生成纯文本 (中文)
- **HTML 报告**: `src/html_report.py` 生成 Apple 风格页面
- **空值处理**: 无符合条件的标的时显示 "(无符合条件的标的)",而非留空

### 5.3 版本控制
- 报告中不显示模块编号 (Module 1/2/3)
- 不显示版本号 (V1.9)
- 直接使用业务描述作为章节标题 (如 "波动率极值监控")

---

## VI. Phase 路线图索引 (Roadmap Index)

| Phase | 需求文档 | 状态 | 核心功能 |
|-------|----------|------|---------|
| Phase 1 | `archive/phase_1_monitor_market.md` | ✅ 已实现 | IV Extremes, MA200 Crossover, LEAPS Setup, Sell Put Scanner |
| Phase 2-IV | `archive/phase_2_iv.md` | ✅ 已实现 | IV Momentum (5-day), Earnings Gap Profiler |
| Phase 2-Dividend | `archive/phase_2_high_dividend.md` | ✅ 已实现 | 高股息防御双打 — 每周标的池筛选 + 每日买入信号 + LLM防御性评分 |
| Phase 3 | `archive/phase_3_clawhub.md` | ✅ 已实现 | ClawHub trading-navigator skill + Fly.io agent + 多LLM支持 |
| Phase 4 P1 | `req/phase_4_data_sources.md` | ✅ 已实现 | 多数据源互备份 — Polygon (价格+基本面) + Tradier (期权) + providers/ 包 |
| Phase 4 P2 | `req/phase_4_data_sources.md` | ⏳ 待审批 | IBKR REST API (OAuth 2.0) — 等待 developer.ibkr.com 审批 |
| Phase 5 | `req/phase_5_cloud_deployment.md` | 📋 待实现 | 云端部署 + Web Dashboard + OpenClaw/WhatsApp 集成 + Flex 仓位查询 |
| Phase 6 | `req/phase_6_portfolio_risk.md` | 📋 待实现 | 仓位风险报告 — Flex 读仓位 + 17 维度风险分析 + AI 操作建议 |

**注意**: 详细需求以各 Phase 文档为准,本索引仅供快速导航。

---

## VII. 文档生命周期 (Document Lifecycle)

### 7.1 永久文档
- `req/GLOBAL_MASTER.md` (本文档)
- `req/PHASE_N_*.md` (实现完成后归档到 `archive/`)
- `docs/specs/*.md` (与代码 1:1 映射,代码存在即保留)

### 7.2 临时文档
- `docs/plans/*.md` (实现完成且 specs 同步后删除)

### 7.3 Spec-to-Code 映射

**Status**: ✅ 完成（Phase 1 + Phase 2）

| Spec File | Source Modules | Purpose |
|-----------|----------------|---------|
| `docs/specs/data_pipeline.md` | `data_loader.py`, `market_data.py`, `iv_store.py` | 数据获取、市场分类、IV 存储 |
| `docs/specs/indicators.md` | `data_engine.py` | 技术指标计算引擎 |
| `docs/specs/scanners.md` | `scanners.py` | 扫描器逻辑规则 (Phase 1 + Phase 2) |
| `docs/specs/reporting.md` | `report.py`, `html_report.py` | 战报生成 (文本 + HTML) |

---

## VIII. 协议遵守检查清单

在开始任何新 Phase 前,确认:
- [ ] 已读取本文档 (`req/GLOBAL_MASTER.md`)
- [ ] 已读取对应 Phase 需求文档 (`req/PHASE_N_*.md`)
- [ ] 已检查 Spec-to-Code 映射,理解现有模块职责
- [ ] 新功能符合模块依赖层级规则
- [ ] TickerData 扩展遵循 Optional 类型约定
- [ ] 配置项已添加到 `config.yaml`
- [ ] 测试文件已创建 (Mirror Testing)
- [ ] 金融数据完整性要求 (复权/时差/股息) 已考虑
- [ ] 错误隔离策略已实现
- [ ] 实现完成后已创建/更新 `docs/specs/*.md`
