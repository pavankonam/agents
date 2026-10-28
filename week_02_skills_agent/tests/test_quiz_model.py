import importlib.util
from pathlib import Path

QUIZ = Path(__file__).resolve().parents[1] / "quiz" / "quiz_model.py"
spec = importlib.util.spec_from_file_location("quiz_model", QUIZ)
quiz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quiz)


def test_fake_run_passes(capsys):
    assert quiz.run(fake=True, model=None) == 0
    assert f"{len(quiz.SCENARIOS)}/{len(quiz.SCENARIOS)} passed" in capsys.readouterr().out


def test_only_filter_and_no_match():
    assert quiz.run(fake=True, model=None, only="BHX") == 0
    assert quiz.run(fake=True, model=None, only="zzz-nothing") == 2


def test_preflight_failure_returns_4():
    assert quiz.run(fake=False, model="x", check=lambda m: (False, "down")) == 4


def test_every_expected_skill_exists_and_answer_is_only_in_body():
    from skills_agent import SkillLibrary, list_resources
    lib = SkillLibrary.discover(quiz.SKILLS_DIR)
    catalog = lib.catalog().lower()
    for question, skills, files, scripts, expected in quiz.SCENARIOS:
        for s in skills:
            assert lib.get(s) is not None
        for f in files:
            skill, _, path = f.partition("/")
            assert skill in skills and path in list_resources(lib.get(skill))
        for part in quiz.parts(expected):
            if skills and part != "fix" and not part[0].isdigit():
                # glossary answers must not leak into level 1, or the check proves nothing
                assert part.lower() not in catalog


def test_level3_answer_is_only_in_the_file():
    """The incident scenario must need the reference file, not just the body."""
    from skills_agent import SkillLibrary
    lib = SkillLibrary.discover(quiz.SKILLS_DIR)
    for question, skills, files, scripts, expected in quiz.SCENARIOS:
        if files:
            bodies = " ".join(lib.get(s).body for s in skills).lower()
            for part in quiz.parts(expected):
                assert part.lower() not in bodies
                assert part.lower() not in lib.catalog().lower()


def test_script_answer_is_only_in_the_script_output():
    """The ticket scenario must need the script: the answer is nowhere in the text."""
    from skills_agent import SkillLibrary, list_scripts
    lib = SkillLibrary.discover(quiz.SKILLS_DIR)
    seen = 0
    for question, skills, files, scripts, expected in quiz.SCENARIOS:
        for target, args in scripts:
            seen += 1
            skill, _, path = target.partition("/")
            assert skill in skills and path in list_scripts(lib.get(skill))
            for part in quiz.parts(expected):
                assert part not in lib.get(skill).body and part not in lib.catalog()
                assert part not in question
    assert seen >= 1


def test_quiz_fails_when_script_output_lacks_the_answer(capsys, monkeypatch):
    """A fake model that claims the answer without the script saying it must fail."""
    bad = [("Ticket HX-11111?", ["ticket-checksum"], [],
            [("ticket-checksum/scripts/check_letter.py", ["HX-11111"])], "HX-40217-C")]
    monkeypatch.setattr(quiz, "SCENARIOS", bad)
    assert quiz.run(fake=True, model=None) == 1
    assert "ran scripts" in capsys.readouterr().out


def test_fake_run_reports_context(capsys):
    assert quiz.run(fake=True, model=None, only="BHX") == 0
    out = capsys.readouterr().out
    assert "tokens)" in out and "pasting every skill would start at" in out


def test_tight_budget_makes_skill_scenarios_fail(capsys):
    assert quiz.run(fake=True, model=None, only="BHX", budget=50) == 1
    assert "budget refused: load_skill team-glossary" in capsys.readouterr().out


def test_cli_checks_pass_with_fake_model(capsys):
    assert quiz.run(fake=True, model=None, only="ORCA") == 0
    out = capsys.readouterr().out
    assert "cli checks: 4/4 passed" in out and "[PASS] cli: validate exits 1" in out


def test_cli_check_fails_when_run_misroutes(monkeypatch):
    """A model that loads the wrong skill through the CLI must fail the run check."""
    from skills_agent import LOAD_SKILL, LLMResponse, ToolCall
    monkeypatch.setattr(quiz, "fake_script", lambda *a: [
        LLMResponse(tool_calls=[ToolCall(LOAD_SKILL, {"name": "unit-converter"})]),
        LLMResponse(content="Blue Heron Expansion")])
    results = dict(quiz.cli_checks(fake=True, model=None))
    assert sum(results.values()) == 3
    assert not any(ok for name, ok in results.items() if name.startswith("run --json"))


def test_json_report_and_results_table(tmp_path, capsys):
    path = tmp_path / "r" / "fake.json"
    assert quiz.run(fake=True, model=None, json_path=str(path)) == 0
    import json
    report = json.loads(path.read_text())
    n = len(quiz.SCENARIOS)
    assert report["model"] == "fake" and report["passed"] == n and len(report["scenarios"]) == n
    assert report["routing"]["exact"] == n and all(c["ok"] for c in report["cli"])
    kinds = {r["kind"] for r in report["scenarios"]}
    assert kinds == set(quiz.KINDS)
    capsys.readouterr()
    assert quiz.table([str(path)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("| model | date | total | level 2 |")
    assert out[2].startswith(f"| fake | {report['date']} | {n}/{n} | 5/5 | 1/1 | 1/1 | 1/1 | 1/1 | 3/3 |")


def test_kind_groups_every_scenario():
    counts = {}
    for q, skills, files, scripts, _ in quiz.SCENARIOS:
        k = quiz.kind(q, skills, files, scripts)
        counts[k] = counts.get(k, 0) + 1
    assert counts == {"level 2": 5, "level 3": 1, "script": 1, "two skills": 1,
                      "no skill": 1, "near miss": 3}


def test_table_bad_or_missing_report(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert quiz.table([str(bad)]) == 2
    assert quiz.table([str(tmp_path / "missing.json")]) == 2
    assert quiz.table([]) == 2


def test_failed_scenario_is_recorded_in_report(tmp_path, monkeypatch):
    """A real model that answers without loading a skill shows up as a FAIL row."""
    from skills_agent import FakeClient, LLMResponse
    import json

    class Lazy(FakeClient):
        def __init__(self, **kw):
            super().__init__([LLMResponse(content="No idea.")])

    monkeypatch.setattr(quiz, "OllamaClient", Lazy)
    # keep the CLI checks away from a real Ollama that may be running on the machine
    monkeypatch.setattr(quiz, "cli_checks", lambda fake, model: [("stub", True)])
    path = tmp_path / "lazy.json"
    code = quiz.run(fake=False, model="lazy", only="BHX stand for on our team",
                    check=lambda m: (True, "ok"), json_path=str(path))
    report = json.loads(path.read_text())
    assert code == 1 and report["model"] == "lazy" and report["passed"] == 0
    row = report["scenarios"][0]
    assert row["ok"] is False and row["loaded_skills"] == [] and row["answer"] == "No idea."
    assert report["routing"]["per_skill"]["team-glossary"]["fn"] == 1
