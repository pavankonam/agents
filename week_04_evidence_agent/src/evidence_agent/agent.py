"""The agent loop: the model investigates through tools until it concludes (D6)."""

from __future__ import annotations

import json

from .bounds import DEFAULT_MAX_QUERIES, KillSwitch
from .grading import score_line
from .investigation import TOOLS, Investigation, Report
from .llm import LLMClient
from .memory import KEPT, FindingMemory
from .telemetry import Scenario

SYSTEM_PROMPT = """You are an incident investigator. You find the root cause of a production problem
using only the telemetry tools you are given.

Rules:
- Every tool result line starts with an evidence id in brackets, like [ev_003].
- You may only cite evidence ids that a tool returned to you in this investigation.
  Never make up an id. A finding or conclusion with an unknown id is rejected.
- Record what you learn with report_finding: one claim and the ids that support it.
  Add a check so the claim is verified against the rows you cite, for example
  {{"service": "checkout", "field": "p95_latency_ms", "op": ">", "value": 2000, "at": "14:05"}}.
  field is a metric name, or level/message for logs, or version/note for deploys.
  A check that your cited rows contradict or do not cover rejects the finding.
- When you know the cause, call conclude with the root cause service, a short summary
  and the evidence ids. A plain text answer does not count as a conclusion.
- You have at most {max_steps} tool calls, of which at most {max_queries} may be queries
  (search_logs, get_metric, list_deploys). Plan them; extra queries are refused.
- The incident window is {start} to {end}. since and until must lie inside it.
- An operator can stop you at any time. Services: {services}."""


def system_prompt(scenario: Scenario, max_steps: int,
                  max_queries: int = DEFAULT_MAX_QUERIES) -> str:
    start, end = scenario.window
    return SYSTEM_PROMPT.format(max_steps=max_steps, max_queries=max_queries, start=start,
                                end=end, services=", ".join(scenario.services))


def run_investigation(llm: LLMClient, scenario: Scenario, max_steps: int = 12,
                      max_turns: int | None = None, max_queries: int = DEFAULT_MAX_QUERIES,
                      kill_switch: KillSwitch | None = None,
                      memory: FindingMemory | None = None) -> Report:
    """Run one investigation. With `memory`, remembered findings are re-checked and
    recalled before the first turn, and the run's supported findings are stored after
    it (in memory; the caller saves the file) (D28 to D32)."""
    inv = Investigation(scenario, max_steps=max_steps, max_queries=max_queries,
                        kill_switch=kill_switch)
    question = scenario.question
    if memory is not None:
        note = inv.preload(memory.recall(scenario))
        if note:
            question = f"{question}\n\n{note}"
    messages = [
        {"role": "system", "content": system_prompt(scenario, max_steps, max_queries)},
        {"role": "user", "content": question},
    ]
    turns = max_turns if max_turns is not None else max_steps + 2
    for _ in range(turns):
        if inv.check_kill():  # an operator stop is honoured before the model is asked again
            break
        resp = llm.chat(messages, TOOLS)
        msg: dict = {"role": "assistant", "content": resp.content}
        if resp.tool_calls:
            msg["tool_calls"] = [{"function": {"name": c.name, "arguments": c.arguments}}
                                 for c in resp.tool_calls]
        messages.append(msg)
        if not resp.tool_calls:
            inv.finish("no_conclusion")
            break
        for call in resp.tool_calls:
            res = inv.call(call.name, call.arguments)
            text = res.content if res.ok else f"error: {res.error}" + (
                f"\n{res.content}" if res.content else "")
            messages.append({"role": "tool", "tool_name": call.name, "content": text})
            if res.done:
                break
        if inv.done:
            break
    inv.finish("turn_limit")
    if memory is not None:
        inv.remembered = memory.remember(scenario, inv.findings, inv.ledger)
    return inv.report()


def report_lines(report: Report) -> list[str]:
    lines = [f"scenario {report.scenario}: {'PASS' if report.passed else 'FAIL'} "
             f"(end {report.end_reason}, {len(report.steps)} steps, "
             f"{report.evidence_issued} evidence ids issued, "
             f"{report.queries_used}/{report.max_queries} queries)"]
    for r in report.recall:
        if r.status == KEPT:
            lines.append(f"  recall: kept {r.claim!r} as {', '.join(r.ids)}")
        else:
            lines.append(f"  recall: dropped {r.claim!r}: {r.reason}")
    for f in report.findings:
        mark = "accepted" if f.accepted else "REJECTED"
        lines.append(f"  finding [{mark}, {f.support}] {f.claim!r} cites "
                     f"{', '.join(f.evidence_ids) or 'nothing'}")
        for p in f.problems:
            lines.append(f"    problem: {p}")
    counts = report.support_counts()
    if counts:
        lines.append("  claim support: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    c = report.conclusion
    if c:
        lines.append(f"  conclusion: {c['root_cause_service']} "
                     f"({'correct' if report.root_cause_correct else 'wrong'}) cites "
                     f"{', '.join(c['evidence_ids'])}")
        lines.append(f"    {c['summary']}")
    else:
        lines.append("  conclusion: none")
    if report.grade:
        lines.append("  " + score_line(report.grade))
    for entry in report.audit:
        lines.append("  audit: " + entry.line())
    if report.recall or report.remembered:
        kept, dropped = report.recall_counts
        lines.append(f"  memory: recalled {kept}, dropped {dropped}, "
                     f"stored {report.remembered} verified finding(s)")
    return lines


def report_json(report: Report, model: str = "") -> str:
    d = report.to_dict()
    d["model"] = model
    return json.dumps(d, sort_keys=True)
