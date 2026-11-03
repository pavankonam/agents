import pytest

from agent_gym import (KINDS, Action, CalendarEnv, StepLog, UnknownIdError, classify,
                       count_kinds, run_episode, summarize)
from agent_gym.cli import main
from agent_gym.llm import FakeClient, LLMResponse, ToolCall
from agent_gym.types import SUBMIT

SPECS = CalendarEnv().tool_specs()
REF = CalendarEnv.tasks["delete_by_title"].reference  # list_calendars, list_events, delete_event


def kinds(steps, reference=REF):
    return [f.kind for f in classify([StepLog(*s) for s in steps], reference, SPECS)]


def play(task_id, actions):
    env = CalendarEnv()
    env.reset(task_id)
    for tool, args in actions:
        env.step(Action(tool, args))
    if not env.state.done:
        env.step(Action(SUBMIT, {}))
    return env.state


def test_reference_runs_have_no_failures():
    for task in CalendarEnv.tasks.values():
        st = play(task.id, [(a.tool, a.arguments) for a in task.reference])
        assert st.passed and st.failures == []


@pytest.mark.parametrize("action,kind", [
    (("guess_id", {}), "wrong_tool"),
    (("delete_event", {"id": "evt_002"}), "wrong_arguments"),
    (("list_events", {"calendar_id": "cal_team", "date": "11/02"}), "wrong_arguments"),
    (("delete_event", {"event_id": "evt_999"}), "invented_id"),
    (("list_events", {"calendar_id": "Team"}), "invented_id"),
])
def test_refused_steps_get_a_kind_from_the_env(action, kind):
    st = play("delete_by_title", [action])
    assert [f["kind"] for f in st.failures] == [kind]
    assert st.failures[0]["index"] == 1


def test_overlap_is_wrong_arguments_and_env_tags_error_kind():
    env = CalendarEnv()
    env.reset("first_free_slot")
    obs = env.step(Action("create_event", {"calendar_id": "cal_team", "title": "Retro",
                                           "date": "2026-11-02", "start": "14:00",
                                           "end": "15:00"}))
    assert not obs.ok and obs.metadata["error_kind"] == "tool_error"
    assert env._steps[-1].error_kind == "tool_error"


def test_unknown_id_error_is_a_tool_error():
    from agent_gym import ToolError
    assert issubclass(UnknownIdError, ToolError)


def test_repeated_lookup_only_for_identical_read_only_calls():
    assert kinds([("list_calendars", {}, True), ("list_calendars", {}, True)]) == \
        ["repeated_lookup"]
    # same tool, other arguments, within the reference count: clean
    assert kinds([("list_calendars", {}, True),
                  ("list_events", {"calendar_id": "cal_team"}, True)]) == []


def test_refused_call_does_not_make_the_retry_a_repeat():
    assert kinds([("list_calendars", {}, True),
                  ("list_events", {"calendar_id": "Team"}, False, "unknown_id"),
                  ("list_events", {"calendar_id": "cal_team"}, True)]) == ["invented_id"]


def test_extra_and_wrong_tool_for_tools_outside_the_reference():
    ref = CalendarEnv.tasks["create_explicit"].reference  # create_event only
    assert kinds([("list_calendars", {}, True)], ref) == ["extra_step"]
    assert kinds([("delete_event", {"event_id": "evt_001"}, True)], ref) == ["wrong_tool"]


def test_more_calls_than_the_reference_is_extra_step():
    assert kinds([("list_calendars", {}, True),
                  ("list_events", {"calendar_id": "cal_team"}, True),
                  ("list_events", {"calendar_id": "cal_team", "date": "2026-11-02"}, True)]
                 ) == ["extra_step"]


def test_wrong_order_reports_each_missing_prerequisite_once():
    # skips list_calendars: list_events is flagged, the delete after it is not
    f = classify([StepLog("list_events", {"calendar_id": "cal_team"}, True),
                  StepLog("delete_event", {"event_id": "evt_002"}, True)], REF, SPECS)
    assert [(x.index, x.kind) for x in f] == [(1, "wrong_order")]
    assert "list_calendars" in f[0].reason
    # guessing the id and writing first is wrong order, even if the outcome is right
    st = play("create_by_name", [("create_event", {"calendar_id": "cal_personal",
                                                   "title": "Dentist", "date": "2026-11-03",
                                                   "start": "15:00", "end": "16:00"})])
    assert st.passed and [f["kind"] for f in st.failures] == ["wrong_order"]


def test_submit_is_never_classified_and_taxonomy_does_not_change_reward():
    st = play("create_explicit", [("list_calendars", {}),
                                  ("create_event", {"calendar_id": "cal_team",
                                                    "title": "Design review",
                                                    "date": "2026-11-02",
                                                    "start": "10:00", "end": "10:30"})])
    assert [f["kind"] for f in st.failures] == ["extra_step"]
    assert st.reward == pytest.approx(0.98)  # trajectory -0.1 only, as on day 2


def test_count_kinds_and_summarize():
    assert list(count_kinds([])) == list(KINDS)
    eps = []
    for script in ([ToolCall("guess_id", {})], [ToolCall("list_calendars", {})]):
        client = FakeClient([LLMResponse(tool_calls=[tc]) for tc in script] +
                            [LLMResponse(content="done")])
        eps.append(run_episode(CalendarEnv(), client, "create_explicit"))
    s = summarize(eps)
    assert s["create_explicit"]["wrong_tool"] == 1 and s["create_explicit"]["extra_step"] == 1
    assert s["total"] == s["create_explicit"]
    assert eps[0].failures[0]["kind"] == "wrong_tool"


def test_cli_run_prints_failures(capsys):
    client = FakeClient([LLMResponse(tool_calls=[ToolCall("delete_event",
                                                          {"event_id": "evt_9"})]),
                         LLMResponse(tool_calls=[ToolCall(SUBMIT, {})])])
    assert main(["run", "delete_by_title"], client=client) == 1
    assert "failure: step 1 delete_event: invented_id" in capsys.readouterr().out


# Day 6: wrong_target (D30)

def test_wrong_target_is_a_kind_between_arguments_and_order():
    assert KINDS.index("wrong_target") == KINDS.index("wrong_arguments") + 1
    assert len(KINDS) == 7


def test_delete_the_look_alike_event_is_wrong_target():
    st = play("delete_by_title", [("list_calendars", {}),
                                  ("list_events", {"calendar_id": "cal_team"}),
                                  ("delete_event", {"event_id": "evt_004"})])
    assert not st.passed and st.reward == 0.0
    assert [(f["index"], f["kind"]) for f in st.failures] == [(3, "wrong_target")]
    assert "event_id=evt_004, reference event_id=evt_002" in st.failures[0]["reason"]


def test_wrong_target_does_not_use_up_the_reference_call():
    # Wrong event first, right one after: the second delete is not an extra_step.
    ks = kinds([("list_calendars", {}, True), ("list_events", {"calendar_id": "cal_team"}, True),
                ("delete_event", {"event_id": "evt_004"}, True),
                ("delete_event", {"event_id": "evt_002"}, True)])
    assert ks == ["wrong_target"]


def test_non_id_arguments_never_make_a_wrong_target():
    # The date filter of a lookup and the time of a create are not targets.
    ref = CalendarEnv.tasks["first_free_slot"].reference
    ks = kinds([("list_calendars", {}, True), ("list_events", {"calendar_id": "cal_team"}, True),
                ("create_event", {"calendar_id": "cal_team", "title": "Retro",
                                  "date": "2026-11-02", "start": "14:00", "end": "15:00"}, True)],
               ref)
    assert ks == []


def test_create_on_the_wrong_calendar_is_wrong_target():
    ref = CalendarEnv.tasks["create_by_name"].reference
    ks = kinds([("list_calendars", {}, True),
                ("create_event", {"calendar_id": "cal_team", "title": "Dentist",
                                  "date": "2026-11-03", "start": "15:00", "end": "16:00"}, True)],
               ref)
    assert ks == ["wrong_target"]


def test_wrong_target_on_inbox_close_by_name():
    from agent_gym import InboxEnv
    env = InboxEnv()
    env.reset("close_by_name")
    for a in [Action("search_tickets", {"query": "login loop"}),
              Action("set_status", {"ticket_id": "T-1003", "status": "closed"}),
              Action(SUBMIT, {})]:
        env.step(a)
    assert not env.state.passed
    assert [f["kind"] for f in env.state.failures] == ["wrong_target"]


def test_every_failed_reference_mutation_in_quiz_has_a_kind():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "quiz"))
    import quiz_model
    from agent_gym import ENVIRONMENTS
    for (env_name, task_id), (tool, key, value) in quiz_model.WRONG_TARGET.items():
        cls = ENVIRONMENTS[env_name]
        ep = run_episode(cls(), FakeClient(quiz_model.wrong_target_script(
            cls.tasks[task_id], tool, key, value)), task_id)
        assert not ep.passed and [f["kind"] for f in ep.failures] == ["wrong_target"]
