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
