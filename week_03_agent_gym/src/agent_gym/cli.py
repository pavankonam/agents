"""CLI so far: `list` tasks and `run` one episode (reward breakdown, failure kinds). Full CLI is day 6.

A task can be named `env/task` (for example `inbox/assign_by_name`) instead of using --env.
"""

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
    run.add_argument("task", help="task id or env/task, see `list`")
    run.add_argument("--env", default=None, choices=sorted(ENVIRONMENTS),
                     help="environment (default: calendar, or the env/ prefix of the task)")
    run.add_argument("--model", default=DEFAULT_MODEL)
    run.add_argument("--max-steps", type=int, default=20)
    run.add_argument("--json", action="store_true")
    run.add_argument("--breakdown", action="store_true", help="print the rubric tree")
    return p


def breakdown_lines(node: dict, indent: int = 0) -> list[str]:
    """Render Episode.breakdown (RubricResult.to_dict) one node per line."""
    w = f" x{node['weight']:g}" if "weight" in node else ""
    out = [f"{'  ' * indent}{node['name']}{w}: {node['score']:.3f}"]
    out += [f"{'  ' * (indent + 1)}- {d}" for d in node.get("detail", [])]
    for c in node.get("children", []):
        out += breakdown_lines(c, indent + 1)
    return out


def main(argv: list[str], client=None, check=check_ollama) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else EXIT_OK
    if args.command == "list":
        rows = [{"env": name, "task": t.id, "tags": list(t.tags), "pair": t.pair,
                 "variant": t.variant, "prompt": t.prompt}
                for name, cls in ENVIRONMENTS.items() for t in cls.tasks.values()]
        if args.json:
            print(json.dumps({"tasks": rows}, indent=2))
        else:
            for r in rows:
                pair = f" pair {r['pair']} ({r['variant']})" if r["pair"] else ""
                print(f"{r['env']}/{r['task']:<18} [{', '.join(r['tags'])}]{pair}\n"
                      f"    {r['prompt']}")
        return EXIT_OK
    env_name, task_id = args.env, args.task
    if "/" in task_id:
        prefix, task_id = task_id.split("/", 1)
        if prefix not in ENVIRONMENTS or (env_name and env_name != prefix):
            print(f"unknown or conflicting environment '{prefix}'. "
                  f"Environments: {', '.join(ENVIRONMENTS)}")
            return EXIT_USAGE
        env_name = prefix
    env_cls = ENVIRONMENTS[env_name or "calendar"]
    args.task = task_id
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
        print(f"{'PASS' if ep.success else 'FAIL'} | reward {ep.reward} | end {ep.end_reason} | "
              f"steps {len(ep.steps)} | turns {ep.turns}")
        for p in ep.problems:
            print(f"  problem: {p}")
        for f in ep.failures:
            print(f"  failure: step {f['index']} {f['tool']}: {f['kind']} ({f['reason']})")
        if args.breakdown:
            print("reward breakdown:")
            for line in breakdown_lines(ep.breakdown):
                print(f"  {line}")
    return EXIT_OK if ep.success else EXIT_FAILED
