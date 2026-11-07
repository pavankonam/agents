"""Scripted model runs for tests and quiz_model --fake (D10).

Each scenario has a reference run, what a careful investigator does: every
finding carries a check that its cited rows support (D17) and the conclusion
cites a row that shows the cause, so it scores 100 (D19). The controls each
break one rule; how they must end is in CONTROLS, which scenario they run on
in CONTROL_SCENARIO and their rubric score in CONTROL_SCORES.
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


def reference_config_push() -> list[LLMResponse]:
    """The 503s come from the gateway timing out; the worker CPU spike is a nightly job (D18)."""
    return [
        _call("list_deploys"),                                    # ev_001 gateway cfg-118
        _call("search_logs", service="gateway", level="ERROR"),   # ev_002, ev_003
        _call("get_metric", service="api", metric="p95_latency_ms"),  # ev_004..ev_007
        _call("report_finding", claim="gateway config cfg-118 at 09:07 cut the upstream "
                                      "timeout from 30s to 300ms",
              evidence_ids=["ev_001"],
              check={"service": "gateway", "field": "note", "op": "contains",
                     "value": "30000ms -> 300ms", "at": "09:07"}),
        _call("report_finding", claim="from 09:10 the gateway times out on api after 300ms "
                                      "and returns 503",
              evidence_ids=["ev_002", "ev_003"],
              check={"service": "gateway", "field": "message", "op": "contains",
                     "value": "timed out after 300ms"}),
        _call("report_finding", claim="api p95 stayed around 440ms, above the new 300ms timeout",
              evidence_ids=["ev_006"],
              check={"service": "api", "field": "p95_latency_ms", "op": ">",
                     "value": 300, "at": "09:10"}),
        _call("conclude", root_cause_service="gateway",
              summary="The gateway config push cfg-118 cut the upstream timeout to 300ms while "
                      "api p95 is about 440ms, so the gateway gives up and returns 503.",
              evidence_ids=["ev_001", "ev_002", "ev_006"]),
    ]


def reference_dependency_outage() -> list[LLMResponse]:
    """The email vendor is down; the 16:10 web deploy only changed page copy (D18)."""
    return [
        _call("search_logs", service="signup", level="ERROR"),    # ev_001, ev_002
        _call("get_metric", service="email_vendor", metric="availability"),  # ev_003..ev_006
        _call("list_deploys"),                                    # ev_007 web, ev_008 signup
        _call("report_finding", claim="signups fail because email_vendor returns 503",
              evidence_ids=["ev_001", "ev_002"],
              check={"service": "signup", "field": "message", "op": "contains",
                     "value": "email_vendor returned 503"}),
        _call("report_finding", claim="email_vendor availability fell from 0.99 to 0.12 at 16:20",
              evidence_ids=["ev_004", "ev_005"],
              check={"service": "email_vendor", "field": "availability", "op": "<",
                     "value": 0.5, "at": "16:20"}),
        _call("report_finding", claim="the 16:10 web deploy only changed the signup page copy",
              evidence_ids=["ev_007"],
              check={"service": "web", "field": "note", "op": "contains",
                     "value": "page copy", "at": "16:10"}),
        _call("report_finding", claim="the signup deploy v3.0.4 came at 16:30, after the "
                                      "failures began",
              evidence_ids=["ev_008"],
              check={"service": "signup", "field": "version", "op": "==",
                     "value": "v3.0.4", "at": "16:30"}),
        _call("conclude", root_cause_service="email_vendor",
              summary="The external email vendor became unreachable around 16:18, so signup "
                      "cannot send verification emails. The web deploy was only page copy.",
              evidence_ids=["ev_002", "ev_005"]),
    ]


REFERENCE = {"checkout_latency": reference_checkout,
             "config_push": reference_config_push,
             "dependency_outage": reference_dependency_outage}


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


def control_blame_cpu_spike() -> list[LLMResponse]:
    """config_push: a true, supported claim about the red herring is still the wrong cause."""
    return [
        _call("get_metric", service="worker", metric="cpu_pct"),  # ev_001..ev_004
        _call("report_finding", claim="worker cpu hit 96% at 09:08", evidence_ids=["ev_003"],
              check={"service": "worker", "field": "cpu_pct", "op": ">", "value": 90,
                     "at": "09:08"}),
        _call("conclude", root_cause_service="worker",
              summary="The worker CPU spike at 09:08 came just before the 503s.",
              evidence_ids=["ev_003"])]


def control_blame_first_deploy() -> list[LLMResponse]:
    """dependency_outage: the first deploy is the obvious suspect and is innocent."""
    return [_call("list_deploys"),                                 # ev_001 web, ev_002 signup
            _call("conclude", root_cause_service="web",
                  summary="The web deploy at 16:10 broke signups.", evidence_ids=["ev_001"])]


def control_cause_not_cited() -> list[LLMResponse]:
    """dependency_outage: right service, but only signup rows cited, none from email_vendor."""
    return [_call("search_logs", service="signup", level="ERROR"),  # ev_001, ev_002
            _call("conclude", root_cause_service="email_vendor",
                  summary="Signup errors say email_vendor returned 503.",
                  evidence_ids=["ev_001"])]


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
    "blame_cpu_spike": (control_blame_cpu_spike, False, "concluded", 0, (S,)),
    "blame_first_deploy": (control_blame_first_deploy, False, "concluded", 0, ()),
    "cause_not_cited": (control_cause_not_cited, True, "concluded", 0, ()),
}

# which scenario each control runs on (default checkout_latency)
CONTROL_SCENARIO = {"blame_cpu_spike": "config_push", "blame_first_deploy": "dependency_outage",
                    "cause_not_cited": "dependency_outage"}

# the rubric score each control must get (D19 to D21); every reference must score 100
CONTROL_SCORES = {"text_only": 0, "invented_id": 0, "rejected_then_fixed": 100,
                  "wrong_service": 30, "contradicted_claim": 80, "irrelevant_citation": 100,
                  "blame_cpu_spike": 30, "blame_first_deploy": 30, "cause_not_cited": 70}


def control_scenario(name: str) -> str:
    return CONTROL_SCENARIO.get(name, "checkout_latency")
