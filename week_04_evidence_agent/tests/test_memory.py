import dataclasses
import io
import json

import pytest

from evidence_agent.agent import report_json, report_lines, run_investigation
from evidence_agent.cli import main
from evidence_agent.investigation import Investigation
from evidence_agent.llm import FakeClient, LLMResponse, ToolCall
from evidence_agent.memory import DROPPED, KEPT, FindingMemory, identity, row_record
from evidence_agent.scripted import (STALE_ENTRIES, control_recall_reuse, make_control,
                                     reference_checkout, reference_memory)
from evidence_agent.telemetry import CHECKOUT_LATENCY, CONFIG_PUSH, Record


def _with_record(index, record):
    """checkout_latency with one record replaced (the data changed since memory was written)."""
    records = list(CHECKOUT_LATENCY.records)
    if record is None:
        del records[index]
    else:
        records[index] = record
    return dataclasses.replace(CHECKOUT_LATENCY, records=tuple(records))


def test_remember_stores_supported_findings_with_backing_rows_only():
    mem = reference_memory()
    assert [len(e["rows"]) for e in mem.entries] == [1, 2, 1]
    # the checkout finding cited the 14:00 and 14:05 rows; only the 14:05 row backs it
    assert mem.entries[2]["rows"] == [CHECKOUT_LATENCY.records[11].to_dict()]
    assert {e["scenario"] for e in mem.entries} == {"checkout_latency"}


def test_unchecked_and_rejected_findings_are_not_stored():
    inv = Investigation(CHECKOUT_LATENCY)
    inv.call("list_deploys", {})
    inv.call("report_finding", {"claim": "payments deployed", "evidence_ids": ["ev_002"]})
    inv.call("report_finding", {"claim": "search broke", "evidence_ids": ["ev_001"],
                                "check": {"service": "search", "field": "note", "op": "contains",
                                          "value": "outage"}})
    assert [f.accepted for f in inv.findings] == [True, False]
    mem = FindingMemory()
    assert mem.remember(CHECKOUT_LATENCY, inv.findings, inv.ledger) == 0 and mem.entries == []


def test_remembering_the_same_check_again_replaces_it():
    mem = reference_memory()
    run_investigation(FakeClient(reference_checkout()), CHECKOUT_LATENCY, memory=mem)
    assert len(mem.entries) == 3


def test_recall_keeps_unchanged_findings_and_issues_ids_first():
    client, opts = make_control("recall_reuse")
    r = run_investigation(client, CHECKOUT_LATENCY, **opts)
    assert [(x.status, x.ids) for x in r.recall] == [
        (KEPT, ["ev_001"]), (KEPT, ["ev_002", "ev_003"]), (KEPT, ["ev_004"])]
    assert r.recall_counts == (3, 0) and r.queries_used == 1 and r.passed and r.score == 100
    question = client.calls[0][1]["content"]
    assert "[ev_001] 14:02 payments deploy v2.3.1: db connection pool size 50 -> 5" in question
    assert "dropped" not in question
    # the new supported finding is stored as well
    assert r.remembered == 1 and len(opts["memory"].entries) == 4


def test_changed_value_is_contradicted_and_dropped():
    changed = _with_record(8, Record("deploy", "14:02", "payments",
                                     {"version": "v2.3.1", "note": "db connection pool size 50 -> 40"}))
    mem = reference_memory()
    out = mem.recall(changed)
    assert [x.status for x in out] == [DROPPED, KEPT, KEPT]
    assert out[0].reason.startswith("claim now contradicted: current rows contradict payments note "
                                    "contains 'pool size 50 -> 5' at 14:02: 14:02 payments deploy")
    assert len(mem.entries) == 2  # the dropped finding is forgotten


def test_missing_row_is_dropped():
    gone = _with_record(15, None)  # the 14:06 pool exhausted log is gone
    out = reference_memory().recall(gone)
    assert out[1].status == DROPPED
    assert out[1].reason == ("row no longer in the data: 14:06 payments ERROR db pool exhausted: "
                             "waited 3000ms for a connection")


def test_stale_entries_dropped_and_model_told():
    client, opts = make_control("recall_stale")
    r = run_investigation(client, CHECKOUT_LATENCY, **opts)
    assert [x.status for x in r.recall] == [DROPPED, DROPPED, KEPT, KEPT, KEPT]
    assert "14:00 checkout p95_latency_ms=230 has 230" in r.recall[0].reason
    assert r.recall[1].reason.startswith("row no longer in the data: 14:01 payments deploy v2.3.0")
    assert "2 remembered finding(s) no longer hold" in client.calls[0][1]["content"]
    assert [x.ids for x in r.recall][2:] == [["ev_001"], ["ev_002", "ev_003"], ["ev_004"]]
    lines = report_lines(r)
    assert "  memory: recalled 3, dropped 2, stored 1 verified finding(s)" in lines
    d = json.loads(report_json(r))
    assert [x["status"] for x in d["recall"]] == ["dropped", "dropped", "kept", "kept", "kept"]


def test_other_scenario_recalls_nothing_and_keeps_entries():
    mem = reference_memory()
    assert mem.recall(CONFIG_PUSH) == [] and len(mem.entries) == 3


def test_recalled_ids_cost_no_query_and_are_citable_but_invented_ids_are_not():
    mem = reference_memory()
    fake = FakeClient([LLMResponse(tool_calls=[ToolCall("conclude", {
        "root_cause_service": "payments", "summary": "s", "evidence_ids": ["ev_005"]})]),
        LLMResponse(tool_calls=[ToolCall("conclude", {
            "root_cause_service": "payments", "summary": "s", "evidence_ids": ["ev_001"]})])])
    r = run_investigation(fake, CHECKOUT_LATENCY, memory=mem)
    assert r.refused_steps == 1 and r.passed and r.queries_used == 0 and r.evidence_issued == 4


def test_preload_after_first_step_is_an_error():
    inv = Investigation(CHECKOUT_LATENCY)
    inv.call("list_services", {})
    with pytest.raises(RuntimeError):
        inv.preload([])


def test_malformed_entries_are_dropped_not_crashing():
    mem = FindingMemory(entries=[
        {"scenario": "checkout_latency", "claim": "a", "check": {"service": "x"}, "rows": []},
        {"scenario": "checkout_latency", "claim": "b", "check": STALE_ENTRIES[0]["check"],
         "rows": [{"kind": "metric", "ts": "14:00"}]},
        {"scenario": "checkout_latency", "claim": "c", "check": STALE_ENTRIES[0]["check"],
         "rows": []}])
    out = mem.recall(CHECKOUT_LATENCY)
    assert [x.reason for x in out] == ["invalid check: check is missing: field, op, value",
                                       "malformed stored row", "no stored rows"]
    assert mem.entries == []


def test_identity_ignores_the_value():
    a = Record("metric", "14:00", "checkout", {"metric": "p95_latency_ms", "value": 230})
    b = Record("metric", "14:00", "checkout", {"metric": "p95_latency_ms", "value": 2400})
    assert identity(a) == identity(b) and row_record(a.to_dict()) == a
    assert row_record({"kind": "trace", "ts": "14:00", "service": "x", "data": {}}) is None


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "mem.json"
    mem = reference_memory()
    mem.save(path)
    again = FindingMemory.load(path)
    assert again.entries == json.loads(json.dumps(mem.entries))
    assert [x.status for x in again.recall(CHECKOUT_LATENCY)] == [KEPT] * 3
    assert FindingMemory.load(tmp_path / "none.json").entries == []


def test_load_rejects_malformed_files(tmp_path):
    bad = tmp_path / "bad.json"
    for text in ("{not json", '{"version": 2, "entries": []}', '{"version": 1, "entries": [{}]}'):
        bad.write_text(text)
        with pytest.raises(ValueError):
            FindingMemory.load(bad)


def _cli(argv, client):
    out = io.StringIO()
    return main(argv, client=client, out=out), out.getvalue()


def test_cli_memory_across_two_runs(tmp_path):
    path = tmp_path / "mem.json"
    code, _ = _cli(["run", "checkout_latency", "--memory", str(path)],
                   FakeClient(reference_checkout()))
    assert code == 0 and len(json.loads(path.read_text())["entries"]) == 3
    code, text = _cli(["run", "checkout_latency", "--memory", str(path), "--json"],
                      FakeClient(control_recall_reuse()))
    d = json.loads(text)
    assert code == 0 and d["score"] == 100 and d["remembered"] == 1
    assert [x["ids"] for x in d["recall"]] == [["ev_001"], ["ev_002", "ev_003"], ["ev_004"]]
    assert len(json.loads(path.read_text())["entries"]) == 4


def test_cli_malformed_memory_is_usage_error(tmp_path):
    path = tmp_path / "mem.json"
    path.write_text("[]")
    assert _cli(["run", "checkout_latency", "--memory", str(path)], FakeClient([]))[0] == 2
