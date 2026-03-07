# agent/claude_agent.py
import logging
from agent.db import AgentDB
from agent.tools import AgentTools, TOOL_DEFINITIONS
from agent.llm_client import make_llm_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是交易领航员，一个专业的量化交易助手。
你帮助用户：
- 查看每日市场扫描信号和机会卡片
- 分析持仓风险
- 管理自选标的池
- 回答交易策略问题

回复简洁，使用中文，重要数字加粗。不提供具体买卖建议，只陈述数据和分析。"""


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

    def process(self, user_id: str, user_message: str) -> str:
        """Process a user message, execute tools if needed, return reply text."""
        if not self.db.get_user(user_id):
            self.db.save_user(user_id)

        self.db.add_message(user_id, "user", user_message)

        history = self.db.get_history(user_id, limit=20)
        messages = [{"role": m["role"], "content": m["content"]} for m in history]

        tools_instance = AgentTools(self.db, user_id=user_id)

        try:
            reply = self._llm_client.chat(
                system=SYSTEM_PROMPT,
                messages=messages,
                tools_schema=TOOL_DEFINITIONS,
                tool_executor=lambda name, args: self._execute_tool(name, args, tools_instance),
            )
        except Exception as e:
            logger.warning(f"LLM agent error for {user_id}: {e}")
            reply = "抱歉，处理请求时出错，请稍后重试。"

        self.db.add_message(user_id, "assistant", reply)
        return reply

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
