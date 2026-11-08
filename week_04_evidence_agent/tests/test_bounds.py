import io
import json
import threading

import pytest

from evidence_agent.agent import report_json, report_lines, run_investigation, system_prompt
from evidence_agent.bounds import FileKillSwitch, KillSwitch, window_problem
from evidence_agent.cli import main
from evidence_agent.investigation import Investigation
from evidence_agent.llm import FakeClient, LLMResponse, ToolCall
from evidence_agent.scripted import (CONTROLS, KILL_BY, KILL_REASON, REFERENCE, audit_tuples,
                                     control_over_budget, control_scenario, expected_audit,
                                     make_control, reference_checkout)
from evidence_agent.telemetry import CHECKOUT_LATENCY, SCENARIOS


def test_window_problem():
    w = ("13:45", "14:15")
    assert window_problem(w, None, None) == ""
    assert window_problem(w, "13:45", "14:15") == ""
    assert "outside the incident window 13:45 to 14:15" in window_problem(w, "12:00", None)
    assert "until 14:30 is outside" in window_problem(w, None, "14:30")
    assert window_problem(w, "2pm", None) == "since must be HH:MM, got '2pm'"
    assert window_problem(w, "14:10", "14:00") == "since 14:10 is after until 14:00"


def test_every_scenario_record_lies_in_its_window():
    for s in SCENARIOS.values():
        start, end = s.window
        assert all(start <= r.ts <= end for r in s.records), s.name


def test_query_budget_refuses_and_audits_without_spending():
    inv = Investigation(CHECKOUT_LATENCY, max_queries=1)
    assert inv.call("list_deploys", {}).ok
    res = inv.call("search_logs", {"service": "payments"})
    assert not res.ok and res.error.startswith("query budget of 1 used up")
    assert inv.call("list_services", {}).ok  # not a query, no budget
    assert inv.queries_used == 1 and len(inv.ledger) == 2
    assert [(a.step, a.event, a.rule, a.actor) for a in inv.audit] == [
        (2, "refused", "query_budget", "system")]


def test_window_refusal_spends_no_budget_and_since_until_filter_rows():
    inv = Investigation(CHECKOUT_LATENCY, max_queries=2)
    assert not inv.call("get_metric", {"service": "checkout", "metric": "p95_latency_ms",
                                       "until": "15:00"}).ok
    assert inv.queries_used == 0 and inv.audit[0].rule == "time_window"
    res = inv.call("get_metric", {"service": "checkout", "metric": "p95_latency_ms",
                                  "since": "14:05", "until": "14:10"})
    assert res.ok and res.content.splitlines() == [
        "[ev_001] 14:05 checkout p95_latency_ms=2900", "[ev_002] 14:10 checkout p95_latency_ms=3100"]
    empty = inv.call("list_deploys", {"since": "14:03", "until": "14:04"})
    assert empty.ok and empty.content == "no deploys" and inv.queries_used == 2


def test_since_until_must_be_strings():
    inv = Investigation(CHECKOUT_LATENCY)
    res = inv.call("list_deploys", {"since": 1400})
    assert res.error == "argument since of list_deploys must be a string" and inv.queries_used == 0


def test_kill_switch_needs_who_and_why_and_first_trip_wins():
    ks = KillSwitch()
    with pytest.raises(ValueError):
        ks.trigger("", "x")
    with pytest.raises(ValueError):
        ks.trigger("pavan", "  ")
    ks.trigger("pavan", "first")
    ks.trigger("ops", "second")
    assert ks.tripped() == ("pavan", "first")


def test_kill_from_another_thread_stops_before_the_next_call():
    ks = KillSwitch()
    inv = Investigation(CHECKOUT_LATENCY, kill_switch=ks)
    assert inv.call("list_deploys", {}).ok
    t = threading.Thread(target=ks.trigger, args=("oncall:ana", "rollback started"))
    t.start()
    t.join()
    res = inv.call("search_logs", {"service": "payments"})
    assert res.done and res.error == "investigation stopped by oncall:ana: rollback started"
    assert len(inv.steps) == 1 and inv.end_reason == "killed"
    assert inv.audit[-1].line() == "step 1 stop killed by oncall:ana: rollback started"


def test_kill_before_first_turn_never_asks_the_model():
    ks = KillSwitch()
    ks.trigger("pavan", "drill")
    fake = FakeClient(reference_checkout())
    r = run_investigation(fake, CHECKOUT_LATENCY, kill_switch=ks)
    assert fake.calls == [] and r.end_reason == "killed" and r.steps == []
    assert audit_tuples(r) == ((0, "stop", "killed", "pavan"),)


def test_file_kill_switch(tmp_path):
    path = tmp_path / "stop.txt"
    ks = FileKillSwitch(path)
    assert ks.tripped() is None
    path.write_text("pavan: wrong service under investigation\nignored\n")
    assert ks.tripped() == ("pavan", "wrong service under investigation")
    path.write_text("someone else: later")
    assert ks.tripped() == ("pavan", "wrong service under investigation")
    other = tmp_path / "plain.txt"
    other.write_text("")
    assert FileKillSwitch(other).tripped() == ("operator", f"kill file {other} present")


def test_every_run_ends_with_exactly_one_audited_stop():
    for name in CONTROLS:
        client, opts = make_control(name)
        r = run_investigation(client, SCENARIOS[control_scenario(name)], **opts)
        stops = [a for a in r.audit if a.event == "stop"]
        assert len(stops) == 1 and stops[0].rule == r.end_reason and r.audit[-1] is stops[0], name
        assert audit_tuples(r) == expected_audit(name, len(r.steps)), name
    for name, factory in REFERENCE.items():
        r = run_investigation(FakeClient(factory()), SCENARIOS[name])
        assert [(a.event, a.rule, a.actor) for a in r.audit] == [("stop", "concluded", "agent")]


def test_step_and_turn_limits_are_audited_as_system():
    many = [LLMResponse(tool_calls=[ToolCall("list_services", {})]) for _ in range(5)]
    r = run_investigation(FakeClient(many), CHECKOUT_LATENCY, max_steps=2)
    assert audit_tuples(r) == ((2, "stop", "step_limit", "system"),)
    r = run_investigation(FakeClient(many), CHECKOUT_LATENCY, max_steps=10, max_turns=3)
    assert audit_tuples(r) == ((3, "stop", "turn_limit", "system"),)


def test_operator_kill_control_report():
    client, opts = make_control("operator_kill")
    r = run_investigation(client, CHECKOUT_LATENCY, **opts)
    assert r.queries_used == 2 and r.evidence_issued == 4 and r.score == 0
    assert f"  audit: step 2 stop killed by {KILL_BY}: {KILL_REASON}" in report_lines(r)
    d = json.loads(report_json(r))
    assert d["audit"] == [{"step": 2, "event": "stop", "rule": "killed", "actor": KILL_BY,
                           "reason": KILL_REASON}]
    assert d["queries_used"] == 2 and d["max_queries"] == 8


def test_system_prompt_states_bounds():
    p = system_prompt(CHECKOUT_LATENCY, 12, 5)
    assert "at most 5 may be queries" in p and "incident window is 13:45 to 14:15" in p
    assert "An operator can stop you" in p


def test_investigation_rejects_zero_budget():
    with pytest.raises(ValueError):
        Investigation(CHECKOUT_LATENCY, max_queries=0)


def _cli(argv, client):
    out = io.StringIO()
    return main(argv, client=client, out=out), out.getvalue()


def test_cli_kill_file_and_audit(tmp_path):
    stop, audit = tmp_path / "stop.txt", tmp_path / "audit.jsonl"
    stop.write_text("pavan: taking over by hand")
    code, text = _cli(["run", "checkout_latency", "--kill-file", str(stop), "--audit", str(audit),
                       "--model", "m"], FakeClient(reference_checkout()))
    assert code == 1 and "audit: step 0 stop killed by pavan: taking over by hand" in text
    rows = [json.loads(x) for x in audit.read_text().splitlines()]
    assert rows == [{"scenario": "checkout_latency", "model": "m", "step": 0, "event": "stop",
                     "rule": "killed", "actor": "pavan", "reason": "taking over by hand"}]


def test_cli_max_queries():
    code, text = _cli(["run", "checkout_latency", "--max-queries", "2"],
                      FakeClient(control_over_budget()))
    assert code == 0 and "2/2 queries" in text and "step 3 refused query_budget" in text
    # the full reference needs 3 queries: with 2 its later citations are never issued
    code, text = _cli(["run", "checkout_latency", "--max-queries", "2"],
                      FakeClient(reference_checkout()))
    assert code == 1 and "end no_conclusion" in text
    assert _cli(["run", "checkout_latency", "--max-queries", "0"], FakeClient([]))[0] == 2
