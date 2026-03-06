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
