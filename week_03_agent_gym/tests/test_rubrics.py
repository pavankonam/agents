import pytest

from agent_gym import (Action, CalendarEnv, Gate, RubricContext, StateCheck, StepLog,
                       Task, TrajectoryRubric, WeightedSum, default_rubric, run_episode)
from agent_gym.cli import breakdown_lines
from agent_gym.llm import FakeClient, LLMResponse, ToolCall
from agent_gym.types import SUBMIT

OK_CHECK = lambda i, f: []  # noqa: E731
BAD_CHECK = lambda i, f: ["missing event: x"]  # noqa: E731
REF = [Action("list_calendars"), Action("create_event", {})]


def ctx(steps=(), reference=REF):
    return RubricContext({}, {}, [StepLog(t, {}, ok) for t, ok in steps], list(reference))


class Fixed:
    def __init__(self, value, name="fixed"):
        self.value, self.name = value, name

    def score(self, c):
        from agent_gym import RubricResult
        return RubricResult(self.name, self.value)


def test_state_check_scores_and_reports_problems():
    assert StateCheck(OK_CHECK).score(ctx()).score == 1.0
    r = StateCheck(BAD_CHECK).score(ctx())
    assert r.score == 0.0 and r.detail == ["missing event: x"]


def test_trajectory_clean_run_is_one_and_submit_not_counted():
    r = TrajectoryRubric().score(ctx([("list_calendars", True), ("create_event", True),
                                      (SUBMIT, True)]))
    assert r.score == 1.0 and r.detail == []


def test_trajectory_refused_and_extra_steps_are_charged_separately():
    # 2 refused (0.2 each) + 3 accepted vs reference 2 -> 1 extra (0.1)
    steps = [("guess", False), ("create_event", False), ("list_calendars", True),
             ("list_calendars", True), ("create_event", True), (SUBMIT, True)]
    r = TrajectoryRubric().score(ctx(steps))
    assert r.score == pytest.approx(0.5)
    assert r.detail == ["2 refused step(s) -0.4", "1 step(s) over the reference of 2 -0.1"]


def test_trajectory_is_clipped_at_zero_and_rejects_negative_penalties():
    assert TrajectoryRubric().score(ctx([("x", False)] * 9)).score == 0.0
    with pytest.raises(ValueError):
        TrajectoryRubric(refused_penalty=-1)


def test_weighted_sum_is_weighted_mean_and_records_weights():
    r = WeightedSum([(Fixed(1.0, "a"), 3), (Fixed(0.0, "b"), 1)]).score(ctx())
    assert r.score == 0.75 and [c.weight for c in r.children] == [3, 1]


@pytest.mark.parametrize("parts", [[], [(Fixed(1.0), 0)], [(Fixed(1.0), -2)]])
def test_weighted_sum_rejects_bad_parts(parts):
    with pytest.raises(ValueError):
        WeightedSum(parts)


def test_gate_blocks_inner_below_threshold():
    r = Gate(Fixed(0.0, "g"), Fixed(0.9, "inner")).score(ctx())
    assert r.score == 0.0 and [c.name for c in r.children] == ["g"]
    assert "inner rubric not scored" in r.detail[0]
    r = Gate(Fixed(0.6, "g"), Fixed(0.9, "inner"), threshold=0.5).score(ctx())
    assert r.score == 0.9 and [c.name for c in r.children] == ["g", "inner"]


def test_default_rubric_values():
    rub = default_rubric(OK_CHECK)
    assert rub.score(ctx()).score == 1.0
    # one refused step: process 0.8 -> 0.8*1 + 0.2*0.8 = 0.96
    assert rub.score(ctx([("x", False)])).score == pytest.approx(0.96)
    assert default_rubric(BAD_CHECK).score(ctx()).score == 0.0


def call(name, **args):
    return LLMResponse(tool_calls=[ToolCall(name, args)])


def test_env_records_steps_and_breakdown_messy_but_correct():
    env = CalendarEnv()
    env.reset("first_free_slot")
    env.step(Action("list_calendars"))
    env.step(Action("list_events", {"calendar_id": "cal_team", "date": "2026-11-02"}))
    bad = env.step(Action("create_event", {"calendar_id": "cal_team", "title": "Retro",
                                           "date": "2026-11-02", "start": "14:00",
                                           "end": "15:00"}))
    assert not bad.ok and "overlaps" in bad.content
    env.step(Action("create_event", {"calendar_id": "cal_team", "title": "Retro",
                                     "date": "2026-11-02", "start": "15:00", "end": "16:00"}))
    obs = env.step(Action(SUBMIT))
    assert obs.metadata["passed"] and obs.metadata["problems"] == []
    assert obs.reward == pytest.approx(0.96)
    st = env.state
    assert st.passed and st.reward == pytest.approx(0.96) and st.breakdown["name"] == "gate"
    assert "reward" not in obs.content and "0.96" not in obs.content


def test_episode_success_follows_state_check_not_reward():
    client = FakeClient([call("nope"), call("create_event", calendar_id="cal_team",
                                            title="Design review", date="2026-11-02",
                                            start="10:00", end="10:30"), call(SUBMIT)])
    ep = run_episode(CalendarEnv(), client, "create_explicit")
    assert ep.success and ep.passed and ep.reward == pytest.approx(0.96)
    assert ep.to_dict()["breakdown"]["children"][1]["children"][1]["name"] == "trajectory"


def test_failed_state_gates_reward_to_zero_whatever_the_process():
    ep = run_episode(CalendarEnv(), FakeClient([call(SUBMIT)]), "create_explicit")
    assert not ep.success and ep.reward == 0.0
    assert ep.breakdown["children"][0]["detail"]  # state problems in the tree


def test_task_can_override_rubric():
    env = CalendarEnv()
    task = CalendarEnv.tasks["create_explicit"]
    custom = Task(task.id, task.prompt, task.reference, task.check, task.tags,
                  rubric=StateCheck(task.check, name="outcome_only"))
    env.tasks = {task.id: custom}
    env.reset(task.id)
    env.step(Action("bad_tool"))
    for a in task.reference:
        env.step(a)
    obs = env.step(Action(SUBMIT))
    assert obs.reward == 1.0 and obs.metadata["breakdown"]["name"] == "outcome_only"


def test_steps_reset_between_episodes():
    env = CalendarEnv()
    env.reset("create_explicit")
    env.step(Action("bad_tool"))
    env.finish("x")
    env.reset("create_explicit")
    for a in CalendarEnv.tasks["create_explicit"].reference:
        env.step(a)
    assert env.step(Action(SUBMIT)).reward == 1.0


def test_non_dict_arguments_are_logged_without_crashing():
    env = CalendarEnv()
    env.reset("create_explicit")
    assert not env.step(Action("list_calendars", "oops")).ok  # type: ignore[arg-type]
    assert env.finish("x").reward == 0.0


def test_breakdown_lines_render_tree():
    lines = breakdown_lines(default_rubric(OK_CHECK).score(ctx([("x", False)])).to_dict())
    assert lines[0] == "gate: 0.960"
    assert any(line.strip() == "trajectory x0.2: 0.800" for line in lines)
    assert any("1 refused step(s)" in line for line in lines)
