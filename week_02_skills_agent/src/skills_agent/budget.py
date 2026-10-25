"""Context budget: token estimates per disclosure level and a per run limit.

Two parts (decision.md D24 to D27):

* `context_report(library)` estimates what each level costs and compares
  progressive disclosure with the naive approach of pasting every skill
  (bodies and bundled files) into the system prompt.
* `ContextBudget` is the per run meter the agent uses. With a limit set, a
  `load_skill`, `read_skill_file` or script result that would push the run past
  the limit is replaced by a short `error: context budget ...` message.

Tokens are estimated as ceil(characters / 4). That is a rough rule for English
text with Llama and Qwen tokenizers; it is only used to compare and to limit,
never to bill, so the same estimate on both sides is what matters (D24).

Run the report:  PYTHONPATH=src python3 -m skills_agent.budget [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .skills import SkillError, SkillLibrary, list_resources, read_resource

CHARS_PER_TOKEN = 4
KINDS = ("system", "load", "read", "script", "other")

EAGER_TEMPLATE = """You are a helpful assistant. Below are the full instructions for every
skill you know, with the files bundled with each. Follow the instructions of the skill
that matches the user's task. If no skill matches, answer directly.

{skills}"""


def estimate_tokens(text: str) -> int:
    """Rough token count: ceil(chars / 4). Empty text costs 0."""
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


def tools_tokens(tools: list[dict]) -> int:
    """Estimate for the tool schemas, which Ollama sends with every request."""
    return estimate_tokens(json.dumps(tools, separators=(",", ":"))) if tools else 0


@dataclass
class SkillCost:
    name: str
    catalog: int  # level 1: this skill's entry in the catalog
    body: int  # level 2: the load_skill result
    files: dict[str, int] = field(default_factory=dict)  # level 3: per bundled text file

    @property
    def full(self) -> int:
        """Body plus every bundled file: what pasting this skill would cost."""
        return self.body + sum(self.files.values())


def _file_texts(skill) -> dict[str, str]:
    texts = {}
    for rel in list_resources(skill):
        try:
            texts[rel], _ = read_resource(skill, rel)
        except SkillError:  # binary or unreadable files are never shown to the model
            continue
    return texts


def skill_costs(library: SkillLibrary) -> list[SkillCost]:
    costs = []
    for name in library.names():
        s = library.skills[name]
        files = {rel: estimate_tokens(t) for rel, t in _file_texts(s).items()}
        costs.append(SkillCost(name, estimate_tokens(library.catalog_entry(name)),
                               estimate_tokens(s.body), files))
    return costs


def eager_prompt(library: SkillLibrary) -> str:
    """The baseline: every body and every bundled file pasted into one system prompt."""
    parts = []
    for name in library.names():
        s = library.skills[name]
        files = "".join(f'\n<skill_file path="{rel}">\n{text}\n</skill_file>'
                        for rel, text in _file_texts(s).items())
        parts.append(f'<skill name="{name}">\n{s.body}{files}\n</skill>')
    return EAGER_TEMPLATE.format(skills="\n".join(parts))


def context_report(library: SkillLibrary) -> dict:
    """Compare progressive disclosure with pasting every skill (D25)."""
    from .agent import Agent  # local import: agent.py imports this module
    from .llm import FakeClient

    agent = Agent(FakeClient([]), library)
    prompt = estimate_tokens(agent.system_prompt())
    tools = tools_tokens(agent.tools())
    costs = skill_costs(library)
    base = prompt + tools
    eager = estimate_tokens(eager_prompt(library))
    all_loaded = base + sum(c.full for c in costs)
    one_skill = (base + round(sum(c.full for c in costs) / len(costs))) if costs else base
    projection = []
    if costs:  # same average skill, more of them: where progressive disclosure wins (D25)
        avg_cat = sum(c.catalog for c in costs) / len(costs)
        avg_full = sum(c.full for c in costs) / len(costs)
        fixed_prog = base - sum(c.catalog for c in costs)
        fixed_eager = eager - sum(c.full for c in costs)
        for n in (5, 20, 50, 100):
            prog = round(fixed_prog + n * avg_cat + avg_full)
            projection.append({"skills": n, "progressive_one_skill": prog,
                               "eager": round(fixed_eager + n * avg_full)})
    return {
        "chars_per_token": CHARS_PER_TOKEN,
        "projection": projection,
        "skills": [{"name": c.name, "catalog": c.catalog, "body": c.body,
                    "files": c.files, "full": c.full} for c in costs],
        "progressive": {"system_prompt": prompt, "tools": tools, "base": base,
                        "one_skill_avg": one_skill, "all_loaded": all_loaded},
        "eager": {"system_prompt": eager},
        "base_vs_eager_pct": round(100 * (1 - base / eager), 1) if eager else 0.0,
        "one_skill_vs_eager_pct": round(100 * (1 - one_skill / eager), 1) if eager else 0.0,
    }


def format_report(r: dict) -> str:
    lines = [f"Context cost in estimated tokens (1 token = {r['chars_per_token']} chars)", "",
             f"{'skill':<20}{'L1 catalog':>11}{'L2 body':>9}{'L3 files':>10}{'pasted':>8}"]
    for s in r["skills"]:
        lines.append(f"{s['name']:<20}{s['catalog']:>11}{s['body']:>9}"
                     f"{sum(s['files'].values()):>10}{s['full']:>8}")
    p, e = r["progressive"], r["eager"]
    lines += ["",
              f"progressive, before any load: {p['base']} "
              f"(prompt {p['system_prompt']} + tool schemas {p['tools']})",
              f"progressive, one average skill used: {p['one_skill_avg']}",
              f"progressive, every skill and file loaded: {p['all_loaded']}",
              f"paste every skill into the prompt: {e['system_prompt']}",
              f"saving before any load: {r['base_vs_eager_pct']}%, "
              f"with one skill used: {r['one_skill_vs_eager_pct']}% "
              "(negative means progressive costs more)"]
    if r["projection"]:
        lines += ["", "projection with more skills of the same average size:",
                  f"{'skills':>8}{'progressive, one used':>24}{'pasted':>9}"]
        lines += [f"{x['skills']:>8}{x['progressive_one_skill']:>24}{x['eager']:>9}"
                  for x in r["projection"]]
    return "\n".join(lines)


class ContextBudget:
    """Per run token meter. `limit=None` only measures and never refuses."""

    def __init__(self, limit: int | None = None):
        if limit is not None and limit <= 0:
            raise ValueError("budget limit must be a positive number of tokens")
        self.limit = limit
        self.used = {k: 0 for k in KINDS}
        self.refused: list[str] = []

    @property
    def spent(self) -> int:
        return sum(self.used.values())

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(self.limit - self.spent, 0)

    def fits(self, tokens: int) -> bool:
        return self.limit is None or self.spent + tokens <= self.limit

    def charge(self, kind: str, tokens: int) -> None:
        if kind not in self.used:
            raise ValueError(f"unknown budget kind {kind!r}")
        self.used[kind] += tokens

    def summary(self) -> dict:
        return {"limit": self.limit, "spent": self.spent, **self.used,
                "refused": list(self.refused)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m skills_agent.budget",
                                 description="Context cost report for a skills folder.")
    ap.add_argument("--skills-dir", default=str(Path(__file__).resolve().parents[2] / "skills"))
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    a = ap.parse_args(argv)
    lib = SkillLibrary.discover(a.skills_dir)
    for problem in lib.rejected:
        print(f"skipped skill: {problem}", file=sys.stderr)
    r = context_report(lib)
    print(json.dumps(r, indent=2) if a.json else format_report(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
