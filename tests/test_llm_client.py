"""Tests for src/llm_client.py — multi-provider LLM client."""
from unittest.mock import MagicMock, patch

import pytest

from src.llm_client import LLMClient, make_llm_client, make_llm_client_from_env


# ---------------------------------------------------------------------------
# LLMClient.simple_chat — Anthropic path
# ---------------------------------------------------------------------------

def _make_anthropic_client(text: str):
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=text)]
    mock_client.messages.create.return_value = mock_resp
    return mock_client


def _make_openai_client(text: str):
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = text
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_resp
    return mock_client


def test_simple_chat_anthropic_returns_text():
    raw_client = _make_anthropic_client('{"score": 80.0}')
    client = LLMClient("anthropic", raw_client, "claude-opus-4-6")
    result = client.simple_chat("system prompt", "user message", max_tokens=100)
    assert result == '{"score": 80.0}'


def test_simple_chat_anthropic_passes_correct_kwargs():
    raw_client = _make_anthropic_client("ok")
    client = LLMClient("anthropic", raw_client, "claude-opus-4-6")
    client.simple_chat("sys", "usr", max_tokens=200)
    raw_client.messages.create.assert_called_once()
    call_kwargs = raw_client.messages.create.call_args[1]
    assert call_kwargs["model"] == "claude-opus-4-6"
    assert call_kwargs["max_tokens"] == 200
    assert call_kwargs["system"] == "sys"
    assert call_kwargs["messages"] == [{"role": "user", "content": "usr"}]


def test_simple_chat_openai_returns_text():
    raw_client = _make_openai_client("hello world")
    client = LLMClient("openai", raw_client, "gpt-4o")
    result = client.simple_chat("system", "user", max_tokens=100)
    assert result == "hello world"


def test_simple_chat_openai_passes_system_as_message():
    raw_client = _make_openai_client("ok")
    client = LLMClient("openai", raw_client, "gpt-4o")
    client.simple_chat("my system prompt", "my user message", max_tokens=150)
    raw_client.chat.completions.create.assert_called_once()
    call_kwargs = raw_client.chat.completions.create.call_args[1]
    assert call_kwargs["model"] == "gpt-4o"
    assert call_kwargs["max_tokens"] == 150
    messages = call_kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "my system prompt"}
    assert messages[1] == {"role": "user", "content": "my user message"}


# ---------------------------------------------------------------------------
# make_llm_client_from_env — provider auto-detection
# ---------------------------------------------------------------------------

def test_make_llm_client_from_env_deepseek_priority(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")
    with patch("src.llm_client.make_llm_client") as mock_make:
        mock_make.return_value = MagicMock()
        make_llm_client_from_env()
        assert mock_make.call_args[0][0] == "deepseek"


def test_make_llm_client_from_env_openai_when_no_deepseek(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")
    with patch("src.llm_client.make_llm_client") as mock_make:
        mock_make.return_value = MagicMock()
        make_llm_client_from_env()
        assert mock_make.call_args[0][0] == "openai"


def test_make_llm_client_from_env_anthropic_fallback(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")
    with patch("src.llm_client.make_llm_client") as mock_make:
        mock_make.return_value = MagicMock()
        make_llm_client_from_env()
        assert mock_make.call_args[0][0] == "anthropic"


def test_make_llm_client_from_env_explicit_api_key_used_as_anthropic(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("src.llm_client.make_llm_client") as mock_make:
        mock_make.return_value = MagicMock()
        make_llm_client_from_env(api_key="explicit-key")
        assert mock_make.call_args[0][0] == "anthropic"
        assert mock_make.call_args[0][1] == "explicit-key"


def test_make_llm_client_from_env_returns_none_when_no_keys(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = make_llm_client_from_env()
    assert result is None


def test_make_llm_client_from_env_deepseek_uses_deepseek_chat_model(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("src.llm_client.make_llm_client") as mock_make:
        mock_make.return_value = MagicMock()
        make_llm_client_from_env()
        _, _, model_arg = mock_make.call_args[0]
        assert model_arg == "deepseek-chat"


def test_make_llm_client_from_env_claude_model_replaced_for_deepseek(monkeypatch):
    """Claude model ID should be replaced with deepseek-chat for DeepSeek provider."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("src.llm_client.make_llm_client") as mock_make:
        mock_make.return_value = MagicMock()
        make_llm_client_from_env(model="claude-opus-4-6")
        _, _, model_arg = mock_make.call_args[0]
        assert model_arg == "deepseek-chat"
