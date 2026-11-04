"""LLM access through an OpenAI-compatible endpoint, plus a fake client for tests.

Every call records the model string, system fingerprint, and token usage, because hosted
models change silently. No response cache: reported runs must see real sampling noise.
"""

import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from dotenv import load_dotenv

if TYPE_CHECKING:
    from mar.config import ModelConfig


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[dict[str, Any]]
    model: str
    system_fingerprint: str | None
    usage: dict[str, int]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


class LLMClient(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> LLMResponse: ...


# A judge call takes ~5 s and an agent call under 30 s; the SDK default of 600 s with retries let one
# hung request stall a batch for 40 minutes.
REQUEST_TIMEOUT_SECONDS = 120


class OpenAICompatibleClient:
    """Chat completions against BASE_URL with TRITONAI_API_KEY, both read from the environment."""

    def __init__(self, model: str, temperature: float = 0.0, max_tokens: int = 4096, client: Any | None = None) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = client

    @classmethod
    def from_config(cls, config: "ModelConfig") -> "OpenAICompatibleClient":
        load_dotenv()
        return cls(config.name, config.temperature, config.max_tokens)

    @property
    def client(self) -> Any:
        if self._client is None:
            import openai

            self._client = openai.OpenAI(
                base_url=os.environ["BASE_URL"], api_key=os.environ["TRITONAI_API_KEY"],
                timeout=REQUEST_TIMEOUT_SECONDS, max_retries=3,
            )
        return self._client

    def complete(self, messages, tools=None, schema=None) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": schema},
            }
        response = self.client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        return LLMResponse(
            content=message.content,
            tool_calls=[_parse_tool_call(call) for call in (message.tool_calls or [])],
            model=response.model,
            system_fingerprint=response.system_fingerprint,
            usage=response.usage.model_dump() if response.usage else {},
            raw=response.model_dump(),
        )


def _parse_tool_call(call: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = {"id": call.id, "name": call.function.name, "args": {}}
    try:
        args = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError as error:
        parsed["args_error"] = f"malformed tool arguments: {error}"
        return parsed
    if not isinstance(args, dict):
        parsed["args_error"] = f"tool arguments must be a JSON object, got {type(args).__name__}"
        return parsed
    parsed["args"] = args
    return parsed


class FakeLLM:
    """Returns scripted responses in order; records what it was asked."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, messages, tools=None, schema=None) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, "schema": schema})
        return self.responses.pop(0)
