"""Scripted model runs for tests and quiz_model --fake (D10).

The reference run is what a careful investigator does on `checkout_latency`:
every finding carries a check that its cited rows support (D17). The controls
each break one rule; what they must score is in CONTROLS.
"""

from __future__ import annotations

from .llm import LLMResponse, ToolCall


def _call(name: str, **args) -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(name, args)])


def _queries() -> list[LLMResponse]:
    return [
        _call("list_deploys"),                                    # ev_001 search, ev_002 payments
        _call("search_logs", service="payments", level="ERROR"),  # ev_003, ev_004
        _call("get_metric", service="checkout", metric="p95_latency_ms"),  # ev_005..ev_008
    ]


def _findings_and_conclusion() -> list[LLMResponse]:
    return [
        _call("report_finding", claim="payments v2.3.1 at 14:02 cut the db pool from 50 to 5",
              evidence_ids=["ev_002"],
              check={"service": "payments", "field": "note", "op": "contains",
                     "value": "pool size 50 -> 5", "at": "14:02"}),
        _call("report_finding", claim="from 14:05 payments cannot get a db connection",
              evidence_ids=["ev_003", "ev_004"],
              check={"service": "payments", "field": "message", "op": "contains",
                     "value": "db pool exhausted"}),
        _call("report_finding", claim="checkout p95 went from 230ms to 2900ms at 14:05",
              evidence_ids=["ev_006", "ev_007"],
              check={"service": "checkout", "field": "p95_latency_ms", "op": ">",
                     "value": 2000, "at": "14:05"}),
        _call("conclude", root_cause_service="payments",
              summary="The payments v2.3.1 deploy shrank the db pool to 5, payments calls wait "
                      "3s for a connection and checkout times out on them.",
              evidence_ids=["ev_002", "ev_003", "ev_007"]),
    ]


def reference_checkout() -> list[LLMResponse]:
    return _queries() + _findings_and_conclusion()


REFERENCE = {"checkout_latency": reference_checkout}


def control_text_only() -> list[LLMResponse]:
    return [LLMResponse(content="The root cause is payments.")]


def control_invented_id() -> list[LLMResponse]:
    return [_call("conclude", root_cause_service="payments", summary="payments broke",
                  evidence_ids=["ev_042"]),
            LLMResponse(content="Payments is the root cause.")]


def control_rejected_then_fixed() -> list[LLMResponse]:
    return [_call("report_finding", claim="payments is failing", evidence_ids=["ev_010"])] + \
        reference_checkout()


def control_wrong_service() -> list[LLMResponse]:
    return _queries() + [
        _call("conclude", root_cause_service="search",
              summary="The search deploy at 13:55 came first.", evidence_ids=["ev_001"])]


def control_contradicted_claim() -> list[LLMResponse]:
    """Real ids, wrong reading: ev_006 is checkout p95 230 at 14:00, not above 2000."""
    return _queries() + [
        _call("report_finding", claim="checkout p95 was already above 2s at 14:00",
              evidence_ids=["ev_006"],
              check={"service": "checkout", "field": "p95_latency_ms", "op": ">",
                     "value": 2000, "at": "14:00"})] + _findings_and_conclusion()


def control_irrelevant_citation() -> list[LLMResponse]:
    """Real id, wrong row: a db cpu claim citing the payments deploy row."""
    return _queries() + [
        _call("report_finding", claim="db cpu was above 80%", evidence_ids=["ev_002"],
              check={"service": "db", "field": "cpu_pct", "op": ">", "value": 80})] + \
        _findings_and_conclusion()


S, C, U, N = "supported", "contradicted", "unsupported", "unchecked"

# name -> (responses factory, must pass, expected end reason, expected rejected findings,
#          expected support status of each finding in order)
CONTROLS = {
    "text_only": (control_text_only, False, "no_conclusion", 0, ()),
    "invented_id": (control_invented_id, False, "no_conclusion", 0, ()),
    "rejected_then_fixed": (control_rejected_then_fixed, True, "concluded", 1, (N, S, S, S)),
    "wrong_service": (control_wrong_service, False, "concluded", 0, ()),
    "contradicted_claim": (control_contradicted_claim, True, "concluded", 1, (C, S, S, S)),
    "irrelevant_citation": (control_irrelevant_citation, True, "concluded", 1, (U, S, S, S)),
}
