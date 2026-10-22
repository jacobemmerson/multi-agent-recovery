from mar.artifacts import Finding, PlanStep
from mar.judge import match_by_position, noise_floor
from mar.run import RunRecord


def rec(tmp_path, name, findings, steps):
    r = RunRecord.start(tmp_path, {"run_id": name})
    for i, text in enumerate(findings):
        r.graph.add(Finding(id=f"{name}:f{i}", producer="r", task_id="t", source="s", content={"text": text}))
    for i, text in enumerate(steps):
        r.graph.add(PlanStep(id=f"{name}:p{i}", producer="p", task_id="t", index=i, content={"instruction": text}))
    return r


def test_identical_runs_have_zero_floor(tmp_path):
    a, b = rec(tmp_path, "a", ["x", "y"], ["s"]), rec(tmp_path, "b", ["x", "y"], ["s"])
    assert noise_floor(a, b) == {"findings": 0.0, "plan_steps": 0.0, "executed_steps": 0.0, "tool_sequence_differs": False}


def test_unmatched_tail_counts_as_difference(tmp_path):
    a, b = rec(tmp_path, "a", ["x", "y", "z"], []), rec(tmp_path, "b", ["x", "q"], [])
    pairs = match_by_position(a.graph, b.graph)
    assert len([p for p in pairs if p[0] is not None and p[0].kind == "finding"]) == 3
    assert noise_floor(a, b)["findings"] == 2 / 3


def test_missing_on_left_side_also_counts(tmp_path):
    a, b = rec(tmp_path, "a", ["x"], ["s"]), rec(tmp_path, "b", ["x"], ["s", "t"])
    assert noise_floor(a, b)["plan_steps"] == 1 / 2
