import io
import json
from dataclasses import asdict

from evidence_agent.agent import report_json, run_investigation
from evidence_agent.cli import main
from evidence_agent.evaluation import (EvalRun, ReplayClient, comparison_markdown, evaluate,
                                       summaries_from_records)
from evidence_agent.llm import FakeClient
from evidence_agent.scripted import REFERENCE, control_invented_id, control_wrong_service
from evidence_agent.telemetry import CHECKOUT_LATENCY, SCENARIOS


def run(argv):
    out = io.StringIO()
    return main(argv, out=out), out.getvalue()


def recorded_eval(tmp_path, name="eval.jsonl", seeds=2):
    path = tmp_path / name
    assert run(["eval", "--fake", "--seeds", str(seeds), "--record", str(path)])[0] == 0
    return path


def test_runs_rebuilt_from_records_match_the_live_eval(tmp_path):
    live = []
    evaluate(lambda b, s: ReplayClient(REFERENCE[b.name](), b), list(SCENARIOS.values()), 2,
             model="fake", on_run=lambda rep, r: live.append((rep, r)))
    for rep, r in live:
        d = json.loads(report_json(rep, model="fake"))
        d["seed"], d["kind"] = r.seed, r.kind
        assert asdict(EvalRun.from_record(d)) == asdict(r)  # noise recomputed from the seed


def test_failures_and_rejected_citations_survive_the_round_trip():
    for factory, kind, rejected in ((control_wrong_service, "wrong_root_cause", 0),
                                    (control_invented_id, "no_conclusion", 1)):
        rep = run_investigation(FakeClient(factory()), CHECKOUT_LATENCY)
        d = json.loads(report_json(rep, model="m"))  # no seed, no kind: run --record shape
        r = EvalRun.from_record(d)
        assert (r.seed, r.kind, r.passed, r.noise_rows) == (0, kind, False, 0)
        assert r.rejected_citations == rejected


def test_report_groups_by_model_and_builds_a_comparison_table(tmp_path):
    path = recorded_eval(tmp_path)
    other = tmp_path / "small.jsonl"
    rep = run_investigation(FakeClient(control_wrong_service()), CHECKOUT_LATENCY)
    other.write_text(report_json(rep, model="tiny:1b") + "\n")
    records = [json.loads(x) for p in (path, other) for x in p.read_text().splitlines()]
    sums = summaries_from_records(records)
    assert [(s.model, len(s.runs), s.passed, s.seeds) for s in sums] == [("fake", 6, 6, 2),
                                                                        ("tiny:1b", 1, 0, 1)]
    md = comparison_markdown(sums)
    assert "| fake | 6 | 2 | 6 | 100% | 100.0 | 0 | 0 | 0 | none |" in md
    assert "| tiny:1b | 1 | 1 | 0 | 0% | 30.0 | 0 | 0 | 0 | wrong_root_cause 1 |" in md
    assert md.count("## ") == 2 and "# Eval:" not in md


def test_cli_report_formats_and_exit_codes(tmp_path):
    path = recorded_eval(tmp_path)
    code, text = run(["report", str(path)])
    assert code == 0 and text.startswith("eval fake: 6/6 passed (100%)")
    code, text = run(["report", str(path), "--json"])
    assert code == 0 and [d["model"] for d in json.loads(text)] == ["fake"]
    code, text = run(["report", str(path), "--markdown"])
    assert code == 0 and text.startswith("# Results\n")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n")
    assert run(["report", str(empty)])[0] == 3
    assert run(["report", str(tmp_path / "missing.jsonl")])[0] == 2
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"x": 1}\n')
    assert run(["report", str(bad)])[0] == 2
    bad.write_text("not json\n")
    assert run(["report", str(bad)])[0] == 2
    assert run(["report", str(path), "--json", "--markdown"])[0] == 2


def test_committed_results_match_a_fresh_fake_eval(tmp_path):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "results"
    path = recorded_eval(tmp_path, seeds=3)
    fresh = run(["report", str(path), "--markdown"])[1]
    assert run(["report", str(root / "fake_eval.jsonl"), "--markdown"])[1] == fresh
