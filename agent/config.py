# agent/config.py
import os
from dotenv import load_dotenv

load_dotenv()


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def get_llm_config() -> dict:
    """Resolve LLM provider, api_key, model from env vars.

    Priority:
    1. LLM_PROVIDER + LLM_API_KEY (new style)
    2. ANTHROPIC_API_KEY present → provider=anthropic (backward compat)
    3. Raise ValueError if neither is set.
    """
    provider = get("LLM_PROVIDER")
    api_key = get("LLM_API_KEY")
    model = get("LLM_MODEL") or None

    # Backward compat: ANTHROPIC_API_KEY
    if not provider and not api_key:
        anthropic_key = get("ANTHROPIC_API_KEY")
        if anthropic_key:
            provider = "anthropic"
            api_key = anthropic_key
            model = model or get("CLAUDE_MODEL") or None

    if not provider or not api_key:
        raise ValueError(
            "LLM not configured. Set LLM_PROVIDER + LLM_API_KEY, "
            "or set ANTHROPIC_API_KEY for backward compat."
        )

    return {"provider": provider, "api_key": api_key, "model": model}
