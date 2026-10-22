"""LLM access through an OpenAI-compatible endpoint, plus a fake client for tests.

Every call records the model string, system fingerprint, and token usage, because hosted
models change silently. No response cache: reported runs must see real sampling noise.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


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


class OpenAICompatibleClient:
    """Reads BASE_URL and TRITONAI_API_KEY from the environment."""

    def __init__(self, model: str, temperature: float = 0.0, max_tokens: int = 4096) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def complete(self, messages, tools=None, schema=None) -> LLMResponse:
        raise NotImplementedError


class FakeLLM:
    """Returns scripted responses in order; records what it was asked."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, messages, tools=None, schema=None) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, "schema": schema})
        return self.responses.pop(0)
