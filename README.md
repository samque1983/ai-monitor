# AI Monitor — 量化扫描雷达

自动扫描美股/港股/A股市场机会，支持钉钉推送和 ClawHub 接入。

---

## 架构

```
本地扫描器 (Mac)
    → 每日运行扫描
    → POST /api/scan_results 推送到 Fly.io agent
           ↓
Fly.io Agent (FastAPI)
    → 存储扫描结果 (SQLite)
    → GET /api/scan_results 公开读取
    → POST /dingtalk/webhook 接收钉钉消息，AI 回复
           ↓
OpenClaw / 钉钉用户
    → ClawHub skill 定时拉取分析
    → 钉钉机器人对话
```

---

## 本地扫描器

### 依赖安装

```bash
pip install -r requirements.txt
```

### 配置

复制并编辑配置文件：

```bash
cp config.yaml config.local.yaml  # 可选，本地覆盖
```

`config.yaml` 中的 `agent` 部分：

```yaml
agent:
  url: "https://ai-monitor.fly.dev"   # Fly.io agent 地址
  api_key: ""                          # 通过环境变量 SCAN_API_KEY 传入
```

### 运行扫描

```bash
# 基本运行
python3 -m src.main

# 带 agent 推送（需设置 SCAN_API_KEY）
SCAN_API_KEY=<your-key> python3 -m src.main
```

### 每日股息池筛选

```bash
python3 scripts/run_dividend_screening.py
```

---

## Fly.io Agent 部署

### 环境变量 (Fly.io Secrets)

在 [Fly.io Dashboard](https://fly.io/apps/ai-monitor/secrets) 或通过 CLI 设置：

```bash
flyctl secrets set \
  LLM_PROVIDER=deepseek \       # 或 openai / anthropic
  LLM_API_KEY=<your-llm-key> \
  SCAN_API_KEY=<random-secret> \
  DINGTALK_APP_SECRET=<dingtalk-secret> \
  --app ai-monitor
```

| 变量 | 说明 | 必填 |
|------|------|------|
| `LLM_PROVIDER` | `deepseek` / `openai` / `anthropic` | 是 |
| `LLM_API_KEY` | 对应 LLM 的 API Key | 是 |
| `LLM_MODEL` | 模型名称（可选，有默认值） | 否 |
| `SCAN_API_KEY` | 推送扫描结果的认证 key | 建议设置 |
| `DINGTALK_APP_SECRET` | 钉钉机器人签名密钥 | 钉钉功能必填 |

**LLM 默认模型：**
- `deepseek` → `deepseek-chat`
- `openai` → `gpt-4o`
- `anthropic` → `claude-opus-4-6`

**向后兼容：** 旧版 `ANTHROPIC_API_KEY` 仍有效，无需迁移。

### 自动部署

Push 到 `main` 分支自动触发 GitHub Actions 部署：

```bash
git push origin main
```

首次部署前需在 GitHub repo Settings → Secrets 添加 `FLY_API_TOKEN`。

### API 端点

| 端点 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/health` | GET | 无 | 健康检查 |
| `/api/scan_results` | GET | 无 | 读取最新扫描结果 |
| `/api/scan_results` | POST | `X-API-Key` | 推送扫描结果 |
| `/dingtalk/webhook` | POST | 签名验证 | 钉钉消息入口 |

---

## ClawHub (OpenClaw 接入)

```bash
npx clawhub@latest install trading-navigator
```

安装后无需配置，自动从 `https://ai-monitor.fly.dev/api/scan_results` 拉取数据。

定时检查（工作日 17:30）：

```
30 17 * * 1-5  openclaw run trading-navigator:check
```

---

## UI 设计系统

前端卡片、徽章、排版、动画规范提取为独立 Claude Code skill：

**[ai-monitor-ui](https://github.com/samque1983/ai-monitor-ui)** — 深色金融终端设计系统

---

## 测试

```bash
# 全量测试
python3 -m pytest tests/ -q

# 仅 agent 测试
python3 -m pytest tests/agent/ -q
```
