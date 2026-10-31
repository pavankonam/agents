"""Failure taxonomy: name what went wrong in each refused or wasted step (D17, D18).

After Turing's Calendar Gym study (wrong arguments 51%, wrong tool 23%, wrong
order 18%). Every work step of an episode gets at most one kind; clean steps get
none. `submit` is never classified.

Refused steps (the env said ok=False), from the env's error_kind:

    unknown_tool             -> wrong_tool       the tool does not exist
    bad_arguments            -> wrong_arguments  missing, unexpected, wrong type, unparseable
    tool_error               -> wrong_arguments  the tool rejected the values (bad date, overlap)
    unknown_id               -> invented_id      an id that is not in the env's data

Accepted steps, checked against the task's reference solution, first match wins:

    repeated_lookup  a read only call identical (tool and arguments) to an earlier accepted one
    wrong_tool       a write tool that the reference never uses
    extra_step       a read only tool the reference never uses, or more accepted calls of
                     a tool than the reference makes
    wrong_order      the reference calls other tools before this one and at least one of
                     them has not been accepted yet (each missing prerequisite reported once)

The taxonomy explains a reward, it never changes it (D19).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from .rubrics import StepLog
from .types import SUBMIT, Action

KINDS = ("wrong_tool", "wrong_arguments", "wrong_order", "invented_id",
         "repeated_lookup", "extra_step")

REFUSED_KIND = {"unknown_tool": "wrong_tool", "bad_arguments": "wrong_arguments",
                "tool_error": "wrong_arguments", "unknown_id": "invented_id"}


@dataclass
class StepFailure:
    index: int  # 1 based position among all steps, same as StepRecord.index
    tool: str
    kind: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sig(tool: str, arguments: dict) -> str:
    return tool + json.dumps(arguments, sort_keys=True, default=str)


def classify(steps: Sequence[StepLog], reference: Sequence[Action],
             specs: Mapping[str, Any]) -> list[StepFailure]:
    """Classify every step; return only the ones that are failures, in step order."""
    ref_tools = [a.tool for a in reference]
    ref_count = Counter(ref_tools)
    seen_sigs: set[str] = set()
    accepted = Counter()
    reported_missing: set[str] = set()
    out: list[StepFailure] = []
    for i, s in enumerate(steps, start=1):
        if s.tool == SUBMIT:
            continue
        if not s.ok:
            kind = REFUSED_KIND.get(s.error_kind, "wrong_arguments")
            out.append(StepFailure(i, s.tool, kind, f"refused ({s.error_kind or 'unknown'})"))
            continue
        spec = specs.get(s.tool)
        read_only = bool(getattr(spec, "read_only", False))
        sig = _sig(s.tool, s.arguments)
        failure = None
        if read_only and sig in seen_sigs:
            failure = ("repeated_lookup", "same call already answered")
        elif s.tool not in ref_count:
            failure = (("extra_step", "lookup the reference does not need") if read_only
                       else ("wrong_tool", "write tool the reference does not use"))
        elif accepted[s.tool] >= ref_count[s.tool]:
            failure = ("extra_step", f"reference calls {s.tool} {ref_count[s.tool]} time(s)")
        else:
            before = ref_tools[:ref_tools.index(s.tool)]
            missing = [t for t in dict.fromkeys(before)
                       if accepted[t] == 0 and t not in reported_missing]
            if missing:
                reported_missing.update(missing)
                failure = ("wrong_order", "called before " + ", ".join(missing))
        seen_sigs.add(sig)
        accepted[s.tool] += 1
        if failure:
            out.append(StepFailure(i, s.tool, *failure))
    return out


def count_kinds(failures: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Counts per kind, every kind present (0 if none), in KINDS order."""
    c = Counter(f["kind"] for f in failures)
    return {k: c.get(k, 0) for k in KINDS}


def summarize(episodes: Iterable[Any]) -> dict[str, dict[str, int]]:
    """Per task counts plus a `total` row, from anything with task_id and failures."""
    rows: dict[str, Counter] = {}
    total: Counter = Counter()
    for ep in episodes:
        c = Counter(count_kinds(ep.failures))
        rows.setdefault(ep.task_id, Counter()).update(c)
        total.update(c)
    out = {task: {k: c.get(k, 0) for k in KINDS} for task, c in rows.items()}
    out["total"] = {k: total.get(k, 0) for k in KINDS}
    return out
