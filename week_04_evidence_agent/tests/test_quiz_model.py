import importlib.util
import io
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "quiz_model", Path(__file__).resolve().parents[1] / "quiz" / "quiz_model.py")
qm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qm)


def test_fake_mode_passes_and_records(tmp_path):
    out = io.StringIO()
    path = tmp_path / "fake.jsonl"
    assert qm.main(["--fake", "--record", str(path)], out=out) == 0
    assert "quiz_model (fake): 12/12 OK" in out.getvalue()
    recs = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["scenario"] for r in recs] == ["checkout_latency", "config_push", "dependency_outage"]
    assert all(r["model"] == "fake" and r["passed"] and r["score"] == 100 for r in recs)
    assert "scores: checkout_latency 100, config_push 100, dependency_outage 100 (mean 100)" \
        in out.getvalue()


def test_live_mode_without_ollama_exits_4(monkeypatch):
    monkeypatch.setattr(qm, "check_ollama", lambda m: (False, "down"))
    assert qm.main([], out=io.StringIO()) == 4
