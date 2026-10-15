# Daily Playbook

This file is the procedure the daily 2pm automation follows. It lives in the repo so the process is versioned along with the work.

## Rules for every project

* Topic: AI agents that run on **free, local LLMs** (Ollama). No paid APIs.
* Language: Python 3.10+.
* Folder name: `week_NN_<project_name>/` (for example `week_01_guarded_tool_agent/`).
* Every project folder must contain:
  * `PRD.md`: problem, scope, daily milestones (checked off as completed), success criteria.
  * `decision.md`: every decision made, with the reason and alternatives considered. Append, never rewrite history.
  * `flow.md`: Mermaid diagram plus short explanation of how the project works. Kept in sync with the code.
  * `quiz/quiz.md`: questions about the project. The automation answers them itself, then verifies each answer against the code and docs and records PASS or FAIL. Any FAIL is fixed (in the docs or the code) the same day.
  * `quiz/quiz_model.py`: runnable script that quizzes the agent the project builds through Ollama and checks its answers. `--fake` mode runs without Ollama.
  * `tests/`: pytest suite that runs with a fake LLM, so no model is required.
  * `README.md`: what it is and how to run it locally with Ollama.

## Weekly cycle (7 days, weekends included)

* **Day 1 (kickoff):** Research what is leading or very recent in AI agents (last few weeks). Pick a project that fits in 7 days and runs on Ollama. Write the PRD with a milestone for each of days 1 to 7, scaffold the folder, implement the day 1 milestone, update `state.json` and the root `README.md` index.
* **Days 2 to 7:** Implement the next unchecked milestone in the PRD. One focused, real change per day (feature, test, refactor, docs, fix). Then update `decision.md`, `flow.md`, `quiz/quiz.md`, and the PRD checklist.
* **Day 7 also:** close the project: final README results, a short retro section at the end of `decision.md`, set `state.json` so the next run starts a new week.

## Daily steps

The run happens on the Mac (Claude's local Linux shell). GitHub is the source of truth, and `~/Documents/agents` is kept as a mirror you can open locally.

1. Read the GitHub token from `~/Documents/agents/.gh_token` (gitignored, created by the owner). If it is missing, stop and report.
2. Clone `https://github.com/pavankonam/agents.git` into a fresh scratch folder. If the remote has no commits yet, initialise the clone from the files in `~/Documents/agents` and commit them as `week 01 day 1` first.
3. Read `state.json` to find the current week, project folder and day number. If the project is closed, start a new week (Day 1).
4. Do the day's work as described above.
5. Run `python3 -m pytest -q` inside the project folder. Fix until green.
6. Run `python3 quiz/quiz_model.py --fake` and make sure it passes.
7. Answer the questions in `quiz/quiz.md` from memory, check them against the code, record PASS or FAIL with the date.
8. Update `state.json` (increment `day`, set `last_run`) and the root `README.md` index.
9. Append a line to `CHANGELOG.md`: date, week, day, one sentence.
10. Commit with message `week NN day D: <what changed>` and `git push origin main`.
11. Copy the working tree (without `.git`) back to `~/Documents/agents`.
12. If the push fails, report why. Nothing is lost because the next run starts from GitHub plus the mirror.
