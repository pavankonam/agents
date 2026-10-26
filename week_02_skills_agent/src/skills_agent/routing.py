"""Routing quality: a description linter and per skill precision / recall.

The model picks a skill from its name and description only (level 1), so the
description is the whole routing signal. This module checks descriptions for
the problems that make a small model pick wrong (D28), and scores routing runs
per skill (D29).

    PYTHONPATH=src python3 -m skills_agent.routing          # lint the shipped skills
    PYTHONPATH=src python3 -m skills_agent.routing --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .skills import SkillLibrary

MIN_WORDS = 12
OVERLAP_MAX = 0.35  # Jaccard of content words; above this two skills compete
TRIGGER_RE = re.compile(
    r"\b(use (it |this )?(when|whenever|if|for|to)|when (the|a) user|whenever)\b", re.I)
FIRST_PERSON_RE = re.compile(r"\b(i|i'm|i'll|me|my|we|our)\b", re.I)
VAGUE = ("helps with", "various", "stuff", "things", "misc", "anything", "everything",
         "general purpose", "and more", "etc")
STOPWORDS = set("""a an and are as at be by for from how in into is it its of on or that the
their them this to use used user users when whenever with you your asks ask says
does do what which who will can about not""".split())


@dataclass
class LintIssue:
    skill: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.skill}: {self.code} {self.message}"


def content_words(text: str) -> set[str]:
    """Lowercase words of 3+ chars that are not stopwords; digits and hyphens kept."""
    return {w for w in re.findall(r"[a-z0-9][a-z0-9-]+", text.lower())
            if len(w) >= 3 and w not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def lint_description(name: str, description: str) -> list[LintIssue]:
    """Issues in one description, independent of the other skills."""
    issues: list[LintIssue] = []
    words = description.split()
    if len(words) < MIN_WORDS:
        issues.append(LintIssue(name, "R1-short",
                                f"only {len(words)} words; say what it does and when to use it "
                                f"(at least {MIN_WORDS})"))
    if not TRIGGER_RE.search(description):
        issues.append(LintIssue(name, "R2-no-trigger",
                                "no 'Use when ...' clause, so the model cannot tell when to load it"))
    low = description.lower()
    vague = [v for v in VAGUE if re.search(rf"\b{re.escape(v)}\b", low)]
    if vague:
        issues.append(LintIssue(name, "R3-vague", "vague wording: " + ", ".join(vague)))
    if FIRST_PERSON_RE.search(description):
        issues.append(LintIssue(name, "R4-first-person",
                                "write in the third person ('Converts ...', not 'I convert ...')"))
    return issues


def lint_library(library: SkillLibrary, overlap_max: float = OVERLAP_MAX) -> list[LintIssue]:
    """All issues for every valid skill, plus pairs whose descriptions overlap."""
    issues: list[LintIssue] = []
    names = library.names()
    for n in names:
        issues += lint_description(n, library.get(n).description)
    words = {n: content_words(library.get(n).description) for n in names}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            score = jaccard(words[a], words[b])
            if score > overlap_max:
                shared = ", ".join(sorted(words[a] & words[b])[:8])
                issues.append(LintIssue(a, "R5-overlap",
                                        f"description overlaps {b!r} ({score:.2f} > "
                                        f"{overlap_max}): {shared}"))
    return issues


def max_overlap(library: SkillLibrary) -> tuple[float, str, str]:
    """Highest pairwise Jaccard score and the pair, for the report."""
    names = library.names()
    words = {n: content_words(library.get(n).description) for n in names}
    best = (0.0, "", "")
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            s = jaccard(words[a], words[b])
            if s > best[0]:
                best = (s, a, b)
    return best


def routing_metrics(records: list[tuple[list[str], list[str]]],
                    skills: list[str] | None = None) -> dict:
    """Score routing runs. Each record is (expected skills, loaded skills).

    Per skill: tp (expected and loaded), fp (loaded, not expected), fn (expected,
    not loaded), precision tp/(tp+fp) and recall tp/(tp+fn), None when undefined.
    Totals: exact (runs whose loaded set equals the expected set), abstain
    (runs that expected no skill and loaded none) and micro precision / recall.
    """
    names = set(skills or [])
    for want, got in records:
        names |= set(want) | set(got)
    per = {n: {"tp": 0, "fp": 0, "fn": 0} for n in sorted(names)}
    exact = abstain_ok = abstain_n = 0
    for want, got in records:
        w, g = set(want), set(got)
        exact += w == g
        if not w:
            abstain_n += 1
            abstain_ok += not g
        for n in w & g:
            per[n]["tp"] += 1
        for n in g - w:
            per[n]["fp"] += 1
        for n in w - g:
            per[n]["fn"] += 1

    def ratio(a: int, b: int):
        return round(a / b, 3) if b else None

    for row in per.values():
        row["precision"] = ratio(row["tp"], row["tp"] + row["fp"])
        row["recall"] = ratio(row["tp"], row["tp"] + row["fn"])
    tp = sum(r["tp"] for r in per.values())
    fp = sum(r["fp"] for r in per.values())
    fn = sum(r["fn"] for r in per.values())
    return {"per_skill": per, "runs": len(records), "exact": exact,
            "abstain": {"correct": abstain_ok, "of": abstain_n},
            "micro": {"precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn)}}


def format_metrics(m: dict) -> str:
    def f(x):
        return "n/a" if x is None else f"{x:.2f}"

    width = max([5] + [len(n) for n in m["per_skill"]])
    lines = [f"{'skill'.ljust(width)}  tp  fp  fn  precision  recall"]
    for n, r in m["per_skill"].items():
        lines.append(f"{n.ljust(width)}  {r['tp']:>2}  {r['fp']:>2}  {r['fn']:>2}  "
                     f"{f(r['precision']):>9}  {f(r['recall']):>6}")
    lines.append(f"exact routing {m['exact']}/{m['runs']}, no-skill runs answered without "
                 f"a skill {m['abstain']['correct']}/{m['abstain']['of']}, micro precision "
                 f"{f(m['micro']['precision'])}, recall {f(m['micro']['recall'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lint skill descriptions for routing problems.")
    ap.add_argument("--skills-dir", default=str(Path(__file__).resolve().parents[2] / "skills"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    lib = SkillLibrary.discover(a.skills_dir)
    issues = lint_library(lib)
    score, x, y = max_overlap(lib)
    if a.json:
        print(json.dumps({"skills": lib.names(), "issues": [vars(i) for i in issues],
                          "max_overlap": {"score": round(score, 3), "pair": [x, y]}}, indent=2))
    else:
        for i in issues:
            print(i)
        print(f"{len(lib.names())} skills, {len(issues)} description issues; highest overlap "
              f"{score:.2f} ({x} / {y}), limit {OVERLAP_MAX}")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
