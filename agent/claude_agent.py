import logging
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
                http_client=httpx.Client(verify=False),  # corporate proxy workaround
            )
        return self._client

    def process(self, user_id: str, user_message: str) -> str:
        """Process a user message, execute tools if needed, return reply text."""
        if not self.db.get_user(user_id):
            self.db.save_user(user_id)

        self.db.add_message(user_id, "user", user_message)

        history = self.db.get_history(user_id, limit=20)
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
                for block in response.content:
                    if block.type == "text":
                        return block.text
                return "（无回复）"

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = self._execute_tool(block.name, block.input, tools)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

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
