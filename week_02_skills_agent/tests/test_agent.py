from pathlib import Path

from skills_agent import LOAD_SKILL, Agent, FakeClient, LLMResponse, SkillLibrary, ToolCall

SKILLS = Path(__file__).resolve().parents[1] / "skills"


def lib():
    return SkillLibrary.discover(SKILLS)


def load(name):
    return LLMResponse(tool_calls=[ToolCall(LOAD_SKILL, {"name": name})])


def test_system_prompt_has_catalog_only():
    fake = FakeClient([LLMResponse(content="hi")])
    Agent(fake, lib()).run("hello")
    system = fake.calls[0][0]["content"]
    assert "<name>team-glossary</name>" in system
    assert "Blue Heron Expansion" not in system


def test_tool_schema_enumerates_skill_names():
    tools = Agent(FakeClient([]), lib()).tools()
    assert len(tools) == 1
    fn = tools[0]["function"]
    assert fn["name"] == LOAD_SKILL
    assert fn["parameters"]["properties"]["name"]["enum"] == lib().names()


def test_no_skills_means_no_tools():
    assert Agent(FakeClient([]), SkillLibrary()).tools() == []


def test_load_skill_returns_body_then_answers():
    fake = FakeClient([load("team-glossary"), LLMResponse(content="BHX is Blue Heron Expansion.")])
    r = Agent(fake, lib()).run("What does BHX mean?")
    assert r.stopped_reason == "final_answer"
    assert r.loaded_skills == ["team-glossary"]
    tool_msg = fake.calls[1][-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["content"].startswith('<skill name="team-glossary">')
    assert "Blue Heron Expansion" in tool_msg["content"]


def test_no_skill_needed():
    r = Agent(FakeClient([LLMResponse(content="ready")]), lib()).run("Say ready")
    assert r.loaded_skills == [] and r.tool_calls == [] and r.answer == "ready"


def test_unknown_skill_lists_available():
    fake = FakeClient([load("nope"), LLMResponse(content="done")])
    r = Agent(fake, lib()).run("x")
    assert r.loaded_skills == []
    msg = fake.calls[1][-1]["content"]
    assert msg.startswith("error: no skill named 'nope'") and "unit-converter" in msg


def test_rejected_skill_cannot_be_loaded():
    fake = FakeClient([load("broken_skill"), LLMResponse(content="done")])
    Agent(fake, lib()).run("x")
    assert "error: no skill named" in fake.calls[1][-1]["content"]


def test_missing_name_and_unknown_tool():
    fake = FakeClient([LLMResponse(tool_calls=[ToolCall(LOAD_SKILL, {}),
                                               ToolCall("shell", {"cmd": "ls"})]),
                       LLMResponse(content="done")])
    Agent(fake, lib()).run("x")
    contents = [m["content"] for m in fake.calls[1] if m["role"] == "tool"]
    assert contents[0] == "error: load_skill needs a 'name' argument"
    assert contents[1].startswith("error: unknown tool 'shell'")


def test_second_load_is_a_short_note():
    fake = FakeClient([load("unit-converter"), load("unit-converter"), LLMResponse(content="ok")])
    r = Agent(fake, lib()).run("convert")
    assert r.loaded_skills == ["unit-converter"]
    second = [m for m in fake.calls[2] if m["role"] == "tool"][-1]["content"]
    assert second.startswith("note:") and "1.609344" not in second


def test_name_is_stripped():
    fake = FakeClient([load(" commit-message "), LLMResponse(content="ok")])
    assert Agent(fake, lib()).run("x").loaded_skills == ["commit-message"]


def test_two_skills_in_one_turn():
    fake = FakeClient([LLMResponse(tool_calls=[ToolCall(LOAD_SKILL, {"name": "team-glossary"}),
                                               ToolCall(LOAD_SKILL, {"name": "unit-converter"})]),
                       LLMResponse(content="ok")])
    r = Agent(fake, lib()).run("x")
    assert r.loaded_skills == ["team-glossary", "unit-converter"]


def test_max_steps():
    fake = FakeClient([load("team-glossary")] * 10)
    r = Agent(fake, lib(), max_steps=3).run("loop")
    assert r.stopped_reason == "max_steps" and len(fake.calls) == 3


def test_assistant_tool_calls_recorded_in_history():
    fake = FakeClient([load("team-glossary"), LLMResponse(content="ok")])
    r = Agent(fake, lib()).run("x")
    assistant = [m for m in r.messages if m["role"] == "assistant"][0]
    assert assistant["tool_calls"][0]["function"]["name"] == LOAD_SKILL
