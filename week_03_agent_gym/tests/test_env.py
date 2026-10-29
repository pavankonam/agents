import pytest

from agent_gym import (Action, CalendarEnv, Environment, EpisodeOver, Param, ToolSpec,
                       validate_args)
from agent_gym.types import SUBMIT

SPEC = ToolSpec("t", "test", {"a": Param("string", "a"), "n": Param("integer", "n", False)},
                handler=lambda **k: "ok")


def test_validate_args_ok_and_optional():
    assert validate_args(SPEC, {"a": "x"}) is None
    assert validate_args(SPEC, {"a": "x", "n": 3}) is None


@pytest.mark.parametrize("args,needle", [
    ({}, "missing required argument 'a'"),
    ({"a": "x", "zzz": 1}, "unexpected argument(s) for t: zzz"),
    ({"a": 5}, "'a' for t must be a string"),
    ({"a": "x", "n": "3"}, "'n' for t must be a integer"),
    ({"a": "x", "n": True}, "'n' for t must be a integer"),
    ({"_raw": "not json"}, "unexpected argument"),
    ("a=x", "must be an object"),
])
def test_validate_args_problems(args, needle):
    assert needle in validate_args(SPEC, args)


def test_step_before_reset_raises():
    with pytest.raises(EpisodeOver):
        CalendarEnv().step(Action("list_calendars"))
    with pytest.raises(EpisodeOver):
        CalendarEnv().finish("x")


def test_reset_returns_prompt_and_state():
    env = CalendarEnv()
    obs = env.reset("create_by_name", episode_id="ep-7")
    assert "Dentist" in obs.content and not obs.done and obs.reward is None
    assert obs.metadata["tools"][-1] == SUBMIT
    st = env.state
    assert (st.episode_id, st.task_id, st.step_count, st.done) == ("ep-7", "create_by_name", 0,
                                                                   False)


def test_reset_default_task_and_unknown_task():
    env = CalendarEnv()
    env.reset()
    assert env.state.task_id == next(iter(CalendarEnv.tasks))
    assert env.state.episode_id == "calendar-1"
    with pytest.raises(KeyError, match="unknown task"):
        env.reset("nope")


def test_unknown_tool_is_refused_but_counts_as_step():
    env = CalendarEnv()
    env.reset()
    obs = env.step(Action("send_email", {}))
    assert not obs.ok and "unknown tool 'send_email'" in obs.content and "submit" in obs.content
    assert env.state.step_count == 1 and not env.state.done


def test_bad_arguments_are_refused():
    env = CalendarEnv()
    env.reset()
    obs = env.step(Action("delete_event", {"id": "evt_001"}))
    assert not obs.ok and "unexpected argument" in obs.content
    assert len(env.data["events"]) == 4


def test_reset_isolates_episodes():
    env = CalendarEnv()
    env.reset("delete_by_title")
    env.step(Action("delete_event", {"event_id": "evt_001"}))
    assert len(env.data["events"]) == 3
    env.reset("delete_by_title")
    assert len(env.data["events"]) == 4 and env.state.step_count == 0
    assert env.state.episode_id == "calendar-2"


def test_state_is_a_copy():
    env = CalendarEnv()
    env.reset()
    env.state.step_count = 99
    env.state.problems.append("x")
    assert env.state.step_count == 0 and env.state.problems == []


def test_submit_ends_episode_and_step_after_done_raises():
    env = CalendarEnv()
    env.reset("create_explicit")
    obs = env.step(Action(SUBMIT, {"summary": "nothing"}))
    assert obs.done and obs.reward == 0.0 and obs.metadata["end_reason"] == "submitted"
    assert obs.metadata["problems"] and "reward" not in obs.content
    with pytest.raises(EpisodeOver):
        env.step(Action("list_calendars"))
    with pytest.raises(EpisodeOver):
        env.finish("again")


def test_step_limit_ends_episode_on_last_step():
    env = CalendarEnv(max_steps=2)
    env.reset("create_explicit")
    assert not env.step(Action("list_calendars")).done
    obs = env.step(Action("list_calendars"))
    assert obs.done and obs.ok and obs.reward == 0.0 and "step_limit" in obs.content
    assert env.state.end_reason == "step_limit"


def test_step_limit_still_scores_the_state():
    env = CalendarEnv(max_steps=1)
    env.reset("create_explicit")
    obs = env.step(Action("create_event", {"calendar_id": "cal_team", "title": "Design review",
                                           "date": "2026-11-02", "start": "10:00",
                                           "end": "10:30"}))
    assert obs.done and obs.reward == 1.0 and env.state.end_reason == "step_limit"


def test_max_steps_must_be_positive():
    with pytest.raises(ValueError):
        CalendarEnv(max_steps=0)


def test_tools_have_schemas_and_submit_last():
    tools = CalendarEnv().tools()
    names = [t["function"]["name"] for t in tools]
    assert names == ["list_calendars", "list_events", "create_event", "delete_event", SUBMIT]
    ce = tools[2]["function"]["parameters"]
    assert ce["required"] == ["calendar_id", "title", "date", "start", "end"]
    le = tools[1]["function"]["parameters"]
    assert le["required"] == ["calendar_id"] and "date" in le["properties"]
    assert tools[-1]["function"]["parameters"]["required"] == []


def test_base_environment_needs_tasks():
    with pytest.raises(KeyError, match="no tasks"):
        Environment().reset()
