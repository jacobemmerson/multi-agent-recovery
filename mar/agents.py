"""Researcher, planner, executor, and verifier agents.

Agents are pure: inputs plus an injected LLM client and tool runtime produce artifacts.
They never see the orchestrator, so prompts are identical across recovery methods.
Phase 1 uses plain OpenAI-shaped messages; AgentDojo ChatMessage compatibility is
deferred to the Phase 2 built-in-defenses baseline.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from mar.artifacts import Artifact, ExecutedStep, Finding, PlanStep
from mar.llm import LLMClient, LLMResponse

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


def prompt_hashes() -> dict[str, str]:
    return {path.stem: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(PROMPTS_DIR.glob("*.md"))}


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


FINDINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"source": {"type": "string"}, "content": {"type": "string"}},
                "required": ["source", "content"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"instruction": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}},
                "required": ["instruction", "cites"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["steps"],
    "additionalProperties": False,
}

PLANNER_ATTEMPTS = 3


class PlanRejected(Exception):
    """The planner produced no plan with valid citations within PLANNER_ATTEMPTS."""


class Researcher:
    """One Finding per source (document, email, search result). Read-only tools only."""

    def run(self, inputs, llm, tools=None) -> list[Artifact]:
        if tools is None:
            raise ValueError("researcher needs a tool runtime")
        loop = tool_loop(load_prompt("researcher"), inputs["prompt"], llm, tools)
        messages = loop.messages + [
            {"role": "user", "content": "List every fact you gathered as findings, one per source you consulted."}
        ]
        response = llm.complete(messages, schema=FINDINGS_SCHEMA)
        task_id = inputs["task_id"]
        return [
            Finding(
                id=f"{task_id}:f{i}",
                producer="researcher",
                task_id=task_id,
                branch_id=inputs.get("branch_id", "main"),
                source=item["source"],
                tool_reads=loop.action_ids,
                content={"text": item["content"]},
            )
            for i, item in enumerate(json.loads(response.content or "{}").get("findings", []))
        ]


class Planner:
    """Numbered PlanSteps, each citing finding ids; schema-enforced, retried when citations are invalid."""

    def run(self, inputs, llm, tools=None) -> list[Artifact]:
        findings: list[Finding] = inputs["findings"]
        valid_ids = {f.id for f in findings}
        listing = "\n".join(f"[{f.id}] ({f.source}) {f.content.get('text', '')}" for f in findings) or "(no findings)"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": load_prompt("planner")},
            {"role": "user", "content": f"Task: {inputs['prompt']}\n\nFindings:\n{listing}"},
        ]
        for attempt in range(PLANNER_ATTEMPTS):
            response = llm.complete(messages, schema=PLAN_SCHEMA)
            steps = json.loads(response.content or "{}").get("steps", [])
            bad = [s for s in steps if not s["cites"] or not set(s["cites"]) <= valid_ids]
            if steps and not bad:
                task_id = inputs["task_id"]
                return [
                    PlanStep(
                        id=f"{task_id}:p{i}",
                        producer="planner",
                        task_id=task_id,
                        branch_id=inputs.get("branch_id", "main"),
                        index=i,
                        cites=step["cites"],
                        content={"instruction": step["instruction"], "retries": attempt},
                    )
                    for i, step in enumerate(steps)
                ]
            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {
                    "role": "user",
                    "content": "Every step must cite at least one finding id, and only from this list: "
                    + (", ".join(sorted(valid_ids)) or "(none)")
                    + ". Rewrite the plan.",
                }
            )
        raise PlanRejected(f"no valid plan after {PLANNER_ATTEMPTS} attempts")


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


VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["ok", "reason"],
    "additionalProperties": False,
}


class Verifier:
    """Checks one artifact before it is passed on (always-verify baseline).

    Writes content["verified"] and content["verifier_reason"] on the artifact; returns no artifacts.
    """

    def run(self, inputs, llm, tools=None) -> list[Artifact]:
        artifact: Artifact = inputs["artifact"]
        messages = [
            {"role": "system", "content": load_prompt("verifier")},
            {
                "role": "user",
                "content": f"Task: {inputs['prompt']}\n\nArtifact ({artifact.kind}, from {artifact.producer}):\n"
                + json.dumps({k: v for k, v in artifact.content.items() if k not in ("verified", "verifier_reason")}),
            },
        ]
        verdict = json.loads(llm.complete(messages, schema=VERDICT_SCHEMA).content or "{}")
        artifact.content["verified"] = bool(verdict.get("ok", False))
        artifact.content["verifier_reason"] = verdict.get("reason", "")
        return []
