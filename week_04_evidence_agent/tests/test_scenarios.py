from evidence_agent.telemetry import CONFIG_PUSH, DEPENDENCY_OUTAGE, SCENARIOS


def test_three_scenarios_in_order():
    assert list(SCENARIOS) == ["checkout_latency", "config_push", "dependency_outage"]


def test_records_time_ordered_and_cause_rows_on_root_cause_service():
    for s in SCENARIOS.values():
        times = [r.ts for r in s.records]
        assert times == sorted(times), s.name
        assert s.cause and s.reference_steps > 0, s.name
        assert all(s.records[k].service == s.root_cause_service for k in s.cause), s.name
        assert s.root_cause_service in s.services, s.name


def test_config_push_red_herring_is_a_worker_cpu_spike_before_the_errors():
    spike = [r for r in CONFIG_PUSH.records
             if r.kind == "metric" and r.service == "worker" and r.data["value"] > 90]
    first_error = min(r.ts for r in CONFIG_PUSH.records
                      if r.kind == "log" and r.data["level"] == "ERROR")
    assert len(spike) == 1 and spike[0].ts < first_error
    assert CONFIG_PUSH.root_cause_service == "gateway"


def test_dependency_outage_first_deploy_is_innocent():
    deploys = [r for r in DEPENDENCY_OUTAGE.records if r.kind == "deploy"]
    assert deploys[0].service == "web" and deploys[0].service != DEPENDENCY_OUTAGE.root_cause_service
    assert all(r.service != DEPENDENCY_OUTAGE.root_cause_service for r in deploys)
