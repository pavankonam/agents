"""Quiz the agent itself and check its answers.

Real model (on your Mac):  ollama pull qwen3:4b && python3 quiz/quiz_model.py
No model (daily check):     python3 quiz/quiz_model.py --fake

Each scenario checks two things: the agent used the expected tool, and the
final answer contains the expected value. Scenarios grow as the project grows.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guarded_agent import (  # noqa: E402
    Agent, FakeClient, LLMResponse, OllamaClient, ToolCall, ToolRegistry, default_tools,
)

# (question, expected tool or None, expected substring in answer)
SCENARIOS = [
    ("What is 17 * 23? Use the calculator.", "calculator", "391"),
    ("Compute (1250 - 250) / 8.", "calculator", "125"),
    ("What is 2 to the power of 12?", "calculator", "4096"),
    ("What year is it right now in America/Chicago?", "current_time", "2026"),
    ("Reply with exactly the word: ready", None, "ready"),
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


def run(fake: bool, model: str | None) -> int:
    passed = 0
    for question, tool, expected in SCENARIOS:
        llm = FakeClient(fake_script(question, tool, expected)) if fake else OllamaClient(
            **({"model": model} if model else {}))
        result = Agent(llm, ToolRegistry(default_tools())).run(question)
        used = [c.name for c in result.tool_calls]
        tool_ok = (tool is None and not used) or (tool in used)
        answer_ok = expected.lower() in result.answer.lower()
        ok = tool_ok and answer_ok
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {question}")
        if not ok:
            print(f"    tools used: {used} (expected {tool})")
            print(f"    answer: {result.answer[:200]!r} (expected to contain {expected!r})")
    score = passed / len(SCENARIOS)
    print(f"\nScore: {passed}/{len(SCENARIOS)} ({score:.0%})")
    return 0 if score >= 0.8 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true", help="use the scripted fake model")
    ap.add_argument("--model", help="Ollama model name, default qwen3:4b")
    args = ap.parse_args()
    raise SystemExit(run(args.fake, args.model))
