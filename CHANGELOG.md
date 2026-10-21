# Changelog

* 2026-10-15 | week 01 | day 1 | Kicked off Guarded Tool Agent: PRD, docs, core agent loop with Ollama and fake LLM clients, two tools, tests.
* 2026-10-16 | week 01 | day 2 | Permission policy: allow / ask / deny from policy.json, argument rules (path_within, pattern, max_length, one_of), approval callback, fail closed defaults, denials reported to the model.
* 2026-10-17 | week 01 | day 3 | Sandboxed file tools (read_file, list_dir, write_file) confined to workspace/ by both policy path rules and a tool level check; writes need approval; size limits; quiz scenarios for blocked writes and path escapes.
* 2026-10-18 | week 01 | day 4 | JSONL audit log (verdict written before each tool runs, long strings clipped, run_error on crashes), `replay` command with integrity warnings, quiz_model checks every run is complete in the log.
* 2026-10-19 | week 01 | day 5 | Stdlib MCP client over stdio (handshake, paged tools/list, tools/call) with tools registered as server__tool and routed through the same policy and audit log, glob patterns in policy.json, demo MCP server with a denied canary tool, minimal server env.
* 2026-10-20 | week 01 | day 6 | Full argparse CLI (run, tools, doctor, replay) with --json, --non-interactive, --max-steps and stable exit codes, Ollama preflight via /api/tags, quiz_model.py preflight plus --only and --json per scenario report.
* 2026-10-21 | week 01 | day 7 | Prompt injection guard (untrusted output envelope, regex scan, taint that escalates later allow calls to ask), injected.txt trap and injection quiz scenario, results table and retro; project closed.
