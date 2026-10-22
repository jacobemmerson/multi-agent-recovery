"""Researcher, planner, executor, and verifier agents.

Agents are pure: inputs plus an injected LLM client and tool runtime produce artifacts.
They never see the orchestrator, so prompts are identical across recovery methods.
Phase 1 uses plain OpenAI-shaped messages; AgentDojo ChatMessage compatibility is
deferred to the Phase 2 built-in-defenses baseline.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from mar.artifacts import Artifact, ExecutedStep
from mar.llm import LLMClient, LLMResponse

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


@dataclass
class ToolResult:
    status: Literal["ok", "error", "blocked", "buffered"]
    output: str
    action_id: str


class ToolRuntime(Protocol):
    """Implemented by the orchestrator; consults the recovery policy before executing."""

    def call(self, name: str, args: dict[str, Any]) -> ToolResult: ...

    def tool_schemas(self) -> list[dict[str, Any]]: ...


@dataclass
class LoopResult:
    output: str
    messages: list[dict[str, Any]]
    action_ids: list[str]
    llm_calls: int
    truncated: bool


def tool_loop(system: str, user: str, llm: LLMClient, tools: ToolRuntime, max_steps: int = 15) -> LoopResult:
    """Native tool-calling loop over OpenAI-shaped messages until the model replies with text."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    action_ids: list[str] = []
    for step in range(max_steps):
        response = llm.complete(messages, tools=tools.tool_schemas())
        if not response.tool_calls:
            messages.append({"role": "assistant", "content": response.content})
            return LoopResult(response.content or "", messages, action_ids, step + 1, truncated=False)
        messages.append(_assistant_message(response))
        for call in response.tool_calls:
            if "args_error" in call:
                content = call["args_error"]
            else:
                result = tools.call(call["name"], call["args"])
                action_ids.append(result.action_id)
                content = result.output
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
    return LoopResult("", messages, action_ids, max_steps, truncated=True)


def _assistant_message(response: LLMResponse) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": response.content,
        "tool_calls": [
            {"id": call["id"], "type": "function", "function": {"name": call["name"], "arguments": json.dumps(call["args"])}}
            for call in response.tool_calls
        ],
    }


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
        if tools is None:
            raise ValueError("executor needs a tool runtime")
        user = inputs["instruction"]
        if inputs.get("context"):
            user += "\n\nContext:\n" + inputs["context"]
        loop = tool_loop(load_prompt("executor"), user, llm, tools)
        plan_step_id = inputs["plan_step_id"]
        return [
            ExecutedStep(
                id=f"{inputs['task_id']}:exec:{plan_step_id}",
                producer="executor",
                task_id=inputs["task_id"],
                branch_id=inputs.get("branch_id", "main"),
                plan_step_id=plan_step_id,
                cites=[plan_step_id],
                tool_reads=loop.action_ids,
                content={"output": loop.output, "llm_calls": loop.llm_calls, "truncated": loop.truncated},
            )
        ]


class Verifier:
    """Checks one artifact before it is passed on (always-verify baseline)."""

    def run(self, inputs, llm, tools=None) -> list[Artifact]:
        raise NotImplementedError
