import pytest

from evidence_agent.investigation import TOOL_NAMES, Investigation, validate_args
from evidence_agent.telemetry import CHECKOUT_LATENCY, Record, Scenario


def inv(**kw):
    return Investigation(CHECKOUT_LATENCY, **kw)


def test_tools_listed():
    assert TOOL_NAMES == ["list_services", "search_logs", "get_metric", "list_deploys",
                          "report_finding", "conclude"]


def test_list_services_issues_no_evidence():
    i = inv()
    r = i.call("list_services", {})
    assert r.ok and r.content == "services: checkout, db, payments, search"
    assert len(i.ledger) == 0


def test_query_lines_carry_ids_and_same_record_keeps_id():
    i = inv()
    r = i.call("search_logs", {"service": "payments", "level": "ERROR"})
    assert r.content.splitlines()[0].startswith("[ev_001] 14:05 payments ERROR db pool exhausted")
    r2 = i.call("search_logs", {"service": "payments", "contains": "POOL"})
    assert r2.content.splitlines()[0].startswith("[ev_001]")
    assert i.steps[0].evidence_issued == ["ev_001", "ev_002"]
    assert i.steps[1].evidence_issued == ["ev_001", "ev_002"]
    assert len(i.ledger) == 2


def test_get_metric_without_name_lists_metrics_and_issues_nothing():
    i = inv()
    r = i.call("get_metric", {"service": "checkout"})
    assert r.content == "metrics of checkout: p95_latency_ms"
    assert len(i.ledger) == 0
    bad = i.call("get_metric", {"service": "checkout", "metric": "cpu"})
    assert not bad.ok and "unknown metric 'cpu'" in bad.error


def test_unknown_service_and_bad_level_are_refused():
    i = inv()
    assert "unknown service 'billing'" in i.call("search_logs", {"service": "billing"}).error
    assert "level must be one of" in i.call("search_logs", {"service": "db", "level": "FATAL"}).error
    assert "unknown service" in i.call("list_deploys", {"service": "nope"}).error


def test_validate_args():
    assert validate_args("search_logs", {}) == "missing argument(s) for search_logs: service"
    assert validate_args("search_logs", {"service": "x", "id": 1}).startswith("unexpected argument(s)")
    assert validate_args("report_finding", {"claim": "c", "evidence_ids": "ev_001"}) == \
        "argument evidence_ids of report_finding must be a list of strings"
    assert validate_args("conclude", {"_raw": "{"}) == "arguments for conclude were not valid JSON"
    assert validate_args("list_services", "x") == "arguments for list_services must be an object"
    assert validate_args("list_deploys", {}) == ""


def test_unknown_tool_is_a_refused_step():
    i = inv()
    r = i.call("restart_service", {"service": "payments"})
    assert not r.ok and "unknown tool 'restart_service'" in r.error
    assert i.report().refused_steps == 1


def test_finding_with_invented_id_is_rejected_and_kept():
    i = inv()
    r = i.call("report_finding", {"claim": "db is down", "evidence_ids": ["ev_001"]})
    assert not r.ok
    assert r.error == ("finding rejected: unknown evidence id(s): ev_001 "
                       "(never returned by a tool in this run)")
    f = i.findings[0]
    assert not f.accepted and f.evidence_ids == ["ev_001"]


def test_finding_needs_claim_and_evidence():
    i = inv()
    r = i.call("report_finding", {"claim": "  ", "evidence_ids": []})
    assert r.error == "finding rejected: empty claim; no evidence cited"


def test_finding_with_issued_ids_is_accepted():
    i = inv()
    i.call("list_deploys", {"service": "payments"})
    r = i.call("report_finding", {"claim": "pool cut", "evidence_ids": ["ev_001"]})
    assert r.ok and r.content == "finding 1 recorded with 1 citation(s), no check"
    assert i.report().accepted_findings[0].claim == "pool cut"


def test_rejected_conclusion_does_not_end_the_run():
    i = inv()
    r = i.call("conclude", {"root_cause_service": "payments", "summary": "s", "evidence_ids": ["ev_005"]})
    assert not r.ok and not r.done and not i.done
    assert i.conclusion is None
    r = i.call("conclude", {"root_cause_service": "billing", "summary": "", "evidence_ids": []})
    assert "unknown service 'billing'" in r.error and "empty summary" in r.error


def test_correct_conclusion_passes_and_ends():
    i = inv()
    i.call("list_deploys", {})
    r = i.call("conclude", {"root_cause_service": "payments", "summary": "pool",
                            "evidence_ids": ["ev_002"]})
    assert r.ok and r.done
    rep = i.report()
    assert rep.passed and rep.root_cause_correct and rep.end_reason == "concluded"
    with pytest.raises(RuntimeError):
        i.call("list_services", {})


def test_wrong_service_with_real_evidence_fails():
    i = inv()
    i.call("list_deploys", {})
    i.call("conclude", {"root_cause_service": "search", "summary": "deploy", "evidence_ids": ["ev_001"]})
    rep = i.report()
    assert rep.end_reason == "concluded" and not rep.root_cause_correct and not rep.passed


def test_step_limit_ends_with_note():
    i = inv(max_steps=2)
    i.call("list_services", {})
    r = i.call("list_deploys", {})
    assert r.done and r.content.endswith("step limit of 2 reached, investigation over")
    assert i.report().end_reason == "step_limit" and not i.report().passed


def test_hidden_rows_get_no_id():
    logs = tuple(Record("log", f"10:{m:02d}", "svc", {"level": "INFO", "message": "tick"})
                 for m in range(13))
    s = Scenario("many", "many", "q", logs, "svc")
    i = Investigation(s)
    r = i.call("search_logs", {"service": "svc"})
    lines = r.content.splitlines()
    assert len(lines) == 11 and lines[-1].startswith("(3 more not shown")
    assert len(i.ledger) == 10
    assert not i.call("report_finding", {"claim": "c", "evidence_ids": ["ev_011"]}).ok
