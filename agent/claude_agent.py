# agent/claude_agent.py
import json
import logging
from agent.db import AgentDB
from agent.tools import AgentTools, TOOL_DEFINITIONS
from agent.llm_client import make_llm_client

logger = logging.getLogger(__name__)

_BASE_SYSTEM = """你是交易领航员，一个专业的量化交易助手。
你帮助用户：
- 查看每日市场扫描信号和机会卡片
- 分析持仓风险
- 管理自选标的池
- 回答交易策略问题

回复简洁，使用中文，重要数字加粗。不提供具体买卖建议，只陈述数据和分析。"""

_PROFILE_REWRITE_PROMPT = """根据以上对话，提取用户投资偏好并以 JSON 输出，不要任何其他文字：
{"risk_level":"conservative|moderate|aggressive","preferred_markets":["US","HK","CN"],"strategy_tags":["高股息","卖波动率","LEAPS","趋势跟踪","事件驱动"],"summary":"一句话描述用户偏好，不超过80字"}
如信息不足请保留原值。"""


class ClaudeAgent:
    def __init__(
        self,
        db: AgentDB,
        llm_provider: str,
        llm_api_key: str,
        llm_model: str = None,
        # Legacy params for backward compat
        api_key: str = None,
        model: str = None,
    ):
        self.db = db
        if api_key and not llm_api_key:
            llm_api_key = api_key
        if model and not llm_model:
            llm_model = model
        self._llm_client = make_llm_client(llm_provider, llm_api_key, llm_model)

    def _build_system(self, user_id: str) -> str:
        """Build system prompt, injecting user profile if available."""
        profile = self.db.get_profile(user_id)
        if not profile:
            return _BASE_SYSTEM
        parts = [_BASE_SYSTEM, "\n\n【用户画像】"]
        if profile.get("summary"):
            parts.append(f"偏好摘要：{profile['summary']}")
        if profile.get("risk_level"):
            level_map = {"conservative": "保守型", "moderate": "稳健型", "aggressive": "进取型"}
            parts.append(f"风险偏好：{level_map.get(profile['risk_level'], profile['risk_level'])}")
        if profile.get("strategy_tags"):
            parts.append(f"关注策略：{'、'.join(profile['strategy_tags'])}")
        if profile.get("preferred_markets"):
            parts.append(f"偏好市场：{'、'.join(profile['preferred_markets'])}")
        return "\n".join(parts)

    def process(self, user_id: str, user_message: str) -> tuple:
        """Process a user message. Returns (reply_text, profile_updated)."""
        if not self.db.get_user(user_id):
            self.db.save_user(user_id)

        self.db.add_message(user_id, "user", user_message)

        history = self.db.get_history(user_id, limit=20)
        messages = [{"role": m["role"], "content": m["content"]} for m in history]
        tools_instance = AgentTools(self.db, user_id=user_id)

        try:
            reply = self._llm_client.chat(
                system=self._build_system(user_id),
                messages=messages,
                tools_schema=TOOL_DEFINITIONS,
                tool_executor=lambda name, args: self._execute_tool(name, args, tools_instance),
            )
        except Exception as e:
            logger.warning(f"LLM agent error for {user_id}: {e}")
            reply = "抱歉，处理请求时出错，请稍后重试。"

        self.db.add_message(user_id, "assistant", reply)

        # Trigger profile rewrite every 15 user messages
        user_msg_count = sum(1 for m in self.db.get_history(user_id, limit=200) if m["role"] == "user")
        profile_updated = False
        if user_msg_count > 0 and user_msg_count % 15 == 0:
            profile_updated = self._rewrite_profile(user_id)

        return reply, profile_updated

    def _rewrite_profile(self, user_id: str) -> bool:
        """Ask LLM to rewrite user profile from recent conversation. Returns True on success."""
        try:
            history = self.db.get_history(user_id, limit=30)
            messages = [{"role": m["role"], "content": m["content"]} for m in history]
            messages.append({"role": "user", "content": _PROFILE_REWRITE_PROMPT})
            raw = self._llm_client.chat(
                system="你是数据提取助手，只输出 JSON。",
                messages=messages,
                tools_schema=[],
                tool_executor=lambda n, a: "",
            )
            profile = json.loads(raw.strip())
            profile["message_count"] = sum(1 for m in history if m["role"] == "user")
            self.db.update_profile(user_id, profile)
            return True
        except Exception as e:
            logger.warning(f"Profile rewrite failed for {user_id}: {e}")
            return False

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
