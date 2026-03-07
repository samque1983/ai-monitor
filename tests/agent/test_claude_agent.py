import pytest
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
        llm_provider="anthropic",
        llm_api_key="sk-test",
        llm_model="claude-haiku-4-5-20251001",
    )
    yield a
    db.close()


def test_process_text_message(agent):
    with patch.object(agent._llm_client, "chat", return_value="今天市场平静。"):
        reply = agent.process("user_123", "你好")
    assert reply == "今天市场平静。"


def test_process_calls_tool_and_returns_result(agent):
    with patch.object(agent._llm_client, "chat", return_value="今天有 1 个信号: AAPL Sell Put。"):
        reply = agent.process("user_123", "今天有什么信号")
    assert "AAPL" in reply or "信号" in reply


def test_conversation_history_persisted(agent):
    with patch.object(agent._llm_client, "chat", return_value="好的。"):
        agent.process("user_123", "你好")
    history = agent.db.get_history("user_123")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
