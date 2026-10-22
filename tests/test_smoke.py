import agentdojo  # noqa: F401

import mar  # noqa: F401
from mar import agents, artifacts, cli, config, env, faults, judge, llm, metrics, notes, recovery, run  # noqa: F401
from mar.faults import Oracle
from mar.metrics import taint


def test_fake_llm_returns_scripted_responses(fake_llm):
    client = fake_llm("first", "second")
    assert client.complete([{"role": "user", "content": "hi"}]).content == "first"
    assert client.complete([]).content == "second"
    assert len(client.calls) == 2


def test_oracle_reveals_after_delay():
    oracle = Oracle("f1", injected_at_step=3, delay=2)
    assert oracle.reveal_at(4) is None
    assert oracle.reveal_at(5) == "f1"
    assert Oracle("f1", 3, "all").reveal_at(100) is None


def test_taint_counts():
    assert taint({"a", "b"}, {"b", "c"}) == {"under_taint": 1, "over_taint": 1}
