# Week 01: Guarded Tool Agent

A small tool calling agent that runs on a **free local model through Ollama**, where every tool call passes through a permission policy (and, from day 4, an audit log). See [PRD.md](PRD.md) for the plan, [flow.md](flow.md) for how it works and [decision.md](decision.md) for why.

**Status:** Day 2 of 7. Core agent loop, calculator and time tools, permission policy with argument rules and human approval, tests.

## Permission policy

Edit `policy.json`. Every tool is `allow`, `ask` (you approve on the terminal) or `deny`; unlisted tools use `default` (shipped as `deny`). Argument rules can only make a call stricter:

```json
{
  "default": "deny",
  "tools": {
    "calculator": {"verdict": "allow",
                   "rules": [{"arg": "expression", "type": "max_length", "value": 200}]},
    "current_time": "ask"
  }
}
```

Rule types: `path_within` (path must resolve inside a folder, symlinks followed), `pattern` (regex full match), `max_length`, `one_of`. Blocked calls are returned to the model as `error: denied by policy: ...`. Point to another file with `GUARDED_AGENT_POLICY=path/to/policy.json`.

## Run it locally

```bash
# 1. Install Ollama from https://ollama.com and pull a tool capable model
ollama pull qwen3:4b

# 2. From this folder
cd week_01_guarded_tool_agent
pip install -r requirements.txt   # only pytest, the agent itself has no dependencies

# 3. Ask something
PYTHONPATH=src python3 -m guarded_agent "What is 17 * 23?"

# 4. Quiz the agent against the real model
python3 quiz/quiz_model.py            # uses qwen3:4b
python3 quiz/quiz_model.py --model llama3.2

# 5. Tests (no model needed)
python3 -m pytest -q
```

Use another model with `GUARDED_AGENT_MODEL=llama3.2`.

## Layout

```
src/guarded_agent/
  llm.py      OllamaClient (stdlib HTTP) and FakeClient
  tools.py    Tool, ToolRegistry, safe calculator, current_time
  policy.py   Policy (allow / ask / deny), argument rules, approver
  agent.py    the agent loop: every tool call goes through the policy
policy.json   the default policy used by the CLI and quiz_model.py
tests/        pytest suite using FakeClient
quiz/         quiz.md (self quiz) and quiz_model.py (quizzes the agent)
```
