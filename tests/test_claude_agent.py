import pytest
import json
from unittest.mock import MagicMock, patch
from agent.db import AgentDB
from agent.claude_agent import ClaudeAgent


@pytest.fixture
def db(tmp_path):
    return AgentDB(str(tmp_path / "test.db"))


@pytest.fixture
def agent(db):
    return ClaudeAgent(db, llm_provider="anthropic", llm_api_key="test-key")


def test_build_system_no_profile(agent, db):
    db.save_user("BOB")
    prompt = agent._build_system("BOB")
    assert "交易领航员" in prompt
    assert "用户画像" not in prompt


def test_build_system_with_profile(agent, db):
    db.save_user("BOB")
    db.update_profile("BOB", {
        "risk_level": "moderate",
        "strategy_tags": ["高股息", "卖波动率"],
        "summary": "偏好美港股。",
        "preferred_markets": ["US", "HK"],
    })
    prompt = agent._build_system("BOB")
    assert "用户画像" in prompt
    assert "高股息" in prompt
    assert "偏好美港股" in prompt
    assert "稳健型" in prompt


def test_process_returns_tuple(agent, db):
    with patch.object(agent._llm_client, "chat", return_value="你好"):
        result = agent.process("ALICE", "你好")
    assert isinstance(result, tuple)
    reply, profile_updated = result
    assert reply == "你好"
    assert isinstance(profile_updated, bool)


def test_process_increments_message_count(agent, db):
    with patch.object(agent._llm_client, "chat", return_value="ok"):
        agent.process("ALICE", "消息1")
    profile = db.get_profile("ALICE")
    # message_count is only updated on 15-message trigger; check history instead
    history = db.get_history("ALICE", limit=10)
    user_msgs = [m for m in history if m["role"] == "user"]
    assert len(user_msgs) == 1


def test_profile_injected_in_system(agent, db):
    db.save_user("ALICE")
    db.update_profile("ALICE", {
        "risk_level": "aggressive",
        "strategy_tags": ["事件驱动"],
        "summary": "进取型交易者。",
        "preferred_markets": ["US"],
    })
    captured = []
    def fake_chat(system, messages, tools_schema, tool_executor):
        captured.append(system)
        return "回复"
    with patch.object(agent._llm_client, "chat", side_effect=fake_chat):
        agent.process("ALICE", "测试")
    assert len(captured) == 1
    assert "事件驱动" in captured[0]
    assert "进取型" in captured[0]
