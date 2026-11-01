from mar.env import Env
from mar.run import EnvToolRuntime, day1


def test_env_tool_runtime_records_action_and_authorization():
    env = Env("workspace", "user_task_0")
    seen = []
    rt = EnvToolRuntime(env, "s1", on_action=seen.append)
    r = rt.call("get_current_day", {})
    assert r.status == "ok" and r.output == "2024-05-15" and r.action_id == "s1:a1"
    assert seen[0].authorized is True and seen[0].action_class == "read_only"
    r2 = rt.call("send_email", {"recipients": ["a@b.com"], "subject": "s", "body": "b"})
    assert r2.status == "ok"
    assert seen[1].authorized is False and seen[1].action_class == "irreversible"


def test_env_tool_runtime_reports_errors():
    rt = EnvToolRuntime(Env("workspace", "user_task_0"), "s1")
    r = rt.call("send_email", {})
    assert r.status == "error" and "ValidationError" in r.output


def test_env_tool_runtime_handles_unknown_tool():
    seen = []
    rt = EnvToolRuntime(Env("workspace", "user_task_0"), "s1", on_action=seen.append)
    r = rt.call("no_such_tool", {})
    assert r.status == "error" and seen[0].action_class == "unknown" and seen[0].authorized is False


def test_day1_passes_task_when_ground_truth_output_is_produced(fake_llm_responses, resp):
    llm = fake_llm_responses(
        resp(tool_calls=[{"id": "c1", "name": "search_calendar_events", "args": {"query": "Networking event", "date": "2024-05-26"}}]),
        resp(content=Env("workspace", "user_task_0").task.GROUND_TRUTH_OUTPUT),
    )
    [row] = day1(["user_task_0"], "workspace", llm)
    assert row["utility"] is True and row["llm_calls"] == 2 and row["tool_calls"] == 1
    assert row["task_id"] == "user_task_0" and row["seconds"] >= 0


import json

from mar.run import RunRecord, run_pipeline


def test_pipeline_runs_all_three_stages_and_records_provenance(tmp_path, fake_llm_responses, resp):
    env = Env("workspace", "user_task_0")
    gt = env.task.GROUND_TRUTH_OUTPUT
    llm = fake_llm_responses(
        resp(tool_calls=[{"id": "c1", "name": "search_calendar_events", "args": {"query": "Networking event", "date": "2024-05-26"}}]),
        resp(content="ok"),
        resp(content=json.dumps({"findings": [{"source": "calendar", "content": gt}]})),
        resp(content=json.dumps({"steps": [{"instruction": "report the invitees", "cites": ["user_task_0:f0"]}]})),
        resp(content=gt),
    )
    record = RunRecord.start(tmp_path, {"run_id": "r1"})
    result = run_pipeline(env, llm, record, "user_task_0")
    assert result.utility is True and result.llm_calls == 5 and result.plan_retries == 0
    kinds = sorted(a.kind for a in record.graph.artifacts.values())
    assert kinds == ["executed_step", "finding", "plan_step"]
    assert record.graph.descendants("user_task_0:f0") == {"user_task_0:p0", "user_task_0:exec:user_task_0:p0"}
    assert [e["kind"] for e in record.events].count("llm_call") == 5
    assert [e["kind"] for e in record.events].count("tool_action") == 1
    assert len(record.graph.tool_actions) == 1


def test_researcher_runtime_blocks_non_read_only_tools():
    env = Env("workspace", "user_task_0")
    rt = EnvToolRuntime(env, "r", allowed={"get_current_day"})
    assert [s["function"]["name"] for s in rt.tool_schemas()] == ["get_current_day"]
    assert rt.call("send_email", {"recipients": [], "subject": "", "body": ""}).status == "blocked"
    assert len(env.environment.inbox.sent) == len(env.pre_environment.inbox.sent)


from mar.artifacts import Finding
from mar.config import ExperimentConfig, ModelConfig
from mar.run import build_manifest, load_run


def cfg():
    return ExperimentConfig(name="p1", model=ModelConfig(name="api-glm-5.3"), tasks="configs/dev_tasks.yaml", conditions=["none"])


def test_manifest_has_every_pinned_field():
    m = build_manifest(cfg(), run_id="r", suite="workspace", task_id="user_task_0", condition="none", fault_id=None, repeat=0, seed=7)
    assert set(m) == {
        "run_id", "experiment", "suite", "task_id", "condition", "fault_id", "repeat", "seed", "model",
        "benchmark_version", "git_sha", "templates_hash", "prompt_hashes", "parent_run_id", "branch_point", "started_at",
    }
    assert m["model"] == "api-glm-5.3" and len(m["templates_hash"]) == 64 and "executor" in m["prompt_hashes"]
    assert m["parent_run_id"] is None and m["seed"] == 7


def test_run_round_trips_through_disk(tmp_path):
    manifest = build_manifest(cfg(), run_id="r1", suite="workspace", task_id="t", condition="none", fault_id=None, repeat=0, seed=1)
    record = RunRecord.start(tmp_path, manifest)
    record.add_artifact(Finding(id="t:f0", producer="researcher", task_id="t", source="s"))
    record.finish({"utility": True})
    loaded = load_run(tmp_path / "r1")
    assert loaded.manifest["run_id"] == "r1" and loaded.result == {"utility": True}
    assert "t:f0" in loaded.graph.artifacts and loaded.events[0]["kind"] == "artifact"
    assert loaded.graph.artifacts["t:f0"].kind == "finding"
    assert (tmp_path / "r1" / "artifacts" / "t:f0.json").exists()


import yaml

from mar.config import TaskSet
from mar.run import Job, expand_jobs, run_experiment


def test_expand_jobs_is_deterministic_and_resumable_ids():
    tasks = TaskSet(suites={"workspace": ["user_task_0", "user_task_1"]})
    config = cfg().model_copy(update={"repeats": 2, "conditions": ["none"]})
    jobs = expand_jobs(config, tasks, templates=[])
    assert len(jobs) == 4 and jobs == expand_jobs(config, tasks, templates=[])
    assert jobs[0].run_id == "workspace-user_task_0-none-clean-r0"
    assert Job("workspace", "t", "none", "x", 1, twin=True).run_id == "workspace-t-none-x-r1-twin"


def test_run_experiment_skips_completed_runs(tmp_path, fake_llm_responses):
    tasks_path = tmp_path / "tasks.yaml"
    tasks_path.write_text(yaml.safe_dump({"benchmark_version": "v1.2", "suites": {"workspace": ["user_task_0"]}}))
    config_path = tmp_path / "exp.yaml"
    config_path.write_text(yaml.safe_dump({
        "name": "smoke", "model": {"name": "fake"}, "tasks": str(tasks_path), "repeats": 1,
        "conditions": ["none"], "fault_templates": str(tmp_path / "no_templates"),
    }))
    (tmp_path / "no_templates").mkdir()
    done = tmp_path / "runs" / "workspace-user_task_0-none-clean-r0"
    done.mkdir(parents=True)
    (done / "result.json").write_text("{}")
    llm = fake_llm_responses()
    paths = run_experiment(config_path, "dev", tmp_path / "runs", resume=True, llm=llm)
    assert llm.calls == [] and paths == [done]


from mar.artifacts import PlanStep


def test_loaded_artifacts_keep_their_subclass_fields(tmp_path):
    record = RunRecord.start(tmp_path, {"run_id": "r2"})
    record.add_artifact(PlanStep(id="t:p1", producer="planner", task_id="t", index=1, cites=["t:f0"]))
    record.finish({})
    loaded = load_run(tmp_path / "r2").graph.artifacts["t:p1"]
    assert isinstance(loaded, PlanStep) and loaded.index == 1


from mar.faults import FaultTemplate


def test_pipeline_injects_finding_fault_and_saves_checkpoint(tmp_path, fake_llm_responses, resp):
    env = Env("workspace", "user_task_0")
    gt = env.task.GROUND_TRUTH_OUTPUT
    llm = fake_llm_responses(
        resp(tool_calls=[{"id": "c1", "name": "search_calendar_events", "args": {"query": "Networking event", "date": "2024-05-26"}}]),
        resp(content="ok"),
        resp(content=json.dumps({"findings": [{"source": "calendar", "content": "event on 2024-05-26: " + gt}]})),
        resp(content=json.dumps({"steps": [{"instruction": "report the invitees", "cites": ["user_task_0:f0"]}]})),
        resp(content=gt),
    )
    template = FaultTemplate(id="date", stage="finding", type="accidental", strength="obvious", description="d",
                             op="regex_replace", payload={"pattern": r"\d{4}-\d{2}-\d{2}", "replacement": "2031-01-01"})
    record = RunRecord.start(tmp_path, {"run_id": "r1"})
    result = run_pipeline(env, llm, record, "user_task_0", fault=(template, 0))
    assert result.checkpoint_before_fault.stage == "findings"
    assert result.checkpoint_before_fault.artifacts[0].content["text"].startswith("event on 2024-05-26")
    assert record.graph.artifacts["user_task_0:f0"].content["fault"] == "date"
    assert "2031-01-01" in record.graph.artifacts["user_task_0:f0"].content["text"]
    injected = [e for e in record.events if e["kind"] == "fault_injected"]
    assert injected[0]["applied"] is True and injected[0]["artifact_id"] == "user_task_0:f0"
    assert result.fault_applied is True


from mar.run import Checkpoint


def test_twin_resumes_from_checkpoint_without_researcher(tmp_path, fake_llm_responses, resp):
    env = Env("workspace", "user_task_0")
    gt = env.task.GROUND_TRUTH_OUTPUT
    clean = Finding(id="user_task_0:f0", producer="researcher", task_id="user_task_0", source="calendar", content={"text": gt})
    checkpoint = Checkpoint("findings", [clean], env.snapshot(), trace=[])
    llm = fake_llm_responses(
        resp(content=json.dumps({"steps": [{"instruction": "report", "cites": ["user_task_0:f0"]}]})),
        resp(content=gt),
    )
    record = RunRecord.start(tmp_path, {"run_id": "twin"})
    result = run_pipeline(env, llm, record, "user_task_0", checkpoint=checkpoint)
    assert result.llm_calls == 2 and result.utility is True
    assert record.graph.artifacts["user_task_0:f0"].content["text"] == gt
    assert record.graph.descendants("user_task_0:f0") == {"user_task_0:p0", "user_task_0:exec:user_task_0:p0"}


def test_plan_checkpoint_holds_findings_and_clean_steps(tmp_path, fake_llm_responses, resp):
    env = Env("workspace", "user_task_0")
    gt = env.task.GROUND_TRUTH_OUTPUT
    llm = fake_llm_responses(
        resp(content="ok"),
        resp(content=json.dumps({"findings": [{"source": "calendar", "content": gt}]})),
        resp(content=json.dumps({"steps": [{"instruction": "email alice", "cites": ["user_task_0:f0"]}]})),
        resp(content=gt),
    )
    template = FaultTemplate(id="w", stage="plan_step", type="accidental", strength="obvious", description="d",
                             op="regex_replace", payload={"pattern": "alice", "replacement": "bob"})
    record = RunRecord.start(tmp_path, {"run_id": "r1"})
    result = run_pipeline(env, llm, record, "user_task_0", fault=(template, 0))
    kinds = [a.kind for a in result.checkpoint_before_fault.artifacts]
    assert result.checkpoint_before_fault.stage == "plan" and kinds == ["finding", "plan_step"]
    assert result.checkpoint_before_fault.artifacts[1].content["instruction"] == "email alice"
    assert record.graph.artifacts["user_task_0:p0"].content["instruction"] == "email bob"


from mar.agents import VERDICT_SCHEMA
from mar.recovery import AlwaysVerify, RestartStage


def _finding_fault():
    return FaultTemplate(id="date", stage="finding", type="accidental", strength="obvious", description="d",
                         op="regex_replace", payload={"pattern": r"\d{4}-\d{2}-\d{2}", "replacement": "2031-01-01"})


def test_restart_stage_reruns_from_clean_findings(tmp_path, fake_llm_responses, resp):
    env = Env("workspace", "user_task_0")
    gt = env.task.GROUND_TRUTH_OUTPUT
    plan = json.dumps({"steps": [{"instruction": "report", "cites": ["user_task_0:f0"]}]})
    llm = fake_llm_responses(
        resp(tool_calls=[{"id": "c1", "name": "search_calendar_events", "args": {"query": "Networking event", "date": "2024-05-26"}}]),
        resp(content="ok"),
        resp(content=json.dumps({"findings": [{"source": "calendar", "content": "on 2024-05-26: " + gt}]})),
        resp(content=plan),
        resp(content="wrong answer"),
        resp(content=plan),
        resp(content=gt),
    )
    record = RunRecord.start(tmp_path, {"run_id": "r1"})
    result = run_pipeline(env, llm, record, "user_task_0", fault=(_finding_fault(), 0), policy=RestartStage(), delay="all")
    assert result.recovered is True and result.utility is True
    assert result.llm_calls == 7 and result.recovery_llm_calls == 2
    recovery = [e for e in record.events if e["kind"] == "recovery_action"]
    assert recovery[0]["restart_from"] == "findings" and recovery[0]["discarded"] == 3
    assert "2031-01-01" not in record.graph.artifacts["user_task_0:f0"].content["text"]


def test_always_verify_calls_verifier_per_artifact(tmp_path, fake_llm_responses, resp):
    env = Env("workspace", "user_task_0")
    gt = env.task.GROUND_TRUTH_OUTPUT
    ok = resp(content=json.dumps({"ok": True, "reason": "fine"}))
    llm = fake_llm_responses(
        resp(content="ok"),
        resp(content=json.dumps({"findings": [{"source": "calendar", "content": gt}]})),
        ok,
        resp(content=json.dumps({"steps": [{"instruction": "report", "cites": ["user_task_0:f0"]}]})),
        ok,
        resp(content=gt),
    )
    record = RunRecord.start(tmp_path, {"run_id": "r1"})
    result = run_pipeline(env, llm, record, "user_task_0", policy=AlwaysVerify())
    assert result.utility is True and result.llm_calls == 6 and result.verifier_rejections == 0
    assert sum(c["schema"] is VERDICT_SCHEMA for c in llm.calls) == 2
    assert record.graph.artifacts["user_task_0:f0"].content["verified"] is True


def test_always_verify_regenerates_a_rejected_artifact(tmp_path, fake_llm_responses, resp):
    env = Env("workspace", "user_task_0")
    gt = env.task.GROUND_TRUTH_OUTPUT
    findings = resp(content=json.dumps({"findings": [{"source": "calendar", "content": gt}]}))
    llm = fake_llm_responses(
        resp(content="ok"), findings,
        resp(content=json.dumps({"ok": False, "reason": "suspicious"})),
        resp(content="ok"), findings,
        resp(content=json.dumps({"ok": True, "reason": "fine"})),
        resp(content=json.dumps({"steps": [{"instruction": "report", "cites": ["user_task_0:f0"]}]})),
        resp(content=json.dumps({"ok": True, "reason": "fine"})),
        resp(content=gt),
    )
    record = RunRecord.start(tmp_path, {"run_id": "r1"})
    result = run_pipeline(env, llm, record, "user_task_0", policy=AlwaysVerify())
    assert result.verifier_rejections == 1 and result.llm_calls == 9 and result.utility is True


def test_condition_repeats_override_default():
    import pytest

    tasks = TaskSet(suites={"workspace": ["user_task_0"]})
    config = cfg().model_copy(update={"repeats": 3, "conditions": ["none", "restart_stage"], "condition_repeats": {"restart_stage": 1}})
    assert config.repeats_for("none") == 3 and config.repeats_for("restart_stage") == 1
    jobs = expand_jobs(config, tasks, templates=[])
    assert [(j.condition, j.repeat) for j in jobs] == [("none", 0), ("restart_stage", 0), ("none", 1), ("none", 2)]
    with pytest.raises(ValueError, match="restart_scratch"):
        ExperimentConfig(name="p", model=ModelConfig(name="m"), tasks="t", conditions=["none"], condition_repeats={"restart_scratch": 1})


def test_run_jobs_in_parallel_returns_results_in_job_order():
    import threading
    import time

    from mar.run import run_jobs

    seen, lock = [], threading.Lock()

    def work(job):
        time.sleep(0.01 * (5 - job))  # later jobs finish first
        with lock:
            seen.append(job)
        return job * 10

    assert run_jobs(list(range(5)), work, workers=3) == [0, 10, 20, 30, 40]
    assert sorted(seen) == [0, 1, 2, 3, 4] and seen != [0, 1, 2, 3, 4]
    assert run_jobs([1, 2], work, workers=1) == [10, 20]


def test_run_experiment_accepts_workers(tmp_path, fake_llm_responses):
    tasks_path = tmp_path / "tasks.yaml"
    tasks_path.write_text(yaml.safe_dump({"benchmark_version": "v1.2", "suites": {"workspace": ["user_task_0"]}}))
    config_path = tmp_path / "exp.yaml"
    config_path.write_text(yaml.safe_dump({
        "name": "smoke", "model": {"name": "fake"}, "tasks": str(tasks_path), "repeats": 2,
        "conditions": ["none"], "fault_templates": str(tmp_path / "no_templates"),
    }))
    (tmp_path / "no_templates").mkdir()
    for repeat in (0, 1):
        done = tmp_path / "runs" / f"workspace-user_task_0-none-clean-r{repeat}"
        done.mkdir(parents=True)
        (done / "result.json").write_text("{}")
    paths = run_experiment(config_path, "dev", tmp_path / "runs", resume=True, llm=fake_llm_responses(), workers=2)
    assert [p.name for p in paths] == ["workspace-user_task_0-none-clean-r0", "workspace-user_task_0-none-clean-r1"]
