"""CLI: `list` tasks, `run` one episode, `eval` many, `replay` and `report` JSONL files.

    list    [--json]
    run     TASK [--env E] [--model M] [--max-steps N] [--seed S] [--record PATH]
                 [--breakdown] [--json]
    eval    [--env E] [--only TEXT] [--repeats N] [--seed S] [--model M] [--max-steps N]
            [--record PATH] [--json]                                          (D31)
    replay  PATH [--json]                                                     (D26)
    report  PATH [--json]        the eval report rebuilt from JSONL, no model (D32)

A task can be named `env/task` (for example `inbox/assign_by_name`) instead of using --env.

Exit codes, the same for every command (D33):
    0  everything ran and passed (run, eval, report) or replayed the same (replay)
    1  something ran but failed, or a replay differs
    2  usage: bad arguments, unknown env or task, a filter that matches nothing,
       an unreadable or invalid JSONL file
    3  nothing to report: the JSONL file has no records
    4  Ollama is not ready (not running, or the model is not pulled)
"""

from __future__ import annotations

import argparse
import json

from .agent import run_episode
from .envs import ENVIRONMENTS
from .evaluate import build_report, eval_seeds, report_lines, run_eval, select_tasks
from .llm import DEFAULT_MODEL, OllamaClient, check_ollama
from .trajectory import TrajectoryError, read_jsonl, replay, write_jsonl

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_EMPTY, EXIT_OLLAMA = 0, 1, 2, 3, 4


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
    run.add_argument("--seed", type=int, default=None,
                     help="shuffle the env data with this seed (default: canonical order)")
    run.add_argument("--record", default=None, metavar="PATH",
                     help="append the episode to this JSONL file")
    ev = sub.add_parser("eval", help="run every task, N times over seeds, and print a report")
    ev.add_argument("--env", default=None, choices=sorted(ENVIRONMENTS))
    ev.add_argument("--only", default=None, help="tasks whose env/task contains this text")
    ev.add_argument("--repeats", type=int, default=1,
                    help="runs per task; more than 1 uses seeds SEED, SEED+1, ...")
    ev.add_argument("--seed", type=int, default=None,
                    help="first seed (default: canonical data for 1 repeat, else 1)")
    ev.add_argument("--model", default=DEFAULT_MODEL)
    ev.add_argument("--max-steps", type=int, default=20)
    ev.add_argument("--record", default=None, metavar="PATH",
                    help="append every episode to this JSONL file")
    ev.add_argument("--json", action="store_true")
    rep = sub.add_parser("report", help="summarise a JSONL file (pass rate, failure kinds, gap)")
    rep.add_argument("path", help="JSONL file written by run --record or eval --record")
    rep.add_argument("--json", action="store_true")
    rp = sub.add_parser("replay", help="re-run recorded episodes and check they score the same")
    rp.add_argument("path", help="JSONL file written by run --record")
    rp.add_argument("--json", action="store_true")
    return p


def replay_file(path: str, as_json: bool) -> int:
    try:
        records = read_jsonl(path)
        results = [replay(r) for r in records]
    except (OSError, TrajectoryError) as exc:
        print(f"PROBLEM: {exc}")
        return EXIT_USAGE
    if as_json:
        print(json.dumps({"replayed": len(results), "ok": sum(r.ok for r in results),
                          "results": [{"env": r.env, "task": r.task_id, "reward": r.reward,
                                       "passed": r.passed, "mismatches": r.mismatches}
                                      for r in results]}, indent=2))
    else:
        for i, r in enumerate(results, 1):
            print(f"{i:>3}. {'SAME' if r.ok else 'DIFF'} {r.env}/{r.task_id} reward {r.reward:.3f}")
            for m in r.mismatches:
                print(f"       {m}")
        print(f"{sum(r.ok for r in results)}/{len(results)} episodes replayed with the same result")
    return EXIT_OK if all(r.ok for r in results) else EXIT_FAILED


def print_report(report: dict, as_json: bool, title: str) -> int:
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(title)
        for line in report_lines(report):
            print(f"  {line}")
    return EXIT_OK if report["passed"] == report["runs"] else EXIT_FAILED


def report_file(path: str, as_json: bool) -> int:
    try:
        records = read_jsonl(path)
        report = build_report(records, ENVIRONMENTS)
    except (OSError, TrajectoryError) as exc:
        print(f"PROBLEM: {exc}")
        return EXIT_USAGE
    except (KeyError, TypeError, ValueError) as exc:
        print(f"PROBLEM: {path}: record is missing or has a bad field ({exc})")
        return EXIT_USAGE
    if not records:
        print(f"PROBLEM: {path} has no records")
        return EXIT_EMPTY
    return print_report(report, as_json, f"report of {len(records)} episodes from {path}")


def eval_command(args, client, client_factory, check) -> int:
    if args.max_steps < 1 or args.repeats < 1:
        print("--max-steps and --repeats must be at least 1")
        return EXIT_USAGE
    chosen = select_tasks(ENVIRONMENTS, args.env, args.only)
    if not chosen:
        print(f"no task matches env {args.env!r} and --only {args.only!r}")
        return EXIT_USAGE
    if client_factory is None:
        if client is None:
            ok, msg = check(args.model)
            if not ok:
                print(f"PROBLEM: {msg}")
                return EXIT_OLLAMA
            client = OllamaClient(model=args.model)
        client_factory = lambda env_name, task: client  # noqa: E731  (stateless per chat)
    seeds = eval_seeds(args.repeats, args.seed)

    def progress(ep):
        if not args.json:
            seed = "canonical" if ep.seed is None else f"seed {ep.seed}"
            print(f"{'PASS' if ep.passed else 'FAIL'} {ep.env}/{ep.task_id} ({seed}) "
                  f"reward {ep.reward:.3f} {[f['kind'] for f in ep.failures] or ''}".rstrip())

    episodes = run_eval(chosen, client_factory, seeds, args.max_steps, progress)
    if args.record:
        write_jsonl(args.record, episodes, model=getattr(client, "model", "fake"))
    report = build_report(episodes, ENVIRONMENTS)
    return print_report(report, args.json,
                        f"\neval: {len(chosen)} tasks x {len(seeds)} seeds = {len(episodes)} episodes")


def breakdown_lines(node: dict, indent: int = 0) -> list[str]:
    """Render Episode.breakdown (RubricResult.to_dict) one node per line."""
    w = f" x{node['weight']:g}" if "weight" in node else ""
    out = [f"{'  ' * indent}{node['name']}{w}: {node['score']:.3f}"]
    out += [f"{'  ' * (indent + 1)}- {d}" for d in node.get("detail", [])]
    for c in node.get("children", []):
        out += breakdown_lines(c, indent + 1)
    return out


def main(argv: list[str], client=None, check=check_ollama, client_factory=None) -> int:
    """`client` is used for run and eval; `client_factory(env_name, task)` overrides it
    for eval, so tests can give each task its own scripted client."""
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
    if args.command == "replay":
        return replay_file(args.path, args.json)
    if args.command == "report":
        return report_file(args.path, args.json)
    if args.command == "eval":
        return eval_command(args, client, client_factory, check)
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
    ep = run_episode(env_cls(max_steps=args.max_steps), client, args.task, seed=args.seed)
    if args.record:
        write_jsonl(args.record, [ep], model=getattr(client, "model", "fake"))
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
