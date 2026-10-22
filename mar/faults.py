"""Fault templates, injection, positions, and the delayed oracle.

Templates are data under data/fault_templates/ and are hashed into every run manifest.
Every template runs on every task; only the position within the stage is random and
seeded. Injection is pure: it returns a new artifact list and never mutates its input.
"""

import hashlib
import random
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from mar.artifacts import Artifact, PlanStep

Stage = Literal["finding", "plan_step", "note_entry", "environment"]
FaultType = Literal["accidental", "adversarial", "other"]
Strength = Literal["obvious", "subtle"]
Op = Literal["regex_replace", "append", "replace_content", "stale_copy", "insert_step"]

TEXT_FIELD = {"finding": "text", "plan_step": "instruction", "note_entry": "text"}


class FaultTemplate(BaseModel):
    id: str
    stage: Stage
    type: FaultType
    strength: Strength
    description: str
    op: Op
    payload: dict = {}


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


def position_for(fault_id: str, task_id: str, seed: int, n_candidates: int) -> int:
    return random.Random(f"{seed}:{fault_id}:{task_id}").randrange(max(n_candidates, 1))


def inject(template: FaultTemplate, artifacts: list[Artifact], position: int) -> tuple[list[Artifact], bool]:
    """Apply the template at `position`. Returns (new list, whether anything changed)."""
    if not artifacts or position >= len(artifacts):
        return list(artifacts), False
    field = TEXT_FIELD[template.stage]
    target = artifacts[position]
    text = target.content.get(field, "")
    out = [a.model_copy(deep=True) for a in artifacts]

    if template.op == "insert_step":
        if not isinstance(target, PlanStep):
            return out, False
        injected = PlanStep(
            id=f"{target.id}-injected",
            producer=target.producer,
            task_id=target.task_id,
            branch_id=target.branch_id,
            index=target.index + 1,
            cites=list(target.cites),
            content={field: template.payload["instruction"], "fault": template.id},
        )
        out.insert(position + 1, injected)
        for step in out[position + 2 :]:
            step.index += 1
        return out, True

    if template.op == "regex_replace":
        new_text, n = re.subn(template.payload["pattern"], template.payload["replacement"], text, count=1)
        if n == 0:
            return out, False
    elif template.op == "append":
        new_text = text + template.payload["text"]
    elif template.op == "replace_content":
        new_text = template.payload["text"]
    elif template.op == "stale_copy":
        neighbor = position - 1 if position > 0 else position + 1
        if neighbor >= len(artifacts):
            return out, False
        new_text = artifacts[neighbor].content.get(field, "")
    else:
        raise ValueError(f"unknown op {template.op}")

    if new_text == text:
        return out, False
    out[position].content[field] = new_text
    out[position].content["fault"] = template.id
    return out, True


class Oracle:
    def __init__(self, fault_artifact_id: str, injected_at_step: int, delay: int | Literal["all"]) -> None:
        self.fault_artifact_id = fault_artifact_id
        self.injected_at_step = injected_at_step
        self.delay = delay

    def reveal_at(self, step: int, final: bool = False) -> str | None:
        """Fault identity once `delay` steps have passed since injection; "all" means only at the end."""
        if self.delay == "all":
            return self.fault_artifact_id if final else None
        return self.fault_artifact_id if step >= self.injected_at_step + self.delay else None
