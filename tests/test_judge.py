import pandas as pd
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


from mar.judge import agreement, judge_runs, judged_differs, load_judgments, pairs_to_judge, sample_for_hand_labels
from mar.metrics import aggregate


def _runs_dir(tmp_path, build_run):
    """Two clean repeats, one applied fault with a twin, one unapplied fault, one twin-error fault."""
    def finish(record, condition, fault_id, repeat, **result):
        record.manifest.update(task_id="t", condition=condition, fault_id=fault_id, repeat=repeat, suite="workspace")
        record.finish({"utility": True, "llm_calls": 1} | result)
        return record

    finish(build_run("workspace-t-none-clean-r0", ["x"], [("s", ["t:f0"])], ["e"]), "none", None, 0)
    finish(build_run("workspace-t-none-clean-r1", ["x2"], [("s2", ["t:f0"])], ["e2"]), "none", None, 1)
    finish(build_run("workspace-t-none-clean-r2", ["x3"], [("s3", ["t:f0"])], ["e3"]), "none", None, 2)
    finish(build_run("workspace-t-none-date-r0", ["x'"], [("s'", ["t:f0"])], ["e'"], fault_artifact_id="t:f0"), "none", "date", 0, fault_applied=True)
    finish(build_run("workspace-t-none-date-r0-twin", ["x"], [("s", ["t:f0"])], ["e"]), "twin", None, 0)
    finish(build_run("workspace-t-none-nomatch-r0", ["x"], [("s", ["t:f0"])], ["e"]), "none", "nomatch", 0, fault_applied=False)
    finish(build_run("workspace-t-none-broken-r0", ["x'"], [("s'", ["t:f0"])], ["e'"], fault_artifact_id="t:f0"), "none", "broken", 0, fault_applied=True, twin_error="boom")
    finish(build_run("workspace-t-restart_stage-date-r0", ["x'"], [("s'", ["t:f0"])], ["e'"], fault_artifact_id="t:f0"), "restart_stage", "date", 0, fault_applied=True)
    return tmp_path


def test_pairs_to_judge_pairs_twin_and_clean_repeats(tmp_path, build_run):
    runs = _runs_dir(tmp_path, build_run)
    pairs = {(a.name, b.name) for a, b in pairs_to_judge(runs)}
    assert pairs == {
        ("workspace-t-none-clean-r0", "workspace-t-none-clean-r1"),
        ("workspace-t-none-date-r0", "workspace-t-none-date-r0-twin"),
    }


def test_judge_runs_writes_judge_json_and_skips_done(tmp_path, build_run, fake_llm_responses, resp):
    runs = _runs_dir(tmp_path, build_run)
    same = json.dumps({"same": True, "reason": "r"})
    llm = fake_llm_responses(*[resp(content=same)] * 10)
    counts = judge_runs(runs, llm, task_prompt_for=lambda suite, task_id: "prompt")
    # clean pair: 3 artifacts; twin pair: 2 artifacts after the fault (the fault itself is excluded)
    assert counts == {"pairs": 2, "artifacts_judged": 5, "skipped": 0} and len(llm.calls) == 5
    judged = load_judgments(runs / "workspace-t-none-date-r0")
    assert set(judged) == {"t:p0", "t:exec:t:p0"} and judged["t:p0"] is False
    again = judge_runs(runs, llm, task_prompt_for=lambda suite, task_id: "prompt")
    assert again["artifacts_judged"] == 0 and again["skipped"] == 5 and len(llm.calls) == 5
    forced = judge_runs(runs, llm, task_prompt_for=lambda suite, task_id: "prompt", rejudge=True)
    assert forced["artifacts_judged"] == 5


def test_judged_differs_falls_back_to_exact():
    differs = judged_differs({"t:f0": False})
    assert differs(_finding("a"), _finding("b")) is False
    other = Finding(id="t:f9", producer="r", task_id="t", source="s", content={"text": "a"})
    assert differs(other, other.model_copy(update={"content": {"text": "b"}})) is True


def test_aggregate_adds_judged_columns_when_present(tmp_path, build_run, fake_llm_responses, resp):
    runs = _runs_dir(tmp_path, build_run)
    llm = fake_llm_responses(*[resp(content=json.dumps({"same": True, "reason": "r"}))] * 10)
    judge_runs(runs, llm, task_prompt_for=lambda suite, task_id: "prompt")
    df = aggregate(runs, runs / "agg.parquet").set_index("run_id")
    faulted = df.loc["workspace-t-none-date-r0"]
    assert faulted["judged_counterfactual_changed"] == 0 and faulted["judged_ignored"] == True  # noqa: E712
    assert faulted["judged_over_taint"] == 2 and faulted["judged_under_taint"] == 0
    assert df.loc["workspace-t-none-clean-r0", "floor_judged_findings"] == 0.0
    assert df.loc["workspace-t-none-clean-r0", "floor_findings"] == 1.0
    assert pd.isna(df.loc["workspace-t-restart_stage-date-r0", "judged_ignored"])


def test_agreement_is_fraction_equal():
    assert agreement([True, False, True, True], [True, True, True, False]) == 0.5


def test_sample_has_n_rows_and_empty_hand_column(tmp_path, build_run, fake_llm_responses, resp):
    runs = _runs_dir(tmp_path, build_run)
    llm = fake_llm_responses(*[resp(content=json.dumps({"same": False, "reason": "r"}))] * 10)
    judge_runs(runs, llm, task_prompt_for=lambda suite, task_id: "prompt")
    sample = sample_for_hand_labels(runs, n=3, seed=0)
    assert len(sample) == 3 and list(sample.columns) == ["run_id", "artifact_id", "kind", "text_a", "text_b", "judge_differs", "hand_differs"]
    assert (sample["hand_differs"] == "").all() and sample["judge_differs"].all()
    assert sample.equals(sample_for_hand_labels(runs, n=3, seed=0))
