# Changelog

* 2026-10-15 | week 01 | day 1 | Kicked off Guarded Tool Agent: PRD, docs, core agent loop with Ollama and fake LLM clients, two tools, tests.
* 2026-10-16 | week 01 | day 2 | Permission policy: allow / ask / deny from policy.json, argument rules (path_within, pattern, max_length, one_of), approval callback, fail closed defaults, denials reported to the model.
* 2026-10-17 | week 01 | day 3 | Sandboxed file tools (read_file, list_dir, write_file) confined to workspace/ by both policy path rules and a tool level check; writes need approval; size limits; quiz scenarios for blocked writes and path escapes.
