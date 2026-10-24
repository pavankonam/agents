"""Skill scripts: permission from allowed-tools, confinement, no shell, timeout, caps."""

import os
from pathlib import Path

import pytest

from skills_agent import (
    LOAD_SKILL, RUN_SKILL_SCRIPT, Agent, FakeClient, LLMResponse, SkillError, SkillLibrary,
    ToolCall, list_scripts, load_skill_dir, resolve_script, run_script, script_permission,
)
from skills_agent.agent import READ_SKILL_FILE

SKILLS = Path(__file__).resolve().parents[1] / "skills"
CHECK = "scripts/check_letter.py"


def make_skill(root: Path, allowed: str = "run_skill_script", name: str = "demo",
               scripts: dict | None = None) -> Path:
    d = root / name
    (d / "scripts").mkdir(parents=True)
    fm = f"---\nname: {name}\ndescription: a demo skill with scripts used by the tests\n"
    if allowed:
        fm += f"allowed-tools: {allowed}\n"
    (d / "SKILL.md").write_text(fm + "---\nRun scripts/echo.py\n", encoding="utf-8")
    scripts = scripts or {"echo.py": "import sys\nprint('args:', sys.argv[1:])\n"}
    for fname, code in scripts.items():
        (d / "scripts" / fname).write_text(code, encoding="utf-8")
    return d


def call_run(skill, script, args=None):
    a = {"skill": skill, "script": script}
    if args is not None:
        a["args"] = args
    return LLMResponse(tool_calls=[ToolCall(RUN_SKILL_SCRIPT, a)])


def load(name):
    return LLMResponse(tool_calls=[ToolCall(LOAD_SKILL, {"name": name})])


def tool_msgs(fake, turn):
    return [m["content"] for m in fake.calls[turn] if m["role"] == "tool"]


# ---- permission -------------------------------------------------------------

@pytest.mark.parametrize("allowed, rel, ok", [
    ("run_skill_script", "scripts/a.py", True),
    ("run_skill_script(scripts/a.py)", "scripts/a.py", True),
    ("run_skill_script(scripts/a.py)", "scripts/b.py", False),
    ("run_skill_script(scripts/*.py)", "scripts/b.py", True),
    ("run_skill_script(scripts/*.py)", "scripts/b.sh", False),
    ("Bash(git:*) Read", "scripts/a.py", False),
    ("", "scripts/a.py", False),
    ("run_skill_scripts", "scripts/a.py", False),
])
def test_script_permission(tmp_path, allowed, rel, ok):
    s = load_skill_dir(make_skill(tmp_path, allowed))
    assert script_permission(s, rel) is ok


def test_list_scripts_only_permitted_known_types_in_scripts_dir(tmp_path):
    d = make_skill(tmp_path, "run_skill_script(scripts/*)",
                   scripts={"a.py": "", "b.sh": "", "c.rb": ""})
    (d / "tool.py").write_text("print(1)")
    assert list_scripts(load_skill_dir(d)) == ["scripts/a.py", "scripts/b.sh"]


def test_skill_without_allowed_tools_cannot_run(tmp_path):
    s = load_skill_dir(make_skill(tmp_path, allowed=""))
    assert list_scripts(s) == []
    with pytest.raises(SkillError, match="does not allow"):
        run_script(s, "scripts/echo.py")


@pytest.mark.parametrize("bad, msg", [
    ("../x.py", "'..'"), ("/bin/sh", "relative"), ("SKILL.md", "load_skill"),
    ("tool.py", "not in the skill's scripts/"), ("scripts/c.rb", "unsupported"),
    ("scripts/missing.py", "no file"), ("scripts/.hidden.py", "hidden"),
])
def test_resolve_script_refuses(tmp_path, bad, msg):
    d = make_skill(tmp_path, scripts={"echo.py": "", "c.rb": "", ".hidden.py": ""})
    (d / "tool.py").write_text("print(1)")
    with pytest.raises(SkillError, match=msg):
        resolve_script(load_skill_dir(d), bad)


def test_symlinked_script_outside_is_refused(tmp_path):
    d = make_skill(tmp_path)
    evil = tmp_path / "evil.py"
    evil.write_text("print('pwned')")
    os.symlink(evil, d / "scripts" / "evil.py")
    with pytest.raises(SkillError, match="outside"):
        run_script(load_skill_dir(d), "scripts/evil.py")


# ---- running ----------------------------------------------------------------

def test_args_are_not_shell_parsed(tmp_path):
    s = load_skill_dir(make_skill(tmp_path))
    r = run_script(s, "scripts/echo.py", ["a b", "$(touch pwned)", "; rm -rf /"])
    assert r.exit_code == 0 and not r.timed_out
    assert "'a b', '$(touch pwned)', '; rm -rf /'" in r.stdout
    assert not (tmp_path / "demo" / "pwned").exists()


@pytest.mark.parametrize("args, msg", [
    ({"a": 1}, "list"), ([None], "string"), (["x\x00y"], "NUL"),
    (["x"] * 17, "at most"), (["x" * 501], "max"),
])
def test_bad_args_refused(tmp_path, args, msg):
    s = load_skill_dir(make_skill(tmp_path))
    with pytest.raises(SkillError, match=msg):
        run_script(s, "scripts/echo.py", args)


def test_single_string_and_number_args_are_accepted(tmp_path):
    s = load_skill_dir(make_skill(tmp_path))
    assert "['one arg']" in run_script(s, "scripts/echo.py", "one arg").stdout
    assert "['7']" in run_script(s, "scripts/echo.py", [7]).stdout
    assert "['HX-1', 'b']" in run_script(s, "scripts/echo.py", '["HX-1", "b"]').stdout
    assert "['[not json']" in run_script(s, "scripts/echo.py", "[not json").stdout


def test_cwd_env_and_stdin(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "hunter2")
    code = ("import os, sys\nprint(os.getcwd())\nprint(os.environ.get('SECRET_TOKEN'))\n"
            "print(repr(sys.stdin.read()))\n")
    s = load_skill_dir(make_skill(tmp_path, scripts={"env.py": code}))
    out = run_script(s, "scripts/env.py").stdout.splitlines()
    assert out[0] == str((tmp_path / "demo").resolve())
    assert out[1] == "None" and out[2] == "''"


def test_exit_code_and_stderr(tmp_path):
    code = "import sys\nprint('bad input', file=sys.stderr)\nsys.exit(3)\n"
    s = load_skill_dir(make_skill(tmp_path, scripts={"fail.py": code}))
    r = run_script(s, "scripts/fail.py")
    assert r.exit_code == 3 and "bad input" in r.stderr


def test_timeout_kills_the_script(tmp_path):
    s = load_skill_dir(make_skill(tmp_path, scripts={"slow.py": "import time\ntime.sleep(30)\n"}))
    r = run_script(s, "scripts/slow.py", timeout=0.5)
    assert r.timed_out and r.exit_code is None and r.seconds < 5


def test_output_is_capped(tmp_path):
    s = load_skill_dir(make_skill(tmp_path, scripts={"big.py": "print('x' * 100000)\n"}))
    r = run_script(s, "scripts/big.py", max_output=100)
    assert r.truncated and len(r.stdout) == 100


def test_shell_script_runs_with_sh(tmp_path):
    s = load_skill_dir(make_skill(tmp_path, scripts={"hi.sh": 'echo "hi $1"\n'}))
    assert run_script(s, "scripts/hi.sh", ["there"]).stdout == "hi there\n"


def test_shipped_ticket_checksum_script():
    s = SkillLibrary.discover(SKILLS).get("ticket-checksum")
    assert list_scripts(s) == [CHECK]
    assert run_script(s, CHECK, ["HX-40217"]).stdout.strip() == "HX-40217-C"
    assert run_script(s, CHECK, ["hx-40217-c"]).stdout.startswith("VALID")
    bad = run_script(s, CHECK, ["HX-40217-A"])
    assert bad.exit_code == 1 and "expected check letter C" in bad.stdout
    assert run_script(s, CHECK, ["HX40217"]).exit_code == 2


# ---- agent ------------------------------------------------------------------

def test_tool_offered_only_for_skills_with_permitted_scripts():
    agent = Agent(FakeClient([]), SkillLibrary.discover(SKILLS))
    tools = {t["function"]["name"]: t for t in agent.tools()}
    enum = tools[RUN_SKILL_SCRIPT]["function"]["parameters"]["properties"]["skill"]["enum"]
    assert enum == ["ticket-checksum"]


def test_no_run_tool_without_permitted_scripts(tmp_path):
    make_skill(tmp_path, allowed="")
    names = [t["function"]["name"] for t in Agent(FakeClient([]),
                                                  SkillLibrary.discover(tmp_path)).tools()]
    assert RUN_SKILL_SCRIPT not in names and READ_SKILL_FILE in names


def test_agent_runs_script_after_load_and_records_it():
    fake = FakeClient([load("ticket-checksum"), call_run("ticket-checksum", CHECK, ["HX-40217"]),
                       LLMResponse(content="HX-40217-C")])
    r = Agent(fake, SkillLibrary.discover(SKILLS)).run("ticket HX-40217?")
    msg = tool_msgs(fake, 2)[-1]
    assert msg.startswith('<script_result skill="ticket-checksum" '
                          f'script="{CHECK}" exit_code="0">')
    assert "HX-40217-C" in msg
    assert r.ran_scripts == [f"ticket-checksum/{CHECK} exit=0"]


def test_run_before_load_is_refused():
    fake = FakeClient([call_run("ticket-checksum", CHECK, ["HX-40217"]),
                       LLMResponse(content="ok")])
    r = Agent(fake, SkillLibrary.discover(SKILLS)).run("x")
    msg = tool_msgs(fake, 1)[0]
    assert msg.startswith("error: skill 'ticket-checksum' is not loaded")
    assert r.ran_scripts == []


def test_refused_script_lists_runnable_ones(tmp_path):
    make_skill(tmp_path, allowed="run_skill_script(scripts/echo.py)",
               scripts={"echo.py": "print(1)", "other.py": "print(2)"})
    fake = FakeClient([load("demo"), call_run("demo", "scripts/other.py"),
                       LLMResponse(content="ok")])
    r = Agent(fake, SkillLibrary.discover(tmp_path)).run("x")
    msg = tool_msgs(fake, 2)[-1]
    assert "does not allow" in msg and "Scripts this skill may run: scripts/echo.py" in msg
    assert r.ran_scripts == []


def test_failed_and_timed_out_runs_are_reported(tmp_path, monkeypatch):
    import skills_agent.scripts as sc
    monkeypatch.setattr(sc, "SCRIPT_TIMEOUT", 0.5)
    make_skill(tmp_path, scripts={"fail.py": "import sys\nsys.exit(2)\n",
                                  "slow.py": "import time\ntime.sleep(30)\n"})
    fake = FakeClient([load("demo"), call_run("demo", "scripts/fail.py"),
                       call_run("demo", "scripts/slow.py"), LLMResponse(content="ok")])
    r = Agent(fake, SkillLibrary.discover(tmp_path)).run("x")
    fail, slow = tool_msgs(fake, 3)[-2:]
    assert 'exit_code="2"' in fail
    assert 'exit_code="timeout"' in slow and "[stopped:" in slow
    assert r.ran_scripts == ["demo/scripts/fail.py exit=2", "demo/scripts/slow.py exit=timeout"]


def test_run_argument_errors():
    calls = [ToolCall(RUN_SKILL_SCRIPT, {"script": CHECK}),
             ToolCall(RUN_SKILL_SCRIPT, {"skill": "ticket-checksum"}),
             ToolCall(RUN_SKILL_SCRIPT, {"skill": "nope", "script": CHECK})]
    fake = FakeClient([LLMResponse(tool_calls=calls), LLMResponse(content="ok")])
    Agent(fake, SkillLibrary.discover(SKILLS)).run("x")
    a, b, c = tool_msgs(fake, 1)
    assert a == "error: run_skill_script needs a 'skill' argument"
    assert b == "error: run_skill_script needs a 'script' argument"
    assert c == "error: no skill named 'nope'"


def test_system_prompt_mentions_run_tool():
    fake = FakeClient([LLMResponse(content="hi")])
    Agent(fake, SkillLibrary.discover(SKILLS)).run("hello")
    system = fake.calls[0][0]["content"]
    assert RUN_SKILL_SCRIPT in system and "HX-40217-C" not in system
