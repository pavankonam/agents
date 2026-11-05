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

    @property
    def services(self) -> list[str]:
        return sorted({r.service for r in self.records})


def _log(ts, service, level, message):
    return Record("log", ts, service, {"level": level, "message": message})


def _metric(ts, service, metric, value):
    return Record("metric", ts, service, {"metric": metric, "value": value})


def _deploy(ts, service, version, note):
    return Record("deploy", ts, service, {"version": version, "note": note})


CHECKOUT_LATENCY = Scenario(
    name="checkout_latency",
    title="Checkout is slow and orders fail",
    question=("Since about 14:05 checkout p95 latency is above 2 seconds and some orders fail. "
              "Find the service that caused it and why."),
    records=(
        _log("13:50", "checkout", "INFO", "order placed id=o-1881"),
        _deploy("13:55", "search", "v4.1.0", "new ranking model"),
        _metric("13:55", "checkout", "p95_latency_ms", 220),
        _metric("13:55", "payments", "error_rate", 0.01),
        _metric("13:55", "search", "p95_latency_ms", 120),
        _metric("13:55", "db", "cpu_pct", 35),
        _metric("14:00", "checkout", "p95_latency_ms", 230),
        _metric("14:00", "payments", "error_rate", 0.01),
        _deploy("14:02", "payments", "v2.3.1", "db connection pool size 50 -> 5"),
        _log("14:04", "search", "WARN", "cache miss rate 18% above 15% threshold"),
        _log("14:05", "payments", "ERROR", "db pool exhausted: waited 3000ms for a connection"),
        _metric("14:05", "checkout", "p95_latency_ms", 2900),
        _metric("14:05", "payments", "error_rate", 0.32),
        _metric("14:05", "search", "p95_latency_ms", 135),
        _metric("14:05", "db", "cpu_pct", 22),
        _log("14:06", "payments", "ERROR", "db pool exhausted: waited 3000ms for a connection"),
        _log("14:07", "checkout", "WARN", "payments call timed out after 3000ms"),
        _log("14:08", "checkout", "ERROR", "order failed id=o-1902: upstream payments timeout"),
        _metric("14:10", "checkout", "p95_latency_ms", 3100),
        _metric("14:10", "payments", "error_rate", 0.41),
    ),
    root_cause_service="payments",
)

SCENARIOS: dict[str, Scenario] = {s.name: s for s in (CHECKOUT_LATENCY,)}
