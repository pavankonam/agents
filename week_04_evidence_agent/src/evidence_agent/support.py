"""Claim support: check a structured claim against the rows a finding cites (D13 to D16).

A finding may carry a `check`, a small machine readable form of its claim:

    {"service": "checkout", "field": "p95_latency_ms", "op": ">", "value": 2000, "at": "14:05"}

`field` is a metric name for metric rows, `level` or `message` for log rows and
`version` or `note` for deploy rows. `at` is optional; without it the claim
reads "at some cited time". Only the cited rows are looked at, never the rest
of the scenario: the question is whether the evidence the model chose backs
what it says.

Statuses:
    supported     a relevant cited row satisfies the check
    contradicted  relevant cited rows exist and none satisfies the check
    unsupported   no cited row is about this service, field (and time)
    invalid       the check itself is malformed
    unchecked     no check given, or the citations were already rejected
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .ledger import EvidenceLedger
from .telemetry import Record

SUPPORTED, CONTRADICTED, UNSUPPORTED, INVALID, UNCHECKED = (
    "supported", "contradicted", "unsupported", "invalid", "unchecked")
STATUSES = (SUPPORTED, CONTRADICTED, UNSUPPORTED, INVALID, UNCHECKED)

NUMERIC_OPS = (">", ">=", "<", "<=")
TEXT_OPS = ("==", "contains")
OPS = NUMERIC_OPS + TEXT_OPS
# small models often spell the operators out; accept the common words (D15)
OP_ALIASES = {"gt": ">", "gte": ">=", "ge": ">=", "lt": "<", "lte": "<=", "le": "<=",
              "eq": "==", "=": "==", "equals": "=="}
CHECK_KEYS = ("service", "field", "op", "value", "at")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
LOG_FIELDS = ("level", "message")
DEPLOY_FIELDS = ("version", "note")

CHECK_SCHEMA = {
    "type": "object",
    "description": ("optional machine checkable form of the claim, checked against the cited rows. "
                    "field is a metric name, or level/message for logs, or version/note for deploys"),
    "properties": {
        "service": {"type": "string"},
        "field": {"type": "string"},
        "op": {"type": "string", "enum": list(OPS)},
        "value": {"description": "a number for metrics, text for logs and deploys"},
        "at": {"type": "string", "description": "optional HH:MM the claim is about"},
    },
    "required": ["service", "field", "op", "value"],
}


@dataclass
class SupportResult:
    status: str
    reason: str = ""
    ids: list[str] = field(default_factory=list)  # relevant cited rows (backing or contradicting)


def parse_check(raw: Any) -> tuple[dict[str, Any] | None, str]:
    """Normalise a check. Returns (check, "") or (None, error)."""
    if not isinstance(raw, dict):
        return None, "check must be an object"
    extra = sorted(set(raw) - set(CHECK_KEYS))
    if extra:
        return None, f"unexpected key(s) in check: {', '.join(extra)}"
    missing = [k for k in CHECK_KEYS[:4] if k not in raw]
    if missing:
        return None, f"check is missing: {', '.join(missing)}"
    for k in ("service", "field", "op"):
        if not isinstance(raw[k], str) or not raw[k].strip():
            return None, f"check {k} must be a non empty string"
    op = raw["op"].strip().lower()
    op = OP_ALIASES.get(op, op)
    if op not in OPS:
        return None, f"check op must be one of {', '.join(OPS)}"
    value = raw["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None, "check value must be a number or text"
    if op in NUMERIC_OPS:
        try:
            value = float(value)
        except ValueError:
            return None, f"check op {op} needs a number, got {value!r}"
    else:
        value = str(value)
    at = raw.get("at")
    if at is not None and not (isinstance(at, str) and _TIME.match(at)):
        return None, "check at must be a time like 14:05"
    return {"service": raw["service"].strip(), "field": raw["field"].strip(), "op": op,
            "value": value, "at": at}, ""


def field_value(rec: Record, name: str) -> Any:
    """The value `rec` holds for field `name`, or None when the row is not about that field."""
    if rec.kind == "metric":
        return rec.data["value"] if rec.data["metric"] == name else None
    allowed = LOG_FIELDS if rec.kind == "log" else DEPLOY_FIELDS
    return rec.data[name] if name in allowed else None


def holds(actual: Any, op: str, expected: Any) -> bool:
    if op in NUMERIC_OPS:
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
        return {">": actual > expected, ">=": actual >= expected,
                "<": actual < expected, "<=": actual <= expected}[op]
    a, e = str(actual).lower(), str(expected).lower()
    return a == e if op == "==" else e in a


def describe(check: dict[str, Any]) -> str:
    v = check["value"]
    v = f"{v:g}" if isinstance(v, float) else repr(v)
    at = f" at {check['at']}" if check["at"] else ""
    return f"{check['service']} {check['field']} {check['op']} {v}{at}"


def check_support(check: dict[str, Any], ids: list[str], ledger: EvidenceLedger) -> SupportResult:
    """Check a parsed claim against the cited rows only. All ids must already be in the ledger."""
    relevant: list[tuple[str, Any]] = []
    for eid in dict.fromkeys(ids):
        rec = ledger.get(eid).record
        if rec.service != check["service"]:
            continue
        if check["at"] and rec.ts != check["at"]:
            continue
        val = field_value(rec, check["field"])
        if val is not None:
            relevant.append((eid, val))
    if not relevant:
        return SupportResult(UNSUPPORTED, f"no cited row is about {describe(check)}")
    backing = [eid for eid, val in relevant if holds(val, check["op"], check["value"])]
    if backing:
        return SupportResult(SUPPORTED, "", backing)
    shown = ", ".join(f"{eid} has {val}" for eid, val in relevant)
    return SupportResult(CONTRADICTED, f"cited rows contradict {describe(check)}: {shown}",
                         [eid for eid, _ in relevant])
