"""The agent loop: the model investigates through tools until it concludes (D6)."""

from __future__ import annotations

import json

from .investigation import TOOLS, Investigation, Report
from .llm import LLMClient
from .telemetry import Scenario

SYSTEM_PROMPT = """You are an incident investigator. You find the root cause of a production problem
using only the telemetry tools you are given.

Rules:
- Every tool result line starts with an evidence id in brackets, like [ev_003].
- You may only cite evidence ids that a tool returned to you in this investigation.
  Never make up an id. A finding or conclusion with an unknown id is rejected.
- Record what you learn with report_finding: one claim and the ids that support it.
- When you know the cause, call conclude with the root cause service, a short summary
  and the evidence ids. A plain text answer does not count as a conclusion.
- You have at most {max_steps} tool calls. Services: {services}."""


def system_prompt(scenario: Scenario, max_steps: int) -> str:
    return SYSTEM_PROMPT.format(max_steps=max_steps, services=", ".join(scenario.services))


def run_investigation(llm: LLMClient, scenario: Scenario, max_steps: int = 12,
                      max_turns: int | None = None) -> Report:
    inv = Investigation(scenario, max_steps=max_steps)
    messages = [
        {"role": "system", "content": system_prompt(scenario, max_steps)},
        {"role": "user", "content": scenario.question},
    ]
    turns = max_turns if max_turns is not None else max_steps + 2
    for _ in range(turns):
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
    return inv.report()


def report_lines(report: Report) -> list[str]:
    lines = [f"scenario {report.scenario}: {'PASS' if report.passed else 'FAIL'} "
             f"(end {report.end_reason}, {len(report.steps)} steps, "
             f"{report.evidence_issued} evidence ids issued)"]
    for f in report.findings:
        mark = "accepted" if f.accepted else "REJECTED"
        lines.append(f"  finding [{mark}] {f.claim!r} cites {', '.join(f.evidence_ids) or 'nothing'}")
        for p in f.problems:
            lines.append(f"    problem: {p}")
    c = report.conclusion
    if c:
        lines.append(f"  conclusion: {c['root_cause_service']} "
                     f"({'correct' if report.root_cause_correct else 'wrong'}) cites "
                     f"{', '.join(c['evidence_ids'])}")
        lines.append(f"    {c['summary']}")
    else:
        lines.append("  conclusion: none")
    return lines


def report_json(report: Report, model: str = "") -> str:
    d = report.to_dict()
    d["model"] = model
    return json.dumps(d, sort_keys=True)
