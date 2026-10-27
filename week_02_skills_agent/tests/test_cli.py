import json
import shutil
from pathlib import Path

from skills_agent import FakeClient, LLMResponse, ToolCall
from skills_agent.cli import (
    EXIT_CHECK, EXIT_NOT_FOUND, EXIT_OK, EXIT_OLLAMA, EXIT_STOPPED, EXIT_USAGE, doctor_checks,
    main, normalize,
)

SKILLS = Path(__file__).resolve().parents[1] / "skills"
GOOD = ["commit-message", "incident-severity", "team-glossary", "ticket-checksum",
        "unit-converter"]


def tags_with(*names):
    return lambda url, timeout: {"models": [{"name": n} for n in names]}


def unreachable(url, timeout):
    raise OSError("connection refused")


def clean_root(tmp_path):
    root = tmp_path / "clean"
    for name in ("team-glossary", "unit-converter"):
        shutil.copytree(SKILLS / name, root / name)
    return root


def run_json(capsys, argv, **kw):
    code = main(argv + ["--json"], **kw)
    return code, json.loads(capsys.readouterr().out)


def test_list_json_shows_skills_and_rejected(capsys):
    code, data = run_json(capsys, ["list"])
    assert code == EXIT_OK
    assert [s["name"] for s in data["skills"]] == GOOD
    tc = next(s for s in data["skills"] if s["name"] == "ticket-checksum")
    assert tc["scripts"] == ["scripts/check_letter.py"]
    assert len(data["rejected"]) == 1 and data["rejected"][0].startswith("broken_skill")


def test_list_text_has_summary_line(capsys):
    assert main(["list"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "5 skills, 1 rejected" in out and "rejected: broken_skill" in out


def test_multiple_roots_first_wins_and_missing_root_reported(capsys, tmp_path):
    other = tmp_path / "other"
    shutil.copytree(SKILLS / "team-glossary", other / "team-glossary")
    code, data = run_json(capsys, ["list", "--skills-dir", str(other), "--skills-dir",
                                   str(SKILLS), "--skills-dir", str(tmp_path / "nope")])
    assert code == EXIT_OK
    glossary = next(s for s in data["skills"] if s["name"] == "team-glossary")
    assert glossary["path"].startswith(str(other))
    assert any("duplicate skill name 'team-glossary'" in r for r in data["rejected"])
    assert any("skills root does not exist" in r for r in data["rejected"])


def test_validate_fails_on_rejected_skill(capsys):
    code, data = run_json(capsys, ["validate"])
    assert code == EXIT_CHECK and data["ok"] is False
    assert data["valid"] == GOOD and len(data["errors"]) == 1


def test_validate_clean_root_ok_and_strict_fails_on_lint(capsys, tmp_path):
    root = clean_root(tmp_path)
    assert main(["validate", "--skills-dir", str(root)]) == EXIT_OK
    capsys.readouterr()
    vague = root / "vague-skill"
    vague.mkdir()
    (vague / "SKILL.md").write_text("---\nname: vague-skill\ndescription: Helps with "
                                    "stuff.\n---\nDo it.\n")
    code, data = run_json(capsys, ["validate", "--skills-dir", str(root)])
    assert code == EXIT_OK and data["lint"] and data["warnings"]  # warnings only
    code, data = run_json(capsys, ["validate", "--strict", "--skills-dir", str(root)])
    assert code == EXIT_CHECK and data["strict"] and data["ok"] is False


def test_inspect_shows_fields_files_and_tokens(capsys):
    code, data = run_json(capsys, ["inspect", "ticket-checksum"])
    assert code == EXIT_OK
    assert data["allowed_tools"] == ["run_skill_script(scripts/check_letter.py)"]
    assert data["scripts"] == ["scripts/check_letter.py"]
    t = data["tokens"]
    assert t["full"] == t["body"] + sum(t["files"].values()) and t["catalog"] > 0
    assert "body" not in data and data["lint"] == []


def test_inspect_body_flag_and_unknown_skill(capsys):
    assert main(["inspect", "team-glossary", "--body"]) == EXIT_OK
    assert "Blue Heron Expansion" in capsys.readouterr().out
    assert main(["inspect", "nope"]) == EXIT_NOT_FOUND
    assert "no skill named 'nope'" in capsys.readouterr().err


def test_run_json_with_fake_client(capsys):
    fake = FakeClient([LLMResponse(tool_calls=[ToolCall("load_skill", {"name": "team-glossary"})]),
                       LLMResponse(content="BHX is the Blue Heron Expansion.")])
    code, data = run_json(capsys, ["run", "What", "is", "BHX?"], client=fake)
    assert code == EXIT_OK
    assert data["loaded_skills"] == ["team-glossary"]
    assert data["stopped_reason"] == "final_answer" and "Blue Heron" in data["answer"]
    assert data["context"]["load"] > 0
    assert fake.calls[0][-1]["content"] == "What is BHX?"


def test_short_form_still_runs_and_step_limit_exit(capsys):
    loop = [LLMResponse(tool_calls=[ToolCall("load_skill", {"name": "team-glossary"})])] * 5
    fake = FakeClient([LLMResponse(content="done")])
    assert main(["--budget", "5000", "task"], client=fake) == EXIT_OK  # parsed as run
    assert "[context: ~" in capsys.readouterr().out and fake.calls[0][-1]["content"] == "task"
    code = main(["run", "--max-steps", "2", "task"], client=FakeClient(list(loop)))
    assert code == EXIT_STOPPED
    assert normalize(["What is BHX?"]) == ["run", "What is BHX?"]
    assert normalize(["list"]) == ["list"] and normalize(["--help"]) == ["--help"]


def test_run_connection_error_exit_4(capsys):
    class Down:
        def chat(self, messages, tools):
            raise ConnectionError("Ollama is not reachable")
    assert main(["run", "hi"], client=Down()) == EXIT_OLLAMA
    assert "not reachable" in capsys.readouterr().err


def test_usage_errors_exit_2(capsys):
    assert main([]) == EXIT_USAGE
    assert main(["run"]) == EXIT_USAGE
    assert main(["run", "--max-steps", "0", "x"]) == EXIT_USAGE
    assert main(["inspect"]) == EXIT_USAGE
    assert main(["--help"]) == EXIT_OK


def test_doctor_ok_with_model_pulled(capsys):
    code, data = run_json(capsys, ["doctor", "--model", "qwen3:4b"],
                          fetch=tags_with("qwen3:4b"))
    assert code == EXIT_OK and data["ok"] is True
    status = {c["name"]: c["status"] for c in data["checks"]}
    assert status["ollama"] == "ok" and status["rejected skills"] == "warn"
    assert status["valid skills"] == "ok" and status["python"] == "ok"


def test_doctor_ollama_only_failure_is_exit_4(capsys):
    assert main(["doctor"], fetch=unreachable) == EXIT_OLLAMA
    assert main(["doctor", "--model", "llama3.2"], fetch=tags_with("qwen3:4b")) == EXIT_OLLAMA
    assert "ollama pull llama3.2" in capsys.readouterr().out
    assert main(["doctor", "--offline"], fetch=unreachable) == EXIT_OK


def test_doctor_missing_root_or_old_python_is_exit_1(tmp_path):
    checks = doctor_checks([tmp_path / "nope"], "qwen3:4b", offline=True)
    status = {c["name"]: c["status"] for c in checks}
    assert status["skills roots"] == "fail" and status["valid skills"] == "fail"
    assert main(["doctor", "--offline", "--skills-dir", str(tmp_path / "nope")]) == EXIT_CHECK
    old = doctor_checks([SKILLS], "x", offline=True, version=(3, 9, 18))
    assert old[0] == {"name": "python", "status": "fail", "detail": "3.9.18 (needs 3.10+)"}
