"""The id vs name gap: pass rate on explicit id variants minus pass rate on name variants (D21).

Turing's Calendar Gym found agents pass far more often when tasks give ids
(89%) than when they must resolve names (41%). Paired tasks hold the job
constant and change only how it is phrased, so the gap isolates the lookup.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


@dataclass
class Pair:
    env: str
    pair: str
    id_task: str
    name_task: str


def paired_tasks(environments: Mapping[str, Any]) -> list[Pair]:
    """Every (env, pair) with exactly one id and one name variant. Raises on a broken pair."""
    out = []
    for env_name, cls in environments.items():
        groups: dict[str, dict[str, list[str]]] = {}
        for t in cls.tasks.values():
            if t.pair:
                groups.setdefault(t.pair, {"id": [], "name": []})[t.variant].append(t.id)
        for pair, v in groups.items():
            if len(v["id"]) != 1 or len(v["name"]) != 1:
                raise ValueError(f"{env_name} pair '{pair}' needs exactly one id and one name "
                                 f"variant, has id={v['id']} name={v['name']}")
            out.append(Pair(env_name, pair, v["id"][0], v["name"][0]))
    return out


def _rate(passed: int, runs: int) -> float | None:
    return passed / runs if runs else None


def id_name_gap(episodes: Iterable[Any], environments: Mapping[str, Any]) -> dict:
    """Pass counts per pair and overall, from anything with env, task_id and passed.

    Episodes of unpaired tasks are ignored. A pair counts toward the totals only
    if both variants ran, so a filtered run cannot fake a gap. `gap` is
    id_rate - name_rate, None when nothing comparable ran.
    """
    pairs = paired_tasks(environments)
    runs: dict[tuple[str, str], list[bool]] = {}
    for ep in episodes:
        runs.setdefault((ep.env, ep.task_id), []).append(bool(ep.passed))
    rows = []
    tot = {"id_pass": 0, "id_runs": 0, "name_pass": 0, "name_runs": 0}
    for p in pairs:
        i = runs.get((p.env, p.id_task), [])
        n = runs.get((p.env, p.name_task), [])
        if not i and not n:
            continue
        row = {**asdict(p), "id_pass": sum(i), "id_runs": len(i),
               "name_pass": sum(n), "name_runs": len(n)}
        row["complete"] = bool(i and n)
        rows.append(row)
        if row["complete"]:
            for k in tot:
                tot[k] += row[k]
    id_rate = _rate(tot["id_pass"], tot["id_runs"])
    name_rate = _rate(tot["name_pass"], tot["name_runs"])
    gap = id_rate - name_rate if id_rate is not None and name_rate is not None else None
    return {"pairs": rows, **tot, "id_rate": id_rate, "name_rate": name_rate, "gap": gap}


def gap_lines(report: dict) -> list[str]:
    """A small text table for the CLI and quiz_model."""
    def pct(x):
        return "n/a" if x is None else f"{x * 100:.0f}%"

    lines = ["pair".ljust(26) + "id".rjust(8) + "name".rjust(8)]
    for r in report["pairs"]:
        mark = "" if r["complete"] else "  (one variant only, not in total)"
        row = (f"{r['env'] + '/' + r['pair']:<26}"
               f"{r['id_pass']:>4}/{r['id_runs']:<3}{r['name_pass']:>4}/{r['name_runs']:<3}"
               + mark)
        lines.append(row.rstrip())
    gap = report["gap"]
    lines.append(f"pass rate: id {pct(report['id_rate'])}, name {pct(report['name_rate'])}, "
                 f"gap {'n/a' if gap is None else f'{gap * 100:+.0f} points'}")
    return lines
