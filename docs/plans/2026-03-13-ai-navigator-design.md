# AI 领航页面设计文档

**日期**: 2026-03-13
**状态**: 已确认，待实现
**对应路由**: `/chat` (重建 `agent/templates/chat.html`)

---

## 目标

将现有的基础聊天页升级为具备用户画像、富媒体卡片、工具抽屉的 AI 领航中枢。核心价值：AI 认识用户 + 实时对话在同一屏发生。

---

## 页面布局（方案二：分区布局）

### 桌面（≥1024px）：三栏

```
┌──────────────┬──────────────────────┬──────────────┐
│  画像面板     │      对话流           │  工具抽屉     │
│  200px       │      flex-1          │  240px       │
│  只读        │  消息气泡 + 卡片      │  可折叠      │
└──────────────┴──────────────────────┴──────────────┘
```

### 移动端

- 左侧画像面板 → 顶部横向滚动标签条
- 右侧工具抽屉 → 消失，功能收入输入框上方 chip 区
- 对话流占满全屏

### 三区职责

| 区域 | 内容 | 交互 |
|------|------|------|
| **画像面板**（左） | 用户名、风险等级、偏好市场、策略标签 2~4 个、AI 摘要一句话 | 只读；标签点击注入相关问题到对话 |
| **对话流**（中） | 文本气泡 + 富媒体卡片；输入框 + 快捷 chip | 发消息、卡片内操作按钮 |
| **工具抽屉**（右） | 扫描摘要、自选池快速预览、最近信号列表 | 可折叠；点击条目注入对话 |

---

## 用户画像数据模型

### DB 变更

```sql
ALTER TABLE users ADD COLUMN profile_json TEXT DEFAULT '{}';
```

### 画像 JSON 结构

```json
{
  "risk_level": "moderate",
  "preferred_markets": ["US", "HK"],
  "strategy_tags": ["高股息", "卖波动率"],
  "summary": "偏好美港股高股息标的，习惯在 IV 高位卖 Put，风险承受中等。",
  "last_updated": "2026-03-13",
  "message_count": 47
}
```

### 字段约束

| 字段 | 类型 | 允许值 |
|------|------|--------|
| `risk_level` | string | `conservative` / `moderate` / `aggressive` |
| `preferred_markets` | string[] | `US` / `HK` / `CN` |
| `strategy_tags` | string[] | 见下方标签集 |
| `summary` | string | AI 生成，≤80字 |
| `message_count` | int | 累计用户消息数，用于触发更新 |

### 投资领域标签集（预定义）

```
风险偏好：保守型 / 稳健型 / 进取型
策略：高股息 / 卖波动率 / LEAPS / 趋势跟踪 / 事件驱动
市场：偏好美股 / 偏好港股 / 偏好A股
```

### 画像更新逻辑

- **触发条件**: `message_count % 15 == 0`（每 15 条用户消息后）
- **实现**: `ClaudeAgent.process()` 检测到触发条件，追加隐藏 system 调用，让 AI 根据近期对话 rewrite `profile_json`
- **首次建立**: 新用户首次对话，AI 主动问 2~3 个引导问题（偏好市场、关注策略）

### 新增 DB 方法

```python
db.get_profile(user_id: str) -> dict
db.update_profile(user_id: str, profile: dict)
```

---

## 富媒体回复卡片

### API 响应格式（`/api/chat` 扩展）

```json
{
  "reply": "找到 3 个高股息机会：",
  "cards": [
    {
      "type": "opportunity",
      "ticker": "0700.HK",
      "name": "腾讯控股",
      "signal": "dividend_buy",
      "yield": "4.2%",
      "iv_rank": 72,
      "action": "add_watchlist"
    }
  ],
  "profile_updated": false
}
```

### 卡片类型（V1，共 3 种）

| type | 触发意图关键词 | 核心字段 | 操作按钮 |
|------|-------------|---------|---------|
| `opportunity` | "有没有机会" / "高股息" / "Sell Put" | ticker、信号类型、yield、iv_rank | 加自选 |
| `risk_summary` | "分析风险" / "我的持仓" | 风险等级、最大亏损、Greeks 摘要 | 查看完整报告 |
| `watchlist_confirm` | "加自选" / "删除XXX" | 操作结果、当前自选池快照 | 无（确认卡） |

### 渲染规则

- 文本气泡下方追加卡片，样式复用设计系统（dark theme、amber accent、DM Mono 数字）
- 卡片内按钮点击直接调 REST API，成功后 AI 回一条确认消息
- 单条 AI 回复最多展示 5 张卡片，超出折叠

### 快捷 chip（固定 4 个）

```
[扫描摘要]  [我的自选]  [高股息机会]  [分析风险]
```

点击 chip = 将预设文本注入输入框并自动发送。

---

## 后端变更清单

### `agent/db.py`
- `ALTER TABLE users ADD COLUMN profile_json TEXT DEFAULT '{}'`
- `get_profile(user_id)` — 返回解析后的 dict
- `update_profile(user_id, profile)` — 序列化写入

### `agent/claude_agent.py`
- `SYSTEM_PROMPT` 加入用户画像注入：每次对话把 `profile.summary` + `strategy_tags` 拼入 system
- `process()` 加 `message_count % 15` 检测，触发画像 rewrite
- 首次用户检测：`message_count == 0` 时追加引导问题

### `agent/dashboard.py`（或新建 `agent/chat.py`）
- `/api/chat` 响应新增 `cards` 和 `profile_updated` 字段

### `agent/tools.py`
- `get_opportunity_cards(strategy: str) -> list` — 从 DB 取信号，格式化为卡片 JSON
- `get_risk_summary(user_id: str) -> dict` — 取最新风险报告摘要

---

## 前端变更（`agent/templates/chat.html` 重建）

- 三栏布局（CSS Grid，桌面）/ 单栏 + 标签条（移动端）
- 画像面板：从 `/api/profile` 拉取，标签 chip 点击注入对话
- 工具抽屉：从 `/api/signals?limit=5` 拉取最近信号列表
- 消息渲染：支持 `cards` 数组，按 type 渲染不同卡片组件
- 快捷 chip：4 个固定入口，点击自动发送

---

## 不在 V1 范围内

- 用户手动编辑画像（通过对话即可更新）
- 多用户支持（当前固定 `ALICE`）
- 画像历史版本记录
- 卡片内嵌图表

---

## 测试要求

| 测试文件 | 覆盖点 |
|---------|--------|
| `tests/test_agent_db.py` | `get_profile` / `update_profile` 读写正确 |
| `tests/test_claude_agent.py` | 画像注入进 system prompt；15条触发更新 |
| `tests/test_dashboard.py` | `/api/chat` 返回 `cards` 字段结构正确 |
