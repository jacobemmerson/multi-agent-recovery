import pytest

from mar.env import ActionClass, Env, TOOL_ACTION_CLASSES


@pytest.fixture(scope="module")
def env() -> Env:
    return Env("workspace", "user_task_0")


def test_loads_task_prompt_and_tools(env):
    assert "Networking event" in env.prompt
    names = {schema["function"]["name"] for schema in env.tool_schemas()}
    assert {"send_email", "search_calendar_events", "create_file"} <= names


def test_tool_schema_is_openai_shape(env):
    schema = next(s for s in env.tool_schemas() if s["function"]["name"] == "send_email")
    assert schema["type"] == "function"
    assert "recipients" in schema["function"]["parameters"]["properties"]


def test_every_suite_tool_has_an_action_class(env):
    untagged = {tool.name for tool in env.tools} - set(TOOL_ACTION_CLASSES)
    assert untagged == set()


def test_call_runs_tool_and_records_trace(env):
    result, error = env.call("get_current_day", {})
    assert error is None
    assert result == "2024-05-15"
    assert env.trace[-1].function == "get_current_day"


def test_call_reports_unknown_tool_as_error(env):
    result, error = env.call("no_such_tool", {})
    assert result == ""
    assert "ToolNotFoundError" in error


def test_snapshot_and_restore_undo_a_reversible_action():
    env = Env("workspace", "user_task_0")
    before = env.snapshot()
    sent_before = len(env.environment.inbox.sent)
    _, error = env.call("send_email", {"recipients": ["a@b.com"], "subject": "hi", "body": "x"})
    assert error is None
    assert len(env.environment.inbox.sent) == sent_before + 1
    env.restore(before)
    assert len(env.environment.inbox.sent) == sent_before


def test_allowlist_is_ground_truth_plus_read_only(env):
    allowed = env.allowlist()
    assert "search_calendar_events" in allowed
    assert "get_current_day" in allowed
    assert "send_email" not in allowed
    assert env.is_authorized("search_calendar_events")
    assert not env.is_authorized("send_email")


def test_action_class_lookup(env):
    assert env.action_class("send_email") is ActionClass.IRREVERSIBLE
    assert env.action_class("create_calendar_event") is ActionClass.REVERSIBLE
    assert env.action_class("list_files") is ActionClass.READ_ONLY


def test_utility_passes_when_ground_truth_is_replayed():
    env = Env("workspace", "user_task_0")
    for call in env.ground_truth():
        _, error = env.call(call.function, dict(call.args))
        assert error is None
    assert env.check_utility(env.task.GROUND_TRUTH_OUTPUT) is True
    assert env.check_utility("") is False


def test_injection_task_security_check():
    env = Env("workspace", "user_task_0", injection_task_id="injection_task_0")
    assert env.check_security("") is False
    for call in env.injection_task.ground_truth(env.pre_environment):
        env.call(call.function, dict(call.args))
    assert env.check_security("") is True
