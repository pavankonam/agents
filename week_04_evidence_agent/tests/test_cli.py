import io
import json

from evidence_agent.cli import main
from evidence_agent.llm import FakeClient
from evidence_agent.scripted import control_wrong_service, reference_checkout


def run(argv, client=None):
    out = io.StringIO()
    return main(argv, client=client, out=out), out.getvalue()


def test_list():
    code, text = run(["list"])
    assert code == 0 and text.startswith("checkout_latency: Checkout is slow")


def test_run_pass_and_fail_codes():
    assert run(["run", "checkout_latency"], FakeClient(reference_checkout()))[0] == 0
    assert run(["run", "checkout_latency"], FakeClient(control_wrong_service()))[0] == 1


def test_usage_errors():
    assert run(["run", "nope"], FakeClient([]))[0] == 2
    assert run(["run", "checkout_latency", "--max-steps", "0"], FakeClient([]))[0] == 2
    assert run(["bogus"])[0] == 2


def test_json_and_record(tmp_path):
    path = tmp_path / "runs.jsonl"
    code, text = run(["run", "checkout_latency", "--json", "--record", str(path), "--model", "m"],
                     FakeClient(reference_checkout()))
    assert code == 0
    d = json.loads(text)
    assert d["passed"] and d["model"] == "m"
    assert json.loads(path.read_text().splitlines()[0]) == d


def test_run_without_ollama_exits_4(monkeypatch):
    import evidence_agent.cli as cli
    monkeypatch.setattr(cli, "check_ollama", lambda m, h: (False, "not up"))
    assert run(["run", "checkout_latency"])[0] == 4
    assert run(["check"])[0] == 4
