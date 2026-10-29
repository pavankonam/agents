from agent_gym import CalendarEnv, run_episode, system_prompt
from agent_gym.llm import FakeClient, LLMResponse, ToolCall
from agent_gym.types import SUBMIT

CREATE = {"calendar_id": "cal_team", "title": "Design review", "date": "2026-11-02",
          "start": "10:00", "end": "10:30"}


def call(name, **args):
    return LLMResponse(tool_calls=[ToolCall(name, args)])


def test_system_prompt_mentions_env_steps_and_submit():
    sp = system_prompt(CalendarEnv(max_steps=7))
    assert "'calendar'" in sp and "at most 7 steps" in sp and "call submit" in sp


def test_reference_run_scores_one_and_records_steps():
    client = FakeClient([call("create_event", **CREATE), call(SUBMIT, summary="booked")])
    ep = run_episode(CalendarEnv(), client, "create_explicit")
    assert ep.success and ep.end_reason == "submitted" and ep.turns == 2
    assert [s.tool for s in ep.steps] == ["create_event", SUBMIT]
    assert ep.steps[0].content == "created evt_101" and ep.final_text == "booked"
    tool_msgs = [m for m in ep.messages if m["role"] == "tool"]
    assert tool_msgs[0] == {"role": "tool", "tool_name": "create_event",
                            "content": "created evt_101"}


def test_model_sees_task_and_tools():
    client = FakeClient([call(SUBMIT)])
    run_episode(CalendarEnv(), client, "create_by_name")
    first = client.calls[0]
    assert first[0]["role"] == "system" and "Dentist" in first[1]["content"]


def test_text_answer_without_submit_ends_and_is_scored():
    ep = run_episode(CalendarEnv(), FakeClient([LLMResponse(content="All done!")]),
                     "create_explicit")
    assert ep.end_reason == "no_submit" and ep.reward == 0.0 and ep.steps == []
    assert ep.final_text == "All done!" and ep.problems


def test_work_then_text_answer_still_scores_one():
    client = FakeClient([call("create_event", **CREATE), LLMResponse(content="Booked it.")])
    ep = run_episode(CalendarEnv(), client, "create_explicit")
    assert ep.success and ep.end_reason == "no_submit"


def test_several_calls_in_one_turn_stop_at_submit():
    resp = LLMResponse(tool_calls=[ToolCall("create_event", CREATE), ToolCall(SUBMIT, {}),
                                   ToolCall("delete_event", {"event_id": "evt_001"})])
    ep = run_episode(CalendarEnv(), FakeClient([resp]), "create_explicit")
    assert ep.success and [s.tool for s in ep.steps] == ["create_event", SUBMIT]
    assert ep.turns == 1


def test_turn_limit():
    client = FakeClient([call("list_calendars")] * 5)
    ep = run_episode(CalendarEnv(), client, "create_explicit", max_turns=3)
    assert ep.end_reason == "turn_limit" and ep.turns == 3 and len(ep.steps) == 3


def test_step_limit_from_env():
    client = FakeClient([call("list_calendars")] * 5)
    ep = run_episode(CalendarEnv(max_steps=2), client, "create_explicit")
    assert ep.end_reason == "step_limit" and len(ep.steps) == 2 and ep.turns == 2


def test_refused_calls_are_recorded_and_returned_to_model():
    client = FakeClient([LLMResponse(tool_calls=[ToolCall("delete_event", {"_raw": "{bad"})]),
                         call(SUBMIT)])
    ep = run_episode(CalendarEnv(), client, "create_explicit")
    assert not ep.steps[0].ok and "unexpected argument" in ep.steps[0].content
    assert "unexpected argument" in client.calls[1][-1]["content"]


def test_to_dict_drops_messages_by_default():
    ep = run_episode(CalendarEnv(), FakeClient([call(SUBMIT)]), "create_explicit")
    assert "messages" not in ep.to_dict() and "messages" in ep.to_dict(with_messages=True)
    assert ep.to_dict()["steps"][0]["tool"] == SUBMIT
