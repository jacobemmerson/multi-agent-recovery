from types import SimpleNamespace

from mar.llm import OpenAICompatibleClient


def _fake_openai(message, model="api-glm-5.3", fingerprint="fp"):
    fake = SimpleNamespace(last_kwargs=None)

    def create(**kwargs):
        fake.last_kwargs = kwargs
        return SimpleNamespace(
            model=model,
            system_fingerprint=fingerprint,
            usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}),
            choices=[SimpleNamespace(message=message)],
            model_dump=lambda: {"id": "x"},
        )

    fake.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
    return fake


def test_text_response_is_parsed():
    msg = SimpleNamespace(content="hello", tool_calls=None)
    client = OpenAICompatibleClient("api-glm-5.3", 0.0, 100, client=_fake_openai(msg))
    r = client.complete([{"role": "user", "content": "hi"}])
    assert r.content == "hello" and r.tool_calls == []
    assert r.model == "api-glm-5.3" and r.system_fingerprint == "fp"
    assert r.usage["total_tokens"] == 5


def test_tool_calls_are_parsed_and_arguments_decoded():
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name="get_weather", arguments='{"city": "SD"}'))
    msg = SimpleNamespace(content=None, tool_calls=[tc])
    client = OpenAICompatibleClient("m", 0.0, 100, client=_fake_openai(msg))
    r = client.complete([], tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {}}}])
    assert r.tool_calls == [{"id": "c1", "name": "get_weather", "args": {"city": "SD"}}]


def test_malformed_arguments_do_not_raise():
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name="f", arguments="{not json"))
    client = OpenAICompatibleClient("m", 0.0, 100, client=_fake_openai(SimpleNamespace(content=None, tool_calls=[tc])))
    call = client.complete([]).tool_calls[0]
    assert call["args"] == {} and "args_error" in call


def test_schema_is_sent_as_strict_json_schema():
    fake = _fake_openai(SimpleNamespace(content="{}", tool_calls=None))
    OpenAICompatibleClient("m", 0.0, 100, client=fake).complete([], schema={"type": "object", "properties": {}})
    rf = fake.last_kwargs["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert "tools" not in fake.last_kwargs
