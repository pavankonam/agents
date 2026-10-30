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

Exit codes: 0 all pass, 1 some failed, 2 bad --only, 4 Ollama not ready.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_gym.agent import run_episode  # noqa: E402
from agent_gym.envs import ENVIRONMENTS  # noqa: E402
from agent_gym.llm import (DEFAULT_MODEL, FakeClient, LLMResponse, OllamaClient,  # noqa: E402
                           ToolCall, check_ollama)
from agent_gym.types import SUBMIT  # noqa: E402


def reference_script(task) -> list[LLMResponse]:
    """A scripted 'perfect' model: the task's reference actions, one per turn, then submit."""
    turns = [LLMResponse(tool_calls=[ToolCall(a.tool, dict(a.arguments))])
             for a in task.reference]
    return turns + [LLMResponse(tool_calls=[ToolCall(SUBMIT, {"summary": "done"})])]


def messy_script(task) -> list[LLMResponse]:
    """Correct outcome, poor process: one call to an unknown tool, one repeated lookup."""
    noise = [LLMResponse(tool_calls=[ToolCall("guess_id", {})]),
             LLMResponse(tool_calls=[ToolCall("list_calendars", {})])]
    return noise + reference_script(task)


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


def run(fake: bool, model: str | None, only: str | None = None, check=check_ollama) -> int:
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
    for name, cls, task in chosen:
        client = FakeClient(reference_script(task)) if fake else OllamaClient(model=model)
        ep = run_episode(cls(), client, task.id)
        ok = ep.success
        passed += ok
        errors = sum(not s.ok for s in ep.steps)
        print(f"{'PASS' if ok else 'FAIL'} {name}: reward {ep.reward:.3f}, {len(ep.steps)} steps "
              f"({errors} refused), end {ep.end_reason}")
        for p in ep.problems:
            print(f"     problem: {p}")
        if fake:
            for label, script in CONTROLS.items():
                c = run_episode(cls(), FakeClient(script()), task.id)
                controls_run += 1
                controls_ok += c.reward == 0.0
                if c.reward != 0.0:
                    print(f"FAIL control '{label}' scored {c.reward} on {name}")
            m = run_episode(cls(), FakeClient(messy_script(task)), task.id)
            controls_run += 1
            messy_ok = m.success and 0.0 < m.reward < 1.0
            controls_ok += messy_ok
            if not messy_ok:
                print(f"FAIL control 'messy but correct' on {name}: passed {m.success}, "
                      f"reward {m.reward}")
    print(f"\n{passed}/{len(chosen)} tasks passed ({'fake' if fake else model})")
    if fake:
        print(f"{controls_ok}/{controls_run} controls behaved as expected "
              "(do nothing scores 0, messy but correct passes below 1.0)")
    return 0 if passed == len(chosen) and controls_ok == controls_run else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fake", action="store_true", help="scripted model, no Ollama")
    ap.add_argument("--model", default=None)
    ap.add_argument("--only", default=None, help="run tasks whose name contains this text")
    a = ap.parse_args(argv)
    return run(a.fake, a.model, a.only)


if __name__ == "__main__":
    raise SystemExit(main())
