"""Telemetry records and scenarios. Everything is in memory and deterministic (D3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

KINDS = ("log", "metric", "deploy")


@dataclass(frozen=True)
class Record:
    """One piece of telemetry. `data` holds the kind specific fields."""

    kind: str
    ts: str  # "HH:MM", same day, so string order is time order
    service: str
    data: dict[str, Any] = field(default_factory=dict)

    def line(self) -> str:
        d = self.data
        if self.kind == "log":
            return f"{self.ts} {self.service} {d['level']} {d['message']}"
        if self.kind == "metric":
            return f"{self.ts} {self.service} {d['metric']}={d['value']}"
        return f"{self.ts} {self.service} deploy {d['version']}: {d['note']}"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ts": self.ts, "service": self.service, "data": dict(self.data)}


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    question: str
    records: tuple[Record, ...]
    root_cause_service: str
    # indices of the rows that show the cause; the conclusion must cite one (D19)
    cause: tuple[int, ...] = ()
    # tool calls the scripted reference needs; the efficiency criterion counts from it (D20)
    reference_steps: int = 0

    @property
    def services(self) -> list[str]:
        return sorted({r.service for r in self.records})


def _log(ts, service, level, message):
    return Record("log", ts, service, {"level": level, "message": message})


def _metric(ts, service, metric, value):
    return Record("metric", ts, service, {"metric": metric, "value": value})


def _deploy(ts, service, version, note):
    return Record("deploy", ts, service, {"version": version, "note": note})


class _Cause:
    """Marks a row as evidence of the cause when a scenario is built (D19)."""

    def __init__(self, record: Record):
        self.record = record


def _build(*items) -> tuple[tuple[Record, ...], tuple[int, ...]]:
    records, cause = [], []
    for k, item in enumerate(items):
        if isinstance(item, _Cause):
            cause.append(k)
            item = item.record
        records.append(item)
    return tuple(records), tuple(cause)


_CHECKOUT_RECORDS, _CHECKOUT_CAUSE = _build(
    _log("13:50", "checkout", "INFO", "order placed id=o-1881"),
    _deploy("13:55", "search", "v4.1.0", "new ranking model"),
    _metric("13:55", "checkout", "p95_latency_ms", 220),
    _metric("13:55", "payments", "error_rate", 0.01),
    _metric("13:55", "search", "p95_latency_ms", 120),
    _metric("13:55", "db", "cpu_pct", 35),
    _metric("14:00", "checkout", "p95_latency_ms", 230),
    _metric("14:00", "payments", "error_rate", 0.01),
    _Cause(_deploy("14:02", "payments", "v2.3.1", "db connection pool size 50 -> 5")),
    _log("14:04", "search", "WARN", "cache miss rate 18% above 15% threshold"),
    _Cause(_log("14:05", "payments", "ERROR", "db pool exhausted: waited 3000ms for a connection")),
    _metric("14:05", "checkout", "p95_latency_ms", 2900),
    _Cause(_metric("14:05", "payments", "error_rate", 0.32)),
    _metric("14:05", "search", "p95_latency_ms", 135),
    _metric("14:05", "db", "cpu_pct", 22),
    _Cause(_log("14:06", "payments", "ERROR", "db pool exhausted: waited 3000ms for a connection")),
    _log("14:07", "checkout", "WARN", "payments call timed out after 3000ms"),
    _log("14:08", "checkout", "ERROR", "order failed id=o-1902: upstream payments timeout"),
    _metric("14:10", "checkout", "p95_latency_ms", 3100),
    _Cause(_metric("14:10", "payments", "error_rate", 0.41)),
)

CHECKOUT_LATENCY = Scenario(
    name="checkout_latency",
    title="Checkout is slow and orders fail",
    question=("Since about 14:05 checkout p95 latency is above 2 seconds and some orders fail. "
              "Find the service that caused it and why."),
    records=_CHECKOUT_RECORDS,
    root_cause_service="payments",
    cause=_CHECKOUT_CAUSE,
    reference_steps=7,
)

# A gateway config push cuts the upstream timeout below the api's normal latency.
# The red herring is a worker CPU spike from a nightly job a few minutes earlier (D18).
_CONFIG_RECORDS, _CONFIG_CAUSE = _build(
    _metric("09:00", "api", "p95_latency_ms", 420),
    _metric("09:00", "gateway", "http_503_rate", 0.0),
    _metric("09:00", "worker", "cpu_pct", 30),
    _metric("09:05", "api", "p95_latency_ms", 430),
    _metric("09:05", "gateway", "http_503_rate", 0.0),
    _metric("09:05", "worker", "cpu_pct", 31),
    _log("09:06", "worker", "INFO", "nightly reindex started"),
    _Cause(_deploy("09:07", "gateway", "cfg-118", "config push: upstream timeout 30000ms -> 300ms")),
    _metric("09:08", "worker", "cpu_pct", 96),
    _log("09:09", "worker", "WARN", "cpu above 90% for 60s"),
    _Cause(_log("09:10", "gateway", "ERROR", "upstream api timed out after 300ms, returning 503")),
    _metric("09:10", "api", "p95_latency_ms", 440),
    _Cause(_metric("09:10", "gateway", "http_503_rate", 0.34)),
    _Cause(_log("09:11", "gateway", "ERROR", "upstream api timed out after 300ms, returning 503")),
    _log("09:12", "api", "INFO", "request served in 440ms"),
    _metric("09:15", "api", "p95_latency_ms", 435),
    _Cause(_metric("09:15", "gateway", "http_503_rate", 0.36)),
    _metric("09:15", "worker", "cpu_pct", 28),
    _log("09:15", "worker", "INFO", "nightly reindex finished"),
)

CONFIG_PUSH = Scenario(
    name="config_push",
    title="A third of requests get 503 from the gateway",
    question=("Since about 09:10 roughly a third of requests through the gateway fail with 503. "
              "Find the service that caused it and why."),
    records=_CONFIG_RECORDS,
    root_cause_service="gateway",
    cause=_CONFIG_CAUSE,
    reference_steps=7,
)

# An external email vendor goes down. The first deploy of the afternoon (web, page copy)
# is innocent, and a later signup deploy comes after the failures began (D18).
_DEPENDENCY_RECORDS, _DEPENDENCY_CAUSE = _build(
    _metric("16:00", "signup", "success_rate", 0.98),
    _metric("16:00", "email_vendor", "availability", 1.0),
    _deploy("16:10", "web", "v9.2.0", "new signup page copy"),
    _metric("16:10", "signup", "success_rate", 0.97),
    _metric("16:10", "email_vendor", "availability", 0.99),
    _metric("16:10", "web", "p95_latency_ms", 180),
    _Cause(_log("16:18", "email_vendor", "ERROR", "smtp relay unreachable: connection refused")),
    _metric("16:20", "signup", "success_rate", 0.41),
    _Cause(_metric("16:20", "email_vendor", "availability", 0.12)),
    _metric("16:20", "web", "p95_latency_ms", 185),
    _log("16:21", "signup", "ERROR", "verification email failed: email_vendor returned 503"),
    _log("16:22", "signup", "ERROR", "verification email failed: email_vendor returned 503"),
    _log("16:23", "web", "INFO", "signup page rendered in 170ms"),
    _Cause(_log("16:25", "email_vendor", "ERROR", "smtp relay unreachable: connection refused")),
    _deploy("16:30", "signup", "v3.0.4", "retry email sends twice"),
    _metric("16:30", "signup", "success_rate", 0.39),
    _Cause(_metric("16:30", "email_vendor", "availability", 0.10)),
)

DEPENDENCY_OUTAGE = Scenario(
    name="dependency_outage",
    title="Signups fail after an afternoon deploy",
    question=("Since about 16:20 most signups fail. There was a deploy shortly before. "
              "Find the service that caused it and why."),
    records=_DEPENDENCY_RECORDS,
    root_cause_service="email_vendor",
    cause=_DEPENDENCY_CAUSE,
    reference_steps=8,
)

SCENARIOS: dict[str, Scenario] = {
    s.name: s for s in (CHECKOUT_LATENCY, CONFIG_PUSH, DEPENDENCY_OUTAGE)}
