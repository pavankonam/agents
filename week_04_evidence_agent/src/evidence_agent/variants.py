"""Seeded scenario variants for eval (D33 to D35).

`variant(scenario, seed)` returns the same incident with three kinds of noise:

* a few INFO log rows (health checks, heartbeats, gc pauses) on random services
  at random minutes inside the incident window, and
* a different row order among rows that share a timestamp, and
* `id_seed`, so the ledger hands out ids in a seeded order (ev_417, ev_082, ...).

All three change what a model sees or which id a row gets, so a model (or a
script) that memorised `ev_002` instead of reading the tool output gets
caught. None
changes the incident: noise rows are INFO, mention no cause, carry no metric
and no deploy, and the cause rows are remapped so grading still finds them.
Seed 0 is the scenario unchanged.
"""

from __future__ import annotations

import dataclasses
import random

from .telemetry import Record, Scenario

NOISE_MESSAGES = (
    "health check ok",
    "heartbeat sent",
    "gc pause 8ms",
    "metrics flushed",
    "session cache compacted",
    "tls certificate valid for 61 days",
)
MIN_NOISE, MAX_NOISE = 3, 6


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def noise_rows(scenario: Scenario, rng: random.Random) -> list[Record]:
    """Distinct INFO log rows inside the window, none equal to an existing row."""
    start, end = (_minutes(t) for t in scenario.window)
    seen = {(r.kind, r.ts, r.service, r.line()) for r in scenario.records}
    rows: list[Record] = []
    want = rng.randint(MIN_NOISE, MAX_NOISE)
    while len(rows) < want:
        rec = Record("log", _hhmm(rng.randint(start, end)), rng.choice(scenario.services),
                     {"level": "INFO", "message": rng.choice(NOISE_MESSAGES)})
        key = (rec.kind, rec.ts, rec.service, rec.line())
        if key not in seen:
            seen.add(key)
            rows.append(rec)
    return rows


def variant(scenario: Scenario, seed: int) -> Scenario:
    """The scenario with seeded noise rows and a seeded order among same time rows."""
    if seed == 0:
        return scenario
    rng = random.Random(f"{scenario.name}:{seed}")
    items = [(rec, k in scenario.cause) for k, rec in enumerate(scenario.records)]
    items += [(rec, False) for rec in noise_rows(scenario, rng)]
    rng.shuffle(items)
    items.sort(key=lambda it: it[0].ts)  # stable: only same time rows keep the shuffled order
    records = tuple(rec for rec, _ in items)
    cause = tuple(k for k, (_, is_cause) in enumerate(items) if is_cause)
    return dataclasses.replace(scenario, records=records, cause=cause, id_seed=seed)


def noise_count(base: Scenario, varied: Scenario) -> int:
    return len(varied.records) - len(base.records)
