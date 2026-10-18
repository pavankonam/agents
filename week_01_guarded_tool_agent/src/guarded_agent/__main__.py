"""Minimal CLI (full CLI on day 6).

  python -m guarded_agent "what is 17 * 23?"
  python -m guarded_agent replay audit_logs/2026-10-18.jsonl [run_id_prefix]

Loads policy.json from the project folder (or GUARDED_AGENT_POLICY) and asks on
the terminal for any tool marked "ask". File tools work inside ./workspace
(or GUARDED_AGENT_WORKSPACE). Every run is appended to
audit_logs/<UTC date>.jsonl (or GUARDED_AGENT_AUDIT_DIR).
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import (Agent, AuditLog, OllamaClient, Policy, ToolRegistry, console_approver,
               default_tools, file_tools, replay)

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = PROJECT_DIR / "policy.json"
DEFAULT_WORKSPACE = PROJECT_DIR / "workspace"
DEFAULT_AUDIT_DIR = PROJECT_DIR / "audit_logs"


def audit_path() -> Path:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Path(os.environ.get("GUARDED_AGENT_AUDIT_DIR", DEFAULT_AUDIT_DIR)) / f"{day}.jsonl"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print('usage: python -m guarded_agent "your task"\n'
              '       python -m guarded_agent replay <log.jsonl> [run_id]')
        return 2
    if argv[0] == "replay":
        if len(argv) < 2 or not Path(argv[1]).is_file():
            print("usage: python -m guarded_agent replay <log.jsonl> [run_id]")
            return 2
        print(replay(argv[1], argv[2] if len(argv) > 2 else None), end="")
        return 0
    policy = Policy.from_file(os.environ.get("GUARDED_AGENT_POLICY", DEFAULT_POLICY))
    workspace = Path(os.environ.get("GUARDED_AGENT_WORKSPACE", DEFAULT_WORKSPACE))
    workspace.mkdir(parents=True, exist_ok=True)
    tools = default_tools() + file_tools(workspace)
    log = AuditLog(audit_path())
    agent = Agent(OllamaClient(), ToolRegistry(tools),
                  policy=policy, approver=console_approver, audit=log)
    result = agent.run(" ".join(argv))
    for d in result.decisions:
        status = "ran" if d.approved else "blocked"
        print(f"[tool] {d.tool}({d.arguments})  verdict={d.verdict} {status}: {d.reason}")
    print(result.answer)
    print(f"[audit] run {log.run_id} -> {log.path}  "
          f"(replay: python -m guarded_agent replay {log.path} {log.run_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
