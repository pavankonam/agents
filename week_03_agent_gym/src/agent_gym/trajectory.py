"""Trajectories: record episodes as JSONL and replay them against a fresh env (D26, D27).

A record holds what is needed to rebuild the episode without the model: env,
task, seed, max_steps, end reason and every action in order, plus what the
env said and scored. `replay` resets a fresh env with the same task and seed,
steps the recorded actions, ends the episode the same way and compares the
observations, reward, passed, problems and failure kinds with the record.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .types import Action

FORMAT = 1
# Episodes that end on a step are replayed by the steps alone; the others were
# ended by the agent loop calling finish (D27).
ENDS_ON_STEP = ("submitted", "step_limit")


class TrajectoryError(ValueError):
    """A record or JSONL line cannot be read or replayed at all."""


def to_record(ep, **extra) -> dict:
    """One JSON ready dict per episode. `extra` (for example model) is stored under `meta`."""
    return {
        "format": FORMAT,
        "env": ep.env, "task_id": ep.task_id, "episode_id": ep.episode_id,
        "seed": ep.seed, "max_steps": ep.max_steps, "end_reason": ep.end_reason,
        "reward": ep.reward, "passed": ep.passed, "problems": list(ep.problems),
        "failures": [f["kind"] for f in ep.failures],
        "steps": [{"tool": s.tool, "arguments": s.arguments, "ok": s.ok, "content": s.content}
                  for s in ep.steps],
        "meta": dict(extra),
    }


def write_jsonl(path: str | Path, episodes: Iterable, **extra) -> int:
    """Append one line per episode. Returns the number of lines written."""
    n = 0
    with open(path, "a", encoding="utf-8") as fh:
        for ep in episodes:
            fh.write(json.dumps(to_record(ep, **extra), sort_keys=True) + "\n")
            n += 1
    return n


def read_jsonl(path: str | Path) -> list[dict]:
    """Read records, skipping blank lines. A bad line raises with its line number."""
    records = []
    with open(path, encoding="utf-8") as fh:
        for no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TrajectoryError(f"{path}:{no}: not JSON ({exc.msg})") from None
            if not isinstance(rec, dict) or rec.get("format") != FORMAT:
                raise TrajectoryError(f"{path}:{no}: not a format {FORMAT} trajectory record")
            records.append(rec)
    return records


@dataclass
class ReplayResult:
    env: str
    task_id: str
    reward: float
    passed: bool
    mismatches: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches


def replay(record: dict, environments: dict | None = None) -> ReplayResult:
    """Re-run the recorded actions on a fresh env and compare everything the env produced."""
    if environments is None:
        from .envs import ENVIRONMENTS as environments
    for key in ("env", "task_id", "steps", "end_reason", "reward"):
        if key not in record:
            raise TrajectoryError(f"record has no '{key}'")
    cls = environments.get(record["env"])
    if cls is None:
        raise TrajectoryError(f"unknown environment '{record['env']}'")
    if record["task_id"] not in cls.tasks:
        raise TrajectoryError(f"unknown task '{record['task_id']}' for {record['env']}")
    env = cls(max_steps=record.get("max_steps", 20))
    env.reset(record["task_id"], seed=record.get("seed"))
    mismatches: list[str] = []
    steps = record["steps"]
    for i, s in enumerate(steps, 1):
        if env.state.done:
            mismatches.append(f"episode ended before step {i} of {len(steps)}")
            break
        obs = env.step(Action(s["tool"], s.get("arguments", {})))
        content = obs.content  # on step_limit this includes the env's end message, as recorded
        if content != s.get("content") or obs.ok != s.get("ok"):
            mismatches.append(f"step {i} {s['tool']}: observation differs "
                              f"(recorded {s.get('content')!r}, replayed {content!r})")
    st = env.state
    if not st.done:
        if record["end_reason"] in ENDS_ON_STEP:
            mismatches.append(f"recorded end '{record['end_reason']}' but the replayed "
                              "episode is still running")
        env.finish(record["end_reason"])
        st = env.state
    if st.end_reason != record["end_reason"]:
        mismatches.append(f"end reason: recorded {record['end_reason']}, "
                          f"replayed {st.end_reason}")
    reward = st.reward if st.reward is not None else 0.0
    if not math.isclose(reward, record["reward"], abs_tol=1e-9):
        mismatches.append(f"reward: recorded {record['reward']}, replayed {reward}")
    if "passed" in record and st.passed != record["passed"]:
        mismatches.append(f"passed: recorded {record['passed']}, replayed {st.passed}")
    if "problems" in record and st.problems != record["problems"]:
        mismatches.append(f"problems: recorded {record['problems']}, replayed {st.problems}")
    kinds = [f["kind"] for f in st.failures]
    if "failures" in record and kinds != record["failures"]:
        mismatches.append(f"failures: recorded {record['failures']}, replayed {kinds}")
    return ReplayResult(record["env"], record["task_id"], reward, st.passed, mismatches)
