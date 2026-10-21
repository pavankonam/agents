"""JSONL audit log and replay (see decisions D21 to D25).

One JSON object per line. Every event has:
  ts      UTC timestamp, ISO 8601 with milliseconds
  run_id  12 hex chars, the same for every event of one Agent.run
  seq     0, 1, 2 ... within the run (gaps or repeats mean a damaged log)
  type    run_start | model_reply | tool_decision | tool_result | injection_warning |
          run_end | run_error

The tool_decision event is written BEFORE the tool runs, so a verdict is on disk
even if the tool or the process dies halfway (success criterion: no tool runs
without a recorded verdict).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

MAX_FIELD_CHARS = 2000  # long strings (file contents, tool output) are clipped in the log
EVENT_TYPES = ("run_start", "model_reply", "tool_decision", "tool_result", "injection_warning",
               "run_end", "run_error")


def clip(value: Any, limit: int = MAX_FIELD_CHARS) -> Any:
    """Recursively shorten long strings so one write_file cannot bloat the log."""
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[:limit] + f"...[clipped {len(value) - limit} chars]"
    if isinstance(value, dict):
        return {str(k): clip(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clip(v, limit) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return clip(repr(value), limit)


class AuditLog:
    """Appends events to a JSONL file. One instance can record many runs."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id: str | None = None
        self._seq = 0

    def start_run(self, **fields: Any) -> str:
        self.run_id = uuid.uuid4().hex[:12]
        self._seq = 0
        self.write("run_start", **fields)
        return self.run_id

    def write(self, type: str, **fields: Any) -> dict:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown audit event type '{type}'")
        if self.run_id is None:
            raise RuntimeError("start_run() must be called before writing events")
        event = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "seq": self._seq,
            "type": type,
            **clip(fields),
        }
        self._seq += 1
        # open, append, close per event: the line is on disk before the next step runs
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        return event


def load_events(path: str | Path) -> tuple[list[dict], int]:
    """Read a log. Returns (events, number of malformed lines skipped)."""
    events, bad = [], 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if not isinstance(ev, dict) or "run_id" not in ev or "type" not in ev:
            bad += 1
            continue
        events.append(ev)
    return events, bad


def group_runs(events: Iterable[dict]) -> dict[str, list[dict]]:
    runs: dict[str, list[dict]] = {}
    for ev in events:
        runs.setdefault(ev["run_id"], []).append(ev)
    for evs in runs.values():
        evs.sort(key=lambda e: e.get("seq", 0))
    return runs


def _short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def format_event(ev: dict) -> str:
    t, step = ev["type"], ev.get("step")
    tag = f"  [{step}]" if step is not None else "  "
    if t == "run_start":
        return (f"run {ev['run_id']}  {ev.get('ts', '')}  model={ev.get('model', '?')}  "
                f"max_steps={ev.get('max_steps', '?')}\n  task: {_short(ev.get('task', ''))}")
    if t == "model_reply":
        calls = ev.get("tool_calls") or []
        if calls:
            names = ", ".join(f"{c.get('name')}({_short(c.get('arguments', {}), 80)})"
                              for c in calls)
            return f"{tag} model asks for {names}"
        return f"{tag} model answers: {_short(ev.get('content', ''))}"
    if t == "tool_decision":
        outcome = "RAN" if ev.get("approved") else "BLOCKED"
        return (f"{tag} policy {ev.get('tool')}: verdict={ev.get('verdict')} -> {outcome}"
                f"  ({ev.get('reason', '')})")
    if t == "tool_result":
        return f"{tag} result {ev.get('tool')}: {_short(ev.get('output', ''))}"
    if t == "injection_warning":
        return (f"{tag} GUARD {ev.get('tool')}: possible prompt injection "
                f"({', '.join(ev.get('labels') or [])}); later calls need approval")
    if t == "run_end":
        warn = ev.get("injection_warnings", 0)
        return (f"  end: {ev.get('stopped_reason')} after {ev.get('steps')} step(s), "
                f"{ev.get('tool_calls', 0)} tool call(s), {ev.get('blocked', 0)} blocked"
                + (f", {warn} injection warning(s)" if warn else ""))
    if t == "run_error":
        return f"  ERROR: {ev.get('error')}"
    return f"  ? unknown event {t}"


def check_run(evs: list[dict]) -> list[str]:
    """Integrity problems in one run's events (empty list means the run looks complete)."""
    problems = []
    seqs = [e.get("seq") for e in evs]
    if seqs != list(range(len(evs))):
        problems.append(f"seq is not 0..{len(evs) - 1} (events missing or duplicated)")
    if not evs or evs[0]["type"] != "run_start":
        problems.append("no run_start")
    if not evs or evs[-1]["type"] not in ("run_end", "run_error"):
        problems.append("run did not finish (no run_end or run_error)")
    decided = 0
    for e in evs:
        if e["type"] == "tool_decision":
            decided += 1
        elif e["type"] == "tool_result" and decided == 0:
            problems.append(f"tool_result for {e.get('tool')} before any tool_decision")
    results = sum(1 for e in evs if e["type"] == "tool_result")
    if results > decided:
        problems.append(f"{results} tool results but only {decided} verdicts")
    return problems


def replay(path: str | Path, run_id: str | None = None) -> str:
    """Render a log as a readable timeline. run_id may be a prefix."""
    events, bad = load_events(path)
    runs = group_runs(events)
    if run_id:
        runs = {k: v for k, v in runs.items() if k.startswith(run_id)}
        if not runs:
            return f"no run matching '{run_id}' in {path}"
    out = []
    for evs in runs.values():
        out.extend(format_event(e) for e in evs)
        for p in check_run(evs):
            out.append(f"  WARNING: {p}")
        out.append("")
    if bad:
        out.append(f"(skipped {bad} malformed line(s))")
    if not runs:
        out.append(f"no runs in {path}")
    return "\n".join(out).rstrip() + "\n"
