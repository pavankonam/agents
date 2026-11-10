import io
import json

from evidence_agent.agent import run_investigation
from evidence_agent.cli import main
from evidence_agent.evaluation import (PASS, WRONG_ROOT_CAUSE, ReplayClient, evaluate,
                                       failure_kind, rejected_citations)
from evidence_agent.ledger import EvidenceLedger
from evidence_agent.llm import FakeClient
from evidence_agent.scripted import REFERENCE, control_invented_id, control_wrong_service
from evidence_agent.telemetry import CHECKOUT_LATENCY, SCENARIOS
from evidence_agent.variants import MAX_NOISE, MIN_NOISE, NOISE_MESSAGES, variant


def lines_of(s, keys):
    return sorted(s.records[k].line() for k in keys)


def test_seed_zero_is_the_scenario_unchanged():
    for s in SCENARIOS.values():
        assert variant(s, 0) is s


def test_variants_keep_the_incident_and_are_reproducible():
    for s in SCENARIOS.values():
        for seed in (1, 2, 7):
            v = variant(s, seed)
            assert v == variant(s, seed)  # same seed, same variant
            noise = [r for r in v.records if r not in s.records]
            assert MIN_NOISE <= len(noise) <= MAX_NOISE == 6
            assert len(v.records) == len(s.records) + len(noise)
            assert all(r.kind == "log" and r.data["level"] == "INFO"
                       and r.data["message"] in NOISE_MESSAGES for r in noise)
            assert all(s.window[0] <= r.ts <= s.window[1] for r in noise)
            assert [r.ts for r in v.records] == sorted(r.ts for r in v.records)
            assert lines_of(v, v.cause) == lines_of(s, s.cause)  # cause rows remapped
            assert v.root_cause_service == s.root_cause_service and v.id_seed == seed
    assert variant(CHECKOUT_LATENCY, 1).records != variant(CHECKOUT_LATENCY, 2).records


def test_seeded_ledger_ids_are_unique_and_not_in_order():
    a, b = EvidenceLedger(seed=3), EvidenceLedger(seed=3)
    rec = CHECKOUT_LATENCY.records[0]
    ids = [a.issue(k, rec, "t", 1) for k in range(50)]
    assert ids == [b.issue(k, rec, "t", 1) for k in range(50)]
    assert len(set(ids)) == 50 and all(i.startswith("ev_") and len(i) == 6 for i in ids)
    assert ids[:3] != ["ev_001", "ev_002", "ev_003"]
    assert a.issue(0, rec, "t", 9) == ids[0]  # same record keeps its id
    assert EvidenceLedger().issue(0, rec, "t", 1) == "ev_001"


def test_memorised_ids_fail_on_a_variant_but_replay_passes():
    v = variant(CHECKOUT_LATENCY, 1)
    raw = run_investigation(FakeClient(REFERENCE["checkout_latency"]()), v)
    assert not raw.passed and raw.end_reason == "no_conclusion"
    assert rejected_citations(raw) == 4  # 3 findings and the conclusion cite ids never issued
    replay = run_investigation(ReplayClient(REFERENCE["checkout_latency"](), CHECKOUT_LATENCY), v)
    assert replay.passed and replay.score == 100 and not replay.rejected_findings
    assert replay.conclusion["evidence_ids"] != ["ev_002", "ev_003", "ev_007"]


def test_replay_keeps_invented_ids_invented():
    v = variant(CHECKOUT_LATENCY, 2)
    r = run_investigation(ReplayClient(control_invented_id(), CHECKOUT_LATENCY), v)
    assert not r.passed and rejected_citations(r) >= 1


def test_failure_kinds():
    ok = run_investigation(FakeClient(REFERENCE["checkout_latency"]()), CHECKOUT_LATENCY)
    wrong = run_investigation(FakeClient(control_wrong_service()), CHECKOUT_LATENCY)
    text = run_investigation(FakeClient([]), CHECKOUT_LATENCY)
    assert (failure_kind(ok), failure_kind(wrong), failure_kind(text)) == (
        PASS, WRONG_ROOT_CAUSE, "no_conclusion")


def test_evaluate_references_over_all_scenarios_and_seeds():
    s = evaluate(lambda base, seed: ReplayClient(REFERENCE[base.name](), base),
                 list(SCENARIOS.values()), seeds=3, model="fake")
    d = s.to_dict()
    assert (d["runs_total"], d["passed"], d["pass_rate"], d["mean_score"]) == (9, 9, 1.0, 100.0)
    assert d["failure_kinds"] == {} and d["rejected_citations"] == 0
    assert [(r.scenario, r.seed) for r in s.runs][:3] == [
        ("checkout_latency", 0), ("checkout_latency", 1), ("checkout_latency", 2)]
    assert s.runs[0].noise_rows == 0 and all(r.noise_rows >= MIN_NOISE for r in s.runs[1:3])


def test_evaluate_counts_failures():
    s = evaluate(lambda base, seed: FakeClient(REFERENCE[base.name]()),
                 [CHECKOUT_LATENCY], seeds=3, model="memoriser")
    assert s.passed == 1 and s.failure_kinds() == {"no_conclusion": 2}
    assert s.total("rejected_citations") == 8
    md = s.markdown()
    assert "| checkout_latency | 3 | 1 | 33.3 | 8 | 0 | 0 |" in md
    assert "| no_conclusion | 2 |" in md


def run(argv, client=None):
    out = io.StringIO()
    return main(argv, client=client, out=out), out.getvalue()


def test_cli_eval_fake_formats_and_exit_codes(tmp_path):
    code, text = run(["eval", "--fake", "--seeds", "2"])
    assert code == 0 and text.startswith("eval fake: 6/6 passed (100%), mean score 100.0")
    code, text = run(["eval", "--fake", "--seeds", "2", "--json", "--scenario", "config_push"])
    d = json.loads(text)
    assert code == 0 and d["runs_total"] == 2 and list(d["per_scenario"]) == ["config_push"]
    code, text = run(["eval", "--fake", "--seeds", "1", "--markdown"])
    assert code == 0 and text.startswith("# Eval: fake") and "| none | 0 |" in text
    path = tmp_path / "eval.jsonl"
    run(["eval", "--fake", "--seeds", "2", "--scenario", "checkout_latency", "--record", str(path)])
    recs = [json.loads(x) for x in path.read_text().splitlines()]
    assert [(r["seed"], r["kind"], r["model"]) for r in recs] == [(0, "pass", "fake"),
                                                                 (1, "pass", "fake")]


def test_cli_eval_fail_and_min_pass_rate():
    client = FakeClient(control_wrong_service())  # one scripted client: the first run fails
    code, text = run(["eval", "--seeds", "1", "--scenario", "checkout_latency"], client)
    assert code == 1 and "wrong_root_cause 1" in text
    client = FakeClient(control_wrong_service())
    assert run(["eval", "--seeds", "1", "--scenario", "checkout_latency",
                "--min-pass-rate", "0"], client)[0] == 0


def test_cli_eval_usage_and_ollama_codes(monkeypatch):
    assert run(["eval", "--fake", "--seeds", "0"])[0] == 2
    assert run(["eval", "--fake", "--scenario", "nope"])[0] == 2
    assert run(["eval", "--fake", "--min-pass-rate", "1.5"])[0] == 2
    assert run(["eval", "--fake", "--json", "--markdown"])[0] == 2
    import evidence_agent.cli as cli
    monkeypatch.setattr(cli, "check_ollama", lambda m, h: (False, "not up"))
    assert run(["eval"])[0] == 4
