"""Minimal CLI: python -m guarded_agent "what is 17 * 23?"  (full CLI on day 6).

Loads policy.json from the project folder (or GUARDED_AGENT_POLICY) and asks on
the terminal for any tool marked "ask".
"""

import os
import sys
from pathlib import Path

from . import Agent, OllamaClient, Policy, ToolRegistry, console_approver, default_tools

DEFAULT_POLICY = Path(__file__).resolve().parents[2] / "policy.json"


def main() -> int:
    if len(sys.argv) < 2:
        print('usage: python -m guarded_agent "your task"')
        return 2
    policy = Policy.from_file(os.environ.get("GUARDED_AGENT_POLICY", DEFAULT_POLICY))
    agent = Agent(OllamaClient(), ToolRegistry(default_tools()),
                  policy=policy, approver=console_approver)
    result = agent.run(" ".join(sys.argv[1:]))
    for d in result.decisions:
        status = "ran" if d.approved else "blocked"
        print(f"[tool] {d.tool}({d.arguments})  verdict={d.verdict} {status}: {d.reason}")
    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
