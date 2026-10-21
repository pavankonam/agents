"""MCP client tests. They start the stdlib demo server as a real subprocess
(no model, no network, well under a second each)."""

import json
import sys
from pathlib import Path

import pytest

from guarded_agent import unwrap  # noqa: E402
from guarded_agent import (
    Agent, AuditLog, FakeClient, LLMResponse, MCPClient, MCPError, Policy, ToolCall,
    ToolRegistry, connect_mcp, default_tools, load_events,
)
from guarded_agent.audit import check_run
from guarded_agent.mcp import load_servers, minimal_env, result_text, safe_name

PROJECT = Path(__file__).resolve().parents[1]
SERVER = PROJECT / "src" / "guarded_agent" / "demo_mcp_server.py"
POLICY = PROJECT / "policy.json"


def demo(env=None, timeout=10.0, name="demo"):
    client = MCPClient(name, [sys.executable, str(SERVER)], env=env, timeout=timeout)
    client.initialize()
    return client


@pytest.fixture
def client():
    c = demo()
    yield c
    c.close()


def test_handshake_and_namespaced_tools(client):
    assert client.server_info["serverInfo"]["name"] == "guarded-agent-demo"
    methods = [m["method"] for m in client.sent]
    assert methods[0] == "initialize"
    tools = {t.name: t for t in client.tools()}
    assert {"demo__word_count", "demo__reverse", "demo__shell_exec"} <= set(tools)
    wc = tools["demo__word_count"]
    assert wc.description.startswith("[MCP server 'demo']")
    assert wc.parameters["required"] == ["text"]
    assert wc.schema()["function"]["name"] == "demo__word_count"


def test_call_returns_text_and_errors_are_prefixed(client):
    assert client.call_tool("word_count", {"text": "the quick brown fox"}) == "4"
    assert client.call_tool("reverse", {"text": "abc"}) == "cba"
    assert client.call_tool("fail", {"message": "nope"}) == "error: demo__fail: nope"
    with pytest.raises(MCPError, match="unknown tool"):
        client.call_tool("missing", {})


def test_pagination_is_followed():
    c = demo(env={"DEMO_MCP_PAGE_SIZE": "2"})
    try:
        names = [t["name"] for t in c.list_tools()]
        assert len(names) == 5
        cursors = [m.get("params", {}).get("cursor") for m in c.sent if m["method"] == "tools/list"]
        assert cursors == [None, "2", "4"]
    finally:
        c.close()


def test_server_crash_and_timeout_become_tool_errors():
    c = demo()
    reg = ToolRegistry(c.tools())
    out = reg.call("demo__crash", {})
    assert out.startswith("error: demo__crash failed:") and "exited" in out
    assert not c.running
    assert reg.call("demo__word_count", {"text": "a"}).startswith("error:")  # stays dead, no hang
    c.close()
    slow = demo(env={"DEMO_MCP_SLOW": "2"}, timeout=0.3)
    try:
        assert "timed out" in ToolRegistry(slow.tools()).call("demo__reverse", {"text": "x"})
    finally:
        slow.close()


def test_shipped_policy_routes_mcp_tools(client):
    policy = Policy.from_file(POLICY)
    assert policy.check("demo__word_count", {"text": "a b"}).verdict == "allow"
    assert policy.check("demo__word_count", {"text": "a " * 3000}).verdict == "deny"  # rule
    rev = policy.check("demo__reverse", {"text": "x"})
    assert rev.verdict == "ask" and "via pattern 'demo__*'" in rev.reason
    assert policy.check("demo__shell_exec", {"command": "ls"}).verdict == "deny"
    assert policy.check("other__anything", {}).verdict == "deny"  # default


def test_denied_mcp_call_never_reaches_the_server(client, tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    llm = FakeClient([
        LLMResponse(tool_calls=[ToolCall("demo__shell_exec", {"command": "rm -rf ~"})]),
        LLMResponse(tool_calls=[ToolCall("demo__word_count", {"text": "one two three"})]),
        LLMResponse(content="3 words; the shell call was blocked."),
    ])
    agent = Agent(llm, ToolRegistry(default_tools() + client.tools()),
                  policy=Policy.from_file(POLICY), audit=log)
    result = agent.run("count words and run a shell command")
    tool_msgs = [m["content"] for m in result.messages if m["role"] == "tool"]
    assert tool_msgs[0].startswith("error: denied by policy")
    assert "CANARY" not in "".join(tool_msgs)
    assert tool_msgs[1].startswith("<<untrusted output of demo__word_count")  # D37
    assert unwrap(tool_msgs[1]) == "3"
    called = [m["params"]["name"] for m in client.sent if m["method"] == "tools/call"]
    assert called == ["word_count"]  # shell_exec was never sent to the server
    events, _ = load_events(log.path)
    assert check_run(events) == []
    verdicts = [(e["tool"], e["verdict"]) for e in events if e["type"] == "tool_decision"]
    assert verdicts == [("demo__shell_exec", "deny"), ("demo__word_count", "allow")]


def test_ask_mcp_tool_uses_the_approver(client):
    seen = []

    def approver(tool, args, reason):
        seen.append(tool)
        return False

    llm = FakeClient([LLMResponse(tool_calls=[ToolCall("demo__reverse", {"text": "hi"})]),
                      LLMResponse(content="declined")])
    result = Agent(llm, ToolRegistry(client.tools()), policy=Policy.from_file(POLICY),
                   approver=approver).run("reverse hi")
    assert seen == ["demo__reverse"]
    assert result.decisions[0].approved is False
    assert not [m for m in client.sent if m["method"] == "tools/call"]


def test_policy_pattern_precedence():
    p = Policy.from_dict({"default": "deny", "tools": {
        "*": "ask", "demo__*": "allow", "demo__shell*": "deny", "demo__shell_safe": "allow"}})
    assert p.check("demo__shell_exec", {}).verdict == "deny"     # longer pattern wins
    assert p.check("demo__shell_safe", {}).verdict == "allow"    # exact name wins
    assert p.check("demo__reverse", {}).verdict == "allow"
    assert p.check("calculator", {}).verdict == "ask"            # catch all pattern


def test_server_env_is_minimal(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    env = minimal_env({"EXTRA": "1"})
    assert "GITHUB_TOKEN" not in env and env["EXTRA"] == "1"
    assert env.get("PATH")


def test_config_loading_and_connect(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"servers": {"my.srv": {
        "command": "python3", "args": [str(SERVER)], "env": {"DEMO_MCP_PAGE_SIZE": "1"}}}}))
    spec = load_servers(cfg)["my.srv"]
    assert spec["command"][0] == sys.executable and spec["cwd"] == tmp_path.resolve()
    clients, tools = connect_mcp(cfg)
    try:
        assert len(tools) == 5 and all(t.name.startswith("my_srv__") for t in tools)
    finally:
        for c in clients:
            c.close()
    assert not clients[0].running
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"servers": {"x": {"args": []}}}))
    with pytest.raises(ValueError):
        load_servers(bad)


def test_shipped_config_starts_the_demo_server():
    clients, tools = connect_mcp(PROJECT / "mcp_servers.json")
    try:
        assert "demo__word_count" in {t.name for t in tools}
    finally:
        for c in clients:
            c.close()


def test_helpers():
    assert safe_name("my server/v2") == "my_server_v2"
    assert result_text({"content": [{"type": "text", "text": "a"},
                                    {"type": "image", "data": "..."}]}) == "a\n[image content omitted]"
    assert result_text({"content": [], "structuredContent": {"n": 1}}) == '{"n": 1}'
    with pytest.raises(ValueError):
        MCPClient("x", [])
