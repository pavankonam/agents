import pytest

from agent_gym.agent import run_episode
from agent_gym.envs import ENVIRONMENTS, InboxEnv
from agent_gym.envs.inbox_env import SEED, expect_changes
from agent_gym.llm import FakeClient, LLMResponse, ToolCall
from agent_gym.types import SUBMIT, Action


def call(name, **args):
    return LLMResponse(tool_calls=[ToolCall(name, args)])


def submit():
    return call(SUBMIT, summary="done")


def test_registered_and_tools():
    assert ENVIRONMENTS["inbox"] is InboxEnv
    env = InboxEnv()
    env.reset("assign_by_id")
    names = [t["function"]["name"] for t in env.tools()]
    assert names == ["list_agents", "search_tickets", "assign_ticket", "set_status",
                     "set_priority", SUBMIT]
    specs = env.tool_specs()
    assert specs["list_agents"].read_only and specs["search_tickets"].read_only
    assert not specs["assign_ticket"].read_only


def test_search_is_case_insensitive_and_filters_status():
    env = InboxEnv()
    env.reset("close_by_name")
    obs = env.step(Action("search_tickets", {"query": "LOGIN loop"}))
    assert obs.ok and "T-1002" in obs.content and "T-1003" in obs.content
    obs = env.step(Action("search_tickets", {"query": "dana lee", "status": "closed"}))
    assert "T-1004" in obs.content and "T-1001" not in obs.content
    bad = env.step(Action("search_tickets", {"query": "x", "status": "pending"}))
    assert not bad.ok and bad.metadata["error_kind"] == "tool_error"
    empty = env.step(Action("search_tickets", {"query": "  "}))
    assert not empty.ok


def test_unknown_ids_are_unknown_id_errors():
    env = InboxEnv()
    env.reset("assign_by_name")
    a = env.step(Action("assign_ticket", {"ticket_id": "T-1001", "agent_id": "Priya Shah"}))
    t = env.step(Action("set_status", {"ticket_id": "1001", "status": "closed"}))
    assert a.metadata["error_kind"] == "unknown_id" and "list_agents" in a.content
    assert t.metadata["error_kind"] == "unknown_id" and "search_tickets" in t.content


def test_bad_enum_values_are_tool_errors():
    env = InboxEnv()
    env.reset("escalate_by_id")
    o = env.step(Action("set_priority", {"ticket_id": "T-1003", "priority": "urgent"}))
    s = env.step(Action("set_status", {"ticket_id": "T-1003", "status": "done"}))
    assert o.metadata["error_kind"] == "tool_error" and s.metadata["error_kind"] == "tool_error"


@pytest.mark.parametrize("task_id", list(InboxEnv.tasks))
def test_reference_passes_with_full_reward(task_id):
    task = InboxEnv.tasks[task_id]
    script = [call(a.tool, **a.arguments) for a in task.reference] + [submit()]
    ep = run_episode(InboxEnv(), FakeClient(script), task_id)
    assert ep.passed and ep.reward == 1.0 and ep.failures == []


def test_close_wrong_same_subject_ticket_fails():
    ep = run_episode(InboxEnv(), FakeClient([
        call("search_tickets", query="login loop"),
        call("set_status", ticket_id="T-1003", status="closed"), submit()]), "close_by_name")
    assert not ep.passed and ep.reward == 0.0
    assert "T-1002 status is 'open', expected 'closed'" in ep.problems
    assert "unexpected change to T-1003 status: 'open' -> 'closed'" in ep.problems


def test_collateral_change_fails_escalate():
    # Right ticket, right agent, but it also closed the ticket.
    ep = run_episode(InboxEnv(), FakeClient([
        call("set_priority", ticket_id="T-1003", priority="high"),
        call("assign_ticket", ticket_id="T-1003", agent_id="agt_03"),
        call("set_status", ticket_id="T-1003", status="closed"), submit()]), "escalate_by_id")
    assert not ep.passed and ep.problems == ["unexpected change to T-1003 status: "
                                             "'open' -> 'closed'"]
    assert [f["kind"] for f in ep.failures] == ["wrong_tool"]


def test_name_variant_with_guessed_ids_passes_but_shows_wrong_order():
    ep = run_episode(InboxEnv(), FakeClient([
        call("assign_ticket", ticket_id="T-1001", agent_id="agt_01"), submit()]),
        "assign_by_name")
    assert ep.passed and ep.reward == 1.0
    assert [f["kind"] for f in ep.failures] == ["wrong_order"]
    assert "list_agents" in ep.failures[0]["reason"]


def test_expect_changes_reports_removed_new_and_agents():
    check = expect_changes({"T-1001": {"assignee_id": "agt_01"}})
    initial = {"agents": SEED["agents"], "tickets": SEED["tickets"]}
    final = {"agents": SEED["agents"][:2],
             "tickets": [t for t in SEED["tickets"] if t["id"] != "T-1005"]
             + [{"id": "T-2000"}]}
    problems = check(initial, final)
    assert "ticket T-1005 was removed" in problems and "unexpected new ticket T-2000" in problems
    assert "agents changed" in problems
    assert "T-1001 assignee_id is '', expected 'agt_01'" in problems


def test_episodes_do_not_leak():
    env = InboxEnv()
    env.reset("close_by_id")
    env.step(Action("set_status", {"ticket_id": "T-1002", "status": "closed"}))
    env.reset("close_by_id")
    assert env.data == SEED and SEED["tickets"][1]["status"] == "open"
