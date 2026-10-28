"""Quiz the Skills Agent through Ollama and check that it loads the right skill.

    python3 -B quiz/quiz_model.py --fake          # scripted model, no Ollama needed
    python3 -B quiz/quiz_model.py                 # real model (default qwen3:4b)
    python3 -B quiz/quiz_model.py --model llama3.2 --only BHX
    python3 -B quiz/quiz_model.py --fake --budget 1000   # see what a tight budget refuses
    python3 -B quiz/quiz_model.py --only "near miss"      # only the near miss scenarios
    python3 -B quiz/quiz_model.py --json results/qwen3_4b.json   # save a report
    python3 -B quiz/quiz_model.py --table results/*.json         # Markdown results table

A scenario passes when the agent loaded exactly the expected skills (no extra
ones), read exactly the expected skill files (level 3), ran exactly the expected
skill scripts with exit code 0, and the answer contains the expected text, which
only the skill body, the referenced file or the script output knows. That last
check proves the content was used, not just fetched.

The expected text can be a tuple; then the answer must contain every part (used
by the two skill scenario). Scenarios that expect no skill include near misses:
tasks that share words with a skill description but do not need the skill. At
the end the quiz prints per skill precision and recall over all scenarios and
lints the skill descriptions (routing.py, D28 to D30).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from skills_agent import (  # noqa: E402
    LOAD_SKILL, READ_SKILL_FILE, RUN_SKILL_SCRIPT, Agent, FakeClient, LLMResponse, OllamaClient, SkillLibrary,
    ToolCall, check_ollama, context_report,
)
from skills_agent.routing import format_metrics, lint_library, routing_metrics  # noqa: E402
from skills_agent.llm import DEFAULT_MODEL  # noqa: E402
from skills_agent import cli  # noqa: E402

SKILLS_DIR = ROOT / "skills"

# (question, skills that must be loaded, files that must be read as "skill/path",
#  scripts that must run as ("skill/script", [args]), text the answer must contain;
#  a tuple means every part must be in the answer)
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
    # two skill task: both skills are needed, each answer part lives in one body
    ("What does BHX stand for, and how many km is 5 miles?",
     ["team-glossary", "unit-converter"], [], [], ("Blue Heron Expansion", "8.05")),
    # near misses: words from a skill description, but no skill is needed
    ("Convert this sentence to the passive voice: the team fixed the bug.",
     [], [], [], "was fixed"),
    ("What does the acronym NASA stand for?", [], [], [], "Aeronautics"),
    ("In one sentence, what is a git commit?", [], [], [], "snapshot"),
]

# Labels only for the report and --only; the model never sees them (D30).
NEAR_MISS = {
    "Convert this sentence to the passive voice: the team fixed the bug.",
    "What does the acronym NASA stand for?",
    "In one sentence, what is a git commit?",
}


def label(question: str) -> str:
    return f"(near miss) {question}" if question in NEAR_MISS else question


def parts(expected) -> tuple[str, ...]:
    """The expected text as a tuple of strings that must all be in the answer."""
    return (expected,) if isinstance(expected, str) else tuple(expected)


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
    return turns + [LLMResponse(content="Answer: " + "; ".join(parts(expected)))]


def script_output_contains(result, expected) -> bool:
    """True if some script_result tool message contains one of the expected parts."""
    return any(m.get("role") == "tool" and m.get("tool_name") == RUN_SKILL_SCRIPT
               and any(p in m.get("content", "") for p in parts(expected))
               for m in result.messages)


CLI_QUESTION = SCENARIOS[0]  # the BHX scenario, run once more through the CLI (D34)


def _cli(argv: list[str], client=None) -> tuple[int, dict | None]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(argv + ["--skills-dir", str(SKILLS_DIR), "--json"], client=client)
    try:
        return code, json.loads(buf.getvalue())
    except json.JSONDecodeError:
        return code, None


def cli_checks(fake: bool, model: str | None) -> list[tuple[str, bool]]:
    """The CLI must give the same answers as the library, with the documented exit codes."""
    names = SkillLibrary.discover(SKILLS_DIR).names()
    out = []
    code, data = _cli(["list"])
    out.append(("list --json shows every valid skill, exit 0",
                code == 0 and data is not None and [s["name"] for s in data["skills"]] == names))
    code, data = _cli(["validate"])
    out.append(("validate exits 1 with broken_skill as the only error",
                code == 1 and data is not None and len(data["errors"]) == 1
                and data["errors"][0].startswith("broken_skill")))
    code, data = _cli(["inspect", "ticket-checksum"])
    out.append(("inspect ticket-checksum lists its runnable script",
                code == 0 and data is not None
                and data["scripts"] == ["scripts/check_letter.py"]))
    question, skills, files, scripts, expected = CLI_QUESTION
    client = FakeClient(fake_script(skills, files, scripts, expected)) if fake else None
    code, data = _cli(["run"] + (["--model", model] if model and not fake else []) + [question],
                      client=client)
    out.append((f"run --json {question!r} loads {skills} and answers",
                code == 0 and data is not None and data["loaded_skills"] == skills
                and all(p.lower() in data["answer"].lower() for p in parts(expected))))
    return out


def kind(question: str, skills: list[str], files: list[str], scripts: list) -> str:
    """Scenario group for the results table (D35)."""
    if question in NEAR_MISS:
        return "near miss"
    if not skills:
        return "no skill"
    if len(skills) > 1:
        return "two skills"
    if scripts:
        return "script"
    if files:
        return "level 3"
    return "level 2"


KINDS = ["level 2", "level 3", "script", "two skills", "no skill", "near miss"]


def write_report(path: str | Path, report: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def results_table(reports: list[dict]) -> str:
    """One Markdown row per saved report: score per scenario kind, routing, CLI, time."""
    head = ["model", "date", "total"] + KINDS + ["exact routing", "cli", "avg s", "avg tokens"]
    lines = ["| " + " | ".join(head) + " |", "|" + " --- |" * len(head)]
    for r in reports:
        sc = r["scenarios"]
        cells = [r["model"], r["date"], f"{r['passed']}/{len(sc)}"]
        for k in KINDS:
            group = [x for x in sc if x["kind"] == k]
            cells.append(f"{sum(x['ok'] for x in group)}/{len(group)}" if group else "-")
        m = r["routing"]
        cli_ok = sum(c["ok"] for c in r["cli"])
        cells += [f"{m['exact']}/{m['runs']}", f"{cli_ok}/{len(r['cli'])}",
                  f"{sum(x['secs'] for x in sc) / len(sc):.1f}",
                  str(round(sum(x["tokens"] for x in sc) / len(sc)))]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def table(paths: list[str]) -> int:
    reports = []
    for p in paths:
        try:
            reports.append(json.loads(Path(p).read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            print(f"PROBLEM: cannot read report {p}: {exc}")
            return 2
    if not reports:
        print("No report files given")
        return 2
    print(results_table(reports))
    return 0


def run(fake: bool, model: str | None, only: str | None = None, check=check_ollama,
        budget: int | None = None, json_path: str | None = None) -> int:
    if not fake:
        ok, msg = check(model or DEFAULT_MODEL)
        if not ok:
            print(f"PROBLEM: {msg}")
            return 4
    lib = SkillLibrary.discover(SKILLS_DIR)
    scenarios = [s for s in SCENARIOS if not only or only.lower() in label(s[0]).lower()]
    if not scenarios:
        print(f"No scenario matches --only {only!r}")
        return 2
    passed = 0
    spent = []
    routes = []
    rows = []
    for question, skills, files, scripts, expected in scenarios:
        llm = (FakeClient(fake_script(skills, files, scripts, expected)) if fake
               else OllamaClient(**({"model": model} if model else {})))
        t0 = time.perf_counter()
        result = Agent(llm, lib, budget_tokens=budget).run(question)
        secs = time.perf_counter() - t0
        skills_ok = sorted(result.loaded_skills) == sorted(skills)
        files_ok = sorted(result.read_files) == sorted(files)
        want_runs = sorted(f"{t} exit=0" for t, _ in scripts)
        scripts_ok = sorted(result.ran_scripts) == want_runs and (
            not scripts or script_output_contains(result, expected))
        answer_ok = all(p.lower() in result.answer.lower() for p in parts(expected))
        routes.append((skills, result.loaded_skills))
        ok = (skills_ok and files_ok and scripts_ok and answer_ok
              and result.stopped_reason == "final_answer")
        passed += ok
        spent.append(result.context["spent"])
        rows.append({"question": question, "kind": kind(question, skills, files, scripts),
                     "ok": bool(ok), "secs": round(secs, 2), "tokens": result.context["spent"],
                     "expected_skills": skills, "loaded_skills": result.loaded_skills,
                     "read_files": result.read_files, "ran_scripts": result.ran_scripts,
                     "stopped_reason": result.stopped_reason, "answer": result.answer[:500]})
        print(f"[{'PASS' if ok else 'FAIL'}] {label(question)} ({secs:.1f}s, "
              f"~{result.context['spent']} tokens)")
        if result.context["refused"]:
            print(f"    budget refused: {'; '.join(result.context['refused'])}")
        if not ok:
            print(f"    loaded {result.loaded_skills} (expected {skills})")
            print(f"    read files {result.read_files} (expected {files})")
            print(f"    ran scripts {result.ran_scripts} (expected {want_runs})")
            print(f"    answer: {result.answer[:200]!r} (expected to contain {expected!r})")
    print("\nrouting (per skill, over these scenarios):")
    metrics = routing_metrics(routes, lib.names())
    print(format_metrics(metrics))
    issues = lint_library(lib)
    print(f"description lint: {len(issues) or 'no'} issue{'s' * (len(issues) != 1)}")
    for issue in issues:
        print(f"    {issue}")
    eager = context_report(lib)["eager"]["system_prompt"]
    print(f"context: average ~{round(sum(spent) / len(spent))} tokens per scenario, "
          f"max ~{max(spent)}; pasting every skill would start at ~{eager}"
          + (f"; budget {budget}" if budget else ""))
    print(f"{passed}/{len(scenarios)} passed "
          f"({'fake model' if fake else model or DEFAULT_MODEL})")
    checks = cli_checks(fake, model)
    for name, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] cli: {name}")
    cli_passed = sum(ok for _, ok in checks)
    print(f"cli checks: {cli_passed}/{len(checks)} passed")
    if json_path:
        write_report(json_path, {
            "model": "fake" if fake else model or DEFAULT_MODEL,
            "date": time.strftime("%Y-%m-%d"), "budget": budget, "only": only,
            "passed": passed, "scenarios": rows, "routing": metrics,
            "lint_issues": len(issues), "cli": [{"name": n, "ok": o} for n, o in checks]})
        print(f"report written to {json_path}")
    return 0 if passed == len(scenarios) and cli_passed == len(checks) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true", help="use the scripted fake model")
    ap.add_argument("--model", help="Ollama model name, default qwen3:4b")
    ap.add_argument("--only", help="run only scenarios whose question contains this text")
    ap.add_argument("--budget", type=int, help="per run context budget in estimated tokens")
    ap.add_argument("--json", dest="json_path", help="also write a JSON report to this file")
    ap.add_argument("--table", nargs="+", metavar="REPORT",
                    help="print a Markdown results table from saved reports and exit")
    a = ap.parse_args()
    if a.table:
        raise SystemExit(table(a.table))
    raise SystemExit(run(a.fake, a.model, a.only, budget=a.budget, json_path=a.json_path))
