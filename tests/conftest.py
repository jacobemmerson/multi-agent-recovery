import pytest

from mar.llm import FakeLLM, LLMResponse


@pytest.fixture
def fake_llm():
    def make(*contents: str) -> FakeLLM:
        return FakeLLM(
            [
                LLMResponse(content=c, tool_calls=[], model="fake", system_fingerprint=None, usage={})
                for c in contents
            ]
        )

    return make


@pytest.fixture
def fake_llm_responses():
    def make(*responses: LLMResponse) -> FakeLLM:
        return FakeLLM(list(responses))

    return make


@pytest.fixture
def resp():
    def make(content=None, tool_calls=()) -> LLMResponse:
        return LLMResponse(content=content, tool_calls=list(tool_calls), model="fake", system_fingerprint=None, usage={})

    return make


@pytest.fixture
def build_run(tmp_path):
    """RunRecord with findings (texts), steps ((instruction, cites)), executed steps (output per step)."""
    from mar.artifacts import ExecutedStep, Finding, PlanStep
    from mar.run import RunRecord

    def make(name, findings, steps, execs=(), fault_artifact_id=None):
        record = RunRecord.start(tmp_path, {"run_id": name})
        for i, text in enumerate(findings):
            record.add_artifact(Finding(id=f"t:f{i}", producer="r", task_id="t", source="s", content={"text": text}))
        for i, (instruction, cites) in enumerate(steps):
            record.add_artifact(PlanStep(id=f"t:p{i}", producer="p", task_id="t", index=i, cites=cites, content={"instruction": instruction}))
        for i, output in enumerate(execs):
            record.add_artifact(ExecutedStep(id=f"t:exec:t:p{i}", producer="e", task_id="t", plan_step_id=f"t:p{i}", cites=[f"t:p{i}"], content={"output": output}))
        if fault_artifact_id:
            record.emit("fault_injected", template_id="x", stage="finding", position=0, applied=True, artifact_id=fault_artifact_id)
        return record

    return make
