"""Scripted model runs for tests and quiz_model --fake (D10).

The reference run is what a careful investigator does on `checkout_latency`.
The controls each break one rule; what they must score is in CONTROLS.
"""

from __future__ import annotations

from .llm import LLMResponse, ToolCall


def _call(name: str, **args) -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(name, args)])


def reference_checkout() -> list[LLMResponse]:
    return [
        _call("list_deploys"),                                    # ev_001 search, ev_002 payments
        _call("search_logs", service="payments", level="ERROR"),  # ev_003, ev_004
        _call("get_metric", service="checkout", metric="p95_latency_ms"),  # ev_005..ev_008
        _call("report_finding", claim="payments v2.3.1 at 14:02 cut the db pool from 50 to 5",
              evidence_ids=["ev_002"]),
        _call("report_finding", claim="from 14:05 payments cannot get a db connection",
              evidence_ids=["ev_003", "ev_004"]),
        _call("report_finding", claim="checkout p95 went from 230ms to 2900ms at 14:05",
              evidence_ids=["ev_006", "ev_007"]),
        _call("conclude", root_cause_service="payments",
              summary="The payments v2.3.1 deploy shrank the db pool to 5, payments calls wait "
                      "3s for a connection and checkout times out on them.",
              evidence_ids=["ev_002", "ev_003", "ev_007"]),
    ]


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
    return reference_checkout()[:3] + [
        _call("conclude", root_cause_service="search",
              summary="The search deploy at 13:55 came first.", evidence_ids=["ev_001"])]


# name -> (responses factory, must pass, expected end reason, expected rejected findings)
CONTROLS = {
    "text_only": (control_text_only, False, "no_conclusion", 0),
    "invented_id": (control_invented_id, False, "no_conclusion", 0),
    "rejected_then_fixed": (control_rejected_then_fixed, True, "concluded", 1),
    "wrong_service": (control_wrong_service, False, "concluded", 0),
}
