import json

import pytest

from agent_gym import Action, CalendarEnv
from agent_gym.envs.calendar_env import SEED, expect
from agent_gym.types import SUBMIT


def env_for(task="create_explicit"):
    env = CalendarEnv()
    env.reset(task)
    return env


def ev(**kw):
    base = {"calendar_id": "cal_team", "title": "X", "date": "2026-11-05", "start": "10:00",
            "end": "11:00"}
    base.update(kw)
    return Action("create_event", base)


def test_list_calendars_and_events():
    env = env_for()
    cals = json.loads(env.step(Action("list_calendars")).content)
    assert [c["name"] for c in cals] == ["Team", "Personal", "On-call"]
    evs = json.loads(env.step(Action("list_events", {"calendar_id": "cal_team"})).content)
    assert [e["id"] for e in evs] == ["evt_001", "evt_002", "evt_004"]
    day = json.loads(env.step(Action("list_events", {"calendar_id": "cal_team",
                                                     "date": "2026-11-02"})).content)
    assert [e["id"] for e in day] == ["evt_001", "evt_002"]


def test_unknown_calendar_lists_ids():
    obs = env_for().step(Action("list_events", {"calendar_id": "Team"}))
    assert not obs.ok and "cal_team" in obs.content and "list_calendars" in obs.content


@pytest.mark.parametrize("kw,needle", [
    ({"date": "2026-13-01"}, "YYYY-MM-DD"),
    ({"date": "11/05/2026"}, "YYYY-MM-DD"),
    ({"start": "9:00"}, "start must be HH:MM"),
    ({"end": "24:00"}, "end must be HH:MM"),
    ({"start": "11:00", "end": "10:00"}, "must be after start"),
    ({"start": "10:00", "end": "10:00"}, "must be after start"),
    ({"title": "  "}, "title must not be empty"),
    ({"calendar_id": "cal_x"}, "no calendar"),
    ({"date": "2026-11-02", "start": "14:30", "end": "15:30"}, "overlaps evt_002"),
])
def test_create_event_validation(kw, needle):
    env = env_for()
    obs = env.step(ev(**kw))
    assert not obs.ok and needle in obs.content
    assert len(env.data["events"]) == 4


def test_create_touching_events_is_fine_and_ids_count_up():
    env = env_for()
    a = env.step(ev(date="2026-11-02", start="15:00", end="16:00"))
    b = env.step(ev(date="2026-11-02", start="13:00", end="14:00"))
    assert (a.content, b.content) == ("created evt_101", "created evt_102")
    env.reset("create_explicit")
    assert env.step(ev()).content == "created evt_101"


def test_delete_event_and_unknown_id():
    env = env_for()
    assert env.step(Action("delete_event", {"event_id": "evt_002"})).content.startswith(
        "deleted evt_002")
    obs = env.step(Action("delete_event", {"event_id": "evt_002"}))
    assert not obs.ok and "no event" in obs.content


def test_seed_is_never_mutated():
    env = env_for()
    env.step(Action("delete_event", {"event_id": "evt_001"}))
    env.step(ev())
    assert len(SEED["events"]) == 4


@pytest.mark.parametrize("task_id", list(CalendarEnv.tasks))
def test_reference_solution_scores_one(task_id):
    env = CalendarEnv()
    env.reset(task_id)
    for a in CalendarEnv.tasks[task_id].reference:
        assert env.step(a).ok
    obs = env.step(Action(SUBMIT))
    assert obs.reward == 1.0 and obs.metadata["problems"] == []


@pytest.mark.parametrize("task_id", list(CalendarEnv.tasks))
def test_doing_nothing_scores_zero(task_id):
    env = CalendarEnv()
    env.reset(task_id)
    assert env.step(Action(SUBMIT)).reward == 0.0


def test_deleting_the_wrong_old_sync_fails():
    env = env_for("delete_by_title")
    env.step(Action("delete_event", {"event_id": "evt_004"}))
    obs = env.finish("submitted")
    assert obs.reward == 0.0
    assert "event evt_002 should have been deleted" in obs.metadata["problems"]
    assert any("unexpected deletion: evt_004" in p for p in obs.metadata["problems"])


def test_extra_event_fails_even_if_target_is_right():
    env = env_for("create_explicit")
    for a in CalendarEnv.tasks["create_explicit"].reference:
        env.step(a)
    env.step(ev(title="Bonus"))
    obs = env.finish("submitted")
    assert obs.reward == 0.0 and any("unexpected new event" in p for p in obs.metadata["problems"])


def test_title_match_ignores_case_and_spaces():
    env = env_for("create_explicit")
    env.step(ev(title="  design REVIEW ", date="2026-11-02", start="10:00", end="10:30"))
    assert env.finish("submitted").reward == 1.0


def test_wrong_time_is_reported_as_missing_and_unexpected():
    env = env_for("first_free_slot")
    env.step(ev(title="Retro", date="2026-11-02", start="16:00", end="17:00"))
    problems = env.finish("submitted").metadata["problems"]
    assert any(p.startswith("missing event: 'Retro'") for p in problems)
    assert any(p.startswith("unexpected new event: 'Retro'") for p in problems)


def test_expect_flags_changed_events_and_calendars():
    initial = json.loads(json.dumps(SEED))
    final = json.loads(json.dumps(SEED))
    final["events"][0]["title"] = "Renamed"
    final["calendars"].append({"id": "cal_new", "name": "New"})
    problems = expect()(initial, final)
    assert "unexpected change to evt_001" in problems and "calendars changed" in problems
