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
        """Acknowledge scan trigger request."""
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
