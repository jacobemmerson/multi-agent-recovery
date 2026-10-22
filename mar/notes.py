"""Cross-task notes with per-entry provenance.

Agents append at the end of a task and read at the start of the next. A poisoned entry
therefore has a path into later tasks. Coarse purge restores the whole file; fine purge
drops only entries descended from the fault.
"""

from mar.artifacts import NoteEntry, ProvenanceGraph


class NotesStore:
    def __init__(self) -> None:
        self.entries: list[NoteEntry] = []

    def append(self, entry: NoteEntry) -> None:
        self.entries.append(entry)

    def read_all(self) -> list[NoteEntry]:
        return list(self.entries)

    def purge_coarse(self, snapshot: list[NoteEntry]) -> int:
        """Restore a whole-file snapshot; returns entries dropped (collateral included)."""
        raise NotImplementedError

    def purge_fine(self, fault_id: str, graph: ProvenanceGraph) -> int:
        """Drop entries descended from the fault; returns entries dropped."""
        raise NotImplementedError
