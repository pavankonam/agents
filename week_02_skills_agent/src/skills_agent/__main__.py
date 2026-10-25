"""Minimal entry point: python -m skills_agent [--budget N] "task". A full CLI is day 6."""

import sys
from pathlib import Path

from . import Agent, OllamaClient, SkillLibrary

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


def main(argv: list[str]) -> int:
    budget = None
    if argv[:1] == ["--budget"]:
        if len(argv) < 2 or not argv[1].isdigit() or int(argv[1]) <= 0:
            print("--budget needs a positive number of tokens", file=sys.stderr)
            return 2
        budget, argv = int(argv[1]), argv[2:]
    if not argv:
        print('usage: python -m skills_agent [--budget N] "task"')
        return 2
    lib = SkillLibrary.discover(SKILLS_DIR)
    for problem in lib.rejected:
        print(f"skipped skill: {problem}", file=sys.stderr)
    try:
        result = Agent(OllamaClient(), lib, budget_tokens=budget).run(" ".join(argv))
    except ConnectionError as exc:
        print(exc, file=sys.stderr)
        return 4
    print(f"[skills loaded: {', '.join(result.loaded_skills) or 'none'}]"
          + (f" [files read: {', '.join(result.read_files)}]" if result.read_files else "")
          + (f" [scripts run: {', '.join(result.ran_scripts)}]" if result.ran_scripts else "")
          + f" [context: ~{result.context['spent']} tokens"
          + (f" of {budget}" if budget else "") + "]")
    print(result.answer)
    return 0 if result.stopped_reason == "final_answer" else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
