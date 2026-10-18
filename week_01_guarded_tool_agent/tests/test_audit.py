import json

import pytest

from guarded_agent import (
    Agent, AuditLog, FakeClient, LLMResponse, Policy, ToolCall, ToolRegistry, default_tools,
    load_events, replay,
)
from guarded_agent.__main__ import main as cli_main
from guarded_agent.audit import MAX_FIELD_CHARS, check_run, clip, group_runs
from guarded_agent.tools import Tool


def run_logged(tmp_path, responses, policy=None, tools=None, approver=None):
    log = AuditLog(tmp_path / "audit.jsonl")
    agent = Agent(FakeClient(responses), ToolRegistry(tools or default_tools()),
                  policy=policy or Policy.allow_all(), approver=approver, audit=log)
    result = agent.run("task")
    events, bad = load_events(log.path)
    assert bad == 0
    return result, events, log


def test_full_run_is_logged_in_order(tmp_path):
    result, events, log = run_logged(tmp_path, [
        LLMResponse(tool_calls=[ToolCall("calculator", {"expression": "17 * 23"})]),
        LLMResponse(content="391"),
    ])
    assert [e["type"] for e in events] == [
        "run_start", "model_reply", "tool_decision", "tool_result", "model_reply", "run_end"]
    assert [e["seq"] for e in events] == list(range(6))
    assert {e["run_id"] for e in events} == {log.run_id}
    start, _, decision, res, _, end = events
    assert start["task"] == "task" and start["model"] == "FakeClient"
    assert "calculator" in start["tools"]
    assert decision["verdict"] == "allow" and decision["approved"] is True
    assert decision["arguments"] == {"expression": "17 * 23"} and decision["step"] == 1
    assert res["output"] == "391" and res["ran"] is True
    assert end["stopped_reason"] == "final_answer" and end["tool_calls"] == 1
    assert check_run(events) == []


def test_verdict_is_on_disk_before_the_tool_runs(tmp_path):
    path = tmp_path / "audit.jsonl"
    seen = {}

    def spy() -> str:
        seen["types"] = [json.loads(line)["type"] for line in path.read_text().splitlines()]
        return "ok"

    tool = Tool("spy", "test tool", {"type": "object", "properties": {}}, spy)
    agent = Agent(FakeClient([LLMResponse(tool_calls=[ToolCall("spy", {})]),
                              LLMResponse(content="done")]),
                  ToolRegistry([tool]), policy=Policy.allow_all(), audit=AuditLog(path))
    agent.run("t")
    assert seen["types"][-1] == "tool_decision"


def test_blocked_and_unknown_calls_are_logged(tmp_path):
    policy = Policy.from_dict({"default": "deny", "tools": {"calculator": "allow"}})
    result, events, _ = run_logged(tmp_path, [
        LLMResponse(tool_calls=[ToolCall("current_time", {}), ToolCall("rm_rf", {"path": "/"})]),
        LLMResponse(content="blocked"),
    ], policy=policy)
    decisions = [e for e in events if e["type"] == "tool_decision"]
    assert [(d["tool"], d["verdict"], d["approved"]) for d in decisions] == [
        ("current_time", "deny", False), ("rm_rf", "deny", False)]
    assert decisions[1]["reason"] == "unknown tool"
    results = [e for e in events if e["type"] == "tool_result"]
    assert all(r["ran"] is False for r in results)
    assert events[-1]["blocked"] == 2


def test_human_decline_is_logged(tmp_path):
    policy = Policy.from_dict({"tools": {"calculator": "ask"}})
    _, events, _ = run_logged(tmp_path, [
        LLMResponse(tool_calls=[ToolCall("calculator", {"expression": "1+1"})]),
        LLMResponse(content="ok"),
    ], policy=policy, approver=lambda *a: False)
    d = next(e for e in events if e["type"] == "tool_decision")
    assert d["verdict"] == "ask" and d["approved"] is False and "human declined" in d["reason"]


def test_llm_crash_writes_run_error_and_reraises(tmp_path):
    class Boom:
        def chat(self, messages, tools):
            raise ConnectionError("ollama down")

    log = AuditLog(tmp_path / "a.jsonl")
    with pytest.raises(ConnectionError):
        Agent(Boom(), ToolRegistry(default_tools()), audit=log).run("t")
    events, _ = load_events(log.path)
    assert events[-1]["type"] == "run_error" and "ollama down" in events[-1]["error"]
    assert check_run(events) == []


def test_long_strings_are_clipped():
    text = "x" * (MAX_FIELD_CHARS + 50)
    out = clip({"content": text, "nested": [text]})
    assert out["content"].endswith("...[clipped 50 chars]")
    assert len(out["nested"][0]) < len(text)
    assert clip(5) == 5 and clip(None) is None


def test_two_runs_share_a_file_but_not_a_run_id(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    for _ in range(2):
        Agent(FakeClient([LLMResponse(content="hi")]), ToolRegistry(), audit=log).run("t")
    runs = group_runs(load_events(log.path)[0])
    assert len(runs) == 2
    assert all(evs[0]["seq"] == 0 for evs in runs.values())


def test_replay_timeline_and_filters(tmp_path):
    policy = Policy.from_dict({"default": "deny", "tools": {"calculator": "allow"}})
    _, _, log = run_logged(tmp_path, [
        LLMResponse(tool_calls=[ToolCall("calculator", {"expression": "2 ** 12"}),
                                ToolCall("current_time", {})]),
        LLMResponse(content="4096"),
    ], policy=policy)
    text = replay(log.path)
    assert f"run {log.run_id}" in text
    assert "[1] model asks for calculator" in text
    assert "policy calculator: verdict=allow -> RAN" in text
    assert "policy current_time: verdict=deny -> BLOCKED" in text
    assert "[1] result calculator: 4096" in text
    assert "[2] model answers: 4096" in text
    assert "end: final_answer after 2 step(s), 2 tool call(s), 1 blocked" in text
    assert "WARNING" not in text
    assert replay(log.path, log.run_id[:4]).startswith(f"run {log.run_id}")
    assert replay(log.path, "zzzz").startswith("no run matching")


def test_replay_survives_damaged_logs(tmp_path):
    _, _, log = run_logged(tmp_path, [LLMResponse(content="hi")])
    lines = log.path.read_text().splitlines()
    # drop run_end (a crash mid run) and add garbage
    log.path.write_text("\n".join(lines[:-1] + ["{not json", "[1, 2]"]) + "\n")
    text = replay(log.path)
    assert "WARNING: run did not finish" in text
    assert "(skipped 2 malformed line(s))" in text


def test_check_run_spots_result_without_verdict():
    evs = [{"run_id": "r", "seq": 0, "type": "run_start"},
           {"run_id": "r", "seq": 1, "type": "tool_result", "tool": "x"},
           {"run_id": "r", "seq": 2, "type": "run_end"}]
    problems = check_run(evs)
    assert any("before any tool_decision" in p for p in problems)


def test_unknown_event_type_rejected(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    with pytest.raises(RuntimeError):
        log.write("run_end")
    log.start_run()
    with pytest.raises(ValueError):
        log.write("whatever")


def test_cli_replay(tmp_path, capsys):
    _, _, log = run_logged(tmp_path, [LLMResponse(content="hi")])
    assert cli_main(["replay", str(log.path)]) == 0
    assert "model answers: hi" in capsys.readouterr().out
    assert cli_main(["replay", str(tmp_path / "missing.jsonl")]) == 2
