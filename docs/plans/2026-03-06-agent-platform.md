# Agent Platform Implementation Plan (Phase 1)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a DingTalk bidirectional agent (Phase 1: single user) that receives natural language commands, calls Claude API with tool use, and responds with scan results, card details, and watchlist management.

**Architecture:** FastAPI service in `agent/` subdirectory, deployed to Fly.io. SQLite for persistence (Fly Volume). Claude tool use processes commands. Scan job pushes results via POST /api/scan_results. DingTalk Enterprise Internal Bot for bidirectional messaging.

**Tech Stack:** fastapi, uvicorn, anthropic==0.84.0, httpx, sqlite3 (stdlib), requests, python-dotenv. Tests use pytest + httpx.AsyncClient.

---

## Critical Context: DingTalk Bot Types

You MUST use **Enterprise Internal Bot (企业内部机器人)**, NOT group webhook bot.

- Group webhook bot = outbound push only (no incoming messages)
- Enterprise internal bot = bidirectional (receives messages + can reply)

Each incoming message contains a `sessionWebhook` URL — use it to reply to that specific conversation. DingTalk sends a `timestamp` header and `sign` header for signature verification.

**Incoming message format:**
```json
{
  "msgtype": "text",
  "text": {"content": "今天有什么信号"},
  "senderId": "user_xxx",
  "senderNick": "张三",
  "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?session=xxx",
  "sessionWebhookExpiredTime": 1599099671000,
  "conversationId": "cid_xxx"
}
```

**Signature verification** (from request headers):
```python
timestamp = request.headers["timestamp"]
sign = request.headers["sign"]
# Verify: HMAC-SHA256(f"{timestamp}\n{app_secret}") == base64decode(sign)
```

---

## Existing Codebase You Must Know

```
src/main.py          — scan job, calls scan_sell_put, scan_dividend_buy_signal
src/dividend_store.py — SQLite pattern (reference for agent/db.py)
src/card_store.py    — SQLite pattern (if implemented)
config.yaml          — central config, card_engine section already added
```

Scan results live in `data/` SQLite files locally. After this plan, scan results also POST to cloud agent.

---

### Task 1: Project structure + FastAPI skeleton

**Files:**
- Create: `agent/__init__.py`
- Create: `agent/main.py`
- Create: `agent/requirements.txt`
- Create: `tests/agent/__init__.py`
- Create: `tests/agent/test_main.py`

**Step 1: Write the failing test**

```python
# tests/agent/test_main.py
import pytest
from fastapi.testclient import TestClient

def test_health_check():
    from agent.main import app
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

**Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/agent/test_main.py -v
```
Expected: `ModuleNotFoundError: No module named 'agent'`

**Step 3: Create project structure**

```python
# agent/__init__.py
# (empty)
```

```python
# agent/main.py
from fastapi import FastAPI

app = FastAPI(title="交易领航员 Agent")

@app.get("/health")
def health():
    return {"status": "ok"}
```

```
# agent/requirements.txt
fastapi==0.115.0
uvicorn[standard]==0.30.0
anthropic==0.84.0
httpx==0.27.0
requests==2.32.0
python-dotenv==1.0.0
pytest-asyncio==0.23.0
```

```python
# tests/agent/__init__.py
# (empty)
```

**Step 4: Install deps and run test**

```bash
pip3 install fastapi uvicorn httpx pytest-asyncio --quiet
python3 -m pytest tests/agent/test_main.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add agent/ tests/agent/
git commit -m "feat: add agent FastAPI skeleton with health check"
```

---

### Task 2: Database layer

**Files:**
- Create: `agent/db.py`
- Create: `tests/agent/test_db.py`

**Step 1: Write the failing tests**

```python
# tests/agent/test_db.py
import pytest
from datetime import date
from agent.db import AgentDB

def test_save_and_get_user(tmp_path):
    db = AgentDB(str(tmp_path / "agent.db"))
    db.save_user("user_123", dingtalk_webhook="https://oapi.dingtalk.com/xxx")
    user = db.get_user("user_123")
    assert user["user_id"] == "user_123"
    assert user["dingtalk_webhook"] == "https://oapi.dingtalk.com/xxx"
    db.close()

def test_save_and_get_scan_results(tmp_path):
    db = AgentDB(str(tmp_path / "agent.db"))
    results = [{"ticker": "AAPL", "strategy": "SELL_PUT"}]
    db.save_scan_results("2026-03-06", results)
    latest = db.get_latest_scan_results()
    assert latest is not None
    assert latest[0]["ticker"] == "AAPL"
    db.close()

def test_save_and_get_conversation(tmp_path):
    db = AgentDB(str(tmp_path / "agent.db"))
    db.add_message("user_123", "user", "今天有什么信号")
    db.add_message("user_123", "assistant", "今天有 2 个信号")
    history = db.get_history("user_123", limit=10)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    db.close()

def test_get_history_respects_limit(tmp_path):
    db = AgentDB(str(tmp_path / "agent.db"))
    for i in range(25):
        db.add_message("user_123", "user", f"msg {i}")
    history = db.get_history("user_123", limit=20)
    assert len(history) == 20
    db.close()

def test_watchlist_update(tmp_path):
    db = AgentDB(str(tmp_path / "agent.db"))
    db.save_user("user_123")
    db.update_watchlist("user_123", ["AAPL", "NVDA"])
    user = db.get_user("user_123")
    import json
    assert json.loads(user["watchlist_json"]) == ["AAPL", "NVDA"]
    db.close()
```

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/agent/test_db.py -v
```
Expected: `ModuleNotFoundError: No module named 'agent.db'`

**Step 3: Implement AgentDB**

```python
# agent/db.py
import sqlite3
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id          TEXT PRIMARY KEY,
    dingtalk_webhook TEXT DEFAULT '',
    flex_token_enc   TEXT DEFAULT '',
    flex_query_id    TEXT DEFAULT '',
    watchlist_json   TEXT DEFAULT '[]',
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_results (
    scan_date    TEXT PRIMARY KEY,
    results_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

class AgentDB:
    def __init__(self, db_path: str = "data/agent.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def save_user(self, user_id: str, dingtalk_webhook: str = ""):
        self.conn.execute(
            "INSERT OR IGNORE INTO users (user_id, dingtalk_webhook, created_at) VALUES (?,?,?)",
            (user_id, dingtalk_webhook, datetime.now().isoformat())
        )
        if dingtalk_webhook:
            self.conn.execute(
                "UPDATE users SET dingtalk_webhook=? WHERE user_id=?",
                (dingtalk_webhook, user_id)
            )
        self.conn.commit()

    def get_user(self, user_id: str) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT * FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_watchlist(self, user_id: str, tickers: List[str]):
        self.conn.execute(
            "UPDATE users SET watchlist_json=? WHERE user_id=?",
            (json.dumps(tickers), user_id)
        )
        self.conn.commit()

    def save_scan_results(self, scan_date: str, results: List[Dict]):
        self.conn.execute(
            "INSERT OR REPLACE INTO scan_results VALUES (?,?,?)",
            (scan_date, json.dumps(results, ensure_ascii=False),
             datetime.now().isoformat())
        )
        self.conn.commit()

    def get_latest_scan_results(self) -> Optional[List[Dict]]:
        row = self.conn.execute(
            "SELECT results_json FROM scan_results ORDER BY scan_date DESC LIMIT 1"
        ).fetchone()
        return json.loads(row[0]) if row else None

    def add_message(self, user_id: str, role: str, content: str):
        self.conn.execute(
            "INSERT INTO conversations (user_id, role, content, created_at) VALUES (?,?,?,?)",
            (user_id, role, content, datetime.now().isoformat())
        )
        self.conn.commit()

    def get_history(self, user_id: str, limit: int = 20) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT role, content FROM conversations WHERE user_id=? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def close(self):
        self.conn.close()
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/agent/test_db.py -v
```
Expected: 5 passed

**Step 5: Commit**

```bash
git add agent/db.py tests/agent/test_db.py
git commit -m "feat: add AgentDB with users, scan_results, conversations tables"
```

---

### Task 3: DingTalk message parsing + signature verification

**Files:**
- Create: `agent/dingtalk.py`
- Create: `tests/agent/test_dingtalk.py`

**Step 1: Write the failing tests**

```python
# tests/agent/test_dingtalk.py
import pytest
import hmac, hashlib, base64, time
from agent.dingtalk import verify_signature, parse_incoming, format_text_reply

APP_SECRET = "test_secret_12345"

def _make_sign(secret: str, timestamp: str) -> str:
    msg = f"{timestamp}\n{secret}"
    mac = hmac.new(secret.encode(), msg.encode(), digestmod=hashlib.sha256).digest()
    return base64.b64encode(mac).decode()

def test_verify_signature_valid():
    ts = str(int(time.time() * 1000))
    sign = _make_sign(APP_SECRET, ts)
    assert verify_signature(ts, sign, APP_SECRET) is True

def test_verify_signature_invalid():
    ts = str(int(time.time() * 1000))
    assert verify_signature(ts, "bad_sign", APP_SECRET) is False

def test_verify_signature_expired():
    old_ts = str(int((time.time() - 3600) * 1000))  # 1 hour ago
    sign = _make_sign(APP_SECRET, old_ts)
    assert verify_signature(old_ts, sign, APP_SECRET) is False

def test_parse_incoming_text():
    payload = {
        "msgtype": "text",
        "text": {"content": "今天有什么信号 @bot"},
        "senderId": "user_123",
        "senderNick": "张三",
        "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?session=xxx",
        "sessionWebhookExpiredTime": int(time.time() * 1000) + 60000,
        "conversationId": "cid_123",
    }
    msg = parse_incoming(payload)
    assert msg["user_id"] == "user_123"
    assert msg["text"] == "今天有什么信号"  # @bot stripped
    assert msg["session_webhook"] == payload["sessionWebhook"]

def test_format_text_reply():
    payload = format_text_reply("今天有 2 个信号")
    assert payload["msgtype"] == "markdown"
    assert "今天有 2 个信号" in payload["markdown"]["text"]
```

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/agent/test_dingtalk.py -v
```
Expected: `ModuleNotFoundError: No module named 'agent.dingtalk'`

**Step 3: Implement dingtalk.py**

```python
# agent/dingtalk.py
import hmac
import hashlib
import base64
import time
import re
import logging
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

SIGN_TOLERANCE_MS = 60 * 60 * 1000  # 1 hour


def verify_signature(timestamp: str, sign: str, app_secret: str) -> bool:
    """Verify DingTalk request signature."""
    try:
        ts_ms = int(timestamp)
        now_ms = int(time.time() * 1000)
        if abs(now_ms - ts_ms) > SIGN_TOLERANCE_MS:
            return False
        msg = f"{timestamp}\n{app_secret}"
        mac = hmac.new(
            app_secret.encode("utf-8"),
            msg.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        expected = base64.b64encode(mac).decode()
        return hmac.compare_digest(expected, sign)
    except Exception:
        return False


def parse_incoming(payload: Dict) -> Dict:
    """Parse DingTalk incoming message into normalized dict."""
    raw_text = ""
    if payload.get("msgtype") == "text":
        raw_text = payload.get("text", {}).get("content", "")
    # Strip @mentions (e.g. "@bot" or "@所有人")
    text = re.sub(r"@\S+", "", raw_text).strip()
    return {
        "user_id": payload.get("senderId", ""),
        "nick": payload.get("senderNick", ""),
        "text": text,
        "session_webhook": payload.get("sessionWebhook", ""),
        "conversation_id": payload.get("conversationId", ""),
    }


def format_text_reply(text: str) -> Dict:
    """Format a reply payload for DingTalk markdown message."""
    return {
        "msgtype": "markdown",
        "markdown": {
            "title": "交易领航员",
            "text": text,
        },
    }


def send_reply(session_webhook: str, text: str) -> bool:
    """Send reply to a DingTalk session webhook."""
    if not session_webhook:
        return False
    try:
        payload = format_text_reply(text)
        resp = requests.post(
            session_webhook,
            json=payload,
            verify=False,
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"DingTalk reply failed: {e}")
        return False


def push_to_webhook(webhook_url: str, text: str) -> bool:
    """Push proactive message to a DingTalk webhook URL."""
    if not webhook_url:
        return False
    try:
        payload = format_text_reply(text)
        resp = requests.post(
            webhook_url,
            json=payload,
            verify=False,
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"DingTalk push failed: {e}")
        return False
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/agent/test_dingtalk.py -v
```
Expected: 5 passed

**Step 5: Commit**

```bash
git add agent/dingtalk.py tests/agent/test_dingtalk.py
git commit -m "feat: add DingTalk signature verification and message parsing"
```

---

### Task 4: Tools layer

**Files:**
- Create: `agent/tools.py`
- Create: `tests/agent/test_tools.py`

**Step 1: Write the failing tests**

```python
# tests/agent/test_tools.py
import pytest
import json
from agent.db import AgentDB
from agent.tools import AgentTools

@pytest.fixture
def db_and_tools(tmp_path):
    db = AgentDB(str(tmp_path / "agent.db"))
    db.save_user("user_123")
    tools = AgentTools(db, user_id="user_123")
    yield db, tools
    db.close()

def test_get_scan_results_empty(db_and_tools):
    _, tools = db_and_tools
    result = tools.get_scan_results()
    assert "暂无" in result or "没有" in result

def test_get_scan_results_with_data(db_and_tools):
    db, tools = db_and_tools
    db.save_scan_results("2026-03-06", [
        {"ticker": "AAPL", "strategy": "SELL_PUT",
         "trigger_reason": "跌入便宜区间", "action": "卖出 $170 Put"}
    ])
    result = tools.get_scan_results()
    assert "AAPL" in result
    assert "SELL_PUT" in result or "Sell Put" in result

def test_manage_watchlist_add(db_and_tools):
    db, tools = db_and_tools
    result = tools.manage_watchlist("add", "NVDA")
    assert "NVDA" in result
    user = db.get_user("user_123")
    assert "NVDA" in json.loads(user["watchlist_json"])

def test_manage_watchlist_remove(db_and_tools):
    db, tools = db_and_tools
    tools.manage_watchlist("add", "NVDA")
    tools.manage_watchlist("add", "AAPL")
    result = tools.manage_watchlist("remove", "NVDA")
    assert "移除" in result or "removed" in result.lower()
    user = db.get_user("user_123")
    wl = json.loads(user["watchlist_json"])
    assert "NVDA" not in wl
    assert "AAPL" in wl

def test_manage_watchlist_list(db_and_tools):
    db, tools = db_and_tools
    tools.manage_watchlist("add", "AAPL")
    tools.manage_watchlist("add", "KO")
    result = tools.manage_watchlist("list", "")
    assert "AAPL" in result
    assert "KO" in result

def test_get_card_not_found(db_and_tools):
    _, tools = db_and_tools
    result = tools.get_card("AAPL")
    assert "未找到" in result or "没有" in result
```

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/agent/test_tools.py -v
```
Expected: `ModuleNotFoundError: No module named 'agent.tools'`

**Step 3: Implement tools.py**

```python
# agent/tools.py
import json
import logging
from typing import List, Dict, Any, Optional
from agent.db import AgentDB

logger = logging.getLogger(__name__)


class AgentTools:
    """Tool implementations callable by Claude agent."""

    def __init__(self, db: AgentDB, user_id: str):
        self.db = db
        self.user_id = user_id

    def get_scan_results(self) -> str:
        """Return latest scan results as formatted text."""
        results = self.db.get_latest_scan_results()
        if not results:
            return "暂无扫描结果。扫描任务通常在每日17:00后完成。"
        lines = [f"**最新扫描结果**（共 {len(results)} 个信号）\n"]
        for r in results[:10]:  # cap at 10 in message
            ticker = r.get("ticker", "")
            strategy = r.get("strategy", "")
            reason = r.get("trigger_reason", "")
            action = r.get("action", "")
            lines.append(f"- **{ticker}** [{strategy}]")
            if reason:
                lines.append(f"  触发: {reason}")
            if action:
                lines.append(f"  建议: {action}")
        return "\n".join(lines)

    def get_card(self, ticker: str) -> str:
        """Return opportunity card details for a specific ticker."""
        results = self.db.get_latest_scan_results()
        if not results:
            return f"未找到 {ticker} 的卡片，暂无扫描结果。"
        ticker = ticker.upper()
        matches = [r for r in results if r.get("ticker", "").upper() == ticker]
        if not matches:
            return f"未找到 {ticker} 的机会卡片。今日信号中没有该标的。"
        card = matches[0]
        lines = [
            f"**{ticker} · {card.get('strategy','')}**",
            f"触发: {card.get('trigger_reason','')}",
            f"建议: {card.get('action','')}",
            f"逻辑: {card.get('one_line_logic','')}",
        ]
        v = card.get("valuation", {})
        if v:
            lines.append(
                f"估值: 铁底 ${v.get('iron_floor','—')} | 公允价 ${v.get('fair_value','—')}"
            )
            if v.get("logic_summary"):
                lines.append(f"  {v['logic_summary']}")
        if card.get("take_profit"):
            lines.append(f"止盈: {card['take_profit']}")
        if card.get("stop_loss"):
            lines.append(f"止损: {card['stop_loss']}")
        return "\n".join(lines)

    def manage_watchlist(self, action: str, ticker: str) -> str:
        """Add, remove, or list watchlist tickers."""
        user = self.db.get_user(self.user_id)
        if not user:
            return "用户未找到。"
        watchlist: List[str] = json.loads(user.get("watchlist_json") or "[]")
        ticker = ticker.upper().strip()

        if action == "add":
            if ticker and ticker not in watchlist:
                watchlist.append(ticker)
                self.db.update_watchlist(self.user_id, watchlist)
            return f"已加入 {ticker}。当前标的池: {', '.join(watchlist)}"

        elif action == "remove":
            if ticker in watchlist:
                watchlist.remove(ticker)
                self.db.update_watchlist(self.user_id, watchlist)
                return f"已移除 {ticker}。当前标的池: {', '.join(watchlist) or '（空）'}"
            return f"{ticker} 不在标的池中。"

        elif action == "list":
            if not watchlist:
                return "标的池为空。发送「加入 AAPL」来添加标的。"
            return f"当前标的池（{len(watchlist)} 个）: {', '.join(watchlist)}"

        return "未知操作。支持: add / remove / list"

    def trigger_scan(self) -> str:
        """Acknowledge scan trigger request (actual trigger via API key endpoint)."""
        # Phase 1: inform user — actual remote trigger is out of scope
        return "扫描触发请求已记录。下次定时扫描将在今日17:00执行。如需立即扫描，请在本地手动运行。"


# Claude tool definitions (passed to messages.create)
TOOL_DEFINITIONS = [
    {
        "name": "get_scan_results",
        "description": "获取最新市场扫描结果和机会卡片列表",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_card",
        "description": "获取特定标的的详细机会卡片，包含估值、止盈止损",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "股票代码，如 AAPL、NVDA",
                }
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "manage_watchlist",
        "description": "管理用户自选标的池：加入、移除、查看列表",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "remove", "list"],
                    "description": "操作类型",
                },
                "ticker": {
                    "type": "string",
                    "description": "股票代码（list 操作时可为空字符串）",
                },
            },
            "required": ["action", "ticker"],
        },
    },
    {
        "name": "trigger_scan",
        "description": "请求触发一次立即扫描",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/agent/test_tools.py -v
```
Expected: 6 passed

**Step 5: Commit**

```bash
git add agent/tools.py tests/agent/test_tools.py
git commit -m "feat: add agent tools layer (scan results, card lookup, watchlist)"
```

---

### Task 5: Claude agent (tool use conversation engine)

**Files:**
- Create: `agent/claude_agent.py`
- Create: `tests/agent/test_claude_agent.py`

**Step 1: Write the failing tests**

```python
# tests/agent/test_claude_agent.py
import pytest
import json
from unittest.mock import MagicMock, patch
from agent.db import AgentDB
from agent.claude_agent import ClaudeAgent

@pytest.fixture
def agent(tmp_path):
    db = AgentDB(str(tmp_path / "agent.db"))
    db.save_user("user_123")
    db.save_scan_results("2026-03-06", [
        {"ticker": "AAPL", "strategy": "SELL_PUT",
         "trigger_reason": "跌入便宜区间", "action": "卖出 $170 Put",
         "one_line_logic": "安全垫充足", "valuation": {}}
    ])
    a = ClaudeAgent(
        db=db,
        api_key="sk-test",
        model="claude-haiku-4-5-20251001",
    )
    yield a
    db.close()

def _mock_text_response(text: str):
    msg = MagicMock()
    msg.stop_reason = "end_turn"
    content = MagicMock()
    content.type = "text"
    content.text = text
    msg.content = [content]
    return msg

def _mock_tool_response(tool_name: str, tool_input: dict, tool_use_id: str = "tu_1"):
    msg = MagicMock()
    msg.stop_reason = "tool_use"
    content = MagicMock()
    content.type = "tool_use"
    content.name = tool_name
    content.input = tool_input
    content.id = tool_use_id
    msg.content = [content]
    return msg

def test_process_text_message(agent):
    with patch.object(agent, '_get_client') as mock_fn:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_text_response("今天市场平静。")
        mock_fn.return_value = mock_client

        reply = agent.process("user_123", "你好")
        assert isinstance(reply, str)
        assert len(reply) > 0

def test_process_calls_tool_and_returns_result(agent):
    with patch.object(agent, '_get_client') as mock_fn:
        mock_client = MagicMock()
        # First call: Claude requests tool use
        # Second call: Claude returns final text
        mock_client.messages.create.side_effect = [
            _mock_tool_response("get_scan_results", {}),
            _mock_text_response("今天有 1 个信号: AAPL Sell Put。"),
        ]
        mock_fn.return_value = mock_client

        reply = agent.process("user_123", "今天有什么信号")
        assert "AAPL" in reply or "信号" in reply
        assert mock_client.messages.create.call_count == 2

def test_conversation_history_persisted(agent):
    with patch.object(agent, '_get_client') as mock_fn:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_text_response("好的。")
        mock_fn.return_value = mock_client

        agent.process("user_123", "你好")
        history = agent.db.get_history("user_123")
        assert len(history) == 2  # user + assistant
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"
```

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/agent/test_claude_agent.py -v
```
Expected: `ModuleNotFoundError: No module named 'agent.claude_agent'`

**Step 3: Implement ClaudeAgent**

```python
# agent/claude_agent.py
import logging
import os
from typing import Optional
from agent.db import AgentDB
from agent.tools import AgentTools, TOOL_DEFINITIONS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是交易领航员，一个专业的量化交易助手。
你帮助用户：
- 查看每日市场扫描信号和机会卡片
- 分析持仓风险
- 管理自选标的池
- 回答交易策略问题

回复简洁，使用中文，重要数字加粗。不提供具体买卖建议，只陈述数据和分析。"""


class ClaudeAgent:
    def __init__(self, db: AgentDB, api_key: str, model: str = "claude-opus-4-6"):
        self.db = db
        self.api_key = api_key
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            import httpx
            self._client = anthropic.Anthropic(
                api_key=self.api_key,
                http_client=httpx.Client(verify=False),
            )
        return self._client

    def process(self, user_id: str, user_message: str) -> str:
        """Process a user message, execute tools if needed, return reply text."""
        # Ensure user exists
        if not self.db.get_user(user_id):
            self.db.save_user(user_id)

        # Save user message
        self.db.add_message(user_id, "user", user_message)

        # Build message history for Claude
        history = self.db.get_history(user_id, limit=20)
        # history already includes the message we just saved
        messages = [{"role": m["role"], "content": m["content"]} for m in history]

        tools_instance = AgentTools(self.db, user_id=user_id)

        try:
            reply = self._run_tool_loop(messages, tools_instance)
        except Exception as e:
            logger.warning(f"Claude agent error for {user_id}: {e}")
            reply = "抱歉，处理请求时出错，请稍后重试。"

        self.db.add_message(user_id, "assistant", reply)
        return reply

    def _run_tool_loop(self, messages: list, tools: AgentTools) -> str:
        """Run Claude with tool use, handling up to 5 tool calls."""
        client = self._get_client()
        loop_messages = list(messages)

        for _ in range(5):  # max 5 tool calls per turn
            response = client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=loop_messages,
            )

            if response.stop_reason == "end_turn":
                # Extract text from response
                for block in response.content:
                    if block.type == "text":
                        return block.text
                return "（无回复）"

            if response.stop_reason == "tool_use":
                # Execute all tool calls in this response
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = self._execute_tool(block.name, block.input, tools)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                # Append assistant turn + tool results to messages
                loop_messages.append({
                    "role": "assistant",
                    "content": response.content,
                })
                loop_messages.append({
                    "role": "user",
                    "content": tool_results,
                })
                continue

            break  # unexpected stop reason

        return "处理超时，请重试。"

    def _execute_tool(self, name: str, inputs: dict, tools: AgentTools) -> str:
        """Dispatch tool call to AgentTools."""
        try:
            if name == "get_scan_results":
                return tools.get_scan_results()
            elif name == "get_card":
                return tools.get_card(inputs.get("ticker", ""))
            elif name == "manage_watchlist":
                return tools.manage_watchlist(
                    inputs.get("action", "list"),
                    inputs.get("ticker", ""),
                )
            elif name == "trigger_scan":
                return tools.trigger_scan()
            else:
                return f"未知工具: {name}"
        except Exception as e:
            logger.warning(f"Tool {name} failed: {e}")
            return f"工具执行失败: {e}"
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/agent/test_claude_agent.py -v
```
Expected: 3 passed

**Step 5: Commit**

```bash
git add agent/claude_agent.py tests/agent/test_claude_agent.py
git commit -m "feat: add Claude tool use agent with conversation history"
```

---

### Task 6: DingTalk webhook endpoint (wire everything together)

**Files:**
- Modify: `agent/main.py`
- Create: `agent/config.py`
- Create: `tests/agent/test_webhook.py`

**Step 1: Write the failing test**

```python
# tests/agent/test_webhook.py
import pytest
import json
import hmac, hashlib, base64, time
from fastapi.testclient import TestClient
from unittest.mock import patch

APP_SECRET = "test_secret"

def _make_headers(secret=APP_SECRET):
    ts = str(int(time.time() * 1000))
    msg = f"{ts}\n{secret}"
    mac = hmac.new(secret.encode(), msg.encode(), digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(mac).decode()
    return {"timestamp": ts, "sign": sign}

def _make_payload(text: str, user_id="user_123"):
    return {
        "msgtype": "text",
        "text": {"content": text},
        "senderId": user_id,
        "senderNick": "张三",
        "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?session=test",
        "sessionWebhookExpiredTime": int(time.time() * 1000) + 60000,
        "conversationId": "cid_test",
    }

def test_webhook_processes_message(tmp_path):
    import os
    os.environ["AGENT_DB_PATH"] = str(tmp_path / "agent.db")
    os.environ["DINGTALK_APP_SECRET"] = APP_SECRET
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"

    from agent.main import app
    client = TestClient(app)

    with patch("agent.main.claude_agent") as mock_agent:
        mock_agent.process.return_value = "今天有 1 个信号。"

        with patch("agent.dingtalk.send_reply", return_value=True):
            resp = client.post(
                "/dingtalk/webhook",
                json=_make_payload("今天有什么信号"),
                headers=_make_headers(),
            )
    assert resp.status_code == 200

def test_webhook_rejects_bad_signature(tmp_path):
    import os
    os.environ["AGENT_DB_PATH"] = str(tmp_path / "agent.db")
    os.environ["DINGTALK_APP_SECRET"] = APP_SECRET

    from agent.main import app
    client = TestClient(app)

    resp = client.post(
        "/dingtalk/webhook",
        json=_make_payload("hi"),
        headers={"timestamp": "123", "sign": "badsign"},
    )
    assert resp.status_code == 403
```

**Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/agent/test_webhook.py -v
```
Expected: FAIL (no /dingtalk/webhook endpoint)

**Step 3: Add config + wire webhook into main.py**

```python
# agent/config.py
import os
from dotenv import load_dotenv

load_dotenv()

def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)
```

Replace `agent/main.py` with:

```python
# agent/main.py
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from agent import config
from agent.db import AgentDB
from agent.dingtalk import verify_signature, parse_incoming, send_reply
from agent.claude_agent import ClaudeAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Module-level singletons (initialized on startup)
db: AgentDB = None
claude_agent: ClaudeAgent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, claude_agent
    db_path = config.get("AGENT_DB_PATH", "data/agent.db")
    os.makedirs(os.path.dirname(db_path) if "/" in db_path else ".", exist_ok=True)
    db = AgentDB(db_path)
    claude_agent = ClaudeAgent(
        db=db,
        api_key=config.get("ANTHROPIC_API_KEY"),
        model=config.get("CLAUDE_MODEL", "claude-opus-4-6"),
    )
    logger.info("Agent started")
    yield
    db.close()


app = FastAPI(title="交易领航员 Agent", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/dingtalk/webhook")
async def dingtalk_webhook(request: Request):
    # Signature verification
    timestamp = request.headers.get("timestamp", "")
    sign = request.headers.get("sign", "")
    app_secret = config.get("DINGTALK_APP_SECRET")

    if app_secret and not verify_signature(timestamp, sign, app_secret):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()
    msg = parse_incoming(payload)

    if not msg["text"]:
        return JSONResponse({"ok": True})

    # Process async: reply quickly, process in background
    try:
        reply = claude_agent.process(msg["user_id"], msg["text"])
        send_reply(msg["session_webhook"], reply)
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        send_reply(msg["session_webhook"], "处理出错，请稍后重试。")

    return JSONResponse({"ok": True})
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/agent/ -v
```
Expected: all pass

**Step 5: Commit**

```bash
git add agent/main.py agent/config.py tests/agent/test_webhook.py
git commit -m "feat: wire DingTalk webhook to Claude agent with signature verification"
```

---

### Task 7: Scan results push endpoint

**Files:**
- Modify: `agent/main.py`
- Modify: `src/main.py`
- Create: `tests/agent/test_scan_push.py`

**Step 1: Write the failing test**

```python
# tests/agent/test_scan_push.py
import pytest
import os
from fastapi.testclient import TestClient

SCAN_API_KEY = "test-api-key-123"

def test_push_scan_results(tmp_path):
    os.environ["AGENT_DB_PATH"] = str(tmp_path / "agent.db")
    os.environ["SCAN_API_KEY"] = SCAN_API_KEY
    os.environ["DINGTALK_APP_SECRET"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"

    from agent.main import app
    client = TestClient(app)

    payload = {
        "scan_date": "2026-03-06",
        "results": [
            {"ticker": "AAPL", "strategy": "SELL_PUT",
             "trigger_reason": "跌入便宜区间"}
        ],
    }
    resp = client.post(
        "/api/scan_results",
        json=payload,
        headers={"X-API-Key": SCAN_API_KEY},
    )
    assert resp.status_code == 200
    assert resp.json()["saved"] == 1

def test_push_scan_results_rejects_bad_key(tmp_path):
    os.environ["AGENT_DB_PATH"] = str(tmp_path / "agent.db")
    os.environ["SCAN_API_KEY"] = SCAN_API_KEY
    os.environ["DINGTALK_APP_SECRET"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"

    from agent.main import app
    client = TestClient(app)

    resp = client.post(
        "/api/scan_results",
        json={"scan_date": "2026-03-06", "results": []},
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 403
```

**Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/agent/test_scan_push.py -v
```
Expected: FAIL (no /api/scan_results endpoint)

**Step 3: Add scan push endpoint to agent/main.py**

Add after the `/dingtalk/webhook` route:

```python
from pydantic import BaseModel
from typing import List, Any

class ScanResultsPayload(BaseModel):
    scan_date: str
    results: List[Any]

@app.post("/api/scan_results")
async def push_scan_results(payload: ScanResultsPayload, request: Request):
    api_key = config.get("SCAN_API_KEY")
    if api_key and request.headers.get("X-API-Key") != api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")

    db.save_scan_results(payload.scan_date, payload.results)
    logger.info(f"Scan results saved: {payload.scan_date}, {len(payload.results)} signals")
    return {"saved": len(payload.results), "scan_date": payload.scan_date}
```

**Step 4: Add push call to src/main.py**

In `src/main.py`, after generating the report (Step 6), add:

```python
# Step 6.5: Push scan results to cloud agent (if configured)
agent_url = config.get("agent", {}).get("url", "")
agent_api_key = config.get("agent", {}).get("api_key", "")
if agent_url and sell_put_results:
    try:
        import requests as req_lib
        cards_payload = [
            {
                "ticker": signal.ticker,
                "strategy": "SELL_PUT",
                "trigger_reason": f"行权价 ${signal.strike}, 年化 {signal.apy:.1f}%",
                "action": f"卖出 ${signal.strike} Put, DTE {signal.dte}",
            }
            for signal, _ in sell_put_results
        ]
        req_lib.post(
            f"{agent_url}/api/scan_results",
            json={"scan_date": str(today), "results": cards_payload},
            headers={"X-API-Key": agent_api_key},
            verify=False,
            timeout=10,
        )
        logger.info(f"Pushed {len(cards_payload)} results to agent")
    except Exception as e:
        logger.warning(f"Agent push failed: {e}")
```

Add to `config.yaml`:
```yaml
agent:
  url: ""          # e.g. https://your-app.fly.dev
  api_key: ""      # SCAN_API_KEY
```

**Step 5: Run all agent tests**

```bash
python3 -m pytest tests/agent/ -v
```
Expected: all pass

**Step 6: Commit**

```bash
git add agent/main.py tests/agent/test_scan_push.py src/main.py config.yaml
git commit -m "feat: add scan results push endpoint and src/main.py integration"
```

---

### Task 8: Fly.io deployment config

**Files:**
- Create: `Dockerfile.agent`
- Create: `fly.toml`
- Create: `.env.agent.example`

**Step 1: No tests needed (deployment config) — create files directly**

```dockerfile
# Dockerfile.agent
FROM python:3.11-slim

WORKDIR /app
COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ ./agent/
COPY src/ ./src/

RUN mkdir -p /data

CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

```toml
# fly.toml
app = "trading-agent"
primary_region = "nrt"   # Tokyo — closest to HK/CN

[build]
  dockerfile = "Dockerfile.agent"

[env]
  AGENT_DB_PATH = "/data/agent.db"
  CLAUDE_MODEL = "claude-opus-4-6"

[mounts]
  source = "agent_data"
  destination = "/data"

[[services]]
  internal_port = 8080
  protocol = "tcp"

  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]

  [[services.ports]]
    port = 80
    handlers = ["http"]

  [services.concurrency]
    type = "connections"
    hard_limit = 25
    soft_limit = 20
```

```bash
# .env.agent.example
ANTHROPIC_API_KEY=sk-ant-xxx
DINGTALK_APP_SECRET=your_dingtalk_app_secret
SCAN_API_KEY=generate_a_random_key_here
AGENT_DB_PATH=/data/agent.db
CLAUDE_MODEL=claude-opus-4-6
```

**Step 2: Deploy instructions**

```bash
# Install flyctl
brew install flyctl

# Login and create app
flyctl auth login
flyctl launch --no-deploy --name trading-agent

# Create persistent volume (1GB)
flyctl volumes create agent_data --size 1 --region nrt

# Set secrets
flyctl secrets set ANTHROPIC_API_KEY=sk-ant-xxx
flyctl secrets set DINGTALK_APP_SECRET=your_secret
flyctl secrets set SCAN_API_KEY=$(openssl rand -hex 16)

# Deploy
flyctl deploy --dockerfile Dockerfile.agent

# Get public URL
flyctl status
```

After deploy, set `agent.url` in `config.yaml` to your Fly.io URL, and `agent.api_key` to the `SCAN_API_KEY` you set.

**Step 3: Verify health endpoint**

```bash
curl https://trading-agent.fly.dev/health
# Expected: {"status": "ok"}
```

**Step 4: Commit**

```bash
git add Dockerfile.agent fly.toml .env.agent.example
git commit -m "feat: add Fly.io deployment config for agent service"
```

---

## DingTalk Bot Setup (One-Time)

After deployment, register the bot in DingTalk:

1. Go to [DingTalk Open Platform](https://open.dingtalk.com/) → Create App → Robot
2. Set **Message Receive Mode** → HTTP mode
3. Set **Request URL**: `https://trading-agent.fly.dev/dingtalk/webhook`
4. Copy **AppSecret** → `flyctl secrets set DINGTALK_APP_SECRET=xxx`
5. Add the bot to your group chat
6. Test: send "今天有什么信号" in the group, @bot

---

Plan complete and saved to `docs/plans/2026-03-06-agent-platform.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, you review between tasks, fast iteration

**2. Parallel Session (separate)** — Open a new session with executing-plans, batch execution with checkpoints

Which approach?
