# Self Quiz: Guarded Tool Agent

Each day the automation answers these from memory, then checks the answer against the code and docs. A FAIL means either the answer or the docs were wrong, and it gets fixed the same day.

## Day 1 (2026-10-15)

**Q1. What happens if the model calls a tool that does not exist?**
A: `ToolRegistry.call` returns `"error: unknown tool '<name>'. Available: ..."`, which is added as a `tool` message so the model can recover. Nothing is raised.
Check: `tools.py` `ToolRegistry.call`, test `test_unknown_tool_is_reported_not_raised`. **PASS**

**Q2. How does the agent decide it is finished?**
A: When a model reply contains no tool calls, its text is the final answer (`stopped_reason = "final_answer"`).
Check: `agent.py` `Agent.run`. **PASS**

**Q3. What stops an agent that keeps calling tools forever?**
A: `max_steps` (default 6). After that many model turns it returns `"Stopped: step limit reached"` with `stopped_reason = "max_steps"`.
Check: `agent.py`, test `test_max_steps_guard`. **PASS**

**Q4. Why does the calculator not use `eval`?**
A: Model output is untrusted. `safe_eval` walks the `ast` and only allows numeric constants and arithmetic operators, and caps exponents at 100, so code like `__import__('os')` is rejected.
Check: `tools.py` `safe_eval`, test `test_safe_eval_rejects_code`. **PASS**

**Q5. Which default model and how do you change it?**
A: `qwen3:4b`, overridable with the `GUARDED_AGENT_MODEL` environment variable or `--model` in `quiz_model.py`.
Check: `llm.py` `DEFAULT_MODEL`, `decision.md` D3. **PASS**

**Q6. Why is there no Ollama SDK dependency?**
A: The core uses `urllib` to keep zero dependencies so tests run anywhere (decision D4).
Check: `llm.py`, `requirements.txt`. **PASS**

**Q7. How can the tests run without a model?**
A: `FakeClient` replays scripted `LLMResponse` objects and records the messages it received.
Check: `llm.py` `FakeClient`. **PASS**

**Day 1 score: 7/7**

## Day 2 (2026-10-16)

**Q8. A tool is marked `allow` but the model passes `path: "../secrets.txt"` and the tool has a `path_within: workspace` rule. What happens?**
A: Argument rules are checked before the verdict, so the call becomes `deny` with reason `argument rule: ...`, the tool never runs and the approver is not asked.
Check: `policy.py` `Policy.check`, tests `test_rule_violation_denies_even_allowed_tool_and_skips_approver`, `test_path_within`. Ran `Policy.check` on `../a`: `deny`. **PASS**

**Q9. A tool is `ask` but no approver was passed to the Agent. Does it run?**
A: No. `Policy.decide` appends "no approver configured, treated as deny" and `approved` stays False.
Check: `policy.py` `Policy.decide`, test `test_ask_without_approver_is_denied`. Ran it: reason `tool 'x' is ask; no approver configured, treated as deny`. **PASS**

**Q10. What does an `Agent` do if you forget to pass a policy?**
A: It builds `Policy(default="deny")`, so every registered tool is blocked (fail closed, D11).
Check: `agent.py` `Agent.__init__`, test `test_agent_without_policy_fails_closed`. **PASS**

**Q11. How would a symlink inside the workspace that points outside be handled by `path_within`?**
A: Both paths are `resolve()`d, which follows the symlink, so the real target lies outside the root and the call is denied.
Check: `policy.py` `ArgRule.violation`, test `test_path_within_blocks_symlink_escape`. **PASS**

**Day 2 score: 4/4 (running total 11/11)**

## Day 3 (2026-10-17)

**Q12. With the shipped `policy.json`, what happens to `write_file(path="../x", content="a")` and to `write_file(path="a.txt", content="a")`?**
A: The first breaks the `path_within: workspace` rule, so it is `deny` and no human is asked. The second passes the rules and gets the tool's verdict, `ask`.
Check: `policy.json`, `policy.py` `Policy.check`, test `test_write_escape_never_reaches_the_human`. Ran `Policy.check`: `deny`, `ask`. **PASS**

**Q13. If someone runs the agent with `Policy.allow_all()`, can `read_file` read `../policy.json`?**
A: No. The tool itself calls `Workspace.resolve`, which raises `SandboxError`, and the model gets `error: read_file: path '../policy.json' is outside the workspace`.
Check: `files.py` `Workspace.resolve`, `tools.py` `ToolRegistry.call`, test `test_tool_layer_blocks_escape_even_with_allow_all`. Ran it: exactly that message. **PASS**

**Q14. The model calls `list_dir` with no `path` argument. Does the `path_within` rule block it?**
A: No. Rules skip missing arguments (`ArgRule.violation` returns None), so the verdict is `allow`, and the tool defaults to `"."`, the workspace root, which is inside the sandbox.
Check: `policy.py` `ArgRule.violation`, `files.py` `list_dir`. Ran it: verdict `allow`, output `notes.txt  (file)`. **PASS**

**Q15. What does the model see when it reads a 20001 byte text file?**
A: The first 20000 bytes followed by `[truncated: showed 20000 of 20001 bytes]`.
Check: `files.py` `MAX_READ_BYTES`, test `test_read_truncates_large_files_and_refuses_binary`. Ran it on a 20001 byte file: matches. **PASS**

**Day 3 score: 4/4 (running total 15/15)**

## Day 4 (2026-10-18)

**Q16. With an audit log attached, is a tool's verdict written before or after the tool runs?**
A: Before. `_guarded_call` writes `tool_decision` right after the policy decides, then calls the tool, then the loop writes `tool_result`. A tool that crashes the process still leaves its verdict on disk.
Check: `agent.py` `Agent._guarded_call`, test `test_verdict_is_on_disk_before_the_tool_runs` (a spy tool reads the log while running and sees `tool_decision` as the last line). **PASS**

**Q17. An approved `write_file` call writes 50000 chars. What ends up in the file and what in the log?**
A: The file gets all 50000 chars. The log's `tool_decision.arguments.content` holds the first 2000 chars plus `...[clipped 48000 chars]` (2024 chars), and `AgentResult.decisions` keeps the full value.
Check: `audit.py` `clip`, `MAX_FIELD_CHARS`, decision D23. Ran it: file 50000 bytes, logged content 2024 chars ending `...[clipped 48000 chars]`, decision arguments 50000. **PASS**

**Q18. Ollama is not running when the CLI starts a run. What does the log contain?**
A: `run_start`, then `run_error` with `ConnectionError: Could not reach Ollama ...`; the exception is still raised to the caller, and `check_run` reports no problems because the run did finish (with an error).
Check: `agent.py` `Agent.run`, test `test_llm_crash_writes_run_error_and_reraises`. **PASS**

**Q19. The process is killed while writing the last line of a run. What does `replay` show?**
A: The broken line is skipped and counted (`(skipped 1 malformed line(s))`), and the run gets `WARNING: run did not finish (no run_end or run_error)`.
Check: `audit.py` `load_events`, `check_run`, `replay`, test `test_replay_survives_damaged_logs`. Ran it on a log with the last 20 bytes cut: both lines printed. **PASS**

**Day 4 score: 4/4 (running total 19/19)**

## Day 5 (2026-10-19)

**Q20. With the shipped `policy.json` and no approver, the model calls `demo__reverse(text="x")`. What is the verdict and does it run?**
A: There is no exact entry, so the `demo__*` pattern applies and the verdict is `ask`. With no approver it is treated as deny, so it does not run, and the reason says `via pattern 'demo__*'`.
Check: `policy.py` `Policy.lookup` and `decide`, `policy.json`, test `test_shipped_policy_routes_mcp_tools`. Ran `Policy.decide`: `tool 'demo__reverse' is ask (via pattern 'demo__*'); no approver configured, treated as deny`, approved False. **PASS**

**Q21. The model calls `demo__shell_exec`. Does the MCP server ever receive the request?**
A: No. `demo__shell_exec` has an exact `deny` entry, `_guarded_call` returns the denial message without calling the tool, so no `tools/call` is sent. Only `initialize` and `tools/list` appear in the client's sent requests, and no tool result contains `CANARY`.
Check: `agent.py` `_guarded_call`, `mcp.py` `MCPClient.sent`, test `test_denied_mcp_call_never_reaches_the_server`, quiz_model `canary_free`. Ran it: sent methods `['initialize', 'tools/list']`. **PASS**

**Q22. An MCP server exits in the middle of a `tools/call`. What does the model see, and does the agent crash?**
A: The reader thread hits EOF, `request` raises `MCPError("MCP server 'demo' exited (code 3) during tools/call")`, and `ToolRegistry.call` turns it into `error: demo__crash failed: ...` as the tool message. The agent keeps running; later calls to that server also return errors instead of hanging.
Check: `mcp.py` `MCPClient.request`, `tools.py` `ToolRegistry.call`, test `test_server_crash_and_timeout_become_tool_errors`. Ran it: `error: demo__crash failed: MCP server 'demo' exited (code 3) during tools/call`. **PASS**

**Q23. Your shell has `GITHUB_TOKEN` set when the CLI starts an MCP server. Does the server see it?**
A: No. Servers get only `PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`, `SYSTEMROOT` (when set) plus the `env` block from `mcp_servers.json`.
Check: `mcp.py` `PASS_ENV`, `minimal_env`, test `test_server_env_is_minimal`. Ran `minimal_env()` with `GITHUB_TOKEN=x`: keys `HOME, LANG, PATH, TMPDIR`, no token. **PASS**

**Day 5 score: 4/4 (running total 23/23)**

## Day 6 (2026-10-20)

**Q24. You run `python -m guarded_agent --model llama3.2 "what is 2+2"`. Which command runs?**
A: `run`. `normalise` prepends `run` whenever the first argument is not one of `run`, `tools`, `doctor`, `replay`, `-h`, `--help`, so options before the task still work and the day 1 to 5 form is unchanged.
Check: `cli.py` `normalise`, `COMMANDS`, test `test_bare_task_means_run`. Ran it: `['run', '--model', 'llama3.2', 'task']`. **PASS**

**Q25. With `--non-interactive` the model calls `write_file`. Is the approver asked, and is the file written?**
A: Neither. `cmd_run` swaps in `denying_approver`, which returns False, so the `ask` verdict is declined (`approved: false`, reason ends `; human declined`), no prompt appears, and the workspace stays empty.
Check: `cli.py` `cmd_run`, `denying_approver`, `policy.py` `decide`, test `test_non_interactive_declines_ask_without_prompting` (a spy approver passed by the test is never called). **PASS**

**Q26. What exit code does the CLI return when the agent hits the step limit, and how many times was the model called with `--max-steps 2`?**
A: Exit 3 (`EXIT_MAX_STEPS`), the answer text says `step limit reached (2 steps)`, and the model was called exactly 2 times. `--max-steps 0` is rejected with exit 2 before any model call.
Check: `cli.py` `cmd_run`, `agent.py` `_run`, test `test_max_steps_flag_and_exit_code`. **PASS**

**Q27. Only `qwen3:4b` is pulled and you run `doctor --model qwen3`. OK or problem?**
A: Problem, exit 4. A name without a tag means `qwen3:latest`, which is not `qwen3:4b`; the message lists the local models and says `ollama pull qwen3`.
Check: `llm.py` `_model_matches`, `check_ollama`, decision D35, tests `test_model_name_matching`, `test_check_ollama_states`. Ran it: `(False, "Model 'qwen3' is not pulled (local models: qwen3:4b). Run `ollama pull qwen3`.")`. **PASS**

**Day 6 score: 4/4 (running total 27/27)**
