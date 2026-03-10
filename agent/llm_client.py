# agent/llm_client.py
# Re-export from shared src.llm_client to avoid duplication.
from src.llm_client import (  # noqa: F401
    LLMClient,
    make_llm_client,
    make_llm_client_from_env,
    _anthropic_tools_to_openai,
)
