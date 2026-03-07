---
name: trading-navigator
description: 交易领航员 — 查询最新股票扫描信号并进行 AI 分析。支持主动定时推送和用户主动查询两种模式。
---

# 交易领航员 (Trading Navigator)

## 概述

通过调用交易领航员后端 API 获取最新扫描结果，进行 AI 分析，识别高质量机会信号。

**API 端点（公开，无需认证）：**
```
GET https://ai-monitor.fly.dev/api/scan_results
```

---

## 两种使用模式

### 模式 1：`trading-navigator:check`（Crontab 定时调用）

**用途：** 定时检查是否有新信号，有则分析推送，无则静默跳过。

**推荐 Crontab 配置（工作日 17:30）：**
```
30 17 * * 1-5  openclaw run trading-navigator:check
```

**执行步骤：**

1. 读取状态文件 `~/.trading-navigator/state.json`，获取 `last_seen_date`。
   - 如果文件不存在，视为首次运行，`last_seen_date = null`。

2. 调用 API：
   ```bash
   curl -s https://ai-monitor.fly.dev/api/scan_results
   ```
   获取 `scan_date` 和 `results`。

3. **比对日期：**
   - 如果 `scan_date == last_seen_date`：静默退出，不输出任何内容。
   - 如果 `scan_date != last_seen_date`（或 `last_seen_date` 为 null）：继续第 4 步。

4. **分析信号**（见「分析规范」章节）。

5. 更新状态文件：
   ```json
   { "last_seen_date": "<scan_date>" }
   ```
   保存到 `~/.trading-navigator/state.json`。

---

### 模式 2：`trading-navigator:query`（用户主动查询）

**用途：** 用户主动问「今天有什么机会？」时调用。

**执行步骤：**

1. 调用 API 获取最新结果。
2. 直接进行分析，不检查 `last_seen_date`，不更新状态文件。

---

## 分析规范

收到 `results` 列表后，按以下格式输出分析：

### 输出格式

```
📊 交易领航员日报 — {scan_date}
共 {N} 个信号

🔝 重点关注（前3个）：

1. **{ticker}** [{strategy}]
   触发：{trigger_reason}
   建议：{action}

2. ...

💡 综合判断：
[1-2句总结今日市场机会特征，例如：今日信号以高IV环境下的卖PUT为主，集中在科技板块。]
```

### 分析原则

- **只展示前 3 个信号**（避免信息过载）。
- **strategy 含义：**
  - `SELL_PUT`：卖出看跌期权，收取权利金，适合横盘或温和上涨行情
  - `DIVIDEND`：高股息股票买入信号，适合追求稳定现金流
- **不要捏造数据**：只分析 API 返回的实际内容，不添加未在结果中的信息。
- **无信号时**：输出「今日暂无扫描信号，市场可能处于低波动或观望阶段。」

---

## 状态文件格式

路径：`~/.trading-navigator/state.json`

```json
{
  "last_seen_date": "2026-03-07"
}
```

- 如果目录不存在，使用 `mkdir -p ~/.trading-navigator` 创建。
- 仅 `trading-navigator:check` 模式写入此文件。

---

## 安装

```bash
npx clawhub@latest install trading-navigator
```

安装后无需任何配置，直接可用。
