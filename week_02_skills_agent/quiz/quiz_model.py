"""Quiz the Skills Agent through Ollama and check that it loads the right skill.

    python3 -B quiz/quiz_model.py --fake          # scripted model, no Ollama needed
    python3 -B quiz/quiz_model.py                 # real model (default qwen3:4b)
    python3 -B quiz/quiz_model.py --model llama3.2 --only BHX

A scenario passes when the agent loaded exactly the expected skills (no extra
ones), read exactly the expected skill files (level 3), ran exactly the expected
skill scripts with exit code 0, and the answer contains the expected text, which
only the skill body, the referenced file or the script output knows. That last
check proves the content was used, not just fetched.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from skills_agent import (  # noqa: E402
    LOAD_SKILL, READ_SKILL_FILE, RUN_SKILL_SCRIPT, Agent, FakeClient, LLMResponse, OllamaClient, SkillLibrary,
    ToolCall, check_ollama,
)
from skills_agent.llm import DEFAULT_MODEL  # noqa: E402

SKILLS_DIR = ROOT / "skills"

# (question, skills that must be loaded, files that must be read as "skill/path",
#  scripts that must run as ("skill/script", [args]), text the answer must contain)
SCENARIOS = [
    ("What does BHX stand for on our team?", ["team-glossary"], [], [], "Blue Heron Expansion"),
    ("Someone mentioned ORCA in a meeting. What is it?", ["team-glossary"], [], [],
     "Change Approval"),
    ("Convert 26.2 miles to km.", ["unit-converter"], [], [], "42.16"),
    ("Convert 212 Fahrenheit to Celsius.", ["unit-converter"], [], [], "100.00"),
    ("Write a commit message for: fixed a crash when the config file is empty.",
     ["commit-message"], [], [], "fix"),
    ("Checkout has been down for 40% of users for ten minutes. How severe is this incident "
     "and what colour code do we use?", ["incident-severity"],
     ["incident-severity/references/severity-matrix.md"], [], "Crimson"),
    ("What is the full ticket ID, with its check letter, for ticket HX-40217?",
     ["ticket-checksum"], [], [("ticket-checksum/scripts/check_letter.py", ["HX-40217"])],
     "HX-40217-C"),
    ("Reply with exactly the word: ready", [], [], [], "ready"),
]


def fake_script(skills: list[str], files: list[str], scripts: list[tuple[str, list[str]]],
                expected: str) -> list[LLMResponse]:
    """A scripted 'perfect' model, used to check the harness and the agent loop.

    The fake model does not know the answer of a script scenario in advance in
    any special way: the scripts really run, and the quiz checks their exit code.
    """
    turns = [LLMResponse(tool_calls=[ToolCall(LOAD_SKILL, {"name": s})]) for s in skills]
    for f in files:
        skill, _, path = f.partition("/")
        turns.append(LLMResponse(tool_calls=[ToolCall(READ_SKILL_FILE,
                                                      {"skill": skill, "path": path})]))
    for target, args in scripts:
        skill, _, path = target.partition("/")
        turns.append(LLMResponse(tool_calls=[ToolCall(
            RUN_SKILL_SCRIPT, {"skill": skill, "script": path, "args": list(args)})]))
    return turns + [LLMResponse(content=f"Answer: {expected}")]


def script_output_contains(result, expected: str) -> bool:
    """True if some script_result tool message contains the expected text."""
    return any(m.get("role") == "tool" and m.get("tool_name") == RUN_SKILL_SCRIPT
               and expected in m.get("content", "") for m in result.messages)


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
    for question, skills, files, scripts, expected in scenarios:
        llm = (FakeClient(fake_script(skills, files, scripts, expected)) if fake
               else OllamaClient(**({"model": model} if model else {})))
        t0 = time.perf_counter()
        result = Agent(llm, lib).run(question)
        secs = time.perf_counter() - t0
        skills_ok = sorted(result.loaded_skills) == sorted(skills)
        files_ok = sorted(result.read_files) == sorted(files)
        want_runs = sorted(f"{t} exit=0" for t, _ in scripts)
        scripts_ok = sorted(result.ran_scripts) == want_runs and (
            not scripts or script_output_contains(result, expected))
        answer_ok = expected.lower() in result.answer.lower()
        ok = (skills_ok and files_ok and scripts_ok and answer_ok
              and result.stopped_reason == "final_answer")
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {question} ({secs:.1f}s)")
        if not ok:
            print(f"    loaded {result.loaded_skills} (expected {skills})")
            print(f"    read files {result.read_files} (expected {files})")
            print(f"    ran scripts {result.ran_scripts} (expected {want_runs})")
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
