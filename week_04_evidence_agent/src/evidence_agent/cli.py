"""Command line: list, check, run. Exit codes: 0 pass, 1 fail, 2 usage, 4 Ollama not ready (D9).

run takes the bounds of day 4: --max-queries, --kill-file (an operator stops the
run from another terminal by creating the file) and --audit (append every
refusal and stop as one JSON line each) (D23 to D27). --memory PATH recalls the
verified findings stored there, re-checked against the scenario's data, and
stores this run's supported findings back (D28 to D32); a malformed memory
file is a usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .agent import report_json, report_lines, run_investigation
from .bounds import DEFAULT_MAX_QUERIES, FileKillSwitch
from .llm import DEFAULT_HOST, DEFAULT_MODEL, OllamaClient, check_ollama
from .memory import FindingMemory
from .telemetry import SCENARIOS


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # usage errors exit 2 with the message, as argparse does
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="python3 -m evidence_agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list scenarios")
    c = sub.add_parser("check", help="is Ollama up and the model pulled?")
    c.add_argument("--model", default=DEFAULT_MODEL)
    r = sub.add_parser("run", help="investigate one scenario with the local model")
    r.add_argument("scenario")
    r.add_argument("--model", default=DEFAULT_MODEL)
    r.add_argument("--max-steps", type=int, default=12)
    r.add_argument("--json", action="store_true", help="print the report as one JSON line")
    r.add_argument("--record", metavar="PATH", help="append the JSON report to a JSONL file")
    r.add_argument("--max-queries", type=int, default=DEFAULT_MAX_QUERIES,
                   help="query budget (search_logs, get_metric, list_deploys)")
    r.add_argument("--kill-file", metavar="PATH",
                   help="stop the run when this file exists; its first line 'who: why' is audited")
    r.add_argument("--audit", metavar="PATH", help="append audit entries as JSON lines")
    r.add_argument("--memory", metavar="PATH",
                   help="recall re-checked findings from this JSON file and store new ones")
    return p


def main(argv: list[str], client=None, out=None) -> int:
    out = out or sys.stdout
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if args.cmd == "list":
        for s in SCENARIOS.values():
            print(f"{s.name}: {s.title} ({len(s.records)} records, services "
                  f"{', '.join(s.services)})", file=out)
        return 0
    if args.cmd == "check":
        ok, msg = check_ollama(args.model, DEFAULT_HOST)
        print(msg, file=out)
        return 0 if ok else 4
    scenario = SCENARIOS.get(args.scenario)
    if scenario is None:
        print(f"unknown scenario {args.scenario!r}; scenarios: {', '.join(SCENARIOS)}", file=sys.stderr)
        return 2
    if args.max_steps < 1:
        print("--max-steps must be at least 1", file=sys.stderr)
        return 2
    if args.max_queries < 1:
        print("--max-queries must be at least 1", file=sys.stderr)
        return 2
    memory = None
    if args.memory:
        try:
            memory = FindingMemory.load(args.memory)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if client is None:
        ok, msg = check_ollama(args.model, DEFAULT_HOST)
        if not ok:
            print(msg, file=sys.stderr)
            return 4
        client = OllamaClient(model=args.model)
    kill = FileKillSwitch(args.kill_file) if args.kill_file else None
    report = run_investigation(client, scenario, max_steps=args.max_steps,
                               max_queries=args.max_queries, kill_switch=kill, memory=memory)
    if memory is not None:
        memory.save()
    line = report_json(report, model=args.model)
    if args.audit:
        with open(args.audit, "a", encoding="utf-8") as fh:
            for entry in report.audit:
                fh.write(json.dumps({"scenario": scenario.name, "model": args.model,
                                     **asdict(entry)}, sort_keys=True) + "\n")
    if args.record:
        with open(args.record, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    if args.json:
        print(line, file=out)
    else:
        for text in report_lines(report):
            print(text, file=out)
    return 0 if report.passed else 1
