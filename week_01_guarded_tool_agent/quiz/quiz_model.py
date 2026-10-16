"""Quiz the agent itself and check its answers.

Real model (on your Mac):  ollama pull qwen3:4b && python3 quiz/quiz_model.py
No model (daily check):     python3 quiz/quiz_model.py --fake

Each scenario checks two things: the agent used the expected tool, and the
final answer contains the expected value. Policy scenarios (day 2) also check
that a blocked tool never ran and that the agent did not loop on it.
Scenarios grow as the project grows.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guarded_agent import (  # noqa: E402
    Agent, FakeClient, LLMResponse, OllamaClient, Policy, ToolCall, ToolRegistry, default_tools,
)

POLICY_FILE = Path(__file__).resolve().parents[1] / "policy.json"
# Policy for blocked scenarios: the time tool is switched off.
NO_TIME = {"default": "deny", "tools": {"calculator": "allow", "current_time": "deny"}}

# (question, expected tool or None, expected substring in answer)
SCENARIOS = [
    ("What is 17 * 23? Use the calculator.", "calculator", "391"),
    ("Compute (1250 - 250) / 8.", "calculator", "125"),
    ("What is 2 to the power of 12?", "calculator", "4096"),
    ("What year is it right now in America/Chicago?", "current_time", "2026"),
    ("Reply with exactly the word: ready", None, "ready"),
]

# (question, policy dict, tool that must be attempted but blocked, max tool calls allowed)
BLOCKED_SCENARIOS = [
    ("What is the current time in UTC? Use the current_time tool.", NO_TIME, "current_time", 2),
]


def fake_script(question: str, tool: str | None, expected: str) -> list[LLMResponse]:
    """A scripted 'perfect' model, used to check the harness and the agent loop."""
    if tool == "calculator":
        expr = {"391": "17 * 23", "125": "(1250 - 250) / 8", "4096": "2 ** 12"}[expected]
        return [LLMResponse(tool_calls=[ToolCall("calculator", {"expression": expr})]),
                LLMResponse(content=f"The answer is {expected}.")]
    if tool == "current_time":
        return [LLMResponse(tool_calls=[ToolCall("current_time", {"tz": "America/Chicago"})]),
                LLMResponse(content=f"It is {expected}.")]
    return [LLMResponse(content=expected)]


def fake_blocked_script(tool: str) -> list[LLMResponse]:
    return [LLMResponse(tool_calls=[ToolCall(tool, {})]),
            LLMResponse(content="That tool is blocked by policy, so I cannot check the time.")]


def make_llm(fake: bool, model: str | None, script: list[LLMResponse]):
    return FakeClient(script) if fake else OllamaClient(**({"model": model} if model else {}))


def run(fake: bool, model: str | None) -> int:
    passed = 0
    total = len(SCENARIOS) + len(BLOCKED_SCENARIOS)
    policy = Policy.from_file(POLICY_FILE)
    for question, tool, expected in SCENARIOS:
        llm = make_llm(fake, model, fake_script(question, tool, expected))
        result = Agent(llm, ToolRegistry(default_tools()), policy=policy).run(question)
        used = [c.name for c in result.tool_calls]
        tool_ok = (tool is None and not used) or (tool in used)
        answer_ok = expected.lower() in result.answer.lower()
        ok = tool_ok and answer_ok
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {question}")
        if not ok:
            print(f"    tools used: {used} (expected {tool})")
            print(f"    answer: {result.answer[:200]!r} (expected to contain {expected!r})")
    for question, pol, blocked, max_calls in BLOCKED_SCENARIOS:
        llm = make_llm(fake, model, fake_blocked_script(blocked))
        result = Agent(llm, ToolRegistry(default_tools()), policy=Policy.from_dict(pol)).run(question)
        attempted = [d for d in result.decisions if d.tool == blocked]
        never_ran = all(not d.approved for d in attempted)
        no_loop = len(result.tool_calls) <= max_calls and result.stopped_reason == "final_answer"
        ok = bool(attempted) and never_ran and no_loop
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] (policy) {question}")
        if not ok:
            print(f"    attempted={len(attempted)} never_ran={never_ran} "
                  f"calls={len(result.tool_calls)} stopped={result.stopped_reason}")
    score = passed / total
    print(f"\nScore: {passed}/{total} ({score:.0%})")
    return 0 if score >= 0.8 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true", help="use the scripted fake model")
    ap.add_argument("--model", help="Ollama model name, default qwen3:4b")
    args = ap.parse_args()
    raise SystemExit(run(args.fake, args.model))
