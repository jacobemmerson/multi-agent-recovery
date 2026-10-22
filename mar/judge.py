"""Artifact comparison: exact diff, LLM judge, noise floor, and agreement with hand labels.

AgentDojo checkers judge final state only, so intermediate artifacts need their own judge.
Every propagation or divergence number is read against the clean-vs-clean noise floor.
"""

from mar.artifacts import Artifact
from mar.llm import LLMClient


def exact_diff(a: Artifact, b: Artifact) -> bool:
    return a.content != b.content


def judge_diff(a: Artifact, b: Artifact, llm: LLMClient) -> bool:
    raise NotImplementedError


def noise_floor(run_a, run_b) -> dict[str, float]:
    raise NotImplementedError


def agreement(judge_labels: list[bool], hand_labels: list[bool]) -> float:
    raise NotImplementedError
