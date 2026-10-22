"""Pydantic models for the YAML files under configs/."""

from pathlib import Path

import yaml
from pydantic import BaseModel


class ModelConfig(BaseModel):
    name: str
    temperature: float = 0.0
    max_tokens: int = 4096


class TaskSet(BaseModel):
    benchmark_version: str = "v1.2"
    suites: dict[str, list[str]]


class ExperimentConfig(BaseModel):
    name: str
    model: ModelConfig
    tasks: str
    repeats: int = 3
    conditions: list[str]
    fault_templates: Path = Path("data/fault_templates")
    benchmark_version: str = "v1.2"
    detection_delays: list[int | str] = [0]


def load_experiment(path: Path) -> ExperimentConfig:
    return ExperimentConfig.model_validate(yaml.safe_load(path.read_text()))


def load_task_set(path: Path) -> TaskSet:
    return TaskSet.model_validate(yaml.safe_load(path.read_text()))
