"""Day 1 CLI: `list` tasks and `run` one episode. The full CLI is the day 6 milestone."""

from __future__ import annotations

import argparse
import json

from .agent import run_episode
from .envs import ENVIRONMENTS
from .llm import DEFAULT_MODEL, OllamaClient, check_ollama

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_OLLAMA = 0, 1, 2, 4


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent_gym")
    sub = p.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list", help="list environments and tasks")
    ls.add_argument("--json", action="store_true")
    run = sub.add_parser("run", help="run one episode with a model")
    run.add_argument("task", help="task id, see `list`")
    run.add_argument("--env", default="calendar", choices=sorted(ENVIRONMENTS))
    run.add_argument("--model", default=DEFAULT_MODEL)
    run.add_argument("--max-steps", type=int, default=20)
    run.add_argument("--json", action="store_true")
    return p


def main(argv: list[str], client=None, check=check_ollama) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else EXIT_OK
    if args.command == "list":
        rows = [{"env": name, "task": t.id, "tags": list(t.tags), "prompt": t.prompt}
                for name, cls in ENVIRONMENTS.items() for t in cls.tasks.values()]
        if args.json:
            print(json.dumps({"tasks": rows}, indent=2))
        else:
            for r in rows:
                print(f"{r['env']}/{r['task']:<18} [{', '.join(r['tags'])}]\n    {r['prompt']}")
        return EXIT_OK
    env_cls = ENVIRONMENTS[args.env]
    if args.task not in env_cls.tasks:
        print(f"unknown task '{args.task}'. Tasks: {', '.join(env_cls.tasks)}")
        return EXIT_USAGE
    if args.max_steps < 1:
        print("--max-steps must be at least 1")
        return EXIT_USAGE
    if client is None:
        ok, msg = check(args.model)
        if not ok:
            print(f"PROBLEM: {msg}")
            return EXIT_OLLAMA
        client = OllamaClient(model=args.model)
    ep = run_episode(env_cls(max_steps=args.max_steps), client, args.task)
    if args.json:
        print(json.dumps(ep.to_dict(), indent=2))
    else:
        for s in ep.steps:
            print(f"{s.index:>2}. {'ok ' if s.ok else 'ERR'} {s.tool}({json.dumps(s.arguments)})"
                  f" -> {s.content[:120]}")
        print(f"reward {ep.reward} | end {ep.end_reason} | steps {len(ep.steps)} | "
              f"turns {ep.turns}")
        for p in ep.problems:
            print(f"  problem: {p}")
    return EXIT_OK if ep.success else EXIT_FAILED
