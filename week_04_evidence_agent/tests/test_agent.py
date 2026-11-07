import json

from evidence_agent.agent import report_json, report_lines, run_investigation, system_prompt
from evidence_agent.llm import FakeClient, LLMResponse, ToolCall
from evidence_agent.scripted import CONTROLS, control_scenario, reference_checkout
from evidence_agent.telemetry import CHECKOUT_LATENCY, SCENARIOS


def test_reference_passes_with_three_accepted_findings():
    r = run_investigation(FakeClient(reference_checkout()), CHECKOUT_LATENCY)
    assert r.passed and r.end_reason == "concluded"
    assert len(r.accepted_findings) == 3 and not r.rejected_findings
    assert r.refused_steps == 0 and r.evidence_issued == 8


def test_controls_end_as_declared():
    for name, (factory, must_pass, end, rejected, _support) in CONTROLS.items():
        r = run_investigation(FakeClient(factory()), SCENARIOS[control_scenario(name)])
        assert (r.passed, r.end_reason, len(r.rejected_findings)) == (must_pass, end, rejected), name


def test_text_answer_is_not_a_conclusion():
    r = run_investigation(FakeClient([LLMResponse(content="payments")]), CHECKOUT_LATENCY)
    assert r.end_reason == "no_conclusion" and r.conclusion is None and not r.passed


def test_tool_errors_go_back_to_the_model():
    fake = FakeClient([LLMResponse(tool_calls=[ToolCall("report_finding",
                                                        {"claim": "x", "evidence_ids": ["ev_007"]})]),
                       LLMResponse(content="done")])
    run_investigation(fake, CHECKOUT_LATENCY)
    last = fake.calls[1][-1]
    assert last["role"] == "tool" and last["content"].startswith("error: finding rejected")


def test_calls_after_conclude_in_same_turn_are_skipped():
    fake = FakeClient([LLMResponse(tool_calls=[
        ToolCall("list_deploys", {}),
        ToolCall("conclude", {"root_cause_service": "payments", "summary": "s", "evidence_ids": ["ev_002"]}),
        ToolCall("list_services", {})])])
    r = run_investigation(fake, CHECKOUT_LATENCY)
    assert r.passed and [s.tool for s in r.steps] == ["list_deploys", "conclude"]


def test_turn_limit():
    many = [LLMResponse(tool_calls=[ToolCall("list_services", {})]) for _ in range(5)]
    r = run_investigation(FakeClient(many), CHECKOUT_LATENCY, max_steps=10, max_turns=3)
    assert r.end_reason == "turn_limit" and len(r.steps) == 3


def test_system_prompt_names_services_and_limit():
    p = system_prompt(CHECKOUT_LATENCY, 9)
    assert "at most 9 tool calls" in p and "checkout, db, payments, search" in p
    assert "Never make up an id" in p


def test_report_lines_and_json():
    fake = FakeClient(CONTROLS["rejected_then_fixed"][0]())
    r = run_investigation(fake, CHECKOUT_LATENCY)
    lines = report_lines(r)
    assert lines[0].startswith("scenario checkout_latency: PASS")
    assert any("REJECTED" in x for x in lines)
    d = json.loads(report_json(r, model="m"))
    assert d["model"] == "m" and d["rejected"] == 1 and d["accepted"] == 3 and d["passed"]
    assert d["refused_steps"] == 1


def test_rejected_conclusion_is_a_refused_step_not_a_finding():
    r = run_investigation(FakeClient(CONTROLS["invented_id"][0]()), CHECKOUT_LATENCY)
    assert r.refused_steps == 1 and r.findings == [] and r.end_reason == "no_conclusion"


def test_controls_support_statuses_as_declared():
    for name, (factory, _p, _e, _r, support) in CONTROLS.items():
        r = run_investigation(FakeClient(factory()), SCENARIOS[control_scenario(name)])
        assert tuple(f.support for f in r.findings) == support, name


def test_reference_findings_all_supported_and_counted_in_json():
    r = run_investigation(FakeClient(reference_checkout()), CHECKOUT_LATENCY)
    assert all(f.support == "supported" for f in r.findings)
    d = json.loads(report_json(r))
    assert d["support"] == {"supported": 3}
    assert d["findings"][2]["support_ids"] == ["ev_007"]
    assert "  claim support: supported 3" in report_lines(r)


def test_system_prompt_explains_check():
    p = system_prompt(CHECKOUT_LATENCY, 12)
    assert '"op": ">"' in p and "contradict or do not cover rejects the finding" in p
