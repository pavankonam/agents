"""Day 4: context budget, token estimates and the progressive vs paste-all report."""

import json
from pathlib import Path

import pytest

from skills_agent import (
    LOAD_SKILL, READ_SKILL_FILE, RUN_SKILL_SCRIPT, Agent, ContextBudget, FakeClient, LLMResponse,
    SkillLibrary, ToolCall, context_report, estimate_tokens, format_report,
)
from skills_agent.budget import eager_prompt, main, skill_costs, tools_tokens

SKILLS = Path(__file__).resolve().parents[1] / "skills"


def lib():
    return SkillLibrary.discover(SKILLS)


def call(tool, **args):
    return LLMResponse(tool_calls=[ToolCall(tool, args)])


def test_estimate_tokens_is_ceil_chars_over_four():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("x" * 400) == 100


def test_tools_tokens_empty_and_nonempty():
    assert tools_tokens([]) == 0
    tools = Agent(FakeClient([]), lib()).tools()
    assert tools_tokens(tools) == estimate_tokens(json.dumps(tools, separators=(",", ":")))


def test_budget_meter_basics():
    b = ContextBudget(100)
    assert b.fits(100) and not b.fits(101)
    b.charge("load", 60)
    assert b.spent == 60 and b.remaining == 40
    assert not b.fits(41)
    with pytest.raises(ValueError):
        b.charge("nope", 1)
    unlimited = ContextBudget()
    unlimited.charge("system", 10**9)
    assert unlimited.fits(10**9) and unlimited.remaining is None


@pytest.mark.parametrize("bad", [0, -5])
def test_budget_rejects_non_positive_limits(bad):
    with pytest.raises(ValueError):
        ContextBudget(bad)
    with pytest.raises(ValueError):
        Agent(FakeClient([]), lib(), budget_tokens=bad)


def test_skill_costs_cover_every_level():
    costs = {c.name: c for c in skill_costs(lib())}
    assert set(costs) == set(lib().names())
    sev = costs["incident-severity"]
    assert sev.catalog > 0 and sev.body > 0
    assert list(sev.files) == ["references/severity-matrix.md"]
    assert sev.full == sev.body + sev.files["references/severity-matrix.md"]
    assert costs["team-glossary"].files == {}


def test_eager_prompt_contains_every_body_and_file():
    text = eager_prompt(lib())
    for s in lib().skills.values():
        assert s.body in text
    assert "Code Crimson" in text  # level 3 content is pasted too
    assert "broken_skill" not in text  # rejected skills are never pasted


def test_report_numbers_are_consistent():
    r = context_report(lib())
    p = r["progressive"]
    assert p["base"] == p["system_prompt"] + p["tools"]
    assert p["all_loaded"] == p["base"] + sum(s["full"] for s in r["skills"])
    assert p["base"] < p["one_skill_avg"] < p["all_loaded"]
    # with the shipped skills, the catalog is cheaper than pasting everything
    assert p["base"] < r["eager"]["system_prompt"]
    # but loading every skill through tools costs more than pasting (fixed overhead)
    assert p["all_loaded"] > r["eager"]["system_prompt"]
    proj = r["projection"]
    assert [x["skills"] for x in proj] == [5, 20, 50, 100]
    # the gap grows with the number of skills
    gaps = [x["eager"] - x["progressive_one_skill"] for x in proj]
    assert gaps == sorted(gaps) and gaps[-1] > 0


def test_report_on_empty_library():
    r = context_report(SkillLibrary())
    assert r["skills"] == [] and r["projection"] == []
    assert "paste every skill" in format_report(r)


def test_format_report_and_cli(capsys):
    assert main(["--skills-dir", str(SKILLS)]) == 0
    out = capsys.readouterr().out
    assert "incident-severity" in out and "paste every skill" in out and "projection" in out
    assert main(["--skills-dir", str(SKILLS), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["progressive"]["base"] > 0


def test_run_records_context_per_level():
    fake = FakeClient([call(LOAD_SKILL, name="incident-severity"),
                       call(READ_SKILL_FILE, skill="incident-severity",
                            path="references/severity-matrix.md"),
                       LLMResponse(content="Code Crimson")])
    r = Agent(fake, lib()).run("checkout down")
    c = r.context
    assert c["limit"] is None and c["refused"] == []
    assert c["system"] > 0 and c["load"] > 0 and c["read"] > 0 and c["script"] == 0
    assert c["spent"] == c["system"] + c["load"] + c["read"] + c["script"] + c["other"]
    # level 2 charge equals the estimate of exactly what the model received
    assert c["load"] == estimate_tokens(fake.calls[1][-1]["content"])
    assert c["read"] == estimate_tokens(fake.calls[2][-1]["content"])


def test_no_tool_run_costs_only_the_system_part():
    r = Agent(FakeClient([LLMResponse(content="ready")]), lib()).run("Say ready")
    assert r.context["spent"] == r.context["system"]


def _system_cost(task):
    return Agent(FakeClient([LLMResponse(content="x")]), lib()).run(task).context["system"]


def test_load_past_the_limit_is_refused_and_not_loaded():
    task = "What does BHX mean?"
    limit = _system_cost(task) + 10  # fits the prompt, not the glossary body
    fake = FakeClient([call(LOAD_SKILL, name="team-glossary"), LLMResponse(content="unknown")])
    r = Agent(fake, lib(), budget_tokens=limit).run(task)
    msg = fake.calls[1][-1]["content"]
    assert msg.startswith("error: context budget: load_skill team-glossary needs about")
    assert "Blue Heron Expansion" not in msg
    assert r.loaded_skills == []
    assert r.context["load"] == 0 and len(r.context["refused"]) == 1
    assert r.stopped_reason == "final_answer"


def test_refused_load_keeps_files_locked():
    task = "checkout down"
    limit = _system_cost(task) + 10
    fake = FakeClient([call(LOAD_SKILL, name="incident-severity"),
                       call(READ_SKILL_FILE, skill="incident-severity",
                            path="references/severity-matrix.md"),
                       LLMResponse(content="?")])
    r = Agent(fake, lib(), budget_tokens=limit).run(task)
    assert "is not loaded" in fake.calls[2][-1]["content"]
    assert r.read_files == []


def test_read_past_the_limit_is_refused_after_a_successful_load():
    task = "checkout down"
    agent_probe = FakeClient([call(LOAD_SKILL, name="incident-severity"),
                              LLMResponse(content="x")])
    probe = Agent(agent_probe, lib()).run(task).context
    limit = probe["system"] + probe["load"] + 5  # body fits, the matrix file does not
    fake = FakeClient([call(LOAD_SKILL, name="incident-severity"),
                       call(READ_SKILL_FILE, skill="incident-severity",
                            path="references/severity-matrix.md"),
                       LLMResponse(content="SEV2, colour unknown")])
    r = Agent(fake, lib(), budget_tokens=limit).run(task)
    assert r.loaded_skills == ["incident-severity"]
    assert r.read_files == []
    msg = fake.calls[2][-1]["content"]
    assert "read_skill_file incident-severity/references/severity-matrix.md" in msg
    assert "Code Crimson" not in msg
    assert r.context["spent"] <= limit + estimate_tokens(msg)


def test_script_output_past_the_limit_is_withheld_but_run_is_recorded():
    task = "ticket HX-40217"
    probe_fake = FakeClient([call(LOAD_SKILL, name="ticket-checksum"), LLMResponse(content="x")])
    probe = Agent(probe_fake, lib()).run(task).context
    limit = probe["system"] + probe["load"] + 5
    fake = FakeClient([call(LOAD_SKILL, name="ticket-checksum"),
                       call(RUN_SKILL_SCRIPT, skill="ticket-checksum",
                            script="scripts/check_letter.py", args=["HX-40217"]),
                       LLMResponse(content="?")])
    r = Agent(fake, lib(), budget_tokens=limit).run(task)
    msg = fake.calls[2][-1]["content"]
    assert msg.startswith("error: context budget: output of ticket-checksum/")
    assert "HX-40217-C" not in msg
    assert r.ran_scripts == ["ticket-checksum/scripts/check_letter.py exit=0"]
    assert r.context["script"] == 0


def test_generous_budget_changes_nothing():
    script = [call(LOAD_SKILL, name="team-glossary"), LLMResponse(content="Blue Heron Expansion")]
    a = Agent(FakeClient(list(script)), lib()).run("BHX?")
    b = Agent(FakeClient(list(script)), lib(), budget_tokens=100_000).run("BHX?")
    assert a.loaded_skills == b.loaded_skills == ["team-glossary"]
    assert a.context["spent"] == b.context["spent"] and b.context["refused"] == []


def test_budget_resets_between_runs():
    agent = Agent(FakeClient([LLMResponse(content="a"), LLMResponse(content="b")]), lib(),
                  budget_tokens=100_000)
    first = agent.run("one").context["spent"]
    second = agent.run("one").context["spent"]
    assert first == second


def test_main_budget_flag_validation(capsys):
    from skills_agent.__main__ import main as cli
    assert cli(["--budget"]) == 2
    assert cli(["--budget", "abc", "task"]) == 2
    assert cli(["--budget", "0", "task"]) == 2
    assert cli(["--budget", "500"]) == 2
