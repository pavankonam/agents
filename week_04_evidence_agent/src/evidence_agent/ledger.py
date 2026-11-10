"""Evidence ledger: the only source of citable ids (D4).

Every record a tool returns gets an id like ev_001. The same record returned
again keeps its id. An id that the ledger never issued cannot be cited.
With `seed` (eval variants, D34) the ids are still ev_NNN and unique but drawn
in a seeded random order, so ev_001 is not "the first row shown".
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .telemetry import Record


@dataclass(frozen=True)
class Evidence:
    id: str
    record: Record
    first_tool: str  # the tool call that first returned it
    first_step: int
    key: int = -1  # index of the record in the scenario (used by grading, D19)


class EvidenceLedger:
    def __init__(self, seed: int | None = None) -> None:
        self._by_id: dict[str, Evidence] = {}
        self._by_key: dict[int, str] = {}
        self._pool: list[int] | None = None
        if seed is not None:
            self._pool = list(range(1, 1000))
            random.Random(f"ledger:{seed}").shuffle(self._pool)

    def issue(self, key: int, record: Record, tool: str, step: int) -> str:
        """Return the id for `record` (keyed by its index in the scenario)."""
        if key in self._by_key:
            return self._by_key[key]
        n = self._pool[len(self._by_id)] if self._pool is not None else len(self._by_id) + 1
        eid = f"ev_{n:03d}"
        self._by_id[eid] = Evidence(eid, record, tool, step, key)
        self._by_key[key] = eid
        return eid

    def __contains__(self, eid: object) -> bool:
        return eid in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, eid: str) -> Evidence:
        return self._by_id[eid]

    def ids(self) -> list[str]:
        return list(self._by_id)

    def unknown(self, ids: list[str]) -> list[str]:
        """Ids in `ids` that this ledger never issued, in order, without repeats."""
        out: list[str] = []
        for i in ids:
            if i not in self._by_id and i not in out:
                out.append(i)
        return out
