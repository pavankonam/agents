"""Minimal CLI: python -m guarded_agent "what is 17 * 23?"  (full CLI on day 6)."""

import sys

from . import Agent, OllamaClient, ToolRegistry, default_tools


def main() -> int:
    if len(sys.argv) < 2:
        print('usage: python -m guarded_agent "your task"')
        return 2
    agent = Agent(OllamaClient(), ToolRegistry(default_tools()))
    result = agent.run(" ".join(sys.argv[1:]))
    for call in result.tool_calls:
        print(f"[tool] {call.name}({call.arguments})")
    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
