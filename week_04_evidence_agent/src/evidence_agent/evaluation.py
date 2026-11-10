"""Eval: every scenario over N seeded variants, with a summary report (D33 to D37).

Each run is one `run_investigation` on `variant(scenario, seed)`. The summary
counts pass rate and mean score, citations the run rejected (an unknown id or
no id on a finding or a conclusion), findings whose check came back
contradicted or unsupported, and a failure kind per failed run:

    no_conclusion, step_limit, turn_limit, killed   the run ended without concluding
    wrong_root_cause                                concluded on the wrong service

`ReplayClient` lets the scripted references run on variants: it reads the ids
the tools actually returned in this run and rewrites the script's ids through
the rows they stand for, so `--fake` exercises the same path a model does.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .agent import run_investigation
from .bounds import DEFAULT_MAX_QUERIES
from .investigation import CONCLUDE, REPORT_FINDING, Investigation, Report
from .llm import FakeClient, LLMResponse, ToolCall
from .support import CONTRADICTED, UNSUPPORTED
from .telemetry import Scenario
from .variants import noise_count, variant

PASS = "pass"
WRONG_ROOT_CAUSE = "wrong_root_cause"
_ROW = re.compile(r"^\[(ev_\d+)\] (.*)$", re.M)
_CITATION_ERRORS = ("unknown evidence id", "no evidence cited")


def failure_kind(report: Report) -> str:
    if report.passed:
        return PASS
    if report.end_reason != "concluded":
        return report.end_reason
    return WRONG_ROOT_CAUSE


def rejected_citations(report: Report) -> int:
    """Finding and conclude calls refused because an id was unknown or missing."""
    return sum(1 for s in report.steps if s.tool in (REPORT_FINDING, CONCLUDE) and not s.ok
               and any(e in s.error for e in _CITATION_ERRORS))


@dataclass
class EvalRun:
    scenario: str
    seed: int
    passed: bool
    score: int
    kind: str
    end_reason: str
    steps: int
    noise_rows: int
    rejected_citations: int
    contradicted: int
    unsupported: int
    queries_used: int

    @classmethod
    def from_report(cls, report: Report, seed: int, noise: int) -> "EvalRun":
        support = report.support_counts()
        return cls(report.scenario, seed, report.passed, report.score, failure_kind(report),
                   report.end_reason, len(report.steps), noise, rejected_citations(report),
                   support.get(CONTRADICTED, 0), support.get(UNSUPPORTED, 0),
                   report.queries_used)


@dataclass
class EvalSummary:
    model: str
    seeds: int
    runs: list[EvalRun] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(r.passed for r in self.runs)

    @property
    def pass_rate(self) -> float:
        return self.passed / len(self.runs) if self.runs else 0.0

    @property
    def mean_score(self) -> float:
        return sum(r.score for r in self.runs) / len(self.runs) if self.runs else 0.0

    def total(self, attr: str) -> int:
        return sum(getattr(r, attr) for r in self.runs)

    def failure_kinds(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.runs:
            if r.kind != PASS:
                out[r.kind] = out.get(r.kind, 0) + 1
        return dict(sorted(out.items()))

    def per_scenario(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for name in dict.fromkeys(r.scenario for r in self.runs):
            rs = [r for r in self.runs if r.scenario == name]
            out[name] = {"runs": len(rs), "passed": sum(r.passed for r in rs),
                         "mean_score": round(sum(r.score for r in rs) / len(rs), 1),
                         "rejected_citations": sum(r.rejected_citations for r in rs),
                         "contradicted": sum(r.contradicted for r in rs),
                         "unsupported": sum(r.unsupported for r in rs)}
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "seeds": self.seeds, "runs_total": len(self.runs),
                "passed": self.passed, "pass_rate": round(self.pass_rate, 3),
                "mean_score": round(self.mean_score, 1),
                "rejected_citations": self.total("rejected_citations"),
                "contradicted": self.total("contradicted"),
                "unsupported": self.total("unsupported"),
                "failure_kinds": self.failure_kinds(), "per_scenario": self.per_scenario(),
                "runs": [asdict(r) for r in self.runs]}

    def lines(self) -> list[str]:
        out = [f"eval {self.model}: {self.passed}/{len(self.runs)} passed "
               f"({self.pass_rate:.0%}), mean score {self.mean_score:.1f}, "
               f"{self.seeds} seed(s) per scenario"]
        for r in self.runs:
            out.append(f"  {r.scenario} seed {r.seed}: {'PASS' if r.passed else 'FAIL'} "
                       f"{r.kind} score {r.score} steps {r.steps} noise {r.noise_rows} "
                       f"rejected_citations {r.rejected_citations} contradicted "
                       f"{r.contradicted} unsupported {r.unsupported}")
        kinds = self.failure_kinds()
        out.append("failure kinds: " + (", ".join(f"{k} {v}" for k, v in kinds.items())
                                        if kinds else "none"))
        return out

    def markdown(self) -> str:
        rows = [f"# Eval: {self.model}", "",
                f"{self.passed}/{len(self.runs)} runs passed ({self.pass_rate:.0%}), mean score "
                f"{self.mean_score:.1f}, {self.seeds} seed(s) per scenario.", "",
                "| Scenario | Runs | Passed | Mean score | Rejected citations | Contradicted "
                "| Unsupported |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        for name, s in self.per_scenario().items():
            rows.append(f"| {name} | {s['runs']} | {s['passed']} | {s['mean_score']} | "
                        f"{s['rejected_citations']} | {s['contradicted']} | {s['unsupported']} |")
        kinds = self.failure_kinds()
        rows += ["", "| Failure kind | Runs |", "| --- | --- |"]
        rows += [f"| {k} | {v} |" for k, v in kinds.items()] or ["| none | 0 |"]
        return "\n".join(rows) + "\n"


class ReplayClient(FakeClient):
    """Replays a script written against the base scenario on a variant.

    Each id in the script stands for the row it named in the base scenario. At
    every turn the client reads the `[ev_NNN] line` rows the tools returned so
    far in this run and swaps each script id for the id its row got here. An id
    that named no row (an invented one) is passed through unchanged.
    """

    def __init__(self, responses: list[LLMResponse], base: Scenario):
        super().__init__(responses)
        self.base_lines = _base_id_lines(responses, base)

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        resp = super().chat(messages, tools)
        seen: dict[str, str] = {}
        for m in messages:
            if m.get("role") in ("tool", "user"):
                for eid, line in _ROW.findall(m.get("content") or ""):
                    seen.setdefault(line, eid)
        calls = [ToolCall(c.name, self._translate(c.arguments, seen)) for c in resp.tool_calls]
        return LLMResponse(content=resp.content, tool_calls=calls)

    def _translate(self, args: Any, seen: dict[str, str]) -> Any:
        if not isinstance(args, dict) or "evidence_ids" not in args:
            return args
        ids = [seen.get(self.base_lines.get(i, ""), i) for i in args["evidence_ids"]]
        return {**args, "evidence_ids": ids}


def _base_id_lines(responses: list[LLMResponse], base: Scenario) -> dict[str, str]:
    """The row line each id stands for when the script runs on the base scenario."""
    inv = Investigation(base, max_steps=len(responses) * 4 + 1)
    for resp in responses:
        for c in resp.tool_calls:
            if not inv.done:
                inv.call(c.name, c.arguments)
    return {eid: inv.ledger.get(eid).record.line() for eid in inv.ledger.ids()}


ClientFactory = Callable[[Scenario, int], Any]


def evaluate(make_client: ClientFactory, scenarios: list[Scenario], seeds: int,
             model: str = "", max_steps: int = 12,
             max_queries: int = DEFAULT_MAX_QUERIES,
             on_run: Callable[[Report, EvalRun], None] | None = None) -> EvalSummary:
    """Run every scenario on seeds 0..seeds-1. `make_client(base, seed)` builds the client."""
    if seeds < 1:
        raise ValueError("seeds must be at least 1")
    summary = EvalSummary(model=model, seeds=seeds)
    for base in scenarios:
        for seed in range(seeds):
            varied = variant(base, seed)
            report = run_investigation(make_client(base, seed), varied, max_steps=max_steps,
                                       max_queries=max_queries)
            run = EvalRun.from_report(report, seed, noise_count(base, varied))
            summary.runs.append(run)
            if on_run is not None:
                on_run(report, run)
    return summary
