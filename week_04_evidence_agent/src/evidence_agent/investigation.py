"""One investigation: tools over a scenario, the evidence ledger, findings and a conclusion.

The model can only cite ids that a query tool returned in this run (D4). A
finding or conclusion that cites anything else is rejected and the model is
told why, so it can query and try again (D7). The final verdict is computed
here from the ledger and the scenario, never from the model's words (D8).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .ledger import EvidenceLedger
from .telemetry import KINDS, Scenario

REPORT_FINDING = "report_finding"
CONCLUDE = "conclude"
LEVELS = ("INFO", "WARN", "ERROR")
DEFAULT_LIMIT = 10


def _fn(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props, "required": required}}}


_STR = {"type": "string"}
_IDS = {"type": "array", "items": {"type": "string"},
        "description": "evidence ids such as ev_003, exactly as a tool returned them"}

TOOLS: list[dict] = [
    _fn("list_services", "List the services that have telemetry.", {}, []),
    _fn("search_logs", "Search log lines of one service. Each line comes with an evidence id.",
        {"service": _STR, "contains": {"type": "string", "description": "substring, case insensitive"},
         "level": {"type": "string", "enum": list(LEVELS)}}, ["service"]),
    _fn("get_metric", "Get the values of one metric of one service over time, with evidence ids. "
        "Leave metric out to list the metric names of the service.",
        {"service": _STR, "metric": _STR}, ["service"]),
    _fn("list_deploys", "List deploys, optionally for one service, with evidence ids.",
        {"service": _STR}, []),
    _fn(REPORT_FINDING, "Record one finding. It must cite the evidence ids that support it.",
        {"claim": _STR, "evidence_ids": _IDS}, ["claim", "evidence_ids"]),
    _fn(CONCLUDE, "Finish the investigation: name the root cause service, explain it, cite evidence.",
        {"root_cause_service": _STR, "summary": _STR, "evidence_ids": _IDS},
        ["root_cause_service", "summary", "evidence_ids"]),
]
TOOL_NAMES = [t["function"]["name"] for t in TOOLS]
_SCHEMA = {t["function"]["name"]: t["function"]["parameters"] for t in TOOLS}


@dataclass
class ToolResult:
    ok: bool
    content: str
    error: str = ""
    done: bool = False


@dataclass
class StepLog:
    index: int
    tool: str
    arguments: dict[str, Any]
    ok: bool
    error: str = ""
    evidence_issued: list[str] = field(default_factory=list)


@dataclass
class Finding:
    claim: str
    evidence_ids: list[str]
    accepted: bool
    problems: list[str] = field(default_factory=list)
    step: int = 0


@dataclass
class Report:
    scenario: str
    end_reason: str
    steps: list[StepLog]
    findings: list[Finding]
    conclusion: dict[str, Any] | None
    evidence_issued: int
    root_cause_correct: bool
    passed: bool

    @property
    def accepted_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.accepted]

    @property
    def rejected_findings(self) -> list[Finding]:
        return [f for f in self.findings if not f.accepted]

    @property
    def refused_steps(self) -> int:
        return sum(1 for s in self.steps if not s.ok)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["refused_steps"] = self.refused_steps
        d["accepted"] = len(self.accepted_findings)
        d["rejected"] = len(self.rejected_findings)
        return d


def validate_args(name: str, args: Any) -> str:
    """Return an error message, or "" when the arguments fit the tool schema."""
    if not isinstance(args, dict):
        return f"arguments for {name} must be an object"
    if "_raw" in args:
        return f"arguments for {name} were not valid JSON"
    schema = _SCHEMA[name]
    props = schema["properties"]
    extra = sorted(set(args) - set(props))
    if extra:
        return f"unexpected argument(s) for {name}: {', '.join(extra)}"
    missing = [k for k in schema["required"] if k not in args]
    if missing:
        return f"missing argument(s) for {name}: {', '.join(missing)}"
    for k, v in args.items():
        if props[k]["type"] == "string" and not isinstance(v, str):
            return f"argument {k} of {name} must be a string"
        if props[k]["type"] == "array" and not (
                isinstance(v, list) and all(isinstance(x, str) for x in v)):
            return f"argument {k} of {name} must be a list of strings"
    return ""


class Investigation:
    def __init__(self, scenario: Scenario, max_steps: int = 12):
        self.scenario = scenario
        self.max_steps = max_steps
        self.ledger = EvidenceLedger()
        self.steps: list[StepLog] = []
        self.findings: list[Finding] = []
        self.conclusion: dict[str, Any] | None = None
        self.end_reason = ""

    @property
    def done(self) -> bool:
        return bool(self.end_reason)

    # ----- tool dispatch -------------------------------------------------
    def call(self, name: str, args: Any) -> ToolResult:
        if self.done:
            raise RuntimeError("investigation is over")
        index = len(self.steps) + 1
        log = StepLog(index, name, dict(args) if isinstance(args, dict) else {"_raw": args}, False)
        self.steps.append(log)
        if name not in _SCHEMA:
            res = ToolResult(False, "", f"unknown tool {name!r}; tools: {', '.join(TOOL_NAMES)}")
        else:
            err = validate_args(name, args)
            res = ToolResult(False, "", err) if err else getattr(self, "_t_" + name)(args, log)
        log.ok, log.error = res.ok, res.error
        if not res.done and len(self.steps) >= self.max_steps:
            self.end_reason = "step_limit"
            res.done = True
            note = f"step limit of {self.max_steps} reached, investigation over"
            res.content = f"{res.content}\n{note}" if res.content else note
        return res

    def finish(self, reason: str) -> None:
        if not self.done:
            self.end_reason = reason

    def _known_service(self, service: str) -> str:
        if service not in self.scenario.services:
            return f"unknown service {service!r}; services: {', '.join(self.scenario.services)}"
        return ""

    def _rows(self, tool: str, log: StepLog, pred, limit: int | None = None) -> list[str]:
        """Matching records as lines. Only records actually shown get an id (D5)."""
        lines = []
        matches = [(k, r) for k, r in enumerate(self.scenario.records) if pred(r)]
        for key, rec in matches[:limit]:
            eid = self.ledger.issue(key, rec, tool, log.index)
            if eid not in log.evidence_issued:
                log.evidence_issued.append(eid)
            lines.append(f"[{eid}] {rec.line()}")
        hidden = len(matches) - len(lines)
        if hidden:
            lines.append(f"({hidden} more not shown; narrow the search with contains or level)")
        return lines

    # ----- query tools ---------------------------------------------------
    def _t_list_services(self, args, log) -> ToolResult:
        return ToolResult(True, "services: " + ", ".join(self.scenario.services))

    def _t_search_logs(self, args, log) -> ToolResult:
        err = self._known_service(args["service"])
        level = args.get("level")
        if not err and level is not None and level not in LEVELS:
            err = f"level must be one of {', '.join(LEVELS)}"
        if err:
            return ToolResult(False, "", err)
        needle = (args.get("contains") or "").lower()
        lines = self._rows("search_logs", log, lambda r: (
            r.kind == "log" and r.service == args["service"]
            and (level is None or r.data["level"] == level)
            and needle in r.data["message"].lower()), limit=DEFAULT_LIMIT)
        return ToolResult(True, "\n".join(lines) if lines else "no matching log lines")

    def _t_get_metric(self, args, log) -> ToolResult:
        service = args["service"]
        err = self._known_service(service)
        if err:
            return ToolResult(False, "", err)
        names = sorted({r.data["metric"] for r in self.scenario.records
                        if r.kind == "metric" and r.service == service})
        metric = args.get("metric")
        if metric is None:
            return ToolResult(True, f"metrics of {service}: " + (", ".join(names) or "none"))
        if metric not in names:
            return ToolResult(False, "", f"unknown metric {metric!r} for {service}; "
                              f"metrics: {', '.join(names) or 'none'}")
        lines = self._rows("get_metric", log, lambda r: (
            r.kind == "metric" and r.service == service and r.data["metric"] == metric))
        return ToolResult(True, "\n".join(lines))

    def _t_list_deploys(self, args, log) -> ToolResult:
        service = args.get("service")
        if service is not None:
            err = self._known_service(service)
            if err:
                return ToolResult(False, "", err)
        lines = self._rows("list_deploys", log, lambda r: (
            r.kind == "deploy" and (service is None or r.service == service)))
        return ToolResult(True, "\n".join(lines) if lines else "no deploys")

    # ----- citing tools --------------------------------------------------
    def _citation_problems(self, ids: list[str]) -> list[str]:
        if not ids:
            return ["no evidence cited"]
        unknown = self.ledger.unknown(ids)
        if unknown:
            return [f"unknown evidence id(s): {', '.join(unknown)} (never returned by a tool in this run)"]
        return []

    def _t_report_finding(self, args, log) -> ToolResult:
        claim = args["claim"].strip()
        ids = list(args["evidence_ids"])
        problems = [] if claim else ["empty claim"]
        problems += self._citation_problems(ids)
        self.findings.append(Finding(claim, ids, not problems, problems, log.index))
        if problems:
            return ToolResult(False, "", "finding rejected: " + "; ".join(problems))
        return ToolResult(True, f"finding {len(self.accepted_findings())} recorded with {len(ids)} citation(s)")

    def accepted_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.accepted]

    def _t_conclude(self, args, log) -> ToolResult:
        problems = []
        err = self._known_service(args["root_cause_service"])
        if err:
            problems.append(err)
        if not args["summary"].strip():
            problems.append("empty summary")
        problems += self._citation_problems(list(args["evidence_ids"]))
        if problems:
            return ToolResult(False, "", "conclusion rejected: " + "; ".join(problems))
        self.conclusion = {"root_cause_service": args["root_cause_service"],
                           "summary": args["summary"].strip(),
                           "evidence_ids": list(args["evidence_ids"]), "step": log.index}
        self.end_reason = "concluded"
        return ToolResult(True, "conclusion recorded, investigation over", done=True)

    # ----- verdict -------------------------------------------------------
    def report(self) -> Report:
        correct = bool(self.conclusion) and (
            self.conclusion["root_cause_service"] == self.scenario.root_cause_service)
        return Report(
            scenario=self.scenario.name,
            end_reason=self.end_reason or "running",
            steps=list(self.steps),
            findings=list(self.findings),
            conclusion=dict(self.conclusion) if self.conclusion else None,
            evidence_issued=len(self.ledger),
            root_cause_correct=correct,
            passed=correct and self.end_reason == "concluded",
        )
