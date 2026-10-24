from pathlib import Path

import pytest

from skills_agent import SkillError, SkillLibrary, load_skill_dir, parse_frontmatter, validate

SKILLS = Path(__file__).resolve().parents[1] / "skills"


def write_skill(root: Path, folder: str, text: str) -> Path:
    d = root / folder
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    return d


def test_parse_simple_frontmatter_and_body():
    data, body = parse_frontmatter("---\nname: a-b\ndescription: does things\n---\n\n# Hi\nbody\n")
    assert data == {"name": "a-b", "description": "does things"}
    assert body == "# Hi\nbody"


def test_parse_folded_literal_quoted_and_nested():
    text = ("---\nname: x\ndescription: >\n  line one\n  line two\nnotes: |\n  keep\n  lines\n"
            "license: 'it''s MIT'\ncompat: \"say \\\"hi\\\"\"\nmetadata:\n  author: me\n"
            "  version: \"1.0\"\n---\nbody")
    data, body = parse_frontmatter(text)
    assert data["description"] == "line one line two"
    assert data["notes"] == "keep\nlines"
    assert data["license"] == "it's MIT"
    assert data["compat"] == 'say "hi"'
    assert data["metadata"] == {"author": "me", "version": "1.0"}
    assert body == "body"


def test_plain_scalar_continued_on_indented_lines():
    data, _ = parse_frontmatter("---\ndescription: first part\n  second part\n---\n")
    assert data["description"] == "first part second part"


def test_comments_and_bom_are_ignored():
    data, _ = parse_frontmatter("﻿---\n# comment\nname: a\n---\n")
    assert data == {"name": "a"}


@pytest.mark.parametrize("text, msg", [
    ("name: a\n", "must start"),
    ("---\nname: a\n", "not closed"),
    ("---\nname: a\nname: b\n---\n", "duplicate"),
    ("---\njust words\n---\n", "key: value"),
    ("---\n  name: a\n---\n", "indentation"),
])
def test_parse_errors(text, msg):
    with pytest.raises(SkillError, match=msg):
        parse_frontmatter(text)


@pytest.mark.parametrize("name, ok", [
    ("pdf", True), ("data-cleaner-2", True), ("Pdf", False), ("pdf_tools", False),
    ("-pdf", False), ("pdf-", False), ("pdf--x", False), ("a" * 64, True), ("a" * 65, False),
])
def test_name_rules(name, ok):
    errors, _ = validate({"name": name, "description": "long enough description here ok"}, name)
    assert (not errors) == ok


def test_name_must_match_folder():
    errors, _ = validate({"name": "abc", "description": "x y z w v u t"}, "other")
    assert any("does not match folder" in e for e in errors)


def test_description_required_and_bounded():
    assert validate({"name": "a"}, "a")[0] == ["missing required field 'description'"]
    errors, _ = validate({"name": "a", "description": "x" * 1025}, "a")
    assert "max 1024" in errors[0]


def test_warnings_for_short_description_and_unknown_field():
    errors, warnings = validate({"name": "a", "description": "short", "colour": "red"}, "a")
    assert not errors
    assert any("very short" in w for w in warnings)
    assert any("'colour'" in w for w in warnings)


def test_metadata_must_be_mapping():
    errors, _ = validate({"name": "a", "description": "one two three four five six",
                          "metadata": "nope"}, "a")
    assert any("metadata" in e for e in errors)


def test_load_skill_dir_fields(tmp_path):
    d = write_skill(tmp_path, "my-skill", "---\nname: my-skill\ndescription: >\n  Does a thing.\n"
                    "  Use when asked.\nallowed-tools: load_skill read_file\nmetadata:\n"
                    "  author: me\n---\n# Steps\n1. go\n")
    s = load_skill_dir(d)
    assert s.description == "Does a thing. Use when asked."
    assert s.allowed_tools == ["load_skill", "read_file"]
    assert s.metadata == {"author": "me"}
    assert s.body.startswith("# Steps")
    assert s.path == d


def test_empty_body_is_a_warning_not_an_error(tmp_path):
    d = write_skill(tmp_path, "empty", "---\nname: empty\ndescription: one two three four five six\n---\n")
    assert any("no instructions" in w for w in load_skill_dir(d).warnings)


def test_missing_skill_file(tmp_path):
    (tmp_path / "nothing").mkdir()
    with pytest.raises(SkillError, match="no SKILL.md"):
        load_skill_dir(tmp_path / "nothing")


def test_discover_shipped_skills_rejects_broken():
    lib = SkillLibrary.discover(SKILLS)
    assert lib.names() == ["commit-message", "incident-severity", "team-glossary",
                           "ticket-checksum", "unit-converter"]
    assert len(lib.rejected) == 1 and "broken_skill" in lib.rejected[0]


def test_discover_first_root_wins_and_missing_root(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write_skill(a, "dup", "---\nname: dup\ndescription: from root a one two three\n---\nA")
    write_skill(b, "dup", "---\nname: dup\ndescription: from root b one two three\n---\nB")
    write_skill(b, ".hidden", "---\nname: x\n---\n")
    lib = SkillLibrary.discover(a, b, tmp_path / "missing")
    assert lib.get("dup").body == "A"
    assert any("duplicate" in r for r in lib.rejected)
    assert any("does not exist" in r for r in lib.rejected)
    assert len(lib.rejected) == 2  # hidden folder is skipped silently


def test_catalog_has_descriptions_but_no_bodies():
    lib = SkillLibrary.discover(SKILLS)
    cat = lib.catalog()
    assert cat.startswith("<available_skills>")
    for s in lib.skills.values():
        assert f"<name>{s.name}</name>" in cat
    assert "Blue Heron Expansion" not in cat  # body text stays out of level 1
    assert "1.609344" not in cat


def test_catalog_escapes_xml(tmp_path):
    write_skill(tmp_path, "esc", "---\nname: esc\ndescription: Use for <b> & \"quotes\" here\n---\nx")
    assert "&lt;b&gt; &amp;" in SkillLibrary.discover(tmp_path).catalog()


def test_empty_catalog():
    assert SkillLibrary().catalog() == "<available_skills>\n</available_skills>"
