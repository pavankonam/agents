"""Quiz the agent through Ollama: investigate every scenario and check the verdict.

    python3 quiz/quiz_model.py --fake               # scripted runs, no Ollama
    python3 quiz/quiz_model.py [--model M] [--record PATH]

Pass means the investigation concluded with the scenario's true root cause
service and every citation in the conclusion was an evidence id that a tool
returned in this run (D4, D8). The model's own text never decides it.

Every run also gets a rubric score out of 100 (grading.py, D19 to D21) and
the script prints the score per scenario and the mean.

In --fake mode the scripted reference of every scenario must score 100 and pass with no rejected finding and
every finding's check supported, and six controls must end exactly as CONTROLS
in scripted.py says, including the support status of each finding: a text only
answer and a conclusion that cites an invented id both fail with no_conclusion,
a rejected finding followed by the reference still passes with one rejected
finding, a conclusion that blames the red herring service fails, and a finding
whose real cited rows contradict it or say nothing about it is rejected as
contradicted or unsupported (D10, D17). Three controls run on the day 3
scenarios: blaming the worker CPU spike on config_push, blaming the innocent
first deploy on dependency_outage, and naming the right service while citing
no row that shows the cause. Every control must also get the rubric score
CONTROL_SCORES declares (D22).

Live runs print the claim support counts per scenario (D13).

--record PATH appends one JSON report per scenario (live or fake), which is how
the first real baseline gets into results/ (D11).

Exit codes: 0 all pass, 1 some failed, 4 Ollama not ready.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evidence_agent.agent import report_json, report_lines, run_investigation  # noqa: E402
from evidence_agent.llm import DEFAULT_MODEL, FakeClient, OllamaClient, check_ollama  # noqa: E402
from evidence_agent.scripted import CONTROL_SCORES, CONTROLS, REFERENCE, control_scenario  # noqa: E402
from evidence_agent.telemetry import SCENARIOS  # noqa: E402


def check_main(report) -> list[str]:
    """Problems with a main run. Citations are already checked by the investigation, so it must pass."""
    problems = []
    if not report.passed:
        problems.append(f"did not pass (end {report.end_reason}, "
                        f"root cause correct {report.root_cause_correct})")
    return problems


def run_controls(out) -> int:
    failures = 0
    for name, (factory, must_pass, end, rejected, support) in CONTROLS.items():
        scenario = SCENARIOS[control_scenario(name)]
        r = run_investigation(FakeClient(factory()), scenario)
        got_support = tuple(f.support for f in r.findings)
        got = (r.passed, r.end_reason, len(r.rejected_findings), got_support, r.score)
        want_score = CONTROL_SCORES[name]
        ok = got == (must_pass, end, rejected, support, want_score)
        failures += not ok
        print(f"control {name} ({scenario.name}): {'OK' if ok else 'WRONG'} passed={r.passed} "
              f"end={r.end_reason} rejected={len(r.rejected_findings)} "
              f"support={','.join(got_support) or '-'} score={r.score} "
              f"(want {must_pass}, {end}, {rejected}, {','.join(support) or '-'}, "
              f"{want_score})", file=out)
    return failures


def main(argv: list[str] | None = None, out=None) -> int:
    out = out or sys.stdout
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--record", metavar="PATH")
    args = ap.parse_args(argv)
    if not args.fake:
        ok, msg = check_ollama(args.model)
        if not ok:
            print(msg, file=out)
            return 4
    model = "fake" if args.fake else args.model
    failed = 0
    scores: dict[str, int] = {}
    for name, scenario in SCENARIOS.items():
        client = FakeClient(REFERENCE[name]()) if args.fake else OllamaClient(model=args.model)
        report = run_investigation(client, scenario)
        for line in report_lines(report):
            print(line, file=out)
        problems = check_main(report)
        if args.fake and report.rejected_findings:
            problems.append("reference run has rejected findings")
        if args.fake and any(f.support != "supported" for f in report.findings):
            problems.append("reference run has a finding whose check is not supported")
        if args.fake and report.score != 100:
            problems.append(f"reference run scored {report.score}, not 100")
        scores[name] = report.score
        for p in problems:
            print(f"  QUIZ FAIL: {p}", file=out)
        failed += bool(problems)
        if args.record:
            with open(args.record, "a", encoding="utf-8") as fh:
                fh.write(report_json(report, model=model) + "\n")
    print("scores: " + ", ".join(f"{n} {v}" for n, v in scores.items()) +
          f" (mean {sum(scores.values()) / len(scores):.0f})", file=out)
    if args.fake:
        failed += run_controls(out)
    total = len(SCENARIOS) + (len(CONTROLS) if args.fake else 0)
    print(f"quiz_model ({model}): {total - failed}/{total} OK", file=out)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
