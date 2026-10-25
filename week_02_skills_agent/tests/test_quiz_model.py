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
        if skills and expected not in ("fix",) and not expected[0].isdigit():
            # glossary answers must not leak into level 1, or the check proves nothing
            assert expected.lower() not in catalog


def test_level3_answer_is_only_in_the_file():
    """The incident scenario must need the reference file, not just the body."""
    from skills_agent import SkillLibrary
    lib = SkillLibrary.discover(quiz.SKILLS_DIR)
    for question, skills, files, scripts, expected in quiz.SCENARIOS:
        if files:
            bodies = " ".join(lib.get(s).body for s in skills).lower()
            assert expected.lower() not in bodies
            assert expected.lower() not in lib.catalog().lower()


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
            assert expected not in lib.get(skill).body and expected not in lib.catalog()
            assert expected not in question
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
