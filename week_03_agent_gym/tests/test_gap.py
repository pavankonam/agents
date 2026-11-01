from dataclasses import dataclass

import pytest

from agent_gym.env import Task
from agent_gym.envs import ENVIRONMENTS, CalendarEnv
from agent_gym.gap import gap_lines, id_name_gap, paired_tasks


@dataclass
class Ep:
    env: str
    task_id: str
    passed: bool


def test_every_shipped_pair_is_complete():
    pairs = paired_tasks(ENVIRONMENTS)
    assert [(p.env, p.pair) for p in pairs] == [
        ("calendar", "dentist"), ("calendar", "cancel_old_sync"),
        ("inbox", "assign"), ("inbox", "close"), ("inbox", "escalate")]
    for p in pairs:
        tasks = ENVIRONMENTS[p.env].tasks
        assert tasks[p.id_task].variant == "id" and tasks[p.name_task].variant == "name"
        # Same job: both variants are checked against the same final state.
        a, b = tasks[p.id_task], tasks[p.name_task]
        assert a.reference[-1] == b.reference[-1]


def test_id_variants_have_one_reference_step_per_write():
    for p in paired_tasks(ENVIRONMENTS):
        env = ENVIRONMENTS[p.env]()
        specs = env.tool_specs()
        ref = env.tasks[p.id_task].reference
        assert not any(specs[a.tool].read_only for a in ref), p.id_task


def test_task_rejects_bad_variant_or_half_pair():
    with pytest.raises(ValueError):
        Task("x", "p", [], lambda a, b: [], variant="ids", pair="p")
    with pytest.raises(ValueError):
        Task("x", "p", [], lambda a, b: [], pair="p")


def test_broken_pair_raises():
    class Broken(CalendarEnv):
        tasks = {"a": Task("a", "p", [], lambda i, f: [], pair="p", variant="id"),
                 "b": Task("b", "p", [], lambda i, f: [], pair="p", variant="id")}
    with pytest.raises(ValueError, match="exactly one id and one name"):
        paired_tasks({"broken": Broken})


def test_gap_counts_and_rates():
    eps = [Ep("inbox", "assign_by_id", True), Ep("inbox", "assign_by_id", True),
           Ep("inbox", "assign_by_name", False), Ep("inbox", "assign_by_name", True),
           Ep("inbox", "close_by_id", True), Ep("inbox", "close_by_name", False),
           Ep("calendar", "create_explicit", False)]  # unpaired: ignored
    r = id_name_gap(eps, ENVIRONMENTS)
    assert (r["id_pass"], r["id_runs"], r["name_pass"], r["name_runs"]) == (3, 3, 1, 3)
    assert r["id_rate"] == 1.0 and abs(r["gap"] - 2 / 3) < 1e-9
    assert [row["pair"] for row in r["pairs"]] == ["assign", "close"]
    assert "gap +67 points" in gap_lines(r)[-1]


def test_one_sided_pair_is_shown_but_not_totalled():
    r = id_name_gap([Ep("inbox", "close_by_name", True)], ENVIRONMENTS)
    assert r["pairs"][0]["complete"] is False and r["gap"] is None
    lines = gap_lines(r)
    assert "not in total" in lines[1] and lines[-1].endswith("gap n/a")


def test_no_runs_gives_empty_report():
    r = id_name_gap([], ENVIRONMENTS)
    assert r["pairs"] == [] and r["id_rate"] is None and r["gap"] is None
