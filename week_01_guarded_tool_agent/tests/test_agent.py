import pytest

from guarded_agent import Agent, FakeClient, LLMResponse, ToolCall, ToolRegistry, default_tools
from guarded_agent.llm import parse_ollama_message
from guarded_agent.tools import safe_eval


def make_agent(responses, max_steps=6):
    llm = FakeClient(responses)
    return Agent(llm, ToolRegistry(default_tools()), max_steps=max_steps), llm


def test_final_answer_without_tools():
    agent, _ = make_agent([LLMResponse(content="Hello!")])
    result = agent.run("say hi")
    assert result.answer == "Hello!"
    assert result.tool_calls == []
    assert result.steps == 1
    assert result.stopped_reason == "final_answer"


def test_tool_call_then_answer():
    agent, llm = make_agent([
        LLMResponse(tool_calls=[ToolCall("calculator", {"expression": "17 * 23"})]),
        LLMResponse(content="17 * 23 = 391"),
    ])
    result = agent.run("what is 17 * 23?")
    assert result.answer == "17 * 23 = 391"
    assert [c.name for c in result.tool_calls] == ["calculator"]
    tool_msgs = [m for m in result.messages if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "391"
    # the second model call must have seen the tool result
    assert llm.calls[1][-1]["content"] == "391"


def test_unknown_tool_is_reported_not_raised():
    agent, _ = make_agent([
        LLMResponse(tool_calls=[ToolCall("rm_rf", {})]),
        LLMResponse(content="sorry"),
    ])
    result = agent.run("delete everything")
    tool_msg = [m for m in result.messages if m["role"] == "tool"][0]
    assert tool_msg["content"].startswith("error: unknown tool")


def test_bad_arguments_are_reported():
    agent, _ = make_agent([
        LLMResponse(tool_calls=[ToolCall("calculator", {"expr": "1+1"})]),
        LLMResponse(content="oops"),
    ])
    result = agent.run("1+1")
    tool_msg = [m for m in result.messages if m["role"] == "tool"][0]
    assert tool_msg["content"].startswith("error: bad arguments")


def test_max_steps_guard():
    looping = [LLMResponse(tool_calls=[ToolCall("current_time", {})]) for _ in range(10)]
    agent, _ = make_agent(looping, max_steps=3)
    result = agent.run("loop")
    assert result.stopped_reason == "max_steps"
    assert result.steps == 3
    assert len(result.tool_calls) == 3


def test_max_steps_must_be_positive():
    with pytest.raises(ValueError):
        Agent(FakeClient([]), ToolRegistry(), max_steps=0)


@pytest.mark.parametrize("expr,expected", [
    ("1 + 2 * 3", 7), ("(1 + 2) * 3", 9), ("2 ** 10", 1024), ("-5 + 2", -3), ("7 // 2", 3),
])
def test_safe_eval_arithmetic(expr, expected):
    assert safe_eval(expr) == expected


@pytest.mark.parametrize("expr", [
    "__import__('os').system('ls')", "open('x')", "a + 1", "(1).real", "2 ** 1000",
])
def test_safe_eval_rejects_code(expr):
    with pytest.raises(ValueError):
        safe_eval(expr)


def test_calculator_errors_come_back_as_text():
    reg = ToolRegistry(default_tools())
    assert reg.call("calculator", {"expression": "open('x')"}).startswith("error:")


def test_duplicate_tool_names_rejected():
    reg = ToolRegistry(default_tools())
    with pytest.raises(ValueError):
        reg.register(default_tools()[0])


def test_schemas_are_ollama_shape():
    schemas = ToolRegistry(default_tools()).schemas()
    assert {s["function"]["name"] for s in schemas} == {"calculator", "current_time"}
    assert all(s["type"] == "function" for s in schemas)


def test_parse_ollama_message_with_string_arguments():
    msg = {"content": "", "tool_calls": [
        {"function": {"name": "calculator", "arguments": '{"expression": "2+2"}'}}]}
    resp = parse_ollama_message(msg)
    assert resp.tool_calls[0].arguments == {"expression": "2+2"}


def test_current_time_timezone():
    reg = ToolRegistry(default_tools())
    assert reg.call("current_time", {"tz": "America/Chicago"})[:2] == "20"
    assert reg.call("current_time", {"tz": "Not/AZone"}).startswith("error:")
