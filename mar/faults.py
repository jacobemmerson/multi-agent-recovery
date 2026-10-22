"""Fault templates, seeded schedules, injection, and the delayed oracle.

Templates are data under data/fault_templates/ and are hashed into every run manifest.
Injection targets: a finding, a plan step, a note entry, or the environment (AgentDojo
injection task). The oracle reveals fault identity Δ steps after injection.
"""

import hashlib
import random

import yaml
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Stage = Literal["finding", "plan_step", "note_entry", "environment"]
FaultType = Literal["accidental", "adversarial", "other"]
Strength = Literal["obvious", "subtle"]


class FaultTemplate(BaseModel):
    id: str
    stage: Stage
    type: FaultType
    strength: Strength
    description: str
    payload: dict


class ScheduledFault(BaseModel):
    template_id: str
    task_id: str
    position: int  # index among artifacts of that stage


def load_templates(directory: Path) -> list[FaultTemplate]:
    templates = sorted(
        (FaultTemplate.model_validate(yaml.safe_load(path.read_text())) for path in directory.glob("*.yaml")),
        key=lambda t: t.id,
    )
    ids = [t.id for t in templates]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate template ids in {directory}")
    return templates


def templates_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*.yaml")):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def schedule(templates: list[FaultTemplate], task_ids: list[str], seed: int) -> list[ScheduledFault]:
    """Seeded; over-samples plan-step injections because they land most reliably."""
    rng = random.Random(seed)
    raise NotImplementedError


def inject(fault: ScheduledFault, template: FaultTemplate, target) -> None:
    raise NotImplementedError


class Oracle:
    def __init__(self, fault_artifact_id: str, injected_at_step: int, delay: int | Literal["all"]) -> None:
        self.fault_artifact_id = fault_artifact_id
        self.injected_at_step = injected_at_step
        self.delay = delay

    def reveal_at(self, step: int) -> str | None:
        if self.delay == "all":
            return None
        return self.fault_artifact_id if step >= self.injected_at_step + self.delay else None
