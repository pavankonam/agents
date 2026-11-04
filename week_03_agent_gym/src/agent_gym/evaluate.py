"""Eval and report: run many episodes and summarise them, from live runs or JSONL files (D31, D32).

`eval_seeds` picks the data seeds, `run_eval` runs every chosen task once per
seed, and `build_report` turns episodes (or trajectory records read back from
JSONL) into one report: pass rate and mean reward per task, failure kinds per
task and in total, and the id vs name gap. `report_lines` prints it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from .agent import run_episode
from .failures import KINDS, count_kinds
from .gap import gap_lines, id_name_gap


def eval_seeds(repeats: int, seed: int | None = None) -> list[int | None]:
    """One run on the canonical data unless asked for more (D31).

    repeats=1 and no seed -> [None]; otherwise `repeats` seeds counting up from
    `seed` (default 1), so repeated runs always see differently shuffled data.
    """
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    if repeats == 1 and seed is None:
        return [None]
    start = 1 if seed is None else seed
    return [start + i for i in range(repeats)]


def select_tasks(environments: Mapping[str, Any], env: str | None = None,
                 only: str | None = None) -> list[tuple[str, Any, Any]]:
    """(env name, env class, task) for every task, filtered by env and by text in `env/task`."""
    out = []
    for name, cls in environments.items():
        if env and name != env:
            continue
        for task in cls.tasks.values():
            if only and only.lower() not in f"{name}/{task.id}".lower():
                continue
            out.append((name, cls, task))
    return out


def run_eval(chosen: Iterable[tuple[str, Any, Any]], client_for: Callable[[str, Any], Any],
             seeds: list[int | None], max_steps: int = 20,
             on_episode: Callable[[Any], None] | None = None) -> list:
    """Run every chosen task once per seed. `client_for(env_name, task)` gives the client."""
    episodes = []
    for name, cls, task in chosen:
        for seed in seeds:
            ep = run_episode(cls(max_steps=max_steps), client_for(name, task), task.id, seed=seed)
            episodes.append(ep)
            if on_episode:
                on_episode(ep)
    return episodes


@dataclass
class Row:
    """What a report needs from one episode; built from an Episode or a JSONL record."""

    env: str
    task_id: str
    passed: bool
    reward: float
    seed: int | None = None
    failures: list[dict] = field(default_factory=list)
    model: str | None = None


def as_row(item: Any, model: str | None = None) -> Row:
    """`model` fills in the model name when the item does not carry one (a live Episode)."""
    if isinstance(item, Mapping):  # a trajectory record: failures are kind strings
        meta = item.get("meta") or {}
        return Row(item["env"], item["task_id"], bool(item["passed"]), float(item["reward"]),
                   item.get("seed"), [{"kind": k} for k in item.get("failures", [])],
                   meta.get("model") or model)
    return Row(item.env, item.task_id, bool(item.passed), float(item.reward),
               getattr(item, "seed", None), [{"kind": f["kind"]} for f in item.failures], model)


def build_report(items: Iterable[Any], environments: Mapping[str, Any],
                 model: str | None = None) -> dict:
    rows = [as_row(i, model) for i in items]
    tasks: dict[tuple[str, str], list[Row]] = {}
    for r in rows:
        tasks.setdefault((r.env, r.task_id), []).append(r)
    per_task = []
    for (env, task), rs in tasks.items():
        passed = sum(r.passed for r in rs)
        per_task.append({
            "env": env, "task": task, "runs": len(rs), "passed": passed,
            "pass_rate": passed / len(rs),
            "mean_reward": round(sum(r.reward for r in rs) / len(rs), 6),
            "failed_runs_without_kind": sum(not r.passed and not r.failures for r in rs),
            "failures": count_kinds(f for r in rs for f in r.failures),
        })
    passed = sum(r.passed for r in rows)
    return {
        "runs": len(rows), "passed": passed,
        "pass_rate": passed / len(rows) if rows else None,
        "mean_reward": round(sum(r.reward for r in rows) / len(rows), 6) if rows else None,
        "models": sorted({r.model for r in rows if r.model}),
        "seeds": sorted({r.seed for r in rows}, key=lambda s: (s is not None, s or 0)),
        "failed_runs_without_kind": sum(t["failed_runs_without_kind"] for t in per_task),
        "tasks": per_task,
        "failures": count_kinds(f for r in rows for f in r.failures),
        "gap": id_name_gap(rows, environments),
    }


def report_lines(report: dict) -> list[str]:
    short = {"wrong_tool": "tool", "wrong_arguments": "args", "wrong_target": "target",
             "wrong_order": "order", "invented_id": "inv.id", "repeated_lookup": "repeat",
             "extra_step": "extra"}
    head = f"{'task':<28}{'pass':>8}{'reward':>8}" + "".join(f"{short[k]:>8}" for k in KINDS)
    lines = [head]
    for t in report["tasks"]:
        lines.append(f"{t['env'] + '/' + t['task']:<28}{str(t['passed']) + '/' + str(t['runs']):>8}"
                     f"{t['mean_reward']:>8.3f}" + "".join(f"{t['failures'][k]:>8}" for k in KINDS))
    if report["runs"]:
        lines.append(f"{'total':<28}{str(report['passed']) + '/' + str(report['runs']):>8}"
                     f"{report['mean_reward']:>8.3f}"
                     + "".join(f"{report['failures'][k]:>8}" for k in KINDS))
    seeds = ", ".join("canonical" if s is None else str(s) for s in report["seeds"]) or "none"
    lines.append(f"seeds: {seeds}")
    lines.append(f"failed runs with no failure kind: {report['failed_runs_without_kind']}")
    lines += gap_lines(report["gap"])
    return lines


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def markdown_lines(report: dict, title: str | None = None) -> list[str]:
    """The report as Markdown: a summary line, a per task table with every failure kind,
    a total row, and the id vs name pairs (D34). Same numbers as `report_lines`."""
    models = ", ".join(report.get("models") or []) or "unknown"
    seeds = ", ".join("canonical" if s is None else str(s) for s in report["seeds"]) or "none"
    lines = [f"### {title}", ""] if title else []
    if not report["runs"]:
        return lines + ["No runs."]
    lines += [f"Model: {models}. Runs: {report['runs']}, passed {report['passed']} "
              f"({_pct(report['pass_rate'])}), mean reward {report['mean_reward']:.3f}. "
              f"Seeds: {seeds}.", ""]
    names = [k.replace("_", " ") for k in KINDS]
    lines.append("| task | passed | mean reward | " + " | ".join(names) + " |")
    lines.append("| --- | ---: | ---: | " + " | ".join("---:" for _ in KINDS) + " |")
    for t in report["tasks"]:
        lines.append(f"| {t['env']}/{t['task']} | {t['passed']}/{t['runs']} | "
                     f"{t['mean_reward']:.3f} | "
                     + " | ".join(str(t["failures"][k]) for k in KINDS) + " |")
    lines.append(f"| **total** | **{report['passed']}/{report['runs']}** | "
                 f"**{report['mean_reward']:.3f}** | "
                 + " | ".join(f"**{report['failures'][k]}**" for k in KINDS) + " |")
    lines += ["", f"Failed runs with no failure kind: {report['failed_runs_without_kind']}."]
    gap = report["gap"]
    if gap["pairs"]:
        lines += ["", "| pair | id variant | name variant |", "| --- | ---: | ---: |"]
        for r in gap["pairs"]:
            note = "" if r["complete"] else " (one variant only)"
            lines.append(f"| {r['env']}/{r['pair']}{note} | {r['id_pass']}/{r['id_runs']} | "
                         f"{r['name_pass']}/{r['name_runs']} |")
        g = "n/a" if gap["gap"] is None else f"{gap['gap'] * 100:+.0f} points"
        lines += ["", f"Pass rate with ids {_pct(gap['id_rate'])}, with names "
                      f"{_pct(gap['name_rate'])}, gap {g}."]
    return lines
