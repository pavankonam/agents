"""One investigation: tools over a scenario, the evidence ledger, findings and a conclusion.

The model can only cite ids that a query tool returned in this run (D4). A
finding or conclusion that cites anything else is rejected and the model is
told why, so it can query and try again (D7). The final verdict is computed
here from the ledger and the scenario, never from the model's words (D8).
Bounds (D23 to D26): query tools spend a budget, since/until must lie in the
incident window, a tripped kill switch ends the run before the next call, and
every refusal by a bound and every stop is written to the audit log.
Memory (D28 to D32): findings recalled from earlier runs and re-checked against
this data are preloaded before the first turn; their rows get ids from the
ledger like queried rows (tool `recall`, step 0) and cost no query.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .bounds import (AGENT, DEFAULT_MAX_QUERIES, QUERY_TOOLS, REFUSED, STOP, SYSTEM, AuditEntry,
                     KillSwitch, window_problem)
from .grading import grade
from .ledger import EvidenceLedger
from .memory import KEPT, Recalled
from .support import CHECK_SCHEMA, INVALID, SUPPORTED, UNCHECKED, check_support, parse_check
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
_SINCE = {"type": "string", "description": "HH:MM, only rows at or after it; inside the incident window"}
_UNTIL = {"type": "string", "description": "HH:MM, only rows at or before it; inside the incident window"}
_IDS = {"type": "array", "items": {"type": "string"},
        "description": "evidence ids such as ev_003, exactly as a tool returned them"}

TOOLS: list[dict] = [
    _fn("list_services", "List the services that have telemetry.", {}, []),
    _fn("search_logs", "Search log lines of one service. Each line comes with an evidence id.",
        {"service": _STR, "contains": {"type": "string", "description": "substring, case insensitive"},
         "level": {"type": "string", "enum": list(LEVELS)}, "since": _SINCE, "until": _UNTIL},
        ["service"]),
    _fn("get_metric", "Get the values of one metric of one service over time, with evidence ids. "
        "Leave metric out to list the metric names of the service.",
        {"service": _STR, "metric": _STR, "since": _SINCE, "until": _UNTIL}, ["service"]),
    _fn("list_deploys", "List deploys, optionally for one service, with evidence ids.",
        {"service": _STR, "since": _SINCE, "until": _UNTIL}, []),
    _fn(REPORT_FINDING, "Record one finding. It must cite the evidence ids that support it. "
        "Add check to have the claim verified against the cited rows; a check the rows "
        "contradict or do not cover rejects the finding.",
        {"claim": _STR, "evidence_ids": _IDS, "check": CHECK_SCHEMA}, ["claim", "evidence_ids"]),
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
    check: dict[str, Any] | None = None
    support: str = UNCHECKED
    support_ids: list[str] = field(default_factory=list)


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
    grade: dict[str, Any] = field(default_factory=dict)
    audit: list[AuditEntry] = field(default_factory=list)
    queries_used: int = 0
    max_queries: int = DEFAULT_MAX_QUERIES
    recall: list[Recalled] = field(default_factory=list)
    remembered: int = 0

    @property
    def recall_counts(self) -> tuple[int, int]:
        """(kept, dropped) remembered findings at the start of the run."""
        kept = sum(1 for r in self.recall if r.status == KEPT)
        return kept, len(self.recall) - kept

    @property
    def score(self) -> int:
        return int(self.grade.get("score", 0))

    @property
    def accepted_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.accepted]

    @property
    def rejected_findings(self) -> list[Finding]:
        return [f for f in self.findings if not f.accepted]

    @property
    def refused_steps(self) -> int:
        return sum(1 for s in self.steps if not s.ok)

    def support_counts(self) -> dict[str, int]:
        """How many findings ended in each support status (accepted or not)."""
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.support] = counts.get(f.support, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["refused_steps"] = self.refused_steps
        d["support"] = self.support_counts()
        d["accepted"] = len(self.accepted_findings)
        d["rejected"] = len(self.rejected_findings)
        d["score"] = self.score
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
        if props[k].get("type") == "object" and not isinstance(v, dict):
            return f"argument {k} of {name} must be an object"
        if props[k]["type"] == "array" and not (
                isinstance(v, list) and all(isinstance(x, str) for x in v)):
            return f"argument {k} of {name} must be a list of strings"
    return ""


class Investigation:
    def __init__(self, scenario: Scenario, max_steps: int = 12,
                 max_queries: int = DEFAULT_MAX_QUERIES, kill_switch: KillSwitch | None = None):
        if max_queries < 1:
            raise ValueError("max_queries must be at least 1")
        self.scenario = scenario
        self.max_steps = max_steps
        self.max_queries = max_queries
        self.kill_switch = kill_switch
        self.queries_used = 0
        self.audit: list[AuditEntry] = []
        self.ledger = EvidenceLedger(seed=scenario.id_seed)
        self.steps: list[StepLog] = []
        self.findings: list[Finding] = []
        self.conclusion: dict[str, Any] | None = None
        self.end_reason = ""
        self.recall: list[Recalled] = []
        self.remembered = 0

    @property
    def done(self) -> bool:
        return bool(self.end_reason)

    # ----- memory --------------------------------------------------------
    def preload(self, recalled: list[Recalled]) -> str:
        """Issue ids for the backing rows of kept findings and return the text for the model.
        Must run before the first step; recalled rows spend no query (D31)."""
        if self.steps:
            raise RuntimeError("preload must run before the first step")
        self.recall = list(recalled)
        lines: list[str] = []
        for r in self.recall:
            if r.status != KEPT:
                continue
            r.ids = [self.ledger.issue(k, self.scenario.records[k], "recall", 0) for k in r.keys]
            lines.append(f"- {r.claim}")
            lines += [f"  [{eid}] {self.ledger.get(eid).record.line()}" for eid in r.ids]
        dropped = sum(1 for r in self.recall if r.status != KEPT)
        if not lines and not dropped:
            return ""
        text = []
        if lines:
            text.append("Findings remembered from earlier runs, re-checked against this data just "
                        "now. You may cite their evidence ids:")
            text += lines
        if dropped:
            text.append(f"{dropped} remembered finding(s) no longer hold on this data and were "
                        "dropped; do not rely on them.")
        return "\n".join(text)

    # ----- tool dispatch -------------------------------------------------
    def call(self, name: str, args: Any) -> ToolResult:
        if self.done:
            raise RuntimeError("investigation is over")
        if self.check_kill():  # the call never runs and is not a step (D25)
            by, why = self.kill_switch.tripped()
            return ToolResult(False, "", f"investigation stopped by {by}: {why}", done=True)
        index = len(self.steps) + 1
        log = StepLog(index, name, dict(args) if isinstance(args, dict) else {"_raw": args}, False)
        self.steps.append(log)
        if name not in _SCHEMA:
            res = ToolResult(False, "", f"unknown tool {name!r}; tools: {', '.join(TOOL_NAMES)}")
        else:
            err = validate_args(name, args)
            if not err and name in QUERY_TOOLS:
                err = self._bound_problem(args, index)
            res = ToolResult(False, "", err) if err else getattr(self, "_t_" + name)(args, log)
        log.ok, log.error = res.ok, res.error
        if not res.done and len(self.steps) >= self.max_steps:
            self._end("step_limit", SYSTEM, f"step limit of {self.max_steps} reached")
            res.done = True
            note = f"step limit of {self.max_steps} reached, investigation over"
            res.content = f"{res.content}\n{note}" if res.content else note
        return res

    def _bound_problem(self, args: dict, index: int) -> str:
        """Budget first, then the window. A query that passes both spends one query (D23, D24)."""
        if self.queries_used >= self.max_queries:
            why = (f"query budget of {self.max_queries} used up; report findings or conclude "
                   "with the evidence you already have")
            self.audit.append(AuditEntry(index, REFUSED, "query_budget", SYSTEM, why))
            return why
        why = window_problem(self.scenario.window, args.get("since"), args.get("until"))
        if why:
            self.audit.append(AuditEntry(index, REFUSED, "time_window", SYSTEM, why))
            return why
        self.queries_used += 1
        return ""

    def check_kill(self) -> bool:
        """End the run as killed if the operator tripped the switch. True when killed."""
        if not self.done and self.kill_switch is not None:
            trip = self.kill_switch.tripped()
            if trip:
                self._end("killed", trip[0], trip[1])
        return self.end_reason == "killed"

    def _end(self, reason: str, actor: str, why: str) -> None:
        """The only place a run ends: sets the reason and audits who and why (D26)."""
        if not self.done:
            self.end_reason = reason
            self.audit.append(AuditEntry(len(self.steps), STOP, reason, actor, why))

    _FINISH = {"no_conclusion": (AGENT, "answered in plain text without calling conclude"),
               "turn_limit": (SYSTEM, "model turn limit reached")}

    def finish(self, reason: str) -> None:
        actor, why = self._FINISH.get(reason, (SYSTEM, reason))
        self._end(reason, actor, why)

    def _known_service(self, service: str) -> str:
        if service not in self.scenario.services:
            return f"unknown service {service!r}; services: {', '.join(self.scenario.services)}"
        return ""

    def _rows(self, tool: str, log: StepLog, pred, limit: int | None = None,
              since: str | None = None, until: str | None = None) -> list[str]:
        """Matching records as lines. Only records actually shown get an id (D5)."""
        lines = []
        matches = [(k, r) for k, r in enumerate(self.scenario.records) if pred(r)
                   and (since is None or r.ts >= since) and (until is None or r.ts <= until)]
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
            and needle in r.data["message"].lower()), limit=DEFAULT_LIMIT,
            since=args.get("since"), until=args.get("until"))
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
            r.kind == "metric" and r.service == service and r.data["metric"] == metric),
            since=args.get("since"), until=args.get("until"))
        return ToolResult(True, "\n".join(lines) if lines else "no values in that time range")

    def _t_list_deploys(self, args, log) -> ToolResult:
        service = args.get("service")
        if service is not None:
            err = self._known_service(service)
            if err:
                return ToolResult(False, "", err)
        lines = self._rows("list_deploys", log, lambda r: (
            r.kind == "deploy" and (service is None or r.service == service)),
            since=args.get("since"), until=args.get("until"))
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
        cite_problems = self._citation_problems(ids)
        problems += cite_problems
        finding = Finding(claim, ids, False, problems, log.index)
        if "check" in args:
            check, err = parse_check(args["check"])
            if err:
                finding.check, finding.support = dict(args["check"]), INVALID
                problems.append(f"invalid check: {err}")
            else:
                finding.check = check
                if not cite_problems:  # support is only judged on real citations (D14)
                    res = check_support(check, ids, self.ledger)
                    finding.support, finding.support_ids = res.status, res.ids
                    if res.status != SUPPORTED:
                        problems.append(f"claim {res.status}: {res.reason}")
        finding.accepted = not problems
        self.findings.append(finding)
        if problems:
            return ToolResult(False, "", "finding rejected: " + "; ".join(problems))
        note = (f", check supported by {', '.join(finding.support_ids)}"
                if finding.support == SUPPORTED else ", no check")
        return ToolResult(True, f"finding {len(self.accepted_findings())} recorded with "
                                f"{len(ids)} citation(s){note}")

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
        self._end("concluded", AGENT, f"concluded {args['root_cause_service']}")
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
            grade=grade(self.scenario, self.ledger, self.conclusion,
                        [f.support for f in self.findings], len(self.steps)),
            audit=list(self.audit),
            queries_used=self.queries_used,
            max_queries=self.max_queries,
            recall=list(self.recall),
            remembered=self.remembered,
        )
