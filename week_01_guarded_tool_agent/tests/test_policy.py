import json

import pytest

from guarded_agent import Agent, FakeClient, LLMResponse, Policy, ToolCall, ToolRegistry, default_tools
from guarded_agent.tools import Tool

calls_made = []


def _spy(**kwargs):
    calls_made.append(kwargs)
    return "spy ran"


spy_tool = Tool("spy", "records calls", {"type": "object", "properties": {
    "path": {"type": "string"}, "mode": {"type": "string"}}}, _spy)


@pytest.fixture(autouse=True)
def _reset():
    calls_made.clear()


def run(policy, call, approver=None, extra=None):
    llm = FakeClient([LLMResponse(tool_calls=[call]), LLMResponse(content="done")])
    reg = ToolRegistry(default_tools() + [spy_tool])
    agent = Agent(llm, reg, policy=policy, approver=approver)
    result = agent.run("task")
    tool_msg = [m for m in result.messages if m["role"] == "tool"][0]["content"]
    return result, tool_msg


def test_allow_runs_tool_and_records_verdict():
    p = Policy.from_dict({"tools": {"calculator": "allow"}})
    result, msg = run(p, ToolCall("calculator", {"expression": "2+3"}))
    assert msg == "5"
    d = result.decisions[0]
    assert (d.verdict, d.approved) == ("allow", True)


def test_deny_never_runs_and_model_is_told():
    p = Policy.from_dict({"tools": {"spy": "deny"}})
    result, msg = run(p, ToolCall("spy", {"path": "x"}))
    assert calls_made == []
    assert msg.startswith("error: denied by policy")
    assert result.answer == "done"  # run continued instead of crashing


def test_unlisted_tool_uses_default_deny():
    p = Policy.from_dict({"default": "deny", "tools": {}})
    result, msg = run(p, ToolCall("calculator", {"expression": "1+1"}))
    assert msg.startswith("error: denied by policy")
    assert result.decisions[0].reason.startswith("default policy")


def test_agent_without_policy_fails_closed():
    llm = FakeClient([LLMResponse(tool_calls=[ToolCall("calculator", {"expression": "1+1"})]),
                      LLMResponse(content="ok")])
    result = Agent(llm, ToolRegistry(default_tools())).run("1+1")
    assert result.decisions[0].approved is False


def test_ask_without_approver_is_denied():
    p = Policy.from_dict({"tools": {"spy": "ask"}})
    result, msg = run(p, ToolCall("spy", {"path": "a"}))
    assert calls_made == []
    assert "no approver" in result.decisions[0].reason


@pytest.mark.parametrize("answer,ran", [(True, True), (False, False)])
def test_ask_uses_approver(answer, ran):
    seen = []

    def approver(tool, args, reason):
        seen.append((tool, args))
        return answer

    p = Policy.from_dict({"tools": {"spy": "ask"}})
    result, msg = run(p, ToolCall("spy", {"path": "a"}), approver=approver)
    assert seen == [("spy", {"path": "a"})]
    assert bool(calls_made) is ran
    assert result.decisions[0].approved is ran
    assert (msg == "spy ran") is ran


def test_approver_exception_fails_closed():
    def boom(*a):
        raise RuntimeError("tty gone")

    p = Policy.from_dict({"tools": {"spy": "ask"}})
    result, _ = run(p, ToolCall("spy", {"path": "a"}), approver=boom)
    assert calls_made == [] and "approver failed" in result.decisions[0].reason


def test_rule_violation_denies_even_allowed_tool_and_skips_approver(tmp_path):
    p = Policy.from_dict({"tools": {"spy": {"verdict": "ask", "rules": [
        {"arg": "path", "type": "path_within", "value": "workspace"}]}}}, base_dir=tmp_path)
    asked = []
    result, msg = run(p, ToolCall("spy", {"path": "../secrets.txt"}),
                      approver=lambda *a: asked.append(a) or True)
    assert calls_made == [] and asked == []
    assert result.decisions[0].verdict == "deny"


@pytest.mark.parametrize("path,ok", [
    ("notes.txt", True), ("sub/dir/a.md", True), ("../x", False),
    ("sub/../../x", False), ("/etc/passwd", False),
])
def test_path_within(tmp_path, path, ok):
    (tmp_path / "workspace").mkdir()
    p = Policy.from_dict({"tools": {"spy": {"verdict": "allow", "rules": [
        {"arg": "path", "type": "path_within", "value": "workspace"}]}}}, base_dir=tmp_path)
    assert (p.check("spy", {"path": path}).verdict == "allow") is ok


def test_path_within_blocks_symlink_escape(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "link").symlink_to(tmp_path)
    p = Policy.from_dict({"tools": {"spy": {"verdict": "allow", "rules": [
        {"arg": "path", "type": "path_within", "value": "workspace"}]}}}, base_dir=tmp_path)
    assert p.check("spy", {"path": "link/outside.txt"}).verdict == "deny"


def test_pattern_one_of_and_max_length():
    p = Policy.from_dict({"tools": {"spy": {"verdict": "allow", "rules": [
        {"arg": "path", "type": "pattern", "value": r"[a-z]+\.txt"},
        {"arg": "mode", "type": "one_of", "value": ["r", "w"]},
        {"arg": "path", "type": "max_length", "value": 10}]}}})
    assert p.check("spy", {"path": "a.txt", "mode": "r"}).verdict == "allow"
    assert p.check("spy", {"path": "a.txt; rm", "mode": "r"}).verdict == "deny"
    assert p.check("spy", {"path": "a.txt", "mode": "x"}).verdict == "deny"
    assert p.check("spy", {"path": "abcdefghij.txt"}).verdict == "deny"


@pytest.mark.parametrize("bad", [
    {"default": "maybe"},
    {"tools": {"spy": "sometimes"}},
    {"tools": {"spy": {"verdict": "allow", "rules": [{"arg": "p", "type": "glob", "value": "*"}]}}},
])
def test_invalid_policy_rejected(bad):
    with pytest.raises(ValueError):
        Policy.from_dict(bad)


def test_unknown_tool_recorded_as_deny():
    result, msg = run(Policy.allow_all(), ToolCall("rm_rf", {}))
    assert msg.startswith("error: unknown tool")
    assert result.decisions[0].verdict == "deny"


def test_every_tool_call_has_a_decision():
    calls = [ToolCall("calculator", {"expression": "1+1"}), ToolCall("spy", {"path": "a"}),
             ToolCall("nope", {})]
    llm = FakeClient([LLMResponse(tool_calls=calls), LLMResponse(content="done")])
    p = Policy.from_dict({"tools": {"calculator": "allow"}})
    result = Agent(llm, ToolRegistry(default_tools() + [spy_tool]), policy=p).run("t")
    assert len(result.decisions) == len(result.tool_calls) == 3
    assert [d.approved for d in result.decisions] == [True, False, False]


def test_shipped_policy_file_loads():
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "policy.json"
    p = Policy.from_file(path)
    assert p.default == "deny"
    assert p.check("calculator", {"expression": "1+1"}).verdict == "allow"
    assert p.check("calculator", {"expression": "1+" * 200}).verdict == "deny"
    json.loads(path.read_text())
