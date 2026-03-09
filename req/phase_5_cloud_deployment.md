# Phase 5: 云端部署 + Dashboard + OpenClaw 集成

**状态**: 待实现
**优先级**: 中

---

## 背景

当前系统已具备扫描引擎、多数据源路由（Phase 4）。
本阶段目标：将系统部署为单租户云服务，提供 Web Dashboard 和 OpenClaw/WhatsApp 对话接口。

**关键决策：单租户私有部署，非多租户 SaaS**
- 无用户注册/计费逻辑
- 数据不需命名空间隔离
- 适合个人/小团队量化工作流

---

## 架构总览

```
[云端 VPS / Fly.io]
├── ai-monitor 扫描引擎          ← 已有
├── Dashboard (Web UI)            ← 本阶段
├── Agent API                     ← 骨架已有 (ai-monitor.fly.dev)
│    ├── OpenClaw skill 接入      ← 本阶段
│    └── WhatsApp webhook         ← 本阶段
│
└── 数据源（全云端，无本地依赖）
     ├── IBKR REST API (OAuth)    ← Phase 4 P2，审批中
     ├── Polygon                  ← Phase 4 已实现
     └── Tradier                  ← Phase 4 已实现

[本地 / 内网]
└── IB Gateway (TWS)             ← 可选，enabled=true 时本地优先
```

---

## 模块 1: Dashboard (Web UI)

### 功能范围

- 扫描结果展示（IV Momentum、高股息双打信号）
- 仓位快照（从 IBKR REST API 或手动录入）
- 数据源状态（各 provider 启用/禁用状态、最后成功时间）
- 历史报告查阅

### 技术选型

- 后端：FastAPI（已有 agent API 骨架，扩展即可）
- 前端：轻量 HTML + HTMX 或 Vue 单页，部署在同一服务
- 认证：单用户 API Key（Header `X-API-Key`），env var 配置

### 访问控制

- Dashboard 公网可访问，需 API Key 认证
- IB Gateway 仍只在内网/本地暴露，不通过 Dashboard 透传

---

## 模块 2: OpenClaw / Claude Agent 集成

### 用途

通过对话查询：
- 当前仓位
- 最新扫描信号（哪些标的触发）
- 某只股票的基本面 / IV 状态
- 触发手动扫描

### 接入方式

- OpenClaw skill 调用 Agent API（REST）
- Agent API 路由到扫描引擎 / 数据层
- 响应格式：纯文本 + 结构化 JSON

### 关键 API 端点（扩展现有 agent API）

```
GET  /api/signals                 # 最新扫描结果
GET  /api/positions               # 当前仓位（IBKR REST 或缓存）
GET  /api/ticker/{ticker}/status  # 单标的状态（价格/IV/基本面）
POST /api/scan/trigger            # 手动触发扫描
GET  /api/datasources/status      # 各数据源健康状态
```

---

## 模块 3: WhatsApp 集成

### 用途

- 推送扫描信号（有信号时主动推送）
- 接收查询消息，回复仓位 / 机会

### 接入方式

- WhatsApp Business API（或 Twilio WhatsApp 沙盒）
- Webhook 接收用户消息 → 路由到 OpenClaw Agent 处理 → 回复

### 配置

```yaml
notifications:
  whatsapp:
    enabled: false
    webhook_url: ""    # env: WHATSAPP_WEBHOOK_URL
    phone_number: ""   # env: WHATSAPP_PHONE_NUMBER
    api_key: ""        # env: WHATSAPP_API_KEY
```

---

## 模块 4: IBKR REST API Provider

（已在 Phase 4 req 中定义，本阶段实现）

- `IBKRRestProvider` 类加入 `src/providers/` 包
- OAuth 2.0 token 管理（refresh 自动化）
- 路由优先级：TWS → IBKR REST → Polygon/Tradier → yfinance
- Token 存 Fly.io secrets，不写入代码或配置文件

---

## 仓位数据方案

IBKR REST API 支持仓位查询：
- `GET /portfolio/{accountId}/positions` → 当前持仓
- `GET /portfolio/{accountId}/summary` → 账户摘要

无需 IB Gateway 即可获取仓位数据，纯云端可用。

---

## 部署方案

### Fly.io（现有）

```toml
# fly.toml 扩展
[env]
  POLYGON_API_KEY    = ""   # set via fly secrets
  TRADIER_API_KEY    = ""
  IBKR_CLIENT_ID     = ""
  IBKR_ACCESS_TOKEN  = ""
  IBKR_REFRESH_TOKEN = ""
  SCAN_API_KEY       = ""
  WHATSAPP_API_KEY   = ""
```

### 本地运行（开发 / 内网）

```yaml
# config.yaml
data_sources:
  ibkr_tws:
    enabled: true    # 本地开 TWS，优先走本地
```

### 云端自动化

```yaml
data_sources:
  ibkr_tws:
    enabled: false   # 云端关掉 TWS，走 REST API
  ibkr_rest:
    enabled: true
```

---

## 实现优先级

| 优先级 | 模块 | 前置条件 |
|--------|------|---------|
| P1 | IBKR REST API Provider | IBKR developer 审批通过 |
| P1 | Agent API 扩展（仓位/信号端点）| 无 |
| P2 | OpenClaw skill 接入 | Agent API 完成 |
| P2 | Dashboard 基础版 | Agent API 完成 |
| P3 | WhatsApp webhook | OpenClaw 接入验证后 |

---

## 不在本阶段范围

- 多租户（用户注册、计费、命名空间隔离）
- 实时 WebSocket 推送
- 移动端 App
- 富途 OpenD 接入
