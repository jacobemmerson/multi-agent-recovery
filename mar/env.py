"""AgentDojo wrapper: task loading, snapshots, tool action classes, allowlist, checkers.

AgentDojo is used for its suites, TaskEnvironment, FunctionsRuntime and utility/security
checks. Its single-agent AgentPipeline is not used. Tool state is Pydantic objects, so a
deep copy is a snapshot, and tools read the environment on each call, so swapping the
environment object is a restore.
"""

from enum import Enum
from typing import Any

from agentdojo.base_tasks import BaseInjectionTask, BaseUserTask
from agentdojo.functions_runtime import Function, FunctionCall, FunctionsRuntime, TaskEnvironment
from agentdojo.task_suite.load_suites import get_suite


class ActionClass(str, Enum):
    READ_ONLY = "read_only"
    REVERSIBLE = "reversible"
    COMPENSATABLE = "compensatable"
    IRREVERSIBLE = "irreversible"


# AgentDojo tools carry no class tag, so the mapping lives here. Unknown tools fail loudly.
TOOL_ACTION_CLASSES: dict[str, ActionClass] = {
    # workspace: email
    "send_email": ActionClass.IRREVERSIBLE,
    "delete_email": ActionClass.REVERSIBLE,
    "get_unread_emails": ActionClass.READ_ONLY,
    "get_sent_emails": ActionClass.READ_ONLY,
    "get_received_emails": ActionClass.READ_ONLY,
    "get_draft_emails": ActionClass.READ_ONLY,
    "search_emails": ActionClass.READ_ONLY,
    "search_contacts_by_name": ActionClass.READ_ONLY,
    "search_contacts_by_email": ActionClass.READ_ONLY,
    # workspace: calendar
    "get_current_day": ActionClass.READ_ONLY,
    "search_calendar_events": ActionClass.READ_ONLY,
    "get_day_calendar_events": ActionClass.READ_ONLY,
    "create_calendar_event": ActionClass.REVERSIBLE,
    "cancel_calendar_event": ActionClass.REVERSIBLE,
    "reschedule_calendar_event": ActionClass.REVERSIBLE,
    "add_calendar_event_participants": ActionClass.REVERSIBLE,
    # workspace: drive
    "append_to_file": ActionClass.REVERSIBLE,
    "search_files_by_filename": ActionClass.READ_ONLY,
    "create_file": ActionClass.REVERSIBLE,
    "delete_file": ActionClass.REVERSIBLE,
    "get_file_by_id": ActionClass.READ_ONLY,
    "list_files": ActionClass.READ_ONLY,
    "share_file": ActionClass.REVERSIBLE,
    "search_files": ActionClass.READ_ONLY,
}


class Env:
    """One AgentDojo user task with its environment, runtime, and optional injection task."""

    def __init__(
        self,
        suite_name: str,
        task_id: str,
        benchmark_version: str = "v1.2",
        injection_task_id: str | None = None,
        injections: dict[str, str] | None = None,
    ) -> None:
        self.suite = get_suite(benchmark_version, suite_name)
        self.task: BaseUserTask = self.suite.get_user_task_by_id(task_id)
        self.injection_task: BaseInjectionTask | None = (
            self.suite.get_injection_task_by_id(injection_task_id) if injection_task_id else None
        )
        environment = self.suite.load_and_inject_default_environment(injections or {})
        self.environment: TaskEnvironment = self.task.init_environment(environment)
        self.pre_environment: TaskEnvironment = self.snapshot()
        self.runtime = FunctionsRuntime(self.suite.tools)
        self.trace: list[FunctionCall] = []

    @property
    def prompt(self) -> str:
        return self.task.PROMPT

    @property
    def tools(self) -> list[Function]:
        return self.suite.tools

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters.model_json_schema(),
                },
            }
            for tool in self.tools
        ]

    def call(self, name: str, args: dict[str, Any]) -> tuple[Any, str | None]:
        """Run a tool against the live environment. Returns (result, error message or None)."""
        self.trace.append(FunctionCall(function=name, args=args))
        return self.runtime.run_function(self.environment, name, args)

    def snapshot(self) -> TaskEnvironment:
        return self.environment.model_copy(deep=True)

    def restore(self, snapshot: TaskEnvironment) -> None:
        self.environment = snapshot.model_copy(deep=True)

    def action_class(self, tool_name: str) -> ActionClass:
        return TOOL_ACTION_CLASSES[tool_name]

    def ground_truth(self) -> list[FunctionCall]:
        return self.task.ground_truth(self.pre_environment)

    def allowlist(self) -> set[str]:
        """Tools in the ground-truth solution plus read-only tools."""
        read_only = {tool.name for tool in self.tools if self.action_class(tool.name) is ActionClass.READ_ONLY}
        return read_only | {call.function for call in self.ground_truth()}

    def is_authorized(self, tool_name: str) -> bool:
        return tool_name in self.allowlist()

    def check_utility(self, model_output: str) -> bool:
        from_traces = self.task.utility_from_traces(model_output, self.pre_environment, self.environment, self.trace)
        if from_traces is not None:
            return from_traces
        return self.task.utility(model_output, self.pre_environment, self.environment)

    def check_security(self, model_output: str) -> bool:
        """True when the injection task's goal was achieved. Requires an injection task."""
        if self.injection_task is None:
            raise ValueError("no injection task loaded")
        from_traces = self.injection_task.security_from_traces(
            model_output, self.pre_environment, self.environment, self.trace
        )
        if from_traces is not None:
            return from_traces
        return self.injection_task.security(model_output, self.pre_environment, self.environment)
