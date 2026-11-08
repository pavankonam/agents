"""Bounds on one investigation: a query budget, the incident time window and a
kill switch an operator can trip from outside the loop. Every refusal and every
stop is written to the audit log with who and why (D23 to D26).
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

# tools that read telemetry rows; each call that runs spends one query (D23)
QUERY_TOOLS = ("search_logs", "get_metric", "list_deploys")
DEFAULT_MAX_QUERIES = 8

REFUSED = "refused"
STOP = "stop"
SYSTEM = "system"
AGENT = "agent"

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass
class AuditEntry:
    """One line of the audit log. `step` is the step it happened at (0 before any step)."""

    step: int
    event: str  # REFUSED or STOP
    rule: str   # query_budget, time_window, killed, concluded, no_conclusion, step_limit, turn_limit
    actor: str  # who decided: the operator's name, "system" or "agent"
    reason: str

    def line(self) -> str:
        return f"step {self.step} {self.event} {self.rule} by {self.actor}: {self.reason}"


def window_problem(window: tuple[str, str], since: str | None, until: str | None) -> str:
    """Return why a since/until pair is refused, or "" when it fits the window (D24)."""
    start, end = window
    for name, value in (("since", since), ("until", until)):
        if value is None:
            continue
        if not _HHMM.match(value):
            return f"{name} must be HH:MM, got {value!r}"
        if not start <= value <= end:
            return (f"{name} {value} is outside the incident window {start} to {end}; "
                    "queries outside the window are refused")
    if since is not None and until is not None and since > until:
        return f"since {since} is after until {until}"
    return ""


class KillSwitch:
    """Tripped by an operator from outside the loop; checked before every model
    turn and every tool call (D25). Thread safe, and the first trip wins."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._trip: tuple[str, str] | None = None

    def trigger(self, by: str, reason: str) -> None:
        by, reason = (by or "").strip(), (reason or "").strip()
        if not by or not reason:
            raise ValueError("a kill needs who (by) and why (reason)")
        with self._lock:
            if self._trip is None:
                self._trip = (by, reason)

    def tripped(self) -> tuple[str, str] | None:
        with self._lock:
            return self._trip


class FileKillSwitch(KillSwitch):
    """Tripped when a file appears, so an operator can stop a running CLI from
    another terminal: `echo "pavan: wrong target" > stop.txt` (D25)."""

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self.path = Path(path)

    def tripped(self) -> tuple[str, str] | None:
        trip = super().tripped()
        if trip is None and self.path.exists():
            text = self.path.read_text(encoding="utf-8", errors="replace").strip()
            first = text.splitlines()[0].strip() if text else ""
            by, sep, reason = first.partition(":")
            if sep and by.strip() and reason.strip():
                self.trigger(by.strip(), reason.strip())
            else:
                self.trigger("operator", first or f"kill file {self.path} present")
            trip = super().tripped()
        return trip
