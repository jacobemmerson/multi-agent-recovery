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
