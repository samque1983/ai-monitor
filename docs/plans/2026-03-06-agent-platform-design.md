# 交易领航员 Agent Platform 设计文档

**日期**: 2026-03-06
**目标**: 在现有扫描层 + 卡片引擎之上，构建多租户 Agent 平台，支持钉钉对话、持仓风险监控、多用户接入

---

## 产品定位

- **你的 IBKR**：共享行情数据源（期权链、IV、实时价格），供全体用户使用
- **每个用户的 IBKR Flex Token**：只读拉取各自持仓，做风险分析，零安装
- **Claude API**：推理 + 对话大脑（tool use 模式）
- **钉钉**：通知 + 双向对话（预留 WhatsApp/Telegram 接口）

---

## 架构总览

```
你的 Mac / 小型 VPS
├── IBKR Gateway（你的账号）
└── Scan Job（定时扫描，结果 POST 推送云端）
         │
         ▼
    云端 (Fly.io)
    ├── 扫描结果 DB（PostgreSQL）
    ├── 用户配置（Flex Token、钉钉 Webhook、标的池）
    │
    ├── DingTalk Webhook Handler
    │     ↓
    │   Claude API（tool use 模式）
    │     ├── get_scan_results()      查今日信号
    │     ├── get_positions(user)     拉 Flex 持仓
    │     ├── run_risk_check(user)    仓位 × 行情 → 风险
    │     ├── trigger_scan()          触发立刻扫描
    │     └── manage_watchlist()      加/移除标的
    │
    └── APScheduler
          ├── 每日拉 Flex 持仓（风险监控）
          └── 每日推送机会卡片
```

**扫描端改动最小**：扫描完成后加一行 `POST /api/scan_results` 推送到云端，其余不变。

---

## Agent 对话层

Claude API 以 tool use 模式运行，理解自然语言指令，调用对应工具，返回结构化回复。

### 支持指令

| 用户发送 | 调用工具 | 返回内容 |
|---------|---------|---------|
| 今天有什么信号 | `get_scan_results()` | 最新机会卡片 |
| 帮我看看风险 | `get_positions` + `run_risk_check` | 持仓风险摘要 |
| AAPL 为什么推荐 | `get_card("AAPL")` | 卡片详情 + 估值逻辑 |
| 立刻扫一次 | `trigger_scan()` | 触发扫描，完成后推送 |
| 加入 NVDA | `manage_watchlist("add", "NVDA")` | 确认加入 |
| 我的最大回撤多少 | `run_risk_check(user)` | 组合风险指标 |

### 对话状态
- 每个用户独立对话历史，存 PostgreSQL
- Claude 记住上下文，支持追问
- 历史保留最近 20 轮

### 主动推送（无需用户触发）
- 每日扫描完成 → 推机会卡片
- 持仓触发风险阈值 → 即时预警
- 财报临近（≤7天）→ 提前提醒

### 渠道扩展
新增 WhatsApp/Telegram 只需添加新 webhook 路由，Agent 核心逻辑不变。

---

## 多租户数据模型

```sql
-- 用户表
users (
    user_id          TEXT PRIMARY KEY,   -- DingTalk user_id
    dingtalk_webhook TEXT,               -- 推送目标
    flex_token_enc   TEXT,               -- AES-256 加密的 Flex token
    flex_query_id    TEXT,
    watchlist_json   TEXT,               -- 用户自定义标的池
    created_at       TEXT
);

-- 扫描结果（共享，所有用户读同一份）
scan_results (
    scan_id      TEXT PRIMARY KEY,
    scan_date    TEXT,
    results_json TEXT,
    created_at   TEXT
);

-- 持仓快照（按用户隔离，每日拉取）
positions (
    user_id          TEXT,
    snapshot_date    TEXT,
    positions_json   TEXT,
    risk_json        TEXT,
    PRIMARY KEY (user_id, snapshot_date)
);

-- 对话历史（按用户隔离）
conversations (
    id         SERIAL PRIMARY KEY,
    user_id    TEXT,
    role       TEXT,    -- "user" | "assistant"
    content    TEXT,
    created_at TEXT
);
```

**安全**：Flex Token AES-256 加密存储，仅 risk engine 内部解密使用，不传给 Claude。

---

## 风险引擎

持仓数据（Flex）× 行情数据 → 风险指标，每日自动计算。

### 计算内容

**期权仓位：**
- Delta 敞口（持仓 delta × 标的价格）
- 最大亏损（Sell Put: strike × 合约数 × 100）
- 财报风险（是否跨财报，距财报天数）
- 保证金使用率

**整体组合：**
- 单一标的集中度
- 行业集中度
- 最坏情景亏损（全部 Put 行权）

### 即时预警阈值

| 触发条件 | 预警内容 |
|---------|---------|
| 标的下跌，距行权价 ≤ 5% | "AAPL 距行权价仅剩 $X" |
| 持有裸 Put 且财报 ≤ 7 天 | "跨财报风险提醒" |
| 单仓最大亏损 > 净值 5% | "仓位过重预警" |
| 保证金使用率 > 70% | "保证金预警" |

---

## 部署

```
Fly.io App
├── FastAPI server
│     ├── POST /dingtalk/webhook
│     ├── POST /api/scan_results   (扫描端推送，需 API key)
│     ├── POST /users/register
│     └── GET  /health
├── APScheduler
│     ├── 17:00 拉所有用户 Flex 持仓
│     └── 17:05 风险阈值检查 → 推预警
└── PostgreSQL（Fly.io 托管）
```

---

## 分阶段交付

| 阶段 | 内容 | 前置依赖 |
|------|------|---------|
| Phase 1 | 钉钉 Agent：对话 + 查信号 + 管标的池 | 卡片引擎 |
| Phase 2 | Flex 持仓拉取 + 风险指标计算 | Phase 1 |
| Phase 3 | 实时风险预警（财报/保证金/集中度）| Phase 2 |
| Phase 4 | 多用户注册 + Token 加密管理 | Phase 3 |
| Phase 5 | WhatsApp / Telegram 接入 | Phase 1 |

**先跑通 Phase 1 单用户**，验证对话体验，再逐步扩展。

---

## 新增文件（Phase 1）

| 文件 | 职责 |
|------|------|
| `agent/main.py` | FastAPI 入口，DingTalk webhook |
| `agent/claude_agent.py` | Claude tool use 对话引擎 |
| `agent/tools.py` | 工具函数（get_scan_results, manage_watchlist 等）|
| `agent/db.py` | PostgreSQL 连接，用户/对话/扫描结果 CRUD |
| `agent/dingtalk.py` | 钉钉消息解析 + 推送 |
| `fly.toml` | Fly.io 部署配置 |
