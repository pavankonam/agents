"""Composable rubrics: reward is computed inside the env from its final state and recorded steps (D13).

A rubric scores one finished episode and returns a `RubricResult` with a score
in [0, 1], a short detail list and the results of its children, so the whole
reward breaks down into a tree that explains every point lost.

    StateCheck(check)            1.0 if the task's state check finds no problems, else 0.0
    TrajectoryRubric(...)        1.0 minus penalties for refused steps and steps over the reference
    WeightedSum([(r, w), ...])   weighted mean of child scores
    Gate(gate, inner)            inner score only if the gate scores at least the threshold, else 0.0

`default_rubric(task)` is Gate(StateCheck, WeightedSum(0.8 StateCheck, 0.2 TrajectoryRubric)):
a run that leaves the wrong state scores 0 whatever its process, and a correct
run loses at most 0.2 for a messy trajectory (D14, D15).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence

from .types import SUBMIT, Action

Check = Callable[[dict, dict], list[str]]


@dataclass
class StepLog:
    """What the env records per step for rubrics: the action and whether it was accepted."""

    tool: str
    arguments: dict
    ok: bool


@dataclass
class RubricContext:
    initial: dict
    final: dict
    steps: list[StepLog]
    reference: list[Action]
    end_reason: str = ""

    @property
    def work_steps(self) -> list[StepLog]:
        """Steps other than submit."""
        return [s for s in self.steps if s.tool != SUBMIT]


@dataclass
class RubricResult:
    name: str
    score: float
    detail: list[str] = field(default_factory=list)
    children: list["RubricResult"] = field(default_factory=list)
    weight: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "score": self.score}
        if self.weight is not None:
            d["weight"] = self.weight
        if self.detail:
            d["detail"] = list(self.detail)
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d

    def lines(self, indent: int = 0) -> list[str]:
        """Readable breakdown, one line per node."""
        w = f" x{self.weight:g}" if self.weight is not None else ""
        out = [f"{'  ' * indent}{self.name}{w}: {self.score:.3f}"]
        out += [f"{'  ' * (indent + 1)}- {d}" for d in self.detail]
        for c in self.children:
            out += c.lines(indent + 1)
        return out


class Rubric(Protocol):
    name: str

    def score(self, ctx: RubricContext) -> RubricResult: ...


def _clip(x: float) -> float:
    return round(min(1.0, max(0.0, x)), 4)


class StateCheck:
    """Outcome: the task's check(initial, final) must return no problems."""

    def __init__(self, check: Check, name: str = "state"):
        self.check = check
        self.name = name

    def score(self, ctx: RubricContext) -> RubricResult:
        problems = list(self.check(ctx.initial, ctx.final))
        return RubricResult(self.name, 0.0 if problems else 1.0, problems)


class TrajectoryRubric:
    """Process: penalise refused steps and accepted steps beyond the reference solution.

    A refused step (ok=False) costs `refused_penalty`. Accepted work steps over
    len(reference) cost `extra_penalty` each, so a refused step is not also
    charged as an extra step. submit is never counted. Score is clipped at 0.
    """

    def __init__(self, refused_penalty: float = 0.2, extra_penalty: float = 0.1,
                 name: str = "trajectory"):
        if refused_penalty < 0 or extra_penalty < 0:
            raise ValueError("penalties must not be negative")
        self.refused_penalty = refused_penalty
        self.extra_penalty = extra_penalty
        self.name = name

    def score(self, ctx: RubricContext) -> RubricResult:
        work = ctx.work_steps
        refused = sum(not s.ok for s in work)
        accepted = len(work) - refused
        extra = max(0, accepted - len(ctx.reference))
        detail = []
        if refused:
            detail.append(f"{refused} refused step(s) -{refused * self.refused_penalty:g}")
        if extra:
            detail.append(f"{extra} step(s) over the reference of {len(ctx.reference)} "
                          f"-{extra * self.extra_penalty:g}")
        raw = 1.0 - refused * self.refused_penalty - extra * self.extra_penalty
        return RubricResult(self.name, _clip(raw), detail)


class WeightedSum:
    """Weighted mean of the children's scores. Weights must be positive."""

    def __init__(self, parts: Sequence[tuple[Rubric, float]], name: str = "weighted_sum"):
        if not parts:
            raise ValueError("WeightedSum needs at least one part")
        if any(w <= 0 for _, w in parts):
            raise ValueError("weights must be positive")
        self.parts = list(parts)
        self.name = name

    def score(self, ctx: RubricContext) -> RubricResult:
        children = []
        for rubric, w in self.parts:
            r = rubric.score(ctx)
            r.weight = w
            children.append(r)
        total = sum(w for _, w in self.parts)
        value = sum(c.score * c.weight for c in children) / total
        return RubricResult(self.name, _clip(value), children=children)


class Gate:
    """Return the inner score only if the gate scores at least `threshold`; otherwise 0."""

    def __init__(self, gate: Rubric, inner: Rubric, threshold: float = 1.0, name: str = "gate"):
        self.gate = gate
        self.inner = inner
        self.threshold = threshold
        self.name = name

    def score(self, ctx: RubricContext) -> RubricResult:
        g = self.gate.score(ctx)
        if g.score < self.threshold:
            return RubricResult(self.name, 0.0,
                                [f"{g.name} scored {g.score:g} < {self.threshold:g}, "
                                 "inner rubric not scored"], [g])
        inner = self.inner.score(ctx)
        return RubricResult(self.name, inner.score, children=[g, inner])


def default_rubric(check: Check) -> Rubric:
    """Gate on the state check, then 0.8 outcome + 0.2 process."""
    return Gate(StateCheck(check),
                WeightedSum([(StateCheck(check), 0.8), (TrajectoryRubric(), 0.2)],
                            name="outcome_and_process"))
