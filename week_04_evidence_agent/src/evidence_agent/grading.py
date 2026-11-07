"""Grading rubric: a per scenario score out of 100 (D19 to D21).

`passed` stays the strict verdict (concluded with the right service, D8). The
score says how good the investigation was, from four criteria:

    root_cause      40  the conclusion names the true root cause service
    cause_evidence  30  the conclusion cites at least one row that shows the cause
    no_contradicted 20  no finding (accepted or rejected) was contradicted by its rows
    efficiency      10  steps within reference + 2; then 2 points off per extra step

A run without a conclusion scores 0: the last two criteria are only earned by
an investigation that reached an answer (D21).
"""

from __future__ import annotations

from typing import Any, Iterable

from .ledger import EvidenceLedger
from .support import CONTRADICTED
from .telemetry import Scenario

WEIGHTS = {"root_cause": 40, "cause_evidence": 30, "no_contradicted": 20, "efficiency": 10}
STEP_SLACK = 2
STEP_PENALTY = 2


def efficiency_points(steps: int, reference_steps: int) -> int:
    over = steps - (reference_steps + STEP_SLACK)
    return WEIGHTS["efficiency"] if over <= 0 else max(0, WEIGHTS["efficiency"] - STEP_PENALTY * over)


def grade(scenario: Scenario, ledger: EvidenceLedger, conclusion: dict[str, Any] | None,
          supports: Iterable[str], steps: int) -> dict[str, Any]:
    """Score one investigation. `supports` is the support status of every finding."""
    supports = list(supports)
    crit: dict[str, dict[str, Any]] = {}

    def put(name: str, points: int, detail: str) -> None:
        crit[name] = {"points": points, "max": WEIGHTS[name], "detail": detail}

    if conclusion is None:
        for name in WEIGHTS:
            put(name, 0, "no conclusion")
        return {"score": 0, "criteria": crit}

    named = conclusion["root_cause_service"]
    right = named == scenario.root_cause_service
    put("root_cause", WEIGHTS["root_cause"] if right else 0,
        f"named {named}" + ("" if right else f", truth is {scenario.root_cause_service}"))

    cause_ids = [e for e in conclusion["evidence_ids"]
                 if e in ledger and ledger.get(e).key in scenario.cause]
    put("cause_evidence", WEIGHTS["cause_evidence"] if cause_ids else 0,
        f"cites cause rows {', '.join(cause_ids)}" if cause_ids
        else "conclusion cites no row that shows the cause")

    bad = supports.count(CONTRADICTED)
    put("no_contradicted", 0 if bad else WEIGHTS["no_contradicted"],
        f"{bad} contradicted finding(s)" if bad else "no contradicted finding")

    put("efficiency", efficiency_points(steps, scenario.reference_steps),
        f"{steps} steps, reference {scenario.reference_steps}")
    return {"score": sum(c["points"] for c in crit.values()), "criteria": crit}


def score_line(g: dict[str, Any]) -> str:
    parts = ", ".join(f"{k} {c['points']}/{c['max']}" for k, c in g["criteria"].items())
    return f"score {g['score']}/100 ({parts})"
