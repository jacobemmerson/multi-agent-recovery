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
