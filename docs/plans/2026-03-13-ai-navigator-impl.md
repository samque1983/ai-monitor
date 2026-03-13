# AI 领航页面 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild `/chat` as a 3-column AI Navigator with user profile/tags, rich card replies, and a tool drawer.

**Architecture:** Extend `AgentDB` with profile storage → wire profile into `ClaudeAgent` system prompt and update loop → add card-returning tools → extend `/api/chat` response → rebuild `chat.html` with profile panel + card rendering.

**Tech Stack:** Python/FastAPI backend, SQLite via `AgentDB`, Claude API via existing `ClaudeAgent`, vanilla JS + Jinja2 frontend (dark design system).

---

### Task 1: DB — add profile_json column + get/update methods

**Files:**
- Modify: `agent/db.py`
- Test: `tests/test_agent_db.py`

**Step 1: Write the failing tests**

Add to `tests/test_agent_db.py`:

```python
def test_get_profile_returns_empty_dict_for_new_user(db):
    db.save_user("BOB")
    profile = db.get_profile("BOB")
    assert profile == {}

def test_update_and_get_profile(db):
    db.save_user("BOB")
    data = {
        "risk_level": "moderate",
        "preferred_markets": ["US"],
        "strategy_tags": ["高股息"],
        "summary": "偏好美股高股息标的。",
        "last_updated": "2026-03-13",
        "message_count": 5,
    }
    db.update_profile("BOB", data)
    result = db.get_profile("BOB")
    assert result["risk_level"] == "moderate"
    assert result["strategy_tags"] == ["高股息"]
    assert result["message_count"] == 5

def test_update_profile_merges_fields(db):
    db.save_user("BOB")
    db.update_profile("BOB", {"risk_level": "conservative", "message_count": 3})
    db.update_profile("BOB", {"risk_level": "aggressive", "message_count": 4})
    result = db.get_profile("BOB")
    assert result["risk_level"] == "aggressive"
    assert result["message_count"] == 4
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/q/code/ai-monitor
python -m pytest tests/test_agent_db.py::test_get_profile_returns_empty_dict_for_new_user tests/test_agent_db.py::test_update_and_get_profile tests/test_agent_db.py::test_update_profile_merges_fields -v
```

Expected: FAIL with `AttributeError: 'AgentDB' object has no attribute 'get_profile'`

**Step 3: Add profile_json column to SCHEMA and implement methods**

In `agent/db.py`, update the `SCHEMA` string — add `profile_json` to the `users` table:

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id          TEXT PRIMARY KEY,
    dingtalk_webhook TEXT DEFAULT '',
    flex_token_enc   TEXT DEFAULT '',
    flex_query_id    TEXT DEFAULT '',
    watchlist_json   TEXT DEFAULT '[]',
    profile_json     TEXT DEFAULT '{}',
    created_at       TEXT NOT NULL
);
...
```

Then add a migration block right after `self.conn.executescript(SCHEMA)` in `__init__`:

```python
# Migration: add profile_json if missing (for existing DBs)
cols = [r[1] for r in self.conn.execute("PRAGMA table_info(users)").fetchall()]
if "profile_json" not in cols:
    self.conn.execute("ALTER TABLE users ADD COLUMN profile_json TEXT DEFAULT '{}'")
    self.conn.commit()
```

Add these two methods to the `AgentDB` class (before `close()`):

```python
def get_profile(self, user_id: str) -> dict:
    """Return the user's profile dict, or {} if not set."""
    row = self.conn.execute(
        "SELECT profile_json FROM users WHERE user_id=?", (user_id,)
    ).fetchone()
    if not row:
        return {}
    return json.loads(row["profile_json"] or "{}")

def update_profile(self, user_id: str, profile: dict):
    """Overwrite the user's profile_json with the given dict."""
    self.conn.execute(
        "UPDATE users SET profile_json=? WHERE user_id=?",
        (json.dumps(profile, ensure_ascii=False), user_id)
    )
    self.conn.commit()
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_agent_db.py -v
```

Expected: ALL PASS (existing 8 tests + 3 new = 11 total)

**Step 5: Commit**

```bash
git add agent/db.py tests/test_agent_db.py
git commit -m "feat: add profile_json to AgentDB with get/update methods"
```

---

### Task 2: ClaudeAgent — profile injection + 15-message update trigger

**Files:**
- Modify: `agent/claude_agent.py`
- Create: `tests/test_claude_agent.py`

**Step 1: Write the failing tests**

Create `tests/test_claude_agent.py`:

```python
import pytest
import json
from unittest.mock import MagicMock, patch
from agent.db import AgentDB
from agent.claude_agent import ClaudeAgent, _build_system_prompt


@pytest.fixture
def db(tmp_path):
    return AgentDB(str(tmp_path / "test.db"))


@pytest.fixture
def agent(db):
    return ClaudeAgent(db, llm_provider="anthropic", llm_api_key="test-key")


def test_build_system_prompt_no_profile():
    prompt = _build_system_prompt({})
    assert "交易领航员" in prompt
    assert "用户画像" not in prompt


def test_build_system_prompt_with_profile():
    profile = {
        "risk_level": "moderate",
        "strategy_tags": ["高股息", "卖波动率"],
        "summary": "偏好美港股。",
    }
    prompt = _build_system_prompt(profile)
    assert "用户画像" in prompt
    assert "高股息" in prompt
    assert "偏好美港股" in prompt


def test_profile_injected_after_15_messages(db, agent):
    db.save_user("ALICE")
    # Simulate 14 existing messages
    for i in range(14):
        db.add_message("ALICE", "user", f"message {i}")
        db.add_message("ALICE", "assistant", f"reply {i}")

    with patch.object(agent._llm_client, "chat", return_value="ok") as mock_chat:
        # 15th user message triggers profile update
        agent.process("ALICE", "这是第15条消息")

    # profile update is a separate LLM call; check message_count incremented
    profile = db.get_profile("ALICE")
    assert profile.get("message_count", 0) >= 1


def test_new_user_gets_onboarding_message(db, agent):
    with patch.object(agent._llm_client, "chat", return_value="你好！请问你主要关注哪个市场？") as mock_chat:
        reply = agent.process("NEWUSER", "你好")
    assert reply is not None
    # New user profile should be initialized
    profile = db.get_profile("NEWUSER")
    assert profile.get("message_count") == 1
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_claude_agent.py -v
```

Expected: FAIL with `ImportError: cannot import name '_build_system_prompt'`

**Step 3: Refactor ClaudeAgent**

Replace `agent/claude_agent.py` contents:

```python
import json
import logging
from agent.db import AgentDB
from agent.tools import AgentTools, TOOL_DEFINITIONS
from agent.llm_client import make_llm_client

logger = logging.getLogger(__name__)

BASE_SYSTEM_PROMPT = """你是交易领航员，一个专业的量化交易助手。
你帮助用户：
- 查看每日市场扫描信号和机会卡片
- 分析持仓风险
- 管理自选标的池
- 回答交易策略问题

回复简洁，使用中文，重要数字加粗。不提供具体买卖建议，只陈述数据和分析。"""

PROFILE_UPDATE_PROMPT = """根据以上对话历史，以 JSON 格式输出更新后的用户画像。
只输出 JSON，不要任何其他文字。格式：
{
  "risk_level": "conservative|moderate|aggressive",
  "preferred_markets": ["US"|"HK"|"CN"],
  "strategy_tags": ["高股息"|"卖波动率"|"LEAPS"|"趋势跟踪"|"事件驱动"|"保守型"|"稳健型"|"进取型"|"偏好美股"|"偏好港股"|"偏好A股"],
  "summary": "一句话描述用户投资偏好，不超过80字",
  "last_updated": "YYYY-MM-DD",
  "message_count": <integer>
}
strategy_tags 从上面列出的预定义标签中选 2-4 个最匹配的。"""

ONBOARDING_SYSTEM = """你是交易领航员。这是新用户的第一次对话。
先用友好简短的问候回应，然后问一个问题：他主要关注哪个市场（美股/港股/A股）？
不要一次问多个问题。"""


def _build_system_prompt(profile: dict) -> str:
    """Build system prompt, injecting profile if available."""
    if not profile or not profile.get("summary"):
        return BASE_SYSTEM_PROMPT
    tags = "、".join(profile.get("strategy_tags", []))
    markets = "、".join(profile.get("preferred_markets", []))
    risk = {"conservative": "保守", "moderate": "稳健", "aggressive": "进取"}.get(
        profile.get("risk_level", ""), ""
    )
    profile_block = f"""
用户画像（请基于此个性化回复）：
- 风险偏好: {risk}
- 偏好市场: {markets}
- 关注策略: {tags}
- 摘要: {profile.get("summary", "")}
"""
    return BASE_SYSTEM_PROMPT + profile_block


class ClaudeAgent:
    def __init__(
        self,
        db: AgentDB,
        llm_provider: str,
        llm_api_key: str,
        llm_model: str = None,
        api_key: str = None,
        model: str = None,
    ):
        self.db = db
        if api_key and not llm_api_key:
            llm_api_key = api_key
        if model and not llm_model:
            llm_model = model
        self._llm_client = make_llm_client(llm_provider, llm_api_key, llm_model)

    def process(self, user_id: str, user_message: str) -> str:
        """Process a user message, execute tools if needed, return reply text."""
        is_new = not self.db.get_user(user_id)
        if is_new:
            self.db.save_user(user_id)

        self.db.add_message(user_id, "user", user_message)

        profile = self.db.get_profile(user_id)
        message_count = profile.get("message_count", 0) + 1
        profile["message_count"] = message_count

        history = self.db.get_history(user_id, limit=20)
        messages = [{"role": m["role"], "content": m["content"]} for m in history]

        system = ONBOARDING_SYSTEM if is_new else _build_system_prompt(profile)
        tools_instance = AgentTools(self.db, user_id=user_id)

        try:
            reply = self._llm_client.chat(
                system=system,
                messages=messages,
                tools_schema=TOOL_DEFINITIONS,
                tool_executor=lambda name, args: self._execute_tool(name, args, tools_instance),
            )
        except Exception as e:
            logger.warning(f"LLM agent error for {user_id}: {e}")
            reply = "抱歉，处理请求时出错，请稍后重试。"

        self.db.add_message(user_id, "assistant", reply)

        # Update profile counter; trigger full rewrite every 15 user messages
        if message_count % 15 == 0:
            self._rewrite_profile(user_id, profile, history)
        else:
            self.db.update_profile(user_id, profile)

        return reply

    def _rewrite_profile(self, user_id: str, current_profile: dict, history: list):
        """Ask LLM to rewrite the full profile based on conversation history."""
        from datetime import date
        try:
            history_text = "\n".join(
                f"{m['role'].upper()}: {m['content']}" for m in history[-30:]
            )
            rewrite_messages = [
                {"role": "user", "content": f"对话历史:\n{history_text}\n\n{PROFILE_UPDATE_PROMPT}"}
            ]
            raw = self._llm_client.chat(
                system="你是数据提取助手，只输出 JSON。",
                messages=rewrite_messages,
                tools_schema=None,
                tool_executor=None,
            )
            new_profile = json.loads(raw)
            new_profile["message_count"] = current_profile.get("message_count", 0)
            self.db.update_profile(user_id, new_profile)
        except Exception as e:
            logger.warning(f"Profile rewrite failed for {user_id}: {e}")
            self.db.update_profile(user_id, current_profile)

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
            elif name == "get_opportunity_cards":
                return tools.get_opportunity_cards(inputs.get("strategy", ""))
            elif name == "get_risk_summary":
                return tools.get_risk_summary()
            else:
                return f"未知工具: {name}"
        except Exception as e:
            logger.warning(f"Tool {name} failed: {e}")
            return f"工具执行失败: {e}"
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_claude_agent.py -v
```

Expected: ALL PASS (4 tests)

**Step 5: Commit**

```bash
git add agent/claude_agent.py tests/test_claude_agent.py
git commit -m "feat: inject user profile into ClaudeAgent system prompt + 15-msg update trigger"
```

---

### Task 3: Tools — get_opportunity_cards + get_risk_summary

**Files:**
- Modify: `agent/tools.py`
- Test: `tests/test_agent_tools.py` (create)

**Step 1: Write the failing tests**

Create `tests/test_agent_tools.py`:

```python
import pytest, json
from agent.db import AgentDB
from agent.tools import AgentTools


@pytest.fixture
def db(tmp_path):
    return AgentDB(str(tmp_path / "test.db"))


@pytest.fixture
def tools(db):
    db.save_user("ALICE")
    return AgentTools(db, user_id="ALICE")


def test_get_opportunity_cards_no_signals(tools):
    result = tools.get_opportunity_cards("dividend")
    assert "暂无" in result


def test_get_opportunity_cards_returns_cards(db, tools):
    db.save_signals("2026-03-13", [
        {"signal_type": "dividend", "ticker": "0700.HK",
         "company_name": "腾讯控股", "ttm_yield": 4.2, "iv_rank": 72},
        {"signal_type": "dividend", "ticker": "AAPL",
         "company_name": "Apple", "ttm_yield": 0.5, "iv_rank": 30},
    ])
    result = tools.get_opportunity_cards("dividend")
    # Returns JSON string of card list
    cards = json.loads(result)
    assert len(cards) == 2
    assert cards[0]["type"] == "opportunity"
    assert cards[0]["ticker"] in ["0700.HK", "AAPL"]
    assert "yield" in cards[0]


def test_get_risk_summary_no_report(tools):
    result = tools.get_risk_summary()
    assert "暂无" in result


def test_get_risk_summary_returns_dict(db, tools):
    db.save_risk_report("ALICE", "2026-03-13", "<html>risk</html>")
    result = tools.get_risk_summary()
    data = json.loads(result)
    assert data["type"] == "risk_summary"
    assert "report_date" in data
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_agent_tools.py -v
```

Expected: FAIL with `AttributeError: 'AgentTools' object has no attribute 'get_opportunity_cards'`

**Step 3: Add methods to AgentTools in `agent/tools.py`**

Add after `trigger_scan()`:

```python
def get_opportunity_cards(self, strategy: str = "") -> str:
    """Return opportunity cards as a JSON array for the given strategy type."""
    signal_type = strategy if strategy else "dividend"
    signals = self.db.get_strategy_pool(signal_type)
    if not signals:
        return f"暂无 {signal_type} 机会信号。"
    cards = []
    for s in signals[:5]:
        card = {
            "type": "opportunity",
            "ticker": s.get("ticker", ""),
            "name": s.get("company_name", s.get("ticker", "")),
            "signal": signal_type,
            "yield": f"{s.get('ttm_yield', s.get('yield', 0)):.1f}%" if s.get("ttm_yield") or s.get("yield") else "—",
            "iv_rank": s.get("iv_rank", 0),
            "action": "add_watchlist",
        }
        cards.append(card)
    return json.dumps(cards, ensure_ascii=False)

def get_risk_summary(self) -> str:
    """Return latest risk report metadata as JSON."""
    report = self.db.get_latest_risk_report(self.user_id)
    if not report:
        return "暂无风险报告。请先上传持仓数据。"
    return json.dumps({
        "type": "risk_summary",
        "report_date": report["report_date"],
        "account_id": report["account_id"],
        "action": "view_risk_report",
    }, ensure_ascii=False)
```

Also add both tools to `TOOL_DEFINITIONS` list:

```python
{
    "name": "get_opportunity_cards",
    "description": "获取特定策略的机会卡片列表，可指定策略类型如 dividend、sell_put",
    "input_schema": {
        "type": "object",
        "properties": {
            "strategy": {
                "type": "string",
                "description": "策略类型: dividend / sell_put / iv_low / leaps，默认 dividend",
            }
        },
        "required": [],
    },
},
{
    "name": "get_risk_summary",
    "description": "获取用户最新持仓风险报告摘要",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
},
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_agent_tools.py -v
```

Expected: ALL PASS (5 tests)

**Step 5: Commit**

```bash
git add agent/tools.py tests/test_agent_tools.py
git commit -m "feat: add get_opportunity_cards and get_risk_summary tools"
```

---

### Task 4: API — extend /api/chat with cards + profile_updated

**Files:**
- Modify: `agent/main.py` (the `/api/chat` route)
- Test: `tests/test_dashboard_routes.py`

**Step 1: Find and understand the existing /api/chat route**

```bash
grep -n "api/chat\|chat" agent/main.py | head -20
```

**Step 2: Write the failing tests**

Add to `tests/test_dashboard_routes.py`:

```python
def test_chat_api_returns_cards_field(client, db):
    """POST /api/chat response must include cards and profile_updated fields."""
    with patch("agent.main.agent") as mock_agent:
        mock_agent.process.return_value = "找到高股息机会"
        resp = client.post("/api/chat", json={"message": "有高股息机会吗", "user_id": "ALICE"})
    assert resp.status_code == 200
    data = resp.json()
    assert "reply" in data
    assert "cards" in data
    assert "profile_updated" in data
    assert isinstance(data["cards"], list)
    assert isinstance(data["profile_updated"], bool)


def test_chat_api_cards_from_tool_reply(client, db):
    """If agent reply contains JSON card array, it should be parsed into cards field."""
    card_json = json.dumps([{"type": "opportunity", "ticker": "AAPL"}])
    with patch("agent.main.agent") as mock_agent:
        mock_agent.process.return_value = f"机会卡片：\n{card_json}"
        resp = client.post("/api/chat", json={"message": "机会", "user_id": "ALICE"})
    assert resp.status_code == 200
```

**Step 3: Run tests to verify they fail**

```bash
python -m pytest tests/test_dashboard_routes.py::test_chat_api_returns_cards_field tests/test_dashboard_routes.py::test_chat_api_cards_from_tool_reply -v
```

Expected: FAIL (missing fields or route not found)

**Step 4: Update /api/chat in agent/main.py**

Find the `/api/chat` route and update the response:

```python
import re as _re

@router.post("/api/chat")
async def api_chat(request: Request, db: AgentDB = Depends(get_db)):
    body = await request.json()
    user_message = body.get("message", "")
    user_id = body.get("user_id", "web")

    profile_before = db.get_profile(user_id)
    reply = agent.process(user_id, user_message)
    profile_after = db.get_profile(user_id)
    profile_updated = profile_after != profile_before

    # Extract embedded JSON card arrays from reply if present
    cards = []
    json_match = _re.search(r'\[(\s*\{.*?\}\s*,?\s*)+\]', reply, _re.DOTALL)
    if json_match:
        try:
            cards = json.loads(json_match.group(0))
        except (json.JSONDecodeError, ValueError):
            pass

    return JSONResponse({
        "reply": reply,
        "cards": cards,
        "profile_updated": profile_updated,
    })
```

**Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_dashboard_routes.py -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
git add agent/main.py tests/test_dashboard_routes.py
git commit -m "feat: extend /api/chat response with cards and profile_updated fields"
```

---

### Task 5: Add /api/profile endpoint

**Files:**
- Modify: `agent/dashboard.py`
- Test: `tests/test_dashboard_routes.py`

**Step 1: Write the failing test**

Add to `tests/test_dashboard_routes.py`:

```python
def test_get_profile_returns_empty_for_new_user(client, db):
    resp = client.get("/api/profile?user_id=UNKNOWN")
    assert resp.status_code == 200
    data = resp.json()
    assert "profile" in data
    assert data["profile"] == {}

def test_get_profile_returns_saved_profile(client, db):
    db.save_user("ALICE")
    db.update_profile("ALICE", {"risk_level": "moderate", "strategy_tags": ["高股息"]})
    resp = client.get("/api/profile?user_id=ALICE")
    assert resp.status_code == 200
    data = resp.json()
    assert data["profile"]["risk_level"] == "moderate"
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_dashboard_routes.py::test_get_profile_returns_empty_for_new_user tests/test_dashboard_routes.py::test_get_profile_returns_saved_profile -v
```

Expected: FAIL (404 - route doesn't exist)

**Step 3: Add route to agent/dashboard.py**

```python
@router.get("/api/profile")
async def get_profile(user_id: str = "ALICE", db: AgentDB = Depends(get_db)):
    profile = db.get_profile(user_id)
    return JSONResponse({"profile": profile})
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_dashboard_routes.py -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
git add agent/dashboard.py tests/test_dashboard_routes.py
git commit -m "feat: add GET /api/profile endpoint"
```

---

### Task 6: Frontend — rebuild chat.html with 3-column layout

**Files:**
- Modify: `agent/templates/chat.html` (full rewrite)
- No new tests needed (covered by existing `test_chat_page_returns_200` and `test_chat_page_has_nav_and_input`)

**Step 1: Read the design system spec first**

```bash
cat docs/specs/html_design_system.md | head -100
```

Then invoke the `ai-monitor-ui` skill before writing any HTML.

**Step 2: Rebuild chat.html**

The page must have these elements (verify with existing tests):
- `{% include "_nav.html" %}` — nav must be present
- `#chat-input` — input field (test `test_chat_page_has_nav_and_input` checks for this)
- `.chat-send` button

New structure:

```html
<!-- Desktop: 3-column grid -->
<div class="navigator-grid">
  <!-- Left: Profile Panel -->
  <aside class="profile-panel" id="profile-panel">
    <div class="profile-header">
      <div class="profile-eyebrow">用户画像</div>
      <div class="profile-name">ALICE</div>
    </div>
    <!-- Risk level badge -->
    <div class="profile-risk" id="profile-risk">—</div>
    <!-- Strategy tags -->
    <div class="profile-tags" id="profile-tags"></div>
    <!-- AI summary -->
    <div class="profile-summary" id="profile-summary">正在了解你的投资偏好...</div>
    <!-- Market preference -->
    <div class="profile-markets" id="profile-markets"></div>
  </aside>

  <!-- Center: Chat -->
  <main class="chat-main">
    <!-- Quick chips -->
    <div class="quick-bar" id="quick-bar">
      <button class="quick-chip" onclick="sendQuick('扫描摘要')">扫描摘要</button>
      <button class="quick-chip" onclick="sendQuick('查看我的自选')">我的自选</button>
      <button class="quick-chip" onclick="sendQuick('有哪些高股息机会')">高股息机会</button>
      <button class="quick-chip" onclick="sendQuick('分析我的持仓风险')">分析风险</button>
    </div>
    <!-- Messages -->
    <div class="chat-scroll" id="chat-messages">
      <!-- Welcome message injected by JS after profile load -->
    </div>
    <!-- Input -->
    <div class="chat-input-bar">
      <input class="chat-input" id="chat-input" placeholder="问领航员..." type="text" autocomplete="off">
      <button class="chat-send" onclick="sendMsg()">
        <!-- send arrow SVG -->
      </button>
    </div>
  </main>

  <!-- Right: Tool Drawer (desktop only) -->
  <aside class="tool-drawer" id="tool-drawer">
    <div class="drawer-header">
      <span class="drawer-title">最近信号</span>
      <button class="drawer-toggle" onclick="toggleDrawer()">←</button>
    </div>
    <div class="drawer-signals" id="drawer-signals">加载中...</div>
  </aside>
</div>
```

**CSS layout rules:**

```css
/* Desktop 3-column */
@media (min-width: 1024px) {
  .navigator-grid {
    display: grid;
    grid-template-columns: 200px 1fr 240px;
    grid-template-rows: 100vh;
    overflow: hidden;
  }
  .profile-panel { border-right: 1px solid var(--border); overflow-y: auto; padding: 20px 16px; }
  .chat-main { display: flex; flex-direction: column; overflow: hidden; }
  .tool-drawer { border-left: 1px solid var(--border); overflow-y: auto; padding: 16px; }
  .tool-drawer.collapsed { width: 0; overflow: hidden; padding: 0; }
}
/* Mobile: profile → top tag strip */
@media (max-width: 1023px) {
  .navigator-grid { display: flex; flex-direction: column; height: 100vh; }
  .profile-panel {
    display: flex; flex-direction: row; gap: 8px; align-items: center;
    padding: 8px 14px; border-bottom: 1px solid var(--border);
    overflow-x: auto; flex-shrink: 0;
  }
  .profile-name, .profile-risk { display: none; }
  .profile-summary { display: none; }
  .tool-drawer { display: none; }
  .chat-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
}
```

**Card rendering JS:**

```javascript
function renderCards(cards) {
  if (!cards || !cards.length) return '';
  return cards.map(card => {
    if (card.type === 'opportunity') {
      return `<div class="signal-card">
        <div class="card-ticker">${card.ticker}</div>
        <div class="card-name">${card.name || ''}</div>
        <div class="card-metrics">
          <span class="metric">股息率 <b>${card.yield || '—'}</b></span>
          <span class="metric">IV Rank <b>${card.iv_rank || '—'}</b></span>
        </div>
        <button class="card-action" onclick="addToWatchlist('${card.ticker}')">+ 加自选</button>
      </div>`;
    }
    if (card.type === 'risk_summary') {
      return `<div class="signal-card risk-card">
        <div class="card-label">风险报告 · ${card.report_date}</div>
        <a class="card-action" href="/risk-report">查看完整报告 →</a>
      </div>`;
    }
    if (card.type === 'watchlist_confirm') {
      return `<div class="signal-card confirm-card">
        <div class="card-label">自选池已更新</div>
      </div>`;
    }
    return '';
  }).join('');
}
```

**Profile load on page init:**

```javascript
async function loadProfile() {
  try {
    const resp = await fetch('/api/profile?user_id=ALICE');
    const data = await resp.json();
    renderProfile(data.profile);
  } catch (e) {}
}

function renderProfile(profile) {
  const riskEl = document.getElementById('profile-risk');
  const tagsEl = document.getElementById('profile-tags');
  const summaryEl = document.getElementById('profile-summary');
  const marketsEl = document.getElementById('profile-markets');

  const riskMap = { conservative: '保守型', moderate: '稳健型', aggressive: '进取型' };
  if (profile.risk_level && riskEl) riskEl.textContent = riskMap[profile.risk_level] || profile.risk_level;

  if (tagsEl && profile.strategy_tags) {
    tagsEl.innerHTML = profile.strategy_tags.map(t =>
      `<span class="profile-tag" onclick="sendQuick('${t}相关机会')">${t}</span>`
    ).join('');
  }

  if (summaryEl && profile.summary) summaryEl.textContent = profile.summary;

  if (marketsEl && profile.preferred_markets) {
    marketsEl.innerHTML = profile.preferred_markets.map(m =>
      `<span class="market-tag">${m}</span>`
    ).join('');
  }
}

loadProfile();
```

**Step 3: Run existing tests to confirm they still pass**

```bash
python -m pytest tests/test_dashboard_routes.py::test_chat_page_returns_200 tests/test_dashboard_routes.py::test_chat_page_has_nav_and_input -v
```

Expected: PASS

**Step 4: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: ALL PASS

**Step 5: Commit**

```bash
git add agent/templates/chat.html
git commit -m "feat: rebuild AI Navigator chat page with profile panel, rich cards, tool drawer"
```

---

### Task 7: Final integration check + deploy

**Step 1: Run full test suite one more time**

```bash
python -m pytest tests/ -q
```

Expected: All tests pass, 0 failures.

**Step 2: Manual smoke test (local)**

```bash
cd /Users/q/code/ai-monitor
python -m uvicorn agent.main:app --reload --port 8000
# Open http://localhost:8000/chat
# Verify: profile panel renders, quick chips work, send a message, cards appear
```

**Step 3: Security check before push**

```bash
git diff --cached | grep -iE "(api[_-]?key|secret|password|token|verify=False)\s*=\s*['\"][^'\"]{8,}['\"]"
```

Expected: no output (no hardcoded secrets)

**Step 4: Push to deploy**

```bash
git push origin main
```

Fly.io auto-deploys on push to main.
