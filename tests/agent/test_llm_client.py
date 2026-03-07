import json
import pytest
from unittest.mock import MagicMock, patch
from agent.llm_client import make_llm_client, LLMClient


# --- Anthropic provider ---

def test_anthropic_provider_text_reply():
    """Anthropic provider returns text from end_turn response."""
    client = make_llm_client("anthropic", api_key="sk-test", model="claude-haiku-4-5-20251001")

    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "今天市场平静。"
    mock_response.content = [text_block]

    with patch.object(client._client, "messages") as mock_messages:
        mock_messages.create.return_value = mock_response
        result = client.chat(
            system="你是助手",
            messages=[{"role": "user", "content": "你好"}],
            tools_schema=[],
            tool_executor=lambda n, a: "",
        )
    assert result == "今天市场平静。"


def test_anthropic_provider_tool_call():
    """Anthropic provider executes tool call and returns final text."""
    client = make_llm_client("anthropic", api_key="sk-test", model="claude-haiku-4-5-20251001")

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "get_scan_results"
    tool_block.input = {}
    tool_block.id = "tu_1"

    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_response.content = [tool_block]

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "共 1 个信号。"

    final_response = MagicMock()
    final_response.stop_reason = "end_turn"
    final_response.content = [text_block]

    calls = []

    def fake_executor(name, args):
        calls.append(name)
        return "结果数据"

    with patch.object(client._client, "messages") as mock_messages:
        mock_messages.create.side_effect = [tool_response, final_response]
        result = client.chat(
            system="你是助手",
            messages=[{"role": "user", "content": "今天信号"}],
            tools_schema=[{"name": "get_scan_results", "description": "获取信号",
                           "input_schema": {"type": "object", "properties": {}, "required": []}}],
            tool_executor=fake_executor,
        )
    assert result == "共 1 个信号。"
    assert calls == ["get_scan_results"]


# --- OpenAI provider ---

def test_openai_provider_text_reply():
    """OpenAI provider returns text from stop response."""
    client = make_llm_client("openai", api_key="sk-test", model="gpt-4o-mini")

    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message.content = "今天市场平静。"
    choice.message.tool_calls = None

    mock_response = MagicMock()
    mock_response.choices = [choice]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = client.chat(
            system="你是助手",
            messages=[{"role": "user", "content": "你好"}],
            tools_schema=[],
            tool_executor=lambda n, a: "",
        )
    assert result == "今天市场平静。"


def test_openai_provider_tool_call():
    """OpenAI provider executes tool call and returns final text."""
    client = make_llm_client("openai", api_key="sk-test", model="gpt-4o-mini")

    tc = MagicMock()
    tc.id = "call_1"
    tc.function.name = "get_scan_results"
    tc.function.arguments = "{}"

    tool_choice = MagicMock()
    tool_choice.finish_reason = "tool_calls"
    tool_choice.message.tool_calls = [tc]
    tool_choice.message.content = None

    text_choice = MagicMock()
    text_choice.finish_reason = "stop"
    text_choice.message.content = "共 1 个信号。"
    text_choice.message.tool_calls = None

    tool_resp = MagicMock()
    tool_resp.choices = [tool_choice]
    final_resp = MagicMock()
    final_resp.choices = [text_choice]

    calls = []

    def fake_executor(name, args):
        calls.append(name)
        return "结果数据"

    with patch.object(client._client.chat.completions, "create",
                      side_effect=[tool_resp, final_resp]):
        result = client.chat(
            system="你是助手",
            messages=[{"role": "user", "content": "今天信号"}],
            tools_schema=[{"name": "get_scan_results", "description": "获取信号",
                           "input_schema": {"type": "object", "properties": {}, "required": []}}],
            tool_executor=fake_executor,
        )
    assert result == "共 1 个信号。"
    assert calls == ["get_scan_results"]


# --- DeepSeek uses OpenAI provider ---

def test_deepseek_uses_openai_provider_with_custom_base_url():
    """DeepSeek provider is OpenAI-compatible with deepseek base URL."""
    client = make_llm_client("deepseek", api_key="sk-test", model="deepseek-chat")
    assert client._provider == "openai"
    assert "deepseek" in client._client.base_url.host


# --- make_llm_client factory ---

def test_make_llm_client_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        make_llm_client("foobar", api_key="sk-test")
