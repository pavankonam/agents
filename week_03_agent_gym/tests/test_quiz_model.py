import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "quiz_model", Path(__file__).resolve().parents[1] / "quiz" / "quiz_model.py")
quiz_model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quiz_model)


def test_fake_quiz_passes(capsys):
    assert quiz_model.run(fake=True, model=None) == 0
    out = capsys.readouterr().out
    assert "4/4 tasks passed" in out and "8/8 controls" in out


def test_only_filter_and_no_match(capsys):
    assert quiz_model.run(fake=True, model=None, only="delete") == 0
    assert "1/1 tasks passed" in capsys.readouterr().out
    assert quiz_model.run(fake=True, model=None, only="zzz") == 2


def test_ollama_not_ready():
    assert quiz_model.run(fake=False, model="m", check=lambda m: (False, "down")) == 4


def test_reference_script_ends_with_submit():
    task = next(iter(quiz_model.ENVIRONMENTS["calendar"].tasks.values()))
    script = quiz_model.reference_script(task)
    assert script[-1].tool_calls[0].name == quiz_model.SUBMIT
    assert len(script) == len(task.reference) + 1
