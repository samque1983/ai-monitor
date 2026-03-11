import pytest
import os
from unittest.mock import patch


def test_get_llm_config_new_style(monkeypatch):
    """LLM_PROVIDER + LLM_API_KEY are used when set."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-openai-test")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Re-import to pick up monkeypatched env
    import importlib
    import agent.config as cfg
    importlib.reload(cfg)

    result = cfg.get_llm_config()
    assert result["provider"] == "openai"
    assert result["api_key"] == "sk-openai-test"
    assert result["model"] == "gpt-4o-mini"


def test_get_llm_config_anthropic_backward_compat(monkeypatch):
    """ANTHROPIC_API_KEY alone activates anthropic provider."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-4-6")

    import importlib
    import agent.config as cfg
    importlib.reload(cfg)

    result = cfg.get_llm_config()
    assert result["provider"] == "anthropic"
    assert result["api_key"] == "sk-ant-test"
    assert result["model"] == "claude-opus-4-6"


def test_get_llm_config_raises_when_unconfigured(monkeypatch):
    """ValueError raised when neither LLM_API_KEY nor ANTHROPIC_API_KEY is set."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    import importlib
    import agent.config as cfg
    # Patch the source so reload() can't re-import and re-call the real load_dotenv
    with patch("dotenv.load_dotenv"):
        importlib.reload(cfg)
        with pytest.raises(ValueError, match="LLM not configured"):
            cfg.get_llm_config()
