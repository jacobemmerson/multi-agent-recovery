from dataclasses import dataclass, field

from mar.agents import Executor, ToolResult, tool_loop


@dataclass
class RecordingTools:
    results: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)

    def tool_schemas(self):
        return [{"type": "function", "function": {"name": "get_current_day", "parameters": {}}}]

    def call(self, name, args):
        self.calls.append((name, args))
        return self.results.get(name, ToolResult("error", f"ToolNotFoundError: {name}", f"a{len(self.calls)}"))


def test_loop_executes_tool_calls_then_returns_text(fake_llm_responses, resp):
    llm = fake_llm_responses(
        resp(tool_calls=[{"id": "c1", "name": "get_current_day", "args": {}}]),
        resp(content="It is 2024-05-15"),
    )
    tools = RecordingTools({"get_current_day": ToolResult("ok", "2024-05-15", "a1")})
    out = tool_loop("sys", "what day is it", llm, tools)
    assert out.output == "It is 2024-05-15" and out.action_ids == ["a1"] and out.llm_calls == 2
    assert tools.calls == [("get_current_day", {})]
    assert out.messages[-2]["role"] == "tool" and out.messages[-2]["content"] == "2024-05-15"


def test_tool_error_is_fed_back_not_raised(fake_llm_responses, resp):
    llm = fake_llm_responses(resp(tool_calls=[{"id": "c1", "name": "nope", "args": {}}]), resp(content="done"))
    out = tool_loop("sys", "u", llm, RecordingTools())
    assert "ToolNotFoundError" in out.messages[-2]["content"] and out.output == "done"


def test_malformed_args_are_fed_back_as_error(fake_llm_responses, resp):
    llm = fake_llm_responses(
        resp(tool_calls=[{"id": "c1", "name": "get_current_day", "args": {}, "args_error": "bad json"}]),
        resp(content="done"),
    )
    tools = RecordingTools({"get_current_day": ToolResult("ok", "x", "a1")})
    out = tool_loop("sys", "u", llm, tools)
    assert tools.calls == [] and "bad json" in out.messages[-2]["content"]


def test_loop_truncates_at_max_steps(fake_llm_responses, resp):
    llm = fake_llm_responses(*[resp(tool_calls=[{"id": f"c{i}", "name": "get_current_day", "args": {}}]) for i in range(3)])
    out = tool_loop("sys", "u", llm, RecordingTools({"get_current_day": ToolResult("ok", "x", "a")}), max_steps=3)
    assert out.truncated is True and out.output == "" and out.llm_calls == 3


def test_executor_returns_one_executed_step(fake_llm_responses, resp):
    llm = fake_llm_responses(resp(content="sent"))
    [step] = Executor().run({"task_id": "t", "plan_step_id": "p1", "instruction": "send it", "context": ""}, llm, RecordingTools())
    assert step.kind == "executed_step" and step.plan_step_id == "p1" and step.cites == ["p1"]
    assert step.content["output"] == "sent" and step.producer == "executor"


import json

import pytest

from mar.agents import Planner, PlanRejected, Researcher
from mar.artifacts import Finding


def test_researcher_emits_one_finding_per_source(fake_llm_responses, resp):
    llm = fake_llm_responses(
        resp(tool_calls=[{"id": "c1", "name": "get_current_day", "args": {}}]),
        resp(content="ok"),
        resp(content=json.dumps({"findings": [{"source": "calendar", "content": "today is 2024-05-15"}, {"source": "inbox", "content": "no mail"}]})),
    )
    tools = RecordingTools({"get_current_day": ToolResult("ok", "2024-05-15", "a1")})
    findings = Researcher().run({"task_id": "t", "prompt": "p"}, llm, tools)
    assert [f.id for f in findings] == ["t:f0", "t:f1"] and findings[0].tool_reads == ["a1"]
    assert findings[0].source == "calendar" and findings[0].content["text"] == "today is 2024-05-15"
    assert llm.calls[-1]["schema"] is not None


def test_planner_rejects_unknown_citation_then_accepts(fake_llm_responses, resp):
    findings = [Finding(id="t:f0", producer="researcher", task_id="t", source="s", content={"text": "x"})]
    llm = fake_llm_responses(
        resp(content=json.dumps({"steps": [{"instruction": "do", "cites": ["t:f9"]}]})),
        resp(content=json.dumps({"steps": [{"instruction": "do", "cites": ["t:f0"]}]})),
    )
    [step] = Planner().run({"task_id": "t", "prompt": "p", "findings": findings}, llm)
    assert step.cites == ["t:f0"] and step.content["retries"] == 1 and step.id == "t:p0"
    assert step.index == 0 and step.content["instruction"] == "do"


def test_planner_gives_up_after_three_attempts(fake_llm_responses, resp):
    bad = resp(content=json.dumps({"steps": [{"instruction": "do", "cites": []}]}))
    with pytest.raises(PlanRejected):
        Planner().run({"task_id": "t", "prompt": "p", "findings": []}, fake_llm_responses(bad, bad, bad))
