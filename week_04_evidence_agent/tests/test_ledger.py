from evidence_agent.ledger import EvidenceLedger
from evidence_agent.telemetry import CHECKOUT_LATENCY


def test_ids_are_sequential_and_stable_per_record():
    led = EvidenceLedger()
    r0, r1 = CHECKOUT_LATENCY.records[0], CHECKOUT_LATENCY.records[1]
    assert led.issue(0, r0, "search_logs", 1) == "ev_001"
    assert led.issue(1, r1, "list_deploys", 2) == "ev_002"
    assert led.issue(0, r0, "search_logs", 3) == "ev_001"
    assert len(led) == 2
    assert led.get("ev_001").first_step == 1


def test_unknown_keeps_order_and_drops_repeats():
    led = EvidenceLedger()
    led.issue(0, CHECKOUT_LATENCY.records[0], "t", 1)
    assert led.unknown(["ev_009", "ev_001", "ev_009", "EV_001"]) == ["ev_009", "EV_001"]
    assert "ev_001" in led and "ev_002" not in led
