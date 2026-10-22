"""Quiz the Skills Agent through Ollama and check that it loads the right skill.

    python3 -B quiz/quiz_model.py --fake          # scripted model, no Ollama needed
    python3 -B quiz/quiz_model.py                 # real model (default qwen3:4b)
    python3 -B quiz/quiz_model.py --model llama3.2 --only BHX

A scenario passes when the agent loaded exactly the expected skills (no extra
ones) and the answer contains the expected text, which only the skill body
knows. That second check proves the body was used, not just fetched.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from skills_agent import (  # noqa: E402
    LOAD_SKILL, Agent, FakeClient, LLMResponse, OllamaClient, SkillLibrary, ToolCall, check_ollama,
)
from skills_agent.llm import DEFAULT_MODEL  # noqa: E402

SKILLS_DIR = ROOT / "skills"

# (question, skills that must be loaded, text the answer must contain)
SCENARIOS = [
    ("What does BHX stand for on our team?", ["team-glossary"], "Blue Heron Expansion"),
    ("Someone mentioned ORCA in a meeting. What is it?", ["team-glossary"], "Change Approval"),
    ("Convert 26.2 miles to km.", ["unit-converter"], "42.16"),
    ("Convert 212 Fahrenheit to Celsius.", ["unit-converter"], "100.00"),
    ("Write a commit message for: fixed a crash when the config file is empty.",
     ["commit-message"], "fix"),
    ("Reply with exactly the word: ready", [], "ready"),
]


def fake_script(skills: list[str], expected: str) -> list[LLMResponse]:
    """A scripted 'perfect' model, used to check the harness and the agent loop."""
    turns = [LLMResponse(tool_calls=[ToolCall(LOAD_SKILL, {"name": s})]) for s in skills]
    return turns + [LLMResponse(content=f"Answer: {expected}")]


def run(fake: bool, model: str | None, only: str | None = None, check=check_ollama) -> int:
    if not fake:
        ok, msg = check(model or DEFAULT_MODEL)
        if not ok:
            print(f"PROBLEM: {msg}")
            return 4
    lib = SkillLibrary.discover(SKILLS_DIR)
    scenarios = [s for s in SCENARIOS if not only or only.lower() in s[0].lower()]
    if not scenarios:
        print(f"No scenario matches --only {only!r}")
        return 2
    passed = 0
    for question, skills, expected in scenarios:
        llm = (FakeClient(fake_script(skills, expected)) if fake
               else OllamaClient(**({"model": model} if model else {})))
        t0 = time.perf_counter()
        result = Agent(llm, lib).run(question)
        secs = time.perf_counter() - t0
        skills_ok = sorted(result.loaded_skills) == sorted(skills)
        answer_ok = expected.lower() in result.answer.lower()
        ok = skills_ok and answer_ok and result.stopped_reason == "final_answer"
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {question} ({secs:.1f}s)")
        if not ok:
            print(f"    loaded {result.loaded_skills} (expected {skills})")
            print(f"    answer: {result.answer[:200]!r} (expected to contain {expected!r})")
    print(f"\n{passed}/{len(scenarios)} passed "
          f"({'fake model' if fake else model or DEFAULT_MODEL})")
    return 0 if passed == len(scenarios) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true", help="use the scripted fake model")
    ap.add_argument("--model", help="Ollama model name, default qwen3:4b")
    ap.add_argument("--only", help="run only scenarios whose question contains this text")
    a = ap.parse_args()
    raise SystemExit(run(a.fake, a.model, a.only))
