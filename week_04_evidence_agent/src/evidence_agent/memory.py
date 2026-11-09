"""Memory of verified findings across runs (D28 to D32).

After a run, every accepted finding whose check was `supported` is stored with
the rows that backed it. Before the next run on the same scenario each stored
finding is re-checked against the current data: every stored row is looked up
by its identity (kind, time, service and, for metrics, the metric name) and the
check is run again on the rows found now. A finding is recalled only when every
row is still there and the check still holds on the current values; otherwise
it is dropped with the reason and forgotten. Recalled rows get evidence ids in
the new run's ledger, so the model can cite them like rows it queried.

The store is a small JSON file: {"version": 1, "entries": [...]}.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .support import SUPPORTED, check_rows, describe, parse_check
from .telemetry import KINDS, Record, Scenario

VERSION = 1
KEPT, DROPPED = "kept", "dropped"
ENTRY_KEYS = ("scenario", "claim", "check", "rows")


def identity(rec: Record) -> tuple[str, str, str, str]:
    """What a row is about, without its value: a changed value is the same row (D29)."""
    return (rec.kind, rec.ts, rec.service, rec.data.get("metric", "") if rec.kind == "metric" else "")


def row_record(d: Any) -> Record | None:
    """A stored row back as a Record, or None when it is malformed."""
    if not isinstance(d, dict) or d.get("kind") not in KINDS:
        return None
    if not all(isinstance(d.get(k), str) for k in ("ts", "service")):
        return None
    data = d.get("data")
    need = {"log": ("level", "message"), "metric": ("metric", "value"),
            "deploy": ("version", "note")}[d["kind"]]
    if not isinstance(data, dict) or any(k not in data for k in need):
        return None
    return Record(d["kind"], d["ts"], d["service"], dict(data))


@dataclass
class Recalled:
    """The outcome of re-checking one remembered finding against the current data."""

    claim: str
    status: str  # KEPT or DROPPED
    reason: str = ""
    keys: list[int] = field(default_factory=list)  # backing rows, as indices in the scenario
    ids: list[str] = field(default_factory=list)   # evidence ids issued for them in this run


class FindingMemory:
    def __init__(self, path: str | os.PathLike | None = None,
                 entries: list[dict[str, Any]] | None = None):
        self.path = Path(path) if path is not None else None
        self.entries: list[dict[str, Any]] = list(entries or [])

    # ----- file ----------------------------------------------------------
    @classmethod
    def load(cls, path: str | os.PathLike) -> "FindingMemory":
        """Load a memory file; a missing file is an empty memory. Raises ValueError when malformed."""
        p = Path(path)
        if not p.exists():
            return cls(p)
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"memory file {p} is not valid JSON: {exc.msg}") from None
        if not isinstance(raw, dict) or raw.get("version") != VERSION \
                or not isinstance(raw.get("entries"), list):
            raise ValueError(f"memory file {p} is not a version {VERSION} memory")
        for e in raw["entries"]:
            if not isinstance(e, dict) or any(k not in e for k in ENTRY_KEYS):
                raise ValueError(f"memory file {p} has an entry without {', '.join(ENTRY_KEYS)}")
        return cls(p, raw["entries"])

    def save(self, path: str | os.PathLike | None = None) -> None:
        p = Path(path) if path is not None else self.path
        if p is None:
            raise ValueError("no path to save the memory to")
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps({"version": VERSION, "entries": self.entries}, indent=1,
                                  sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, p)

    # ----- recall --------------------------------------------------------
    def recheck(self, entry: dict[str, Any], scenario: Scenario) -> Recalled:
        """Re-check one entry against the scenario's current records."""
        claim = str(entry.get("claim", ""))
        check, err = parse_check(entry.get("check"))
        if err:
            return Recalled(claim, DROPPED, f"invalid check: {err}")
        rows = entry.get("rows")
        if not isinstance(rows, list) or not rows:
            return Recalled(claim, DROPPED, "no stored rows")
        keys: list[int] = []
        for d in rows:
            rec = row_record(d)
            if rec is None:
                return Recalled(claim, DROPPED, "malformed stored row")
            found = [k for k, r in enumerate(scenario.records) if identity(r) == identity(rec)]
            if not found:
                return Recalled(claim, DROPPED, f"row no longer in the data: {rec.line()}")
            keys += [k for k in found if k not in keys]
        by_label = {scenario.records[k].line(): k for k in keys}  # rows are named by their line
        res = check_rows(check, [(label, scenario.records[k]) for label, k in by_label.items()],
                         what="current")
        if res.status != SUPPORTED:
            return Recalled(claim, DROPPED, f"claim now {res.status}: {res.reason}")
        return Recalled(claim, KEPT, "", [by_label[label] for label in res.ids])

    def recall(self, scenario: Scenario) -> list[Recalled]:
        """Re-check every entry of this scenario; dropped entries are forgotten (D30)."""
        out: list[Recalled] = []
        keep: list[dict[str, Any]] = []
        for e in self.entries:
            if e.get("scenario") != scenario.name:
                keep.append(e)
                continue
            r = self.recheck(e, scenario)
            out.append(r)
            if r.status == KEPT:
                keep.append(e)
        self.entries = keep
        return out

    # ----- remember ------------------------------------------------------
    def remember(self, scenario: Scenario, findings, ledger) -> int:
        """Store accepted, supported findings with their backing rows. Returns how many.
        A finding with the same check replaces the older one (D28)."""
        stored = 0
        for f in findings:
            if not (f.accepted and f.support == SUPPORTED and f.check and f.support_ids):
                continue
            entry = {"scenario": scenario.name, "claim": f.claim, "check": dict(f.check),
                     "rows": [ledger.get(i).record.to_dict() for i in f.support_ids]}
            same = describe(f.check)
            self.entries = [e for e in self.entries if not (
                e.get("scenario") == scenario.name and _describe(e.get("check")) == same)]
            self.entries.append(entry)
            stored += 1
        return stored

    def for_scenario(self, name: str) -> list[dict[str, Any]]:
        return [e for e in self.entries if e.get("scenario") == name]


def _describe(raw: Any) -> str:
    check, err = parse_check(raw)
    return "" if err else describe(check)
