"""Command line interface (decision D32).

  python -m guarded_agent "what is 17 * 23?"            run a task (same as `run`)
  python -m guarded_agent run [options] "task"
  python -m guarded_agent tools [--policy P] [--mcp M]  list tools and their verdicts
  python -m guarded_agent doctor [--model M]            is Ollama up, is the model pulled?
  python -m guarded_agent replay <log.jsonl> [run_id]   print a logged run as a timeline

Every option has an environment variable fallback so day 1 to 5 usage still works:
GUARDED_AGENT_POLICY, GUARDED_AGENT_WORKSPACE, GUARDED_AGENT_AUDIT_DIR,
GUARDED_AGENT_MCP, GUARDED_AGENT_MODEL, OLLAMA_HOST.

Exit codes: 0 answered, 2 usage or config error, 3 step limit reached,
4 Ollama not reachable or model missing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TextIO

from .agent import Agent
from .audit import AuditLog, replay
from .files import file_tools
from .llm import DEFAULT_HOST, DEFAULT_MODEL, OllamaClient, check_ollama
from .mcp import MCPError, connect as connect_mcp
from .policy import Approver, Policy, console_approver
from .tools import ToolRegistry, default_tools

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = PROJECT_DIR / "policy.json"
DEFAULT_WORKSPACE = PROJECT_DIR / "workspace"
DEFAULT_AUDIT_DIR = PROJECT_DIR / "audit_logs"
COMMANDS = ("run", "tools", "doctor", "replay")
EXIT_OK, EXIT_USAGE, EXIT_MAX_STEPS, EXIT_OLLAMA = 0, 2, 3, 4


def _env(name: str, default) -> str:
    return os.environ.get(name, str(default))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="guarded_agent",
                                 description="Local Ollama agent with policy checked tools.")
    sub = ap.add_subparsers(dest="command", required=True)

    def setup(p, model=True):
        p.add_argument("--policy", default=_env("GUARDED_AGENT_POLICY", DEFAULT_POLICY),
                       help="policy.json to use")
        p.add_argument("--workspace", default=_env("GUARDED_AGENT_WORKSPACE", DEFAULT_WORKSPACE),
                       help="folder the file tools may touch")
        p.add_argument("--mcp", default=os.environ.get("GUARDED_AGENT_MCP"),
                       help="mcp_servers.json: start these servers and add their tools")
        if model:
            p.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name")
            p.add_argument("--host", default=DEFAULT_HOST, help="Ollama URL")

    run = sub.add_parser("run", help="run a task")
    setup(run)
    run.add_argument("task", nargs="+", help="what the agent should do")
    run.add_argument("--max-steps", type=int, default=6, help="model turns before stopping")
    run.add_argument("--audit-dir", default=_env("GUARDED_AGENT_AUDIT_DIR", DEFAULT_AUDIT_DIR))
    run.add_argument("--no-audit", action="store_true", help="do not write an audit log")
    run.add_argument("--non-interactive", action="store_true",
                     help="never prompt: every 'ask' verdict is declined")
    run.add_argument("--json", action="store_true", help="print one JSON object, nothing else")

    tools = sub.add_parser("tools", help="list available tools and their policy verdicts")
    setup(tools, model=False)

    doc = sub.add_parser("doctor", help="check that Ollama is up and the model is pulled")
    doc.add_argument("--model", default=DEFAULT_MODEL)
    doc.add_argument("--host", default=DEFAULT_HOST)

    rep = sub.add_parser("replay", help="print a logged run as a timeline")
    rep.add_argument("log", help="audit log .jsonl file")
    rep.add_argument("run_id", nargs="?", help="run id or prefix (default: all runs)")
    return ap


def normalise(argv: list[str]) -> list[str]:
    """`guarded_agent "task"` and `guarded_agent --model x "task"` mean `run ...`."""
    if argv and argv[0] not in COMMANDS and argv[0] not in ("-h", "--help"):
        return ["run"] + argv
    return argv


def denying_approver(tool: str, arguments: dict, reason: str) -> bool:
    return False


def load_tools(args, out: TextIO, quiet: bool = False):
    """Built in + file tools + MCP tools. Returns (clients, tools, sources)."""
    workspace = Path(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    tools, sources = [], {}
    for t in default_tools():
        tools.append(t); sources[t.name] = "builtin"
    for t in file_tools(workspace):
        tools.append(t); sources[t.name] = "files"
    clients = []
    if args.mcp:
        clients, mcp_tools = connect_mcp(args.mcp)
        for t in mcp_tools:
            tools.append(t); sources[t.name] = "mcp:" + t.name.split("__", 1)[0]
        if not quiet:
            print(f"[mcp] {len(mcp_tools)} tool(s) from {len(clients)} server(s): "
                  + ", ".join(t.name for t in mcp_tools), file=out)
    return clients, tools, sources


def cmd_tools(args, out: TextIO) -> int:
    policy = Policy.from_file(args.policy)
    clients, tools, sources = load_tools(args, out, quiet=True)
    try:
        width = max(len(t.name) for t in tools)
        print(f"{'TOOL':<{width}}  {'VERDICT':<7}  {'SOURCE':<10}  MATCHED BY", file=out)
        for t in tools:
            key, tp = policy.lookup(t.name)
            if tp is None:
                verdict, via = policy.default, "default"
            else:
                verdict = tp.verdict
                via = ("exact" if key == t.name else f"pattern '{key}'")
                if tp.rules:
                    via += f", {len(tp.rules)} rule(s): " + ", ".join(
                        f"{r.arg} {r.type}" for r in tp.rules)
            print(f"{t.name:<{width}}  {verdict:<7}  {sources[t.name]:<10}  {via}", file=out)
    finally:
        for c in clients:
            c.close()
    return EXIT_OK


def cmd_doctor(args, out: TextIO, check=check_ollama) -> int:
    ok, msg = check(args.model, args.host)
    print(("OK: " if ok else "PROBLEM: ") + msg, file=out)
    return EXIT_OK if ok else EXIT_OLLAMA


def cmd_run(args, out: TextIO, llm_factory: Callable | None, approver: Approver | None) -> int:
    if args.max_steps < 1:
        print("error: --max-steps must be at least 1", file=out)
        return EXIT_USAGE
    policy = Policy.from_file(args.policy)
    if args.non_interactive:
        approver = denying_approver
    elif approver is None:
        approver = console_approver
    llm = (llm_factory or (lambda a: OllamaClient(model=a.model, host=a.host)))(args)
    log = None
    if not args.no_audit:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log = AuditLog(Path(args.audit_dir) / f"{day}.jsonl")
    clients, tools, _ = load_tools(args, out, quiet=args.json)
    agent = Agent(llm, ToolRegistry(tools), max_steps=args.max_steps,
                  policy=policy, approver=approver, audit=log)
    try:
        result = agent.run(" ".join(args.task))
    except ConnectionError as exc:
        _report_failure(args, out, str(exc), log)
        return EXIT_OLLAMA
    finally:
        for c in clients:
            c.close()
    code = EXIT_OK if result.stopped_reason == "final_answer" else EXIT_MAX_STEPS
    if args.json:
        print(json.dumps({
            "answer": result.answer, "stopped_reason": result.stopped_reason,
            "steps": result.steps, "exit_code": code,
            "decisions": [{"tool": d.tool, "arguments": d.arguments, "verdict": d.verdict,
                           "approved": d.approved, "reason": d.reason}
                          for d in result.decisions],
            "injection_warnings": result.warnings,
            "run_id": log.run_id if log else None,
            "audit_log": str(log.path) if log else None,
        }), file=out)
        return code
    for d in result.decisions:
        status = "ran" if d.approved else "blocked"
        print(f"[tool] {d.tool}({json.dumps(d.arguments)})  verdict={d.verdict} "
              f"{status}: {d.reason}", file=out)
    for w in result.warnings:
        print(f"[guard] step {w['step']} {w['tool']}: possible prompt injection "
              f"({', '.join(w['labels'])}); later calls needed approval", file=out)
    print(result.answer, file=out)
    if log:
        print(f"[audit] run {log.run_id} -> {log.path}  "
              f"(replay: python -m guarded_agent replay {log.path} {log.run_id})", file=out)
    return code


def _report_failure(args, out: TextIO, message: str, log: AuditLog | None) -> None:
    if args.json:
        print(json.dumps({"error": message, "exit_code": EXIT_OLLAMA,
                          "run_id": log.run_id if log else None}), file=out)
    else:
        print(f"error: {message}\nTry: python -m guarded_agent doctor --model {args.model}",
              file=out)


def main(argv: list[str] | None = None, *, out: TextIO | None = None,
         llm_factory: Callable | None = None, approver: Approver | None = None) -> int:
    out = out or sys.stdout
    argv = normalise(sys.argv[1:] if argv is None else list(argv))
    parser = build_parser()
    if not argv:
        parser.print_usage(out)
        return EXIT_USAGE
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse already printed the message
        return EXIT_OK if exc.code == 0 else EXIT_USAGE
    try:
        if args.command == "replay":
            if not Path(args.log).is_file():
                print(f"error: no such log file: {args.log}", file=out)
                return EXIT_USAGE
            print(replay(args.log, args.run_id), end="", file=out)
            return EXIT_OK
        if args.command == "doctor":
            return cmd_doctor(args, out)
        if args.command == "tools":
            return cmd_tools(args, out)
        return cmd_run(args, out, llm_factory, approver)
    except (FileNotFoundError, json.JSONDecodeError, ValueError, MCPError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=out)
        return EXIT_USAGE
