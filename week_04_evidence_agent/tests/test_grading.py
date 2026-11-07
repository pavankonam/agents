import json

from evidence_agent.agent import report_json, report_lines, run_investigation
from evidence_agent.grading import WEIGHTS, efficiency_points, grade, score_line
from evidence_agent.investigation import Investigation
from evidence_agent.ledger import EvidenceLedger
from evidence_agent.llm import FakeClient
from evidence_agent.scripted import (CONTROL_SCORES, CONTROLS, REFERENCE, control_scenario,
                                     reference_checkout)
from evidence_agent.telemetry import CHECKOUT_LATENCY, SCENARIOS


def test_weights_sum_to_100():
    assert sum(WEIGHTS.values()) == 100


def test_every_reference_scores_100_in_its_reference_steps():
    for name, factory in REFERENCE.items():
        r = run_investigation(FakeClient(factory()), SCENARIOS[name])
        assert r.passed and r.score == 100, name
        assert len(r.steps) == SCENARIOS[name].reference_steps, name
        assert all(c["points"] == c["max"] for c in r.grade["criteria"].values()), name


def test_every_control_scores_as_declared():
    assert set(CONTROL_SCORES) == set(CONTROLS)
    for name, (factory, *_rest) in CONTROLS.items():
        r = run_investigation(FakeClient(factory()), SCENARIOS[control_scenario(name)])
        assert r.score == CONTROL_SCORES[name], name


def test_no_conclusion_scores_zero_on_every_criterion():
    g = grade(CHECKOUT_LATENCY, EvidenceLedger(), None, [], 3)
    assert g["score"] == 0
    assert all(c["points"] == 0 and c["detail"] == "no conclusion" for c in g["criteria"].values())


def test_right_service_without_cause_rows_loses_cause_evidence():
    inv = Investigation(CHECKOUT_LATENCY)
    inv.call("get_metric", {"service": "checkout", "metric": "p95_latency_ms"})  # ev_001..ev_004
    inv.call("conclude", {"root_cause_service": "payments", "summary": "s",
                          "evidence_ids": ["ev_003"]})
    r = inv.report()
    assert r.passed and r.score == 70
    c = r.grade["criteria"]["cause_evidence"]
    assert c["points"] == 0 and c["detail"] == "conclusion cites no row that shows the cause"


def test_cause_rows_found_through_the_ledger_key():
    inv = Investigation(CHECKOUT_LATENCY)
    inv.call("list_deploys", {})  # ev_001 search (not cause), ev_002 payments deploy (cause)
    assert inv.ledger.get("ev_002").key in CHECKOUT_LATENCY.cause
    assert inv.ledger.get("ev_001").key not in CHECKOUT_LATENCY.cause


def test_efficiency_slack_and_penalty():
    assert efficiency_points(9, 7) == 10      # within reference + 2
    assert efficiency_points(10, 7) == 8      # one step over: 2 off
    assert efficiency_points(14, 7) == 0      # floored at zero
    assert efficiency_points(30, 7) == 0


def test_contradicted_finding_costs_20_even_when_rejected():
    r = run_investigation(FakeClient(CONTROLS["contradicted_claim"][0]()), CHECKOUT_LATENCY)
    assert r.passed and r.grade["criteria"]["no_contradicted"]["points"] == 0
    assert r.grade["criteria"]["no_contradicted"]["detail"] == "1 contradicted finding(s)"


def test_score_in_lines_and_json():
    r = run_investigation(FakeClient(reference_checkout()), CHECKOUT_LATENCY)
    assert report_lines(r)[-1] == "  " + score_line(r.grade)
    assert score_line(r.grade).startswith("score 100/100 (root_cause 40/40, cause_evidence 30/30")
    d = json.loads(report_json(r))
    assert d["score"] == 100 and d["grade"]["criteria"]["efficiency"]["detail"] == \
        "7 steps, reference 7"
