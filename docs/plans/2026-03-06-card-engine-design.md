# 机会卡片引擎 (Card Engine) 设计文档

**日期**: 2026-03-06
**目标**: 为交易领航员 Agent 构建推理层，接 Claude API 生成结构化机会卡片

---

## 产品定位

在现有扫描层（感知层）之上增加推理层：
- 扫描器负责触发条件（硬规则）
- Claude API 负责分析和表达（推理）
- 卡片是推理层的输出，30秒看懂为什么推、怎么做、最坏亏多少

第一版覆盖两个策略：
1. **Sell Put 收租**（场景1）
2. **高股息防御双打**（场景4）

---

## 架构

```
main.py
    ↓ 扫描完信号后
CardEngine.process_signals(sell_put_signals, dividend_signals)
    ├── CardStore（24h 缓存检查）
    ├── AnalysisCache（基本面缓存，TTL 分级）
    │     Step 1: Claude API → 基本面分析
    └── CardGenerator
          Step 2: Claude API → 生成卡片 JSON
    ↓
推送钉钉 + 注入 HTML 报告
```

### 新增文件

| 文件 | 职责 |
|------|------|
| `src/card_engine.py` | 统一入口，orchestrate 全流程 |
| `src/card_store.py` | SQLite 存储（card_store.db） |
| `tests/test_card_engine.py` | 单元测试 |
| `tests/test_card_store.py` | 存储测试 |

---

## 数据流

```
对每个信号：
  1. card_store 检查 24h 缓存
     → 命中：返回缓存卡片（0 token）
     → 未命中：继续

  2. analysis_cache staleness check
     - fundamentals（护城河/商业模式）：30天 TTL
     - valuation（估值区间）：下次财报前有效
     - 技术位：每次实时取（来自扫描器，无需缓存）
     → 未过期：复用缓存（节省 ~800 tokens）
     → 已过期：Step 1 调 Claude API 重新分析

  3. Step 2 调 Claude API 生成卡片
     输入 = 信号硬数据 + Step 1 分析缓存
     输出 = 结构化卡片 JSON

  4. 存入 card_store.db
```

---

## 卡片数据结构

```python
@dataclass
class OpportunityCard:
    card_id: str           # "{ticker}_{strategy}_{date}"
    ticker: str
    strategy: str          # "SELL_PUT" | "HIGH_DIVIDEND"
    created_at: datetime
    signal_hash: str       # 信号指纹，变化时强制刷新

    # 触发场景
    trigger_reason: str

    # AI 核心建议
    action: str
    key_params: dict       # {strike, dte, premium} 或 {yield, annual_dividend}
    one_line_logic: str

    # 跨财报时：双方案对比
    crosses_earnings: bool
    protected_plan: dict   # Bull Put Spread 方案（推荐）
    naked_plan: dict       # Naked Sell Put 方案

    # 胜率分析
    win_scenarios: list    # [{prob, desc, pnl}]

    # 基本面估值
    valuation: dict        # {iron_floor, fair_value, current, logic_summary, confidence}
    # logic_summary: 3-5句话说明估值计算依据（基础逻辑，不含详细推算）

    # 风险
    risk_level: str        # "HIGH" | "MEDIUM" | "LOW"
    risk_points: list

    # 事件预警
    events: list           # [{date, type, impact, days_away}]

    # 风控
    take_profit: str
    stop_loss: str

    # 最坏情况
    max_loss_usd: float
    max_loss_pct: float    # 占总仓位（基于默认仓位配置）
```

---

## SQLite Schema（card_store.db）

```sql
-- 卡片存储（24h TTL）
CREATE TABLE opportunity_cards (
    card_id      TEXT PRIMARY KEY,
    ticker       TEXT NOT NULL,
    strategy     TEXT NOT NULL,
    card_json    TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    signal_hash  TEXT NOT NULL
);

-- 基本面分析缓存（分级 TTL）
CREATE TABLE analysis_cache (
    ticker                TEXT PRIMARY KEY,
    fundamentals_json     TEXT,    -- 护城河/商业模式，30天 TTL
    valuation_json        TEXT,    -- 估值区间，财报前有效
    next_earnings         TEXT,    -- 下次财报日
    cached_at             TEXT,
    fundamentals_expires  TEXT,    -- cached_at + 30天
    valuation_expires     TEXT     -- next_earnings 日期
);
```

---

## Claude API 调用设计

### Step 1 — 基本面分析（条件触发）

```
system: 专业交易分析师，返回严格 JSON，不加解释和 markdown
user:
  分析 {ticker}，当前价 {price}，财报日 {earnings_date}
  返回 JSON：
  {
    "iron_floor": float,
    "fair_value": float,
    "logic_summary": "3-5句，说明估值计算的基础逻辑",
    "confidence": "置信说明（数据来源与假设）",
    "moat": "护城河一句话",
    "risk_factors": [{"desc": str, "level": "HIGH|MEDIUM|LOW"}],
    "risk_level": "HIGH|MEDIUM|LOW"
  }
```

### Step 2 — 卡片生成（每次信号触发）

```
system: 交易领航员，生成机会卡片，返回严格 JSON
user:
  策略: {strategy}  标的: {ticker}  当前价: {price}
  触发条件: {trigger_details}        ← 扫描器硬数据
  基本面分析（缓存）: {analysis_json} ← Step 1 结果
  期权参数: {option_params}          ← 行权价/DTE/权利金
  跨财报: {crosses_earnings}
  财报历史跳空均值: {avg_earnings_gap}

  生成完整卡片 JSON（含双方案对比，如跨财报）
```

**Token 预算**：
- Step 1（未缓存）：~800 tokens/次，30天一次
- Step 2（每次信号）：~1200 tokens/次
- 24h 缓存命中：0 tokens

---

## 跨财报双方案对比

当 `days_to_earnings < dte` 时，同时生成两个方案：

```
方案 A（推荐）· Bull Put Spread 带保护
  卖 $170 Put + 买 $160 Put
  净权利金: $0.9 | 最大亏损: $9.1/股（锁死）
  适合: 不想赌方向，保护优先

方案 B · Naked Sell Put
  卖 $170 Put | 权利金: $1.6 | 最大亏损: 理论 $168.4/股
  适合: 仓位小、确信基本面、愿意接盘
```

---

## 基本面估值摘要格式

```
铁底 $163.5 基于硬件+服务稳定业务 EPS $3.5 × 保守 25x PE。
公允价 $182.5 加入 AI 换机周期贡献约 $0.3 EPS 增量。
当前 $185 略高于公允价，但未脱离合理区间。
主要不确定性来自中国区收入占比（约17%），地缘风险计入折价。

[查看详细分析 ▼]  ← 展开 Step 1 完整 JSON
```

---

## 钉钉推送格式

```markdown
## 🟢 Sell Put 收租 · AAPL
**触发**: 跌入便宜区间，IV Rank 42%
**建议**: 卖出 6月 $170 Put，权利金 $1.6，年化 11.8%

📊 胜率: 安全收租 85% | 行权接盘 15%
💡 估值: 铁底 $163.5 | 公允价 $182.5
⚠️ 财报: 45天后，历史跳空 ±7.5%（跨财报，见双方案）
🛑 止盈: 权利金跌至 $0.32（赚80%）
🔴 止损: 服务营收增速 < 8%
最坏亏损: $9.1/股（Bull Put Spread）
```

---

## 集成点

### main.py（最小改动）

```python
from src.card_engine import CardEngine

if config.get("card_engine", {}).get("enabled", False):
    card_engine = CardEngine(config)
    cards = card_engine.process_signals(
        sell_put_signals=sell_put_results,
        dividend_signals=dividend_signals,
    )
    card_engine.push_dingtalk(cards)
```

### config.yaml 新增

```yaml
card_engine:
  enabled: false
  anthropic_api_key: "${ANTHROPIC_API_KEY}"
  model: "claude-opus-4-6"
  dingtalk_webhook: "${DINGTALK_WEBHOOK_URL}"
  default_position_size: 10000  # 用于计算 max_loss_pct
```

### HTML 报告

`html_report.py` 新增机会卡片 section，折叠式展示，
复用现有 Apple 风格，估值部分有 [查看详细分析] 展开按钮。

---

## 错误处理

- Claude API 失败 → 记录 warning，跳过卡片生成，不中断主流程
- 钉钉推送失败 → 记录 warning，卡片仍存入 DB
- 分析缓存损坏 → 视为过期，重新生成

---

## 测试策略

- Mock Claude API（不实际调用）
- 测试 staleness 判断逻辑（30天/财报日边界）
- 测试 24h 缓存命中/未命中
- 测试跨财报双方案生成
- 测试钉钉 Webhook 格式
