"""Quiz the agent through Ollama: run every task as an episode and check the env's reward.

    python3 quiz/quiz_model.py --fake            # scripted reference solutions, no Ollama
    python3 quiz/quiz_model.py [--model M] [--only TEXT]

Pass means the environment's state check found no problems (D7, D15), never the
model's own claim; the reward printed next to it is the rubric score (D13), which
is below 1.0 when the run had refused or extra steps. In --fake mode two controls
also run per task: a model that answers without doing anything, and one that
submits at once. Both must score 0 (D12). A third, messy control repeats a lookup
and makes one refused call before the reference solution: it must still pass but
score strictly between 0 and 1, which shows the process rubric is live (D16).

Every step that was refused or wasted gets a failure kind (D18). The reference
run must have none, the messy control must show exactly wrong_tool then
repeated_lookup (or extra_step when the reference does not start with that
lookup); the lookup is the env's first argument free read only tool, and the run
ends with a per kind failure table across all tasks (D20). Then a table of the
paired tasks (same job, explicit ids vs names to look up) with pass rates per
variant and the id vs name gap (D21); in --fake mode the gap must be 0 (D23).

Every episode is turned into a trajectory record, sent through JSON and
replayed on a fresh env; the replay must reproduce the observations, reward,
passed, problems and failure kinds (D26). In --fake mode each reference is also
run on seeded data (seed 1 to 3) and must pass with no failures (D28).
--record PATH appends the main runs (not the controls) to a JSONL file.

In --fake mode two day 6 checks also count as controls. A wrong target control
plays the reference but points one write at a look alike object (T-1003 for
T-1002, evt_004 for evt_002, agt_02 for agt_01): it must fail with exactly one
failure kind, wrong_target (D30). And an eval of every reference on seeds 1 and
2 is written to JSONL and read back: the report rebuilt from the file must equal
the live one, with every run passed and no failure kinds (D31, D32), and its
Markdown results table must have one row per task and pair, the total row and
the model name (D34).

Exit codes: 0 all pass, 1 some failed, 2 bad --only, 4 Ollama not ready.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_gym.agent import run_episode  # noqa: E402
from agent_gym.envs import ENVIRONMENTS  # noqa: E402
from agent_gym.evaluate import build_report, markdown_lines, run_eval, select_tasks  # noqa: E402
from agent_gym.failures import KINDS, summarize  # noqa: E402
from agent_gym.gap import gap_lines, id_name_gap  # noqa: E402
from agent_gym.llm import (DEFAULT_MODEL, FakeClient, LLMResponse, OllamaClient,  # noqa: E402
                           ToolCall, check_ollama)
from agent_gym.trajectory import read_jsonl, replay, to_record, write_jsonl  # noqa: E402
from agent_gym.types import SUBMIT  # noqa: E402

SEEDS = (1, 2, 3)


def replays_same(ep) -> list[str]:
    """Round trip the episode through JSON and replay it; returns the mismatches (D26)."""
    return replay(json.loads(json.dumps(to_record(ep)))).mismatches


def reference_script(task) -> list[LLMResponse]:
    """A scripted 'perfect' model: the task's reference actions, one per turn, then submit."""
    turns = [LLMResponse(tool_calls=[ToolCall(a.tool, dict(a.arguments))])
             for a in task.reference]
    return turns + [LLMResponse(tool_calls=[ToolCall(SUBMIT, {"summary": "done"})])]


def noise_lookup(cls) -> str:
    """The env's first read only tool that takes no required arguments (D23)."""
    for name, spec in cls().tool_specs().items():
        if spec.read_only and not any(p.required for p in spec.params.values()):
            return name
    raise ValueError(f"{cls.name} has no argument free lookup for the messy control")


def messy_script(task, cls) -> list[LLMResponse]:
    """Correct outcome, poor process: one call to an unknown tool, one repeated lookup."""
    noise = [LLMResponse(tool_calls=[ToolCall("guess_id", {})]),
             LLMResponse(tool_calls=[ToolCall(noise_lookup(cls), {})])]
    return noise + reference_script(task)


def messy_expected(task, cls) -> list[str]:
    """Failure kinds the messy script must produce on this task."""
    lookup = noise_lookup(cls)
    first = task.reference[0] if task.reference else None
    if first is not None and first.tool == lookup and not first.arguments:
        return ["wrong_tool", "repeated_lookup"]
    if any(a.tool == lookup for a in task.reference):
        raise ValueError(f"{task.id}: the reference uses {lookup} but not first; "
                         "the messy control would not be predictable")
    return ["wrong_tool", "extra_step"]


# (env, task) -> (tool, id argument, look alike value): same tool, wrong object (D30).
WRONG_TARGET = {
    ("inbox", "close_by_name"): ("set_status", "ticket_id", "T-1003"),
    ("inbox", "assign_by_name"): ("assign_ticket", "agent_id", "agt_02"),
    ("calendar", "delete_by_title"): ("delete_event", "event_id", "evt_004"),
}


def wrong_target_script(task, tool: str, key: str, value: str) -> list[LLMResponse]:
    """The reference, with `key` of the first `tool` call replaced by `value`."""
    out, done = [], False
    for r in reference_script(task):
        tc = r.tool_calls[0]
        args = dict(tc.arguments)
        if not done and tc.name == tool:
            args[key], done = value, True
        out.append(LLMResponse(tool_calls=[ToolCall(tc.name, args)]))
    if not done:
        raise ValueError(f"{task.id}: reference has no {tool} call")
    return out


def eval_round_trip(only: str | None) -> list[str]:
    """Eval the references on seeds 1 and 2, write JSONL, rebuild the report; problems found."""
    import tempfile
    chosen = select_tasks(ENVIRONMENTS, only=only)
    eps = run_eval(chosen, lambda env, task: FakeClient(reference_script(task)), [1, 2])
    live = build_report(eps, ENVIRONMENTS, model="fake")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "eval.jsonl"
        write_jsonl(path, eps, model="fake")
        again = build_report(read_jsonl(path), ENVIRONMENTS)
    bad = []
    if again != live:
        bad.append("report rebuilt from JSONL differs from the live report")
    if live["passed"] != live["runs"] or any(live["failures"].values()):
        bad.append(f"eval of references: {live['passed']}/{live['runs']} passed, "
                   f"failures {live['failures']}")
    # The Markdown table (D34): one row per task plus the total, and the model named.
    md = markdown_lines(again, "eval")
    rows = [line for line in md if line.startswith("| ") and "/" in line.split("|")[1]]
    if len(rows) != len(chosen) + len(live["gap"]["pairs"]):
        bad.append(f"markdown table has {len(rows)} task and pair rows, expected "
                   f"{len(chosen)} tasks and {len(live['gap']['pairs'])} pairs")
    if not any(line.startswith("| **total** | **" + f"{live['runs']}/{live['runs']}")
               for line in md) or "Model: fake." not in "\n".join(md):
        bad.append("markdown table is missing the total row or the model name")
    return bad


def failure_table(episodes) -> list[str]:
    rows = summarize(episodes)
    short = [k.replace("_", " ") for k in KINDS]
    lines = ["task".ljust(20) + " ".join(f"{s:>15}" for s in short)]
    for task, counts in rows.items():
        lines.append(task.ljust(20) + " ".join(f"{counts[k]:>15}" for k in KINDS))
    return lines


CONTROLS = {
    "answers without acting": lambda: [LLMResponse(content="Done, the calendar is updated.")],
    "submits at once": lambda: [LLMResponse(tool_calls=[ToolCall(SUBMIT, {"summary": "done"})])],
}


def scenarios(only: str | None):
    for env_name, cls in ENVIRONMENTS.items():
        for task in cls.tasks.values():
            name = f"{env_name}/{task.id}"
            if not only or only.lower() in name.lower():
                yield name, cls, task


def run(fake: bool, model: str | None, only: str | None = None, check=check_ollama,
        record: str | None = None) -> int:
    model = model or DEFAULT_MODEL
    if not fake:
        ok, msg = check(model)
        if not ok:
            print(f"PROBLEM: {msg}")
            return 4
    chosen = list(scenarios(only))
    if not chosen:
        print(f"No task matches --only {only!r}")
        return 2
    passed = 0
    controls_ok = 0
    controls_run = 0
    episodes = []
    replayed = 0
    replay_bad = 0

    def check_replay(ep, label: str) -> None:
        nonlocal replayed, replay_bad
        replayed += 1
        bad = replays_same(ep)
        if bad:
            replay_bad += 1
            print(f"FAIL replay of {label}: {bad[0]}")

    for name, cls, task in chosen:
        client = FakeClient(reference_script(task)) if fake else OllamaClient(model=model)
        ep = run_episode(cls(), client, task.id)
        episodes.append(ep)
        ok = ep.success and not (fake and ep.failures)
        passed += ok
        errors = sum(not s.ok for s in ep.steps)
        print(f"{'PASS' if ok else 'FAIL'} {name}: reward {ep.reward:.3f}, {len(ep.steps)} steps "
              f"({errors} refused), end {ep.end_reason}")
        for p in ep.problems:
            print(f"     problem: {p}")
        for f in ep.failures:
            print(f"     failure: step {f['index']} {f['tool']}: {f['kind']}")
        check_replay(ep, name)
        if fake:
            for seed in SEEDS:
                s = run_episode(cls(), FakeClient(reference_script(task)), task.id, seed=seed)
                controls_run += 1
                seeded_ok = s.success and not s.failures
                controls_ok += seeded_ok
                check_replay(s, f"{name} seed {seed}")
                if not seeded_ok:
                    print(f"FAIL reference on seed {seed} for {name}: problems {s.problems}, "
                          f"failures {[f['kind'] for f in s.failures]}")
            for label, script in CONTROLS.items():
                c = run_episode(cls(), FakeClient(script()), task.id)
                check_replay(c, f"control '{label}' on {name}")
                controls_run += 1
                controls_ok += c.reward == 0.0
                if c.reward != 0.0:
                    print(f"FAIL control '{label}' scored {c.reward} on {name}")
            m = run_episode(cls(), FakeClient(messy_script(task, cls)), task.id)
            check_replay(m, f"messy control on {name}")
            controls_run += 1
            kinds = [f["kind"] for f in m.failures]
            messy_ok = m.success and 0.0 < m.reward < 1.0 and kinds == messy_expected(task, cls)
            controls_ok += messy_ok
            if not messy_ok:
                print(f"FAIL control 'messy but correct' on {name}: passed {m.success}, "
                      f"reward {m.reward}, failures {kinds}")
    if fake:
        for (env_name, task_id), (tool, key, value) in WRONG_TARGET.items():
            name = f"{env_name}/{task_id}"
            if only and only.lower() not in name.lower():
                continue
            cls = ENVIRONMENTS[env_name]
            w = run_episode(cls(), FakeClient(wrong_target_script(cls.tasks[task_id], tool, key,
                                                                  value)), task_id)
            check_replay(w, f"wrong target control on {name}")
            controls_run += 1
            kinds = [f["kind"] for f in w.failures]
            wt_ok = not w.passed and w.reward == 0.0 and kinds == ["wrong_target"]
            controls_ok += wt_ok
            if not wt_ok:
                print(f"FAIL control 'wrong target' on {name}: passed {w.passed}, "
                      f"reward {w.reward}, failures {kinds}")
        controls_run += 1
        problems = eval_round_trip(only)
        controls_ok += not problems
        for p in problems:
            print(f"FAIL eval round trip: {p}")
    print("\nfailure kinds per task (" + ("reference runs" if fake else model) + "):")
    for line in failure_table(episodes):
        print("  " + line)
    gap = id_name_gap(episodes, ENVIRONMENTS)
    print("\nid vs name pairs (" + ("reference runs" if fake else model) + "):")
    for line in gap_lines(gap):
        print("  " + line)
    # The scripted reference solves both variants, so a fake run must show no gap (D23).
    gap_ok = not fake or gap["gap"] in (None, 0.0)
    if not gap_ok:
        print(f"FAIL fake run shows an id vs name gap of {gap['gap']}")
    if record:
        n = write_jsonl(record, episodes, model="fake" if fake else model)
        print(f"\nrecorded {n} episodes to {record}")
    print(f"\n{passed}/{len(chosen)} tasks passed ({'fake' if fake else model})")
    print(f"{replayed - replay_bad}/{replayed} episodes replayed with the same result")
    if fake:
        print(f"{controls_ok}/{controls_run} controls behaved as expected "
              "(do nothing scores 0, messy but correct passes below 1.0 "
              "with the expected failure kinds, seeded references pass clean, "
              "wrong target controls fail as wrong_target, eval report survives JSONL)")
    return 0 if (passed == len(chosen) and controls_ok == controls_run and gap_ok
                 and not replay_bad) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fake", action="store_true", help="scripted model, no Ollama")
    ap.add_argument("--model", default=None)
    ap.add_argument("--only", default=None, help="run tasks whose name contains this text")
    ap.add_argument("--record", default=None, metavar="PATH",
                    help="append the main runs to this JSONL file")
    a = ap.parse_args(argv)
    return run(a.fake, a.model, a.only, record=a.record)


if __name__ == "__main__":
    raise SystemExit(main())
