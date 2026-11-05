"""Evidence ledger: the only source of citable ids (D4).

Every record a tool returns gets an id like ev_001. The same record returned
again keeps its id. An id that the ledger never issued cannot be cited.
"""

from __future__ import annotations

from dataclasses import dataclass

from .telemetry import Record


@dataclass(frozen=True)
class Evidence:
    id: str
    record: Record
    first_tool: str  # the tool call that first returned it
    first_step: int


class EvidenceLedger:
    def __init__(self) -> None:
        self._by_id: dict[str, Evidence] = {}
        self._by_key: dict[int, str] = {}

    def issue(self, key: int, record: Record, tool: str, step: int) -> str:
        """Return the id for `record` (keyed by its index in the scenario)."""
        if key in self._by_key:
            return self._by_key[key]
        eid = f"ev_{len(self._by_id) + 1:03d}"
        self._by_id[eid] = Evidence(eid, record, tool, step)
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
