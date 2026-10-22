"""Researcher, planner, executor, and verifier agents.

Agents are pure: inputs plus an injected LLM client and tool runtime produce artifacts.
They never see the orchestrator, so prompts are identical across recovery methods.
The executor speaks AgentDojo ChatMessage types so its defense elements can be inserted.
"""

from pathlib import Path
from typing import Any, Protocol

from mar.artifacts import Artifact
from mar.llm import LLMClient

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


class ToolResult(Protocol):
    status: str  # "ok" | "blocked" | "buffered"
    output: str | None


class ToolRuntime(Protocol):
    """Implemented by the orchestrator; consults the recovery policy before executing."""

    def call(self, name: str, args: dict[str, Any]) -> ToolResult: ...

    def tool_schemas(self) -> list[dict[str, Any]]: ...


class Agent(Protocol):
    def run(self, inputs: dict[str, Any], llm: LLMClient, tools: ToolRuntime | None = None) -> list[Artifact]: ...


class Researcher:
    """One Finding per source (document, email, search result)."""

    def run(self, inputs, llm, tools=None) -> list[Artifact]:
        raise NotImplementedError


class Planner:
    """Numbered PlanSteps, each citing finding ids; enforced by JSON schema, retried on miss."""

    def run(self, inputs, llm, tools=None) -> list[Artifact]:
        raise NotImplementedError


class Executor:
    """Runs one PlanStep as a native tool-calling loop; returns one ExecutedStep."""

    def run(self, inputs, llm, tools=None) -> list[Artifact]:
        raise NotImplementedError


class Verifier:
    """Checks one artifact before it is passed on (always-verify baseline)."""

    def run(self, inputs, llm, tools=None) -> list[Artifact]:
        raise NotImplementedError
