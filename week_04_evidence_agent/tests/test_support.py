import pytest

from evidence_agent.investigation import Investigation, validate_args
from evidence_agent.ledger import EvidenceLedger
from evidence_agent.support import (CHECK_SCHEMA, check_support, describe, field_value, holds,
                                    parse_check)
from evidence_agent.telemetry import CHECKOUT_LATENCY, Record


def ck(**kw):
    base = {"service": "checkout", "field": "p95_latency_ms", "op": ">", "value": 2000}
    base.update(kw)
    return base


def test_parse_check_normalises_aliases_and_numbers():
    c, err = parse_check(ck(op="GT", value="2000", at="14:05"))
    assert err == "" and c == {"service": "checkout", "field": "p95_latency_ms", "op": ">",
                               "value": 2000.0, "at": "14:05"}
    c, _ = parse_check(ck(op="equals", value=5))
    assert c["op"] == "==" and c["value"] == "5" and c["at"] is None


@pytest.mark.parametrize("raw, err", [
    ("x", "check must be an object"),
    ({"service": "a"}, "check is missing: field, op, value"),
    (ck(unit="ms"), "unexpected key(s) in check: unit"),
    (ck(op="~"), "check op must be one of >, >=, <, <=, ==, contains"),
    (ck(value="high"), "check op > needs a number, got 'high'"),
    (ck(value=True), "check value must be a number or text"),
    (ck(at="2pm"), "check at must be a time like 14:05"),
    (ck(service=" "), "check service must be a non empty string"),
])
def test_parse_check_errors(raw, err):
    assert parse_check(raw) == (None, err)


def test_field_value_by_kind():
    m = Record("metric", "14:05", "db", {"metric": "cpu_pct", "value": 22})
    lg = Record("log", "14:05", "db", {"level": "WARN", "message": "slow"})
    dp = Record("deploy", "14:05", "db", {"version": "v1", "note": "n"})
    assert field_value(m, "cpu_pct") == 22 and field_value(m, "error_rate") is None
    assert field_value(lg, "level") == "WARN" and field_value(lg, "version") is None
    assert field_value(dp, "note") == "n" and field_value(dp, "message") is None


def test_holds():
    assert holds(2900, ">", 2000.0) and not holds(230, ">", 2000.0)
    assert holds(0.32, ">=", 0.32) and holds(22, "<", 35.0)
    assert not holds("2900", ">", 2000.0)  # text is never a number
    assert holds("ERROR", "==", "error") and holds("db pool exhausted: x", "contains", "POOL")


def _ledger_for(*idx):
    led = EvidenceLedger()
    for k in idx:
        led.issue(k, CHECKOUT_LATENCY.records[k], "t", 1)
    return led


def test_check_support_statuses():
    led = _ledger_for(6, 11, 5)  # ev_001 checkout p95 230 @14:00, ev_002 2900 @14:05, ev_003 db cpu
    c, _ = parse_check(ck(at="14:05"))
    r = check_support(c, ["ev_001", "ev_002"], led)
    assert r.status == "supported" and r.ids == ["ev_002"]
    c, _ = parse_check(ck(at="14:00"))
    r = check_support(c, ["ev_001", "ev_002"], led)
    assert r.status == "contradicted" and r.ids == ["ev_001"]
    assert r.reason == "cited rows contradict checkout p95_latency_ms > 2000 at 14:00: ev_001 has 230"
    c, _ = parse_check(ck(service="payments", field="error_rate"))
    r = check_support(c, ["ev_001", "ev_003"], led)
    assert r.status == "unsupported" and r.ids == []
    assert r.reason == "no cited row is about payments error_rate > 2000"


def test_check_support_without_at_needs_one_backing_row():
    led = _ledger_for(6, 11)
    c, _ = parse_check(ck())
    assert check_support(c, ["ev_001", "ev_002"], led).status == "supported"
    assert check_support(c, ["ev_001"], led).status == "contradicted"


def test_describe():
    c, _ = parse_check(ck(value=0.3, field="error_rate"))
    assert describe(c) == "checkout error_rate > 0.3"
    c, _ = parse_check({"service": "s", "field": "message", "op": "contains", "value": "x"})
    assert describe(c) == "s message contains 'x'"


def test_schema_and_validation_of_check_argument():
    assert CHECK_SCHEMA["required"] == ["service", "field", "op", "value"]
    assert validate_args("report_finding", {"claim": "c", "evidence_ids": [], "check": "x"}) == \
        "argument check of report_finding must be an object"


# ----- through the investigation ------------------------------------------
def inv_with_checkout_p95():
    i = Investigation(CHECKOUT_LATENCY)
    i.call("get_metric", {"service": "checkout", "metric": "p95_latency_ms"})  # ev_001..ev_004
    return i


def test_supported_finding_is_accepted_with_backing_ids():
    i = inv_with_checkout_p95()
    r = i.call("report_finding", {"claim": "p95 above 2s at 14:05", "evidence_ids": ["ev_002", "ev_003"],
                                  "check": ck(at="14:05")})
    assert r.ok and r.content == "finding 1 recorded with 2 citation(s), check supported by ev_003"
    f = i.findings[0]
    assert f.accepted and f.support == "supported" and f.support_ids == ["ev_003"]


def test_contradicted_finding_is_rejected_with_the_rows():
    i = inv_with_checkout_p95()
    r = i.call("report_finding", {"claim": "slow at 14:00", "evidence_ids": ["ev_002"],
                                  "check": ck(at="14:00")})
    assert not r.ok and r.error == ("finding rejected: claim contradicted: cited rows contradict "
                                    "checkout p95_latency_ms > 2000 at 14:00: ev_002 has 230")
    f = i.findings[0]
    assert not f.accepted and f.support == "contradicted"


def test_unsupported_and_invalid_findings_are_rejected():
    i = inv_with_checkout_p95()
    r = i.call("report_finding", {"claim": "db hot", "evidence_ids": ["ev_003"],
                                  "check": ck(service="db", field="cpu_pct", value=80)})
    assert "claim unsupported: no cited row is about db cpu_pct > 80" in r.error
    r = i.call("report_finding", {"claim": "x", "evidence_ids": ["ev_003"], "check": ck(op="~")})
    assert "invalid check: check op must be one of" in r.error
    assert [f.support for f in i.findings] == ["unsupported", "invalid"]
    assert i.report().support_counts() == {"unsupported": 1, "invalid": 1}


def test_check_is_not_judged_on_invented_ids():
    i = inv_with_checkout_p95()
    r = i.call("report_finding", {"claim": "x", "evidence_ids": ["ev_003", "ev_099"], "check": ck()})
    assert r.error == ("finding rejected: unknown evidence id(s): ev_099 "
                       "(never returned by a tool in this run)")
    assert i.findings[0].support == "unchecked" and i.findings[0].check["op"] == ">"
