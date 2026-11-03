import json
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "quiz_model", Path(__file__).resolve().parents[1] / "quiz" / "quiz_model.py")
quiz_model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quiz_model)


def test_fake_quiz_passes(capsys):
    assert quiz_model.run(fake=True, model=None) == 0
    out = capsys.readouterr().out
    assert "12/12 tasks passed" in out and "76/76 controls" in out
    assert "87/87 episodes replayed with the same result" in out
    assert "id vs name pairs" in out and "gap +0 points" in out
    assert "failure kinds per task" in out and "with the expected failure kinds" in out


def test_only_filter_and_no_match(capsys):
    assert quiz_model.run(fake=True, model=None, only="delete_by_title") == 0
    out = capsys.readouterr().out
    assert "1/1 tasks passed" in out and "one variant only, not in total" in out
    assert "gap n/a" in out
    assert quiz_model.run(fake=True, model=None, only="zzz") == 2


def test_ollama_not_ready():
    assert quiz_model.run(fake=False, model="m", check=lambda m: (False, "down")) == 4


def test_reference_script_ends_with_submit():
    task = next(iter(quiz_model.ENVIRONMENTS["calendar"].tasks.values()))
    script = quiz_model.reference_script(task)
    assert script[-1].tool_calls[0].name == quiz_model.SUBMIT
    assert len(script) == len(task.reference) + 1


def test_messy_expected_per_env():
    cal, inbox = quiz_model.ENVIRONMENTS["calendar"], quiz_model.ENVIRONMENTS["inbox"]
    assert quiz_model.noise_lookup(cal) == "list_calendars"
    assert quiz_model.noise_lookup(inbox) == "list_agents"
    assert quiz_model.messy_expected(inbox.tasks["assign_by_name"], inbox) == [
        "wrong_tool", "repeated_lookup"]
    assert quiz_model.messy_expected(inbox.tasks["close_by_name"], inbox) == [
        "wrong_tool", "extra_step"]


def test_record_writes_main_runs_only(tmp_path, capsys):
    path = tmp_path / "fake.jsonl"
    assert quiz_model.run(fake=True, model=None, only="inbox/", record=str(path)) == 0
    lines = path.read_text().splitlines()
    assert len(lines) == 6 and "recorded 6 episodes" in capsys.readouterr().out
    assert {json.loads(x)["meta"]["model"] for x in lines} == {"fake"}
