import json
import sys
from pathlib import Path

import pytest

from agent_gym.cli import EXIT_EMPTY, EXIT_FAILED, EXIT_OK, EXIT_OLLAMA, EXIT_USAGE, main
from agent_gym.envs import ENVIRONMENTS
from agent_gym.evaluate import (as_row, build_report, eval_seeds, markdown_lines, report_lines,
                                 run_eval, select_tasks)
from agent_gym.failures import KINDS
from agent_gym.llm import FakeClient, LLMResponse, ToolCall
from agent_gym.trajectory import read_jsonl, write_jsonl
from agent_gym.types import SUBMIT

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "quiz"))
from quiz_model import reference_script, wrong_target_script  # noqa: E402


def ref_factory(env_name, task):
    return FakeClient(reference_script(task))


def test_exit_codes_are_fixed():
    assert (EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_EMPTY, EXIT_OLLAMA) == (0, 1, 2, 3, 4)


@pytest.mark.parametrize("repeats,seed,want", [
    (1, None, [None]), (1, 7, [7]), (3, None, [1, 2, 3]), (2, 10, [10, 11])])
def test_eval_seeds(repeats, seed, want):
    assert eval_seeds(repeats, seed) == want


def test_eval_seeds_rejects_zero():
    with pytest.raises(ValueError):
        eval_seeds(0)


def test_select_tasks_filters_env_and_text():
    assert len(select_tasks(ENVIRONMENTS)) == 12
    assert {n for n, _, _ in select_tasks(ENVIRONMENTS, env="inbox")} == {"inbox"}
    assert [t.id for _, _, t in select_tasks(ENVIRONMENTS, only="calendar/delete")] == [
        "delete_by_title", "delete_by_id"]
    assert select_tasks(ENVIRONMENTS, only="nothing") == []


def test_run_eval_runs_each_task_once_per_seed():
    chosen = select_tasks(ENVIRONMENTS, env="calendar")
    eps = run_eval(chosen, ref_factory, [1, 2, 3])
    assert len(eps) == 18 and all(e.passed for e in eps)
    assert [e.seed for e in eps[:3]] == [1, 2, 3]


def test_report_counts_and_gap():
    eps = run_eval(select_tasks(ENVIRONMENTS), ref_factory, [None])
    r = build_report(eps, ENVIRONMENTS)
    assert r["runs"] == r["passed"] == 12 and r["pass_rate"] == 1.0
    assert r["failures"] == {k: 0 for k in KINDS}
    assert r["gap"]["gap"] == 0.0 and r["seeds"] == [None]
    assert r["failed_runs_without_kind"] == 0


def test_report_from_jsonl_equals_live_report(tmp_path):
    eps = run_eval(select_tasks(ENVIRONMENTS), ref_factory, [1, 2])
    p = tmp_path / "e.jsonl"
    write_jsonl(p, eps)
    assert build_report(read_jsonl(p), ENVIRONMENTS) == build_report(eps, ENVIRONMENTS)


def test_report_counts_failed_runs_without_a_kind():
    nothing = lambda env, task: FakeClient([LLMResponse("done")])  # noqa: E731
    eps = run_eval(select_tasks(ENVIRONMENTS, only="close_by_id"), nothing, [None])
    r = build_report(eps, ENVIRONMENTS)
    assert r["passed"] == 0 and r["failed_runs_without_kind"] == 1
    assert "failed runs with no failure kind: 1" in report_lines(r)


def test_as_row_from_record_and_episode_agree():
    ep = run_eval(select_tasks(ENVIRONMENTS, only="inbox/close_by_name"), ref_factory, [4])[0]
    from agent_gym.trajectory import to_record
    assert as_row(ep) == as_row(json.loads(json.dumps(to_record(ep))))


def test_cli_eval_pass_json_and_record(tmp_path, capsys):
    p = tmp_path / "run.jsonl"
    assert main(["eval", "--env", "inbox", "--repeats", "2", "--record", str(p), "--json"],
                client_factory=ref_factory) == EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert data["runs"] == 12 and data["seeds"] == [1, 2]
    assert len(read_jsonl(p)) == 12


def test_cli_eval_failure_exit_and_kind_in_table(capsys):
    def factory(env, task):
        if task.id == "close_by_name":
            return FakeClient(wrong_target_script(task, "set_status", "ticket_id", "T-1003"))
        return FakeClient(reference_script(task))
    assert main(["eval", "--only", "inbox/close"], client_factory=factory) == EXIT_FAILED
    out = capsys.readouterr().out
    assert "FAIL inbox/close_by_name (canonical) reward 0.000 ['wrong_target']" in out
    assert "inbox/close" in out and "id 100%, name 0%, gap +100 points" in out


def test_cli_eval_usage_and_ollama(capsys):
    assert main(["eval", "--only", "zzz"], client_factory=ref_factory) == EXIT_USAGE
    assert main(["eval", "--repeats", "0"], client_factory=ref_factory) == EXIT_USAGE
    assert main(["eval"], check=lambda m: (False, "not running")) == EXIT_OLLAMA


def test_cli_report_exit_codes(tmp_path, capsys):
    good = tmp_path / "good.jsonl"
    assert main(["eval", "--only", "delete", "--record", str(good)],
                client_factory=ref_factory) == EXIT_OK
    capsys.readouterr()
    assert main(["report", str(good)]) == EXIT_OK
    assert "total" in capsys.readouterr().out
    assert main(["report", str(good), "--json"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["runs"] == 2
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n")
    assert main(["report", str(empty)]) == EXIT_EMPTY
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n")
    assert main(["report", str(bad)]) == EXIT_USAGE
    assert main(["report", str(tmp_path / "missing.jsonl")]) == EXIT_USAGE
    broken = tmp_path / "broken.jsonl"
    broken.write_text(json.dumps({"format": 1, "env": "inbox"}) + "\n")
    assert main(["report", str(broken)]) == EXIT_USAGE


def test_cli_report_of_failed_run_exits_1(tmp_path, capsys):
    p = tmp_path / "f.jsonl"
    nothing = lambda env, task: FakeClient([LLMResponse(tool_calls=[ToolCall(SUBMIT, {})])])  # noqa: E731
    assert main(["eval", "--only", "close_by_id", "--record", str(p)],
                client_factory=nothing) == EXIT_FAILED
    assert main(["report", str(p)]) == EXIT_FAILED


# Day 7: Markdown results table (D34)

def test_report_names_the_model_from_records_and_live(tmp_path):
    chosen = select_tasks(ENVIRONMENTS, only="delete")
    eps = run_eval(chosen, ref_factory, [None])
    assert build_report(eps, ENVIRONMENTS)["models"] == []
    live = build_report(eps, ENVIRONMENTS, model="qwen3:4b")
    assert live["models"] == ["qwen3:4b"]
    p = tmp_path / "m.jsonl"
    write_jsonl(p, eps, model="qwen3:4b")
    assert build_report(read_jsonl(p), ENVIRONMENTS) == live


def test_markdown_lines_has_a_row_per_task_pair_and_total():
    eps = run_eval(select_tasks(ENVIRONMENTS), ref_factory, [None])
    report = build_report(eps, ENVIRONMENTS, model="fake")
    md = markdown_lines(report, "fake references")
    assert md[0] == "### fake references"
    assert "Model: fake. Runs: 12, passed 12 (100%), mean reward 1.000. Seeds: canonical." in md
    header = md[md.index("Model: fake. Runs: 12, passed 12 (100%), mean reward 1.000. "
                         "Seeds: canonical.") + 2]
    assert header.count("|") == len(KINDS) + 4 and "wrong target" in header
    task_rows = [line for line in md if line.startswith("| calendar/") or line.startswith("| inbox/")]
    assert len(task_rows) == 12 + 5
    assert md[md.index(header) + 14].startswith("| **total** | **12/12** | **1.000** |")
    assert "Failed runs with no failure kind: 0." in md
    assert md[-1] == "Pass rate with ids 100%, with names 100%, gap +0 points."
    assert not any("—" in line or "–" in line for line in md)


def test_markdown_counts_a_wrong_target_and_the_gap():
    def factory(env, task):
        if task.id == "close_by_name":
            return FakeClient(wrong_target_script(task, "set_status", "ticket_id", "T-1003"))
        return FakeClient(reference_script(task))
    eps = run_eval(select_tasks(ENVIRONMENTS, only="inbox/close"), factory, [None])
    md = markdown_lines(build_report(eps, ENVIRONMENTS, model="fake"))
    row = next(line for line in md if line.startswith("| inbox/close_by_name |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[1:3] == ["0/1", "0.000"]
    assert cells[3 + KINDS.index("wrong_target")] == "1" and sum(map(int, cells[3:])) == 1
    assert md[-1] == "Pass rate with ids 100%, with names 0%, gap +100 points."


def test_markdown_of_an_empty_report():
    assert markdown_lines(build_report([], ENVIRONMENTS), "x") == ["### x", "", "No runs."]


def test_cli_markdown_for_eval_and_report(tmp_path, capsys):
    p = tmp_path / "r.jsonl"
    assert main(["eval", "--only", "delete", "--record", str(p), "--markdown"],
                client_factory=ref_factory) == EXIT_OK
    live = capsys.readouterr().out
    assert live.startswith("### eval: 2 tasks x 1 seeds = 2 episodes")
    assert "PASS " not in live  # no progress lines in Markdown mode
    assert main(["report", str(p), "--markdown"]) == EXIT_OK
    from_file = capsys.readouterr().out
    assert from_file.startswith(f"### report of 2 episodes from {p}")
    assert live.splitlines()[1:] == from_file.splitlines()[1:]
    assert main(["report", str(p), "--json", "--markdown"]) == EXIT_USAGE
