"""Day 5: description linter, per skill precision / recall, routing quiz scenarios."""

import importlib.util
import json
from pathlib import Path

from skills_agent import LLMResponse, SkillLibrary, ToolCall
from skills_agent.routing import (
    OVERLAP_MAX, content_words, format_metrics, jaccard, lint_description, lint_library, main,
    max_overlap, routing_metrics,
)

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
GOOD = ("Converts between metric and imperial units with the team's rounding rules. "
        "Use when the user asks to convert miles, km, pounds or kg.")

spec = importlib.util.spec_from_file_location("quiz_model_r", ROOT / "quiz" / "quiz_model.py")
quiz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quiz)


def codes(issues):
    return sorted(i.code for i in issues)


def write_skill(root: Path, name: str, desc: str) -> None:
    (root / name).mkdir(parents=True)
    (root / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n\nBody.\n")


# ---- linter -------------------------------------------------------------------------

def test_good_description_has_no_issues():
    assert lint_description("unit-converter", GOOD) == []


def test_short_description_is_flagged():
    assert "R1-short" in codes(lint_description("x", "Converts units. Use when asked."))


def test_missing_trigger_is_flagged():
    desc = "Converts between metric and imperial units for length, weight and temperature values."
    assert codes(lint_description("x", desc)) == ["R2-no-trigger"]


def test_trigger_variants_are_accepted():
    base = "Converts between metric and imperial units for length and weight values. "
    for clause in ("Use when converting.", "Use it if a unit appears.", "Use for any km value.",
                   "Whenever miles appear, load it.", "Load it when the user mentions kg."):
        assert "R2-no-trigger" not in codes(lint_description("x", base + clause)), clause


def test_vague_words_are_flagged_and_named():
    issues = lint_description("x", "Helps with various things and stuff for the team. "
                                   "Use when the user needs anything at all.")
    vague = [i for i in issues if i.code == "R3-vague"]
    assert vague and all(w in vague[0].message for w in ("helps with", "various", "stuff",
                                                         "anything"))


def test_vague_match_is_whole_word():
    # "etc" must not match "fetch", "things" must not match "nothings" style substrings
    desc = "Fetches the latest exchange rates for a currency pair. Use when the user asks for FX."
    assert "R3-vague" not in codes(lint_description("x", desc))


def test_first_person_is_flagged():
    desc = "I convert miles to km and pounds to kg for you. Use when the user asks to convert units."
    assert "R4-first-person" in codes(lint_description("x", desc))


def test_overlapping_descriptions_are_flagged(tmp_path):
    write_skill(tmp_path, "glossary-a", "Definitions of internal team acronyms and project code "
                "names. Use when a question mentions an internal acronym or code name.")
    write_skill(tmp_path, "glossary-b", "Definitions of internal team acronyms and project code "
                "names for the sales team. Use when a question mentions an internal acronym.")
    lib = SkillLibrary.discover(tmp_path)
    over = [i for i in lint_library(lib) if i.code == "R5-overlap"]
    assert len(over) == 1 and "glossary-b" in over[0].message and "acronym" in over[0].message
    assert max_overlap(lib)[0] > OVERLAP_MAX


def test_shipped_skills_lint_clean_and_far_apart():
    lib = SkillLibrary.discover(SKILLS)
    assert lint_library(lib) == []
    score, a, b = max_overlap(lib)
    assert score < OVERLAP_MAX and a and b


def test_content_words_and_jaccard():
    w = content_words("Use when the user asks to convert miles to km, HX-40217.")
    assert w == {"convert", "miles", "hx-40217"}  # stopwords and words under 3 chars dropped
    assert jaccard({"a", "b"}, {"b", "c"}) == 1 / 3 and jaccard(set(), set()) == 0.0


def test_cli_exit_codes_and_json(tmp_path, capsys):
    assert main(["--skills-dir", str(SKILLS)]) == 0
    assert "0 description issues" in capsys.readouterr().out
    write_skill(tmp_path, "vague-one", "Helps with stuff.")
    assert main(["--skills-dir", str(tmp_path), "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["skills"] == ["vague-one"]
    assert {"R1-short", "R2-no-trigger", "R3-vague"} <= {i["code"] for i in data["issues"]}


# ---- metrics ------------------------------------------------------------------------

def test_metrics_count_tp_fp_fn():
    m = routing_metrics([
        (["a"], ["a"]),            # tp a
        (["a"], ["b"]),            # fn a, fp b
        (["a", "b"], ["a"]),       # tp a, fn b
        ([], ["a"]),               # fp a on a near miss
        ([], []),                  # correct abstain
    ])
    assert m["per_skill"]["a"] == {"tp": 2, "fp": 1, "fn": 1, "precision": 0.667,
                                   "recall": 0.667}
    assert m["per_skill"]["b"] == {"tp": 0, "fp": 1, "fn": 1, "precision": 0.0, "recall": 0.0}
    assert m["exact"] == 2 and m["runs"] == 5
    assert m["abstain"] == {"correct": 1, "of": 2}
    assert m["micro"] == {"precision": 0.5, "recall": 0.5}


def test_unused_skill_has_undefined_ratios():
    m = routing_metrics([(["a"], ["a"])], skills=["a", "z"])
    assert m["per_skill"]["z"]["precision"] is None and m["per_skill"]["z"]["recall"] is None
    assert "n/a" in format_metrics(m)


def test_format_metrics_table():
    text = format_metrics(routing_metrics([(["a"], ["a"]), ([], [])]))
    assert "precision  recall" in text and "exact routing 2/2" in text
    assert "without a skill 1/1" in text


# ---- quiz scenarios -----------------------------------------------------------------

def test_quiz_has_near_misses_and_a_two_skill_task():
    lib = SkillLibrary.discover(SKILLS)
    near = [s for s in quiz.SCENARIOS if s[0] in quiz.NEAR_MISS]
    assert len(near) >= 3 and all(s[1] == [] for s in near)
    assert quiz.NEAR_MISS <= {s[0] for s in quiz.SCENARIOS}
    # each near miss shares at least one content word with some skill description
    descs = set().union(*(content_words(lib.get(n).description) for n in lib.names()))
    for q, *_ in near:
        assert content_words(q) & descs, q
        assert "near miss" not in q.lower()  # the label never reaches the model
    two = [s for s in quiz.SCENARIOS if len(s[1]) >= 2]
    assert two and all(len(quiz.parts(s[4])) == len(s[1]) for s in two)


def test_two_skill_answer_parts_each_come_from_one_body():
    lib = SkillLibrary.discover(SKILLS)
    q, skills, _, _, expected = next(s for s in quiz.SCENARIOS if len(s[1]) >= 2)
    glossary_part = quiz.parts(expected)[0]
    assert glossary_part in lib.get("team-glossary").body
    assert glossary_part not in lib.get("unit-converter").body


def test_quiz_reports_metrics_and_lint(capsys):
    assert quiz.run(fake=True, model=None) == 0
    out = capsys.readouterr().out
    n = len(quiz.SCENARIOS)
    assert f"exact routing {n}/{n}" in out and "description lint: no issues" in out
    assert "micro precision 1.00, recall 1.00" in out


def test_only_near_miss_filter(capsys):
    assert quiz.run(fake=True, model=None, only="near miss") == 0
    out = capsys.readouterr().out
    assert f"{len(quiz.NEAR_MISS)}/{len(quiz.NEAR_MISS)} passed" in out


def test_misrouting_model_lowers_precision(capsys, monkeypatch):
    """A model that loads the glossary on the NASA near miss fails it and costs precision."""
    real = quiz.fake_script

    def eager(skills, files, scripts, expected):
        if expected == "Aeronautics":
            return [LLMResponse(tool_calls=[ToolCall("load_skill", {"name": "team-glossary"})]),
                    LLMResponse(content="NASA: National Aeronautics and Space Administration")]
        return real(skills, files, scripts, expected)

    monkeypatch.setattr(quiz, "fake_script", eager)
    assert quiz.run(fake=True, model=None) == 1
    out = capsys.readouterr().out
    assert "[FAIL] (near miss) What does the acronym NASA stand for?" in out
    assert "team-glossary       3   1   0       0.75    1.00" in out
    assert "without a skill 3/4" in out


def test_two_skill_task_fails_if_one_part_is_missing(monkeypatch, capsys):
    bad = [("What does BHX stand for, and how many km is 5 miles?",
            ["team-glossary", "unit-converter"], [], [], ("Blue Heron Expansion", "8.05"))]
    monkeypatch.setattr(quiz, "SCENARIOS", bad)
    real = quiz.fake_script
    monkeypatch.setattr(quiz, "fake_script",
                        lambda *a: real(*a)[:-1] + [LLMResponse(content="Blue Heron Expansion")])
    assert quiz.run(fake=True, model=None) == 1
    assert "expected to contain" in capsys.readouterr().out
