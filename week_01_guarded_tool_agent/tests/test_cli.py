import io
import json
from pathlib import Path

import pytest

from guarded_agent import FakeClient, LLMResponse, ToolCall, check_ollama, load_events
from guarded_agent.cli import EXIT_MAX_STEPS, EXIT_OLLAMA, main, normalise
from guarded_agent.llm import _model_matches

PROJECT = Path(__file__).resolve().parents[1]
POLICY = str(PROJECT / "policy.json")
MCP = str(PROJECT / "mcp_servers.json")


def cli(argv, responses=None, approver=None):
    out = io.StringIO()
    llm = FakeClient(responses or [])
    code = main(argv, out=out, llm_factory=lambda args: llm, approver=approver)
    return code, out.getvalue(), llm


def base(tmp_path):
    return ["--policy", POLICY, "--workspace", str(tmp_path / "ws"),
            "--audit-dir", str(tmp_path / "logs")]


def test_bare_task_means_run():
    assert normalise(["what is 2+2"]) == ["run", "what is 2+2"]
    assert normalise(["--model", "x", "hi"]) == ["run", "--model", "x", "hi"]
    assert normalise(["tools"]) == ["tools"]
    assert normalise(["replay", "a.jsonl"]) == ["replay", "a.jsonl"]


def test_run_prints_decisions_answer_and_audit(tmp_path):
    code, out, _ = cli([*base(tmp_path), "what", "is", "17*23"], [
        LLMResponse(tool_calls=[ToolCall("calculator", {"expression": "17*23"})]),
        LLMResponse(content="391")])
    assert code == 0
    assert '[tool] calculator({"expression": "17*23"})  verdict=allow ran' in out
    assert "\n391\n" in out
    logs = list((tmp_path / "logs").glob("*.jsonl"))
    assert len(logs) == 1
    events, bad = load_events(logs[0])
    assert bad == 0 and events[0]["task"] == "what is 17*23"
    assert [e["type"] for e in events][-1] == "run_end"


def test_json_output_is_one_object(tmp_path):
    code, out, _ = cli([*base(tmp_path), "--json", "hi"], [LLMResponse(content="hello")])
    data = json.loads(out)  # nothing else printed
    assert code == 0
    assert data["answer"] == "hello" and data["stopped_reason"] == "final_answer"
    assert data["decisions"] == [] and data["run_id"] and Path(data["audit_log"]).is_file()


def test_no_audit_writes_nothing(tmp_path):
    code, out, _ = cli([*base(tmp_path), "--no-audit", "hi"], [LLMResponse(content="ok")])
    assert code == 0 and "[audit]" not in out
    assert not (tmp_path / "logs").exists()


def test_non_interactive_declines_ask_without_prompting(tmp_path):
    asked = []
    code, out, _ = cli([*base(tmp_path), "--non-interactive", "--json", "save"], [
        LLMResponse(tool_calls=[ToolCall("write_file", {"path": "a.txt", "content": "x"})]),
        LLMResponse(content="blocked")],
        approver=lambda *a: asked.append(a) or True)
    d = json.loads(out)["decisions"][0]
    assert code == 0 and asked == []
    assert d["verdict"] == "ask" and d["approved"] is False
    assert not (tmp_path / "ws" / "a.txt").exists()


def test_approver_is_used_when_interactive(tmp_path):
    code, out, _ = cli([*base(tmp_path), "--json", "save"], [
        LLMResponse(tool_calls=[ToolCall("write_file", {"path": "a.txt", "content": "x"})]),
        LLMResponse(content="saved")], approver=lambda *a: True)
    assert json.loads(out)["decisions"][0]["approved"] is True
    assert (tmp_path / "ws" / "a.txt").read_text() == "x"


def test_max_steps_flag_and_exit_code(tmp_path):
    loop = [LLMResponse(tool_calls=[ToolCall("calculator", {"expression": "1+1"})])] * 5
    code, out, llm = cli([*base(tmp_path), "--max-steps", "2", "loop"], loop)
    assert code == EXIT_MAX_STEPS and len(llm.calls) == 2
    assert "step limit reached (2 steps)" in out
    assert cli([*base(tmp_path), "--max-steps", "0", "x"])[0] == 2


def test_ollama_down_gives_clear_error_and_logged_run(tmp_path):
    class Down:
        model = "qwen3:4b"

        def chat(self, messages, tools):
            raise ConnectionError("Could not reach Ollama at http://localhost:11434.")
    out = io.StringIO()
    code = main([*base(tmp_path), "hi"], out=out, llm_factory=lambda a: Down())
    assert code == EXIT_OLLAMA
    assert "Could not reach Ollama" in out.getvalue() and "doctor" in out.getvalue()
    events, _ = load_events(next((tmp_path / "logs").glob("*.jsonl")))
    assert events[-1]["type"] == "run_error"


def test_tools_command_shows_verdicts_and_sources(tmp_path):
    out = io.StringIO()
    code = main(["tools", "--policy", POLICY, "--workspace", str(tmp_path / "ws"),
                 "--mcp", MCP], out=out)
    rows = {line.split()[0]: line.split() for line in out.getvalue().splitlines()[1:]}
    assert code == 0
    assert rows["calculator"][1:3] == ["allow", "builtin"]
    assert rows["write_file"][1:3] == ["ask", "files"]
    assert rows["demo__shell_exec"][1:3] == ["deny", "mcp:demo"]
    assert rows["demo__reverse"][1] == "ask" and "pattern" in " ".join(rows["demo__reverse"])


def test_unknown_tool_in_tools_listing_uses_default(tmp_path):
    pol = tmp_path / "p.json"
    pol.write_text(json.dumps({"default": "deny", "tools": {"calculator": "allow"}}))
    out = io.StringIO()
    main(["tools", "--policy", str(pol), "--workspace", str(tmp_path / "ws")], out=out)
    line = next(l for l in out.getvalue().splitlines() if l.startswith("read_file"))
    assert line.split()[1] == "deny" and line.endswith("default")


def test_bad_config_is_a_usage_error_not_a_traceback(tmp_path):
    code, out, _ = cli(["--policy", str(tmp_path / "missing.json"), "hi"])
    assert code == 2 and out.startswith("error: FileNotFoundError")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    code, out, _ = cli(["--policy", str(bad), "hi"])
    assert code == 2 and "JSONDecodeError" in out
    assert cli([])[0] == 2


@pytest.mark.parametrize("wanted,have,ok", [
    ("qwen3:4b", "qwen3:4b", True), ("qwen3", "qwen3:latest", True),
    ("qwen3:4b", "qwen3:latest", False), ("llama3.2", "llama3.2", True),
])
def test_model_name_matching(wanted, have, ok):
    assert _model_matches(wanted, have) is ok


def test_check_ollama_states():
    up = lambda url, timeout: {"models": [{"name": "qwen3:4b"}, {"name": "llama3.2:latest"}]}
    ok, msg = check_ollama("qwen3:4b", "http://h:1/", fetch=up)
    assert ok and "is up" in msg
    ok, msg = check_ollama("gemma3", "http://h:1", fetch=up)
    assert not ok and "ollama pull gemma3" in msg and "llama3.2:latest" in msg

    def down(url, timeout):
        assert url == "http://h:1/api/tags"
        raise OSError("connection refused")
    ok, msg = check_ollama("qwen3:4b", "http://h:1", fetch=down)
    assert not ok and "ollama serve" in msg


def test_doctor_against_closed_port():
    out = io.StringIO()
    code = main(["doctor", "--host", "http://127.0.0.1:9", "--model", "qwen3:4b"], out=out)
    assert code == EXIT_OLLAMA and out.getvalue().startswith("PROBLEM:")
