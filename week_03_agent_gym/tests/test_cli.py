import json

from agent_gym.cli import main
from agent_gym.llm import FakeClient, LLMResponse, ToolCall
from agent_gym.types import SUBMIT


def test_list_json(capsys):
    assert main(["list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [r["task"] for r in data["tasks"]][0] == "create_explicit"


def test_run_unknown_task_and_bad_args(capsys):
    assert main(["run", "nope"]) == 2
    assert main(["run", "create_explicit", "--max-steps", "0"]) == 2
    assert main(["fly"]) == 2


def test_run_fake_success_and_failure(capsys):
    ok = FakeClient([LLMResponse(tool_calls=[ToolCall("create_event", {
        "calendar_id": "cal_team", "title": "Design review", "date": "2026-11-02",
        "start": "10:00", "end": "10:30"})]), LLMResponse(tool_calls=[ToolCall(SUBMIT, {})])])
    assert main(["run", "create_explicit", "--json"], client=ok) == 0
    assert json.loads(capsys.readouterr().out)["reward"] == 1.0
    assert main(["run", "create_explicit"], client=FakeClient([LLMResponse("done")])) == 1
    assert "problem: missing event" in capsys.readouterr().out


def test_run_ollama_missing():
    assert main(["run", "create_explicit"], check=lambda m: (False, "down")) == 4


def test_run_breakdown_flag_prints_rubric_tree(capsys):
    from agent_gym.cli import main
    from agent_gym.llm import FakeClient, LLMResponse, ToolCall
    client = FakeClient([LLMResponse(tool_calls=[ToolCall("nope", {})]),
                         LLMResponse(tool_calls=[ToolCall("create_event", {
                             "calendar_id": "cal_team", "title": "Design review",
                             "date": "2026-11-02", "start": "10:00", "end": "10:30"})]),
                         LLMResponse(tool_calls=[ToolCall("submit", {})])])
    assert main(["run", "create_explicit", "--breakdown"], client=client) == 0
    out = capsys.readouterr().out
    assert "PASS | reward 0.96" in out and "reward breakdown:" in out
    assert "1 refused step(s) -0.2" in out


def test_list_shows_pairs_and_inbox(capsys):
    assert main(["list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["tasks"]
    by = {(r["env"], r["task"]): r for r in rows}
    assert by[("inbox", "assign_by_name")]["pair"] == "assign"
    assert by[("inbox", "assign_by_name")]["variant"] == "name"
    assert by[("calendar", "create_explicit")]["pair"] == ""


def test_run_env_prefix(capsys):
    ok = FakeClient([LLMResponse(tool_calls=[ToolCall("set_status", {
        "ticket_id": "T-1002", "status": "closed"})]), LLMResponse(tool_calls=[ToolCall(SUBMIT, {})])])
    assert main(["run", "inbox/close_by_id"], client=ok) == 0
    assert "PASS | reward 1.0" in capsys.readouterr().out
    assert main(["run", "mars/close_by_id"]) == 2
    assert main(["run", "inbox/close_by_id", "--env", "calendar"]) == 2
    assert main(["run", "close_by_id"]) == 2  # default env is calendar
