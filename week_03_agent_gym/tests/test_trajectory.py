import json

import pytest

from agent_gym import ENVIRONMENTS, CalendarEnv, InboxEnv, run_episode
from agent_gym.cli import main
from agent_gym.llm import FakeClient, LLMResponse, ToolCall
from agent_gym.trajectory import (TrajectoryError, read_jsonl, replay, to_record,
                                  write_jsonl)
from agent_gym.types import SUBMIT, Action


def call(name, **args):
    return LLMResponse(tool_calls=[ToolCall(name, args)])


def reference(task):
    return [call(a.tool, **a.arguments) for a in task.reference] + [call(SUBMIT, summary="ok")]


def roundtrip(ep):
    return json.loads(json.dumps(to_record(ep)))


# ----- seeded data (D25) -----

def test_no_seed_is_canonical_and_same_seed_is_same_data():
    a, b = InboxEnv(), InboxEnv()
    a.reset("assign_by_name")
    b.reset("assign_by_name", seed=None)
    assert a.data == b.data and a.data["tickets"][0]["id"] == "T-1001"
    a.reset("assign_by_name", seed=5)
    b.reset("assign_by_name", seed=5)
    assert a.data == b.data


def test_seed_changes_order_not_content():
    base, env = InboxEnv(), InboxEnv()
    base.reset("assign_by_name")
    orders = set()
    for seed in range(10):
        env.reset("assign_by_name", seed=seed)
        orders.add(tuple(t["id"] for t in env.data["tickets"]))
        key = lambda t: t["id"]  # noqa: E731
        assert sorted(env.data["tickets"], key=key) == sorted(base.data["tickets"], key=key)
    assert len(orders) > 1


def test_calendar_seed_moves_new_event_ids():
    env = CalendarEnv()
    env.reset("create_explicit", seed=3)
    out = env.step(Action("create_event", {"calendar_id": "cal_team", "title": "X",
                                           "date": "2026-11-05", "start": "10:00",
                                           "end": "11:00"}))
    first = int(out.content.split("evt_")[1])
    assert 101 <= first < 1001
    env.reset("create_explicit", seed=3)
    again = env.step(Action("create_event", {"calendar_id": "cal_team", "title": "X",
                                             "date": "2026-11-05", "start": "10:00",
                                             "end": "11:00"}))
    assert again.content == out.content


@pytest.mark.parametrize("env_name", sorted(ENVIRONMENTS))
def test_every_reference_passes_clean_on_many_seeds(env_name):
    cls = ENVIRONMENTS[env_name]
    for task in cls.tasks.values():
        for seed in range(25):
            ep = run_episode(cls(), FakeClient(reference(task)), task.id, seed=seed)
            assert ep.passed and ep.reward == 1.0 and not ep.failures, (task.id, seed)


# ----- records and replay (D26, D27) -----

def test_record_has_what_replay_needs():
    task = InboxEnv.tasks["close_by_name"]
    ep = run_episode(InboxEnv(max_steps=9), FakeClient(reference(task)), task.id, seed=4)
    rec = to_record(ep, model="fake")
    assert rec["seed"] == 4 and rec["max_steps"] == 9 and rec["format"] == 1
    assert [s["tool"] for s in rec["steps"]] == ["search_tickets", "set_status", SUBMIT]
    assert rec["meta"] == {"model": "fake"} and rec["failures"] == []


def test_replay_reproduces_reference_and_messy_runs():
    task = CalendarEnv.tasks["create_by_name"]
    messy = [call("guess_id"), call("list_calendars")] + reference(task)
    for script in (reference(task), messy):
        ep = run_episode(CalendarEnv(), FakeClient(script), task.id, seed=11)
        r = replay(roundtrip(ep))
        assert r.ok and r.reward == ep.reward and r.passed == ep.passed


@pytest.mark.parametrize("script,end", [
    ([LLMResponse(content="done")], "no_submit"),
    ([call("list_calendars")] * 3, "turn_limit"),
    ([call("list_calendars")] * 5, "step_limit"),
])
def test_replay_reproduces_every_end_reason(script, end):
    env = CalendarEnv(max_steps=4)
    ep = run_episode(env, FakeClient(script), "create_by_name",
                     max_turns=3 if end == "turn_limit" else 12)
    assert ep.end_reason == end
    r = replay(roundtrip(ep))
    assert r.ok, r.mismatches


def test_replay_with_wrong_seed_reports_the_differing_observation():
    task = CalendarEnv.tasks["create_explicit"]
    rec = roundtrip(run_episode(CalendarEnv(), FakeClient(reference(task)), task.id, seed=2))
    rec["seed"] = 9
    r = replay(rec)
    assert not r.ok and "step 1 create_event: observation differs" in r.mismatches[0]
    assert r.reward == 1.0  # same outcome, but the record no longer matches


def test_replay_catches_a_tampered_reward_and_passed():
    task = InboxEnv.tasks["assign_by_id"]
    rec = roundtrip(run_episode(InboxEnv(), FakeClient([LLMResponse("ok")]), task.id))
    rec["reward"], rec["passed"] = 1.0, True
    r = replay(rec)
    assert [m.split(":")[0] for m in r.mismatches] == ["reward", "passed"]


def test_replay_catches_a_missing_submit():
    task = InboxEnv.tasks["close_by_id"]
    rec = roundtrip(run_episode(InboxEnv(), FakeClient(reference(task)), task.id))
    rec["steps"] = rec["steps"][:-1]
    assert "still running" in replay(rec).mismatches[0]


def test_replay_rejects_unknown_env_or_task():
    with pytest.raises(TrajectoryError):
        replay({"env": "mars", "task_id": "x", "steps": [], "end_reason": "", "reward": 0})
    with pytest.raises(TrajectoryError):
        replay({"env": "inbox", "task_id": "x", "steps": [], "end_reason": "", "reward": 0})


def test_jsonl_roundtrip_and_bad_lines(tmp_path):
    task = InboxEnv.tasks["escalate_by_id"]
    ep = run_episode(InboxEnv(), FakeClient(reference(task)), task.id)
    path = tmp_path / "t.jsonl"
    assert write_jsonl(path, [ep, ep]) == 2
    path.write_text(path.read_text() + "\n")
    recs = read_jsonl(path)
    assert len(recs) == 2 and all(replay(r).ok for r in recs)
    path.write_text(path.read_text() + "{oops\n")
    with pytest.raises(TrajectoryError, match=":4: not JSON"):
        read_jsonl(path)
    path.write_text('{"format": 99}\n')
    with pytest.raises(TrajectoryError, match="not a format 1"):
        read_jsonl(path)


# ----- CLI (D26) -----

def test_cli_run_record_then_replay(tmp_path, capsys):
    path = tmp_path / "runs.jsonl"
    task = InboxEnv.tasks["assign_by_name"]
    assert main(["run", "inbox/assign_by_name", "--seed", "6", "--record", str(path)],
                client=FakeClient(reference(task))) == 0
    rec = json.loads(path.read_text())
    assert rec["seed"] == 6 and rec["env"] == "inbox"
    capsys.readouterr()
    assert main(["replay", str(path)]) == 0
    assert "1/1 episodes replayed with the same result" in capsys.readouterr().out
    rec["reward"] = 0.5
    path.write_text(json.dumps(rec) + "\n")
    assert main(["replay", str(path), "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] == 0 and out["results"][0]["mismatches"][0].startswith("reward")


def test_cli_replay_missing_or_bad_file(tmp_path, capsys):
    assert main(["replay", str(tmp_path / "none.jsonl")]) == 2
    bad = tmp_path / "bad.jsonl"
    bad.write_text("nope\n")
    assert main(["replay", str(bad)]) == 2
    assert "PROBLEM" in capsys.readouterr().out


def test_truncated_step_limit_record_shows_end_and_failure_diff():
    """Quiz Q19: dropping the last step also drops one failure kind."""
    ep = run_episode(CalendarEnv(max_steps=3), FakeClient([call("list_calendars")] * 5),
                     "create_by_name")
    rec = roundtrip(ep)
    rec["steps"] = rec["steps"][:-1]
    r = replay(rec)
    assert r.reward == 0.0 and len(r.mismatches) == 2
    assert "still running" in r.mismatches[0] and r.mismatches[1].startswith("failures")


def test_wrong_seed_first_mismatch_is_the_lookup():
    """Quiz Q18: the shuffled calendar list differs before the new event id does."""
    task = CalendarEnv.tasks["create_by_name"]
    rec = roundtrip(run_episode(CalendarEnv(), FakeClient(reference(task)), task.id, seed=2))
    rec["seed"] = 9
    r = replay(rec)
    assert r.reward == 1.0 and r.mismatches[0].startswith("step 1 list_calendars")
    assert r.mismatches[1].startswith("step 2 create_event")
