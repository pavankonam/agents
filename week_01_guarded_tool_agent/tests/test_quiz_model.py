import importlib.util
import json
from pathlib import Path

QUIZ = Path(__file__).resolve().parents[1] / "quiz" / "quiz_model.py"
spec = importlib.util.spec_from_file_location("quiz_model", QUIZ)
quiz_model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quiz_model)


def test_real_run_stops_early_when_ollama_is_missing(capsys):
    calls = []
    code = quiz_model.run(False, "qwen3:4b",
                          check=lambda m: calls.append(m) or (False, "not reachable"))
    assert code == 4 and calls == ["qwen3:4b"]
    assert "PROBLEM: not reachable" in capsys.readouterr().out


def test_only_filter_and_json_report(tmp_path):
    report = tmp_path / "r.json"
    assert quiz_model.run(True, None, only="workspace", report=str(report)) == 0
    data = json.loads(report.read_text())
    assert data["model"] == "fake" and data["total"] == data["passed"] >= 3
    assert all("workspace" in r["question"].lower() for r in data["scenarios"])
    assert {r["kind"] for r in data["scenarios"]} == {"task", "policy"}


def test_only_with_no_match_is_an_error():
    assert quiz_model.run(True, None, only="no such scenario") == 2
