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
