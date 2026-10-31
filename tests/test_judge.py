from mar.artifacts import Finding, PlanStep
from mar.judge import match_artifacts, noise_floor
from mar.run import RunRecord


def rec(tmp_path, name, findings, steps):
    r = RunRecord.start(tmp_path, {"run_id": name})
    for i, text in enumerate(findings):
        r.graph.add(Finding(id=f"t:f{i}", producer="r", task_id="t", source="s", content={"text": text}))
    for i, text in enumerate(steps):
        r.graph.add(PlanStep(id=f"t:p{i}", producer="p", task_id="t", index=i, content={"instruction": text}))
    return r


def test_identical_runs_have_zero_floor(tmp_path):
    a, b = rec(tmp_path, "a", ["x", "y"], ["s"]), rec(tmp_path, "b", ["x", "y"], ["s"])
    assert noise_floor(a, b) == {"findings": 0.0, "plan_steps": 0.0, "executed_steps": 0.0, "tool_sequence_differs": False}


def test_unmatched_tail_counts_as_difference(tmp_path):
    a, b = rec(tmp_path, "a", ["x", "y", "z"], []), rec(tmp_path, "b", ["x", "q"], [])
    pairs = match_artifacts(a.graph, b.graph)
    assert len([p for p in pairs if p[0] is not None and p[0].kind == "finding"]) == 3
    assert noise_floor(a, b)["findings"] == 2 / 3


def test_missing_on_left_side_also_counts(tmp_path):
    a, b = rec(tmp_path, "a", ["x"], ["s"]), rec(tmp_path, "b", ["x"], ["s", "t"])
    assert noise_floor(a, b)["plan_steps"] == 1 / 2


import json

from mar.judge import JUDGE_SCHEMA, exact_diff, judge_diff


def _finding(text):
    return Finding(id="t:f0", producer="r", task_id="t", source="s", content={"text": text})


def test_judge_diff_returns_false_when_judge_says_same(fake_llm_responses, resp):
    llm = fake_llm_responses(resp(content=json.dumps({"same": True, "reason": "same facts"})))
    assert judge_diff(_finding("meeting at 10am"), _finding("The meeting is at 10:00"), llm) is False


def test_judge_diff_sends_task_prompt_kind_and_both_texts(fake_llm_responses, resp):
    llm = fake_llm_responses(resp(content=json.dumps({"same": False, "reason": "different time"})))
    assert judge_diff(_finding("at 10am"), _finding("at 11am"), llm, task_prompt="When is the meeting?") is True
    call = llm.calls[-1]
    assert call["schema"] is JUDGE_SCHEMA
    user = call["messages"][-1]["content"]
    assert "When is the meeting?" in user and "finding" in user and "at 10am" in user and "at 11am" in user


def test_judge_diff_malformed_verdict_counts_as_different(fake_llm_responses, resp):
    llm = fake_llm_responses(resp(content="not json"))
    assert judge_diff(_finding("a"), _finding("a"), llm) is True


def test_noise_floor_accepts_custom_differs(tmp_path):
    a, b = rec(tmp_path, "a", ["x", "y"], ["s"]), rec(tmp_path, "b", ["p", "q"], ["r"])
    assert noise_floor(a, b)["findings"] == 1.0
    assert noise_floor(a, b, differs=lambda x, y: False)["findings"] == 0.0
    assert noise_floor(a, b, differs=exact_diff)["plan_steps"] == 1.0
