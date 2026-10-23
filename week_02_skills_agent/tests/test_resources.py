"""Level 3 disclosure: skill files read on demand, confined to the skill folder."""

import os
from pathlib import Path

import pytest

from skills_agent import (
    LOAD_SKILL, READ_SKILL_FILE, Agent, FakeClient, LLMResponse, SkillError, SkillLibrary,
    ToolCall, list_resources, load_skill_dir, read_resource, resolve_resource,
)

SKILLS = Path(__file__).resolve().parents[1] / "skills"
MATRIX = "references/severity-matrix.md"


def make_skill(root: Path, name: str = "demo") -> Path:
    d = root / name
    (d / "references").mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: a demo skill used only by the tests here\n---\n"
        "Read references/notes.md\n", encoding="utf-8")
    (d / "references" / "notes.md").write_text("secret note: kiwi\n", encoding="utf-8")
    return d


def load(name):
    return LLMResponse(tool_calls=[ToolCall(LOAD_SKILL, {"name": name})])


def read(skill, path):
    return LLMResponse(tool_calls=[ToolCall(READ_SKILL_FILE, {"skill": skill, "path": path})])


def tool_msgs(fake, turn):
    return [m["content"] for m in fake.calls[turn] if m["role"] == "tool"]


# ---- skills.py -------------------------------------------------------------

def test_list_resources_skips_skill_md_hidden_and_symlinks(tmp_path):
    d = make_skill(tmp_path)
    (d / ".secret").write_text("x")
    (d / ".git").mkdir()
    (d / ".git" / "config").write_text("x")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    os.symlink(outside, d / "link.txt")
    assert list_resources(load_skill_dir(d)) == ["references/notes.md"]


def test_list_resources_limit(tmp_path):
    d = make_skill(tmp_path)
    for i in range(5):
        (d / f"f{i}.txt").write_text("x")
    assert len(list_resources(load_skill_dir(d), limit=3)) == 3


def test_read_resource_ok_and_dot_slash(tmp_path):
    s = load_skill_dir(make_skill(tmp_path))
    assert read_resource(s, "references/notes.md") == ("secret note: kiwi\n", False)
    assert read_resource(s, "./references/notes.md")[0].startswith("secret")


@pytest.mark.parametrize("bad, msg", [
    ("", "empty"), ("   ", "empty"), (".", "empty"),
    ("/etc/passwd", "relative"), ("C:/x.txt", "relative"),
    ("../demo/SKILL.md", "'..'"), ("references/../../x", "'..'"),
    ("references\\..\\SKILL.md", "'..'"),
    (".env", "hidden"), ("SKILL.md", "load_skill"),
    ("references/missing.md", "no file"), ("references", "not a file"),
])
def test_resolve_refuses(tmp_path, bad, msg):
    s = load_skill_dir(make_skill(tmp_path))
    with pytest.raises(SkillError, match=msg):
        resolve_resource(s, bad)


def test_symlink_escape_is_refused(tmp_path):
    d = make_skill(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("password")
    os.symlink(secret, d / "references" / "escape.md")
    os.symlink(tmp_path, d / "up")
    s = load_skill_dir(d)
    with pytest.raises(SkillError, match="outside"):
        read_resource(s, "references/escape.md")
    with pytest.raises(SkillError, match="outside"):
        read_resource(s, "up/secret.txt")


def test_symlink_inside_the_folder_is_allowed(tmp_path):
    d = make_skill(tmp_path)
    os.symlink(d / "references" / "notes.md", d / "alias.md")
    assert read_resource(load_skill_dir(d), "alias.md")[0].startswith("secret")


def test_size_cap_truncates(tmp_path):
    d = make_skill(tmp_path)
    (d / "big.txt").write_text("a" * 100)
    text, truncated = read_resource(load_skill_dir(d), "big.txt", max_bytes=10)
    assert text == "a" * 10 and truncated


def test_truncation_inside_multibyte_char_is_trimmed(tmp_path):
    d = make_skill(tmp_path)
    (d / "u.txt").write_text("ab" + "é" * 10, encoding="utf-8")  # é is 2 bytes
    text, truncated = read_resource(load_skill_dir(d), "u.txt", max_bytes=5)
    assert text == "abé" and truncated


def test_binary_and_non_utf8_refused(tmp_path):
    d = make_skill(tmp_path)
    (d / "b.bin").write_bytes(b"PK\x00\x01")
    (d / "l.txt").write_bytes(b"caf\xe9 au lait")
    s = load_skill_dir(d)
    with pytest.raises(SkillError, match="binary"):
        read_resource(s, "b.bin")
    with pytest.raises(SkillError, match="UTF-8"):
        read_resource(s, "l.txt")


def test_shipped_incident_skill_has_its_matrix():
    s = SkillLibrary.discover(SKILLS).get("incident-severity")
    assert MATRIX in s.body
    assert list_resources(s) == [MATRIX]
    assert "Code Crimson" in read_resource(s, MATRIX)[0]


# ---- agent.py --------------------------------------------------------------

def test_load_skill_lists_bundled_files_but_not_their_content():
    fake = FakeClient([load("incident-severity"), LLMResponse(content="ok")])
    Agent(fake, SkillLibrary.discover(SKILLS)).run("x")
    body = tool_msgs(fake, 1)[0]
    assert f"<skill_files>\n{MATRIX}\n</skill_files>" in body
    assert "Code Crimson" not in body


def test_skill_without_files_has_no_listing():
    fake = FakeClient([load("team-glossary"), LLMResponse(content="ok")])
    Agent(fake, SkillLibrary.discover(SKILLS)).run("x")
    assert "<skill_files>" not in tool_msgs(fake, 1)[0]


def test_read_after_load_returns_file_and_records_it():
    fake = FakeClient([load("incident-severity"), read("incident-severity", MATRIX),
                       read("incident-severity", "./" + MATRIX), LLMResponse(content="SEV-1")])
    r = Agent(fake, SkillLibrary.discover(SKILLS)).run("checkout is down")
    msg = tool_msgs(fake, 2)[-1]
    assert msg.startswith(f'<skill_file skill="incident-severity" path="{MATRIX}">')
    assert "Code Crimson" in msg
    assert r.read_files == [f"incident-severity/{MATRIX}"]  # second read is not a new entry


def test_read_before_load_is_refused():
    fake = FakeClient([read("incident-severity", MATRIX), LLMResponse(content="ok")])
    r = Agent(fake, SkillLibrary.discover(SKILLS)).run("x")
    msg = tool_msgs(fake, 1)[0]
    assert msg.startswith("error: skill 'incident-severity' is not loaded")
    assert "Code Crimson" not in msg and r.read_files == []


def test_read_errors_list_available_files():
    fake = FakeClient([load("incident-severity"),
                       read("incident-severity", "../team-glossary/SKILL.md"),
                       read("incident-severity", "references/nope.md"),
                       LLMResponse(content="ok")])
    Agent(fake, SkillLibrary.discover(SKILLS)).run("x")
    traversal, missing = tool_msgs(fake, 3)[-2:]
    assert traversal.startswith("error: path") and "'..'" in traversal
    assert "Blue Heron" not in traversal
    assert missing.startswith("error: no file") and MATRIX in missing


def test_read_argument_errors():
    calls = [ToolCall(READ_SKILL_FILE, {"path": "x"}),
             ToolCall(READ_SKILL_FILE, {"skill": "team-glossary"}),
             ToolCall(READ_SKILL_FILE, {"skill": "nope", "path": "x"})]
    fake = FakeClient([LLMResponse(tool_calls=calls), LLMResponse(content="ok")])
    Agent(fake, SkillLibrary.discover(SKILLS)).run("x")
    a, b, c = tool_msgs(fake, 1)
    assert a == "error: read_skill_file needs a 'skill' argument"
    assert b == "error: read_skill_file needs a 'path' argument"
    assert c == "error: no skill named 'nope'"


def test_no_read_tool_when_no_skill_has_files(tmp_path):
    root = tmp_path / "skills"
    d = root / "solo"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: solo\ndescription: one skill with no extra files at all\n---\nhi\n")
    tools = Agent(FakeClient([]), SkillLibrary.discover(root)).tools()
    assert [t["function"]["name"] for t in tools] == [LOAD_SKILL]


def test_truncation_note_reaches_the_model(tmp_path, monkeypatch):
    import skills_agent.skills as sk
    monkeypatch.setattr(sk, "RESOURCE_MAX_BYTES", 8)
    monkeypatch.setattr(sk.read_resource, "__defaults__", (8,))
    d = make_skill(tmp_path / "skills")
    fake = FakeClient([load("demo"), read("demo", "references/notes.md"),
                       LLMResponse(content="ok")])
    Agent(fake, SkillLibrary.discover(d.parent)).run("x")
    msg = tool_msgs(fake, 2)[-1]
    assert "secret n" in msg and "kiwi" not in msg and "[truncated" in msg


def test_system_prompt_mentions_read_tool_and_no_file_content():
    fake = FakeClient([LLMResponse(content="hi")])
    Agent(fake, SkillLibrary.discover(SKILLS)).run("hello")
    system = fake.calls[0][0]["content"]
    assert READ_SKILL_FILE in system and "Code Crimson" not in system
