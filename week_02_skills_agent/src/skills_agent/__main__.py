"""Minimal day 1 entry point: python -m skills_agent "task". A full CLI is day 6."""

import sys
from pathlib import Path

from . import Agent, OllamaClient, SkillLibrary

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


def main(argv: list[str]) -> int:
    if not argv:
        print('usage: python -m skills_agent "task"')
        return 2
    lib = SkillLibrary.discover(SKILLS_DIR)
    for problem in lib.rejected:
        print(f"skipped skill: {problem}", file=sys.stderr)
    try:
        result = Agent(OllamaClient(), lib).run(" ".join(argv))
    except ConnectionError as exc:
        print(exc, file=sys.stderr)
        return 4
    print(f"[skills loaded: {', '.join(result.loaded_skills) or 'none'}]")
    print(result.answer)
    return 0 if result.stopped_reason == "final_answer" else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
