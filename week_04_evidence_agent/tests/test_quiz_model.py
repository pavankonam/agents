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
    assert "quiz_model (fake): 5/5 OK" in out.getvalue()
    rec = json.loads(path.read_text().splitlines()[0])
    assert rec["model"] == "fake" and rec["passed"]


def test_live_mode_without_ollama_exits_4(monkeypatch):
    monkeypatch.setattr(qm, "check_ollama", lambda m: (False, "down"))
    assert qm.main([], out=io.StringIO()) == 4
