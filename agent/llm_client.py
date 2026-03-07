# agent/llm_client.py
import json
import logging
from typing import Callable

logger = logging.getLogger(__name__)


def _anthropic_tools_to_openai(tools: list) -> list:
    """Convert Anthropic tool schema format to OpenAI function format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


class LLMClient:
    """Unified LLM client supporting Anthropic, OpenAI, and DeepSeek."""

    def __init__(self, provider: str, client, model: str):
        self._provider = provider  # "anthropic" or "openai"
        self._client = client
        self._model = model

    def chat(
        self,
        system: str,
        messages: list,
        tools_schema: list,
        tool_executor: Callable[[str, dict], str],
    ) -> str:
        """Run a full tool loop and return final text reply."""
        if self._provider == "anthropic":
            return self._chat_anthropic(system, messages, tools_schema, tool_executor)
        else:
            return self._chat_openai(system, messages, tools_schema, tool_executor)

    def _chat_anthropic(self, system, messages, tools_schema, tool_executor):
        loop_messages = list(messages)
        for _ in range(5):
            kwargs = dict(
                model=self._model,
                max_tokens=1024,
                system=system,
                messages=loop_messages,
            )
            if tools_schema:
                kwargs["tools"] = tools_schema
            response = self._client.messages.create(**kwargs)

            if response.stop_reason == "end_turn":
                for block in response.content:
                    if block.type == "text":
                        return block.text
                return "（无回复）"

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = tool_executor(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                loop_messages.append({"role": "assistant", "content": response.content})
                loop_messages.append({"role": "user", "content": tool_results})
                continue

            break
        return "处理超时，请重试。"

    def _chat_openai(self, system, messages, tools_schema, tool_executor):
        loop_messages = [{"role": "system", "content": system}] + list(messages)
        openai_tools = _anthropic_tools_to_openai(tools_schema) if tools_schema else []

        for _ in range(5):
            kwargs = dict(model=self._model, messages=loop_messages)
            if openai_tools:
                kwargs["tools"] = openai_tools
                kwargs["tool_choice"] = "auto"
            response = self._client.chat.completions.create(**kwargs)
            choice = response.choices[0]

            if choice.finish_reason == "stop" or not choice.message.tool_calls:
                return choice.message.content or "（无回复）"

            if choice.finish_reason == "tool_calls":
                loop_messages.append({
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in choice.message.tool_calls
                    ],
                })
                for tc in choice.message.tool_calls:
                    args = json.loads(tc.function.arguments or "{}")
                    result = tool_executor(tc.function.name, args)
                    loop_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
                continue

            break
        return "处理超时，请重试。"


def make_llm_client(provider: str, api_key: str, model: str = None) -> LLMClient:
    """Factory: create an LLMClient for the given provider."""
    if provider == "anthropic":
        import anthropic
        model = model or "claude-opus-4-6"
        client = anthropic.Anthropic(api_key=api_key)
        return LLMClient("anthropic", client, model)

    elif provider in ("openai", "deepseek"):
        import openai
        model = model or ("gpt-4o" if provider == "openai" else "deepseek-chat")
        kwargs = {"api_key": api_key}
        if provider == "deepseek":
            kwargs["base_url"] = "https://api.deepseek.com/v1"
        client = openai.OpenAI(**kwargs)
        return LLMClient("openai", client, model)

    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}. Use 'anthropic', 'openai', or 'deepseek'.")
