# agents

One new AI agent project every week, built in small daily steps. Every project runs on **free local LLMs through [Ollama](https://ollama.com)**, is written in Python, and documents its reasoning as it goes.

Each project folder has:

| File | Purpose |
| --- | --- |
| `PRD.md` | Problem, scope, and the 7 daily milestones |
| `decision.md` | Every decision made and why |
| `flow.md` | How the project works, as a diagram |
| `quiz/quiz.md` | Self quiz on the project, verified against the code |
| `quiz/quiz_model.py` | Quizzes the agent itself through Ollama and checks its answers |

The daily process is described in [PLAYBOOK.md](PLAYBOOK.md) and the history is in [CHANGELOG.md](CHANGELOG.md).

## Projects

| Week | Project | Topic | Status |
| --- | --- | --- | --- |
| 01 | [Guarded Tool Agent](week_01_guarded_tool_agent/) | Tool calling agent with permission policies, approvals and audit logs | In progress (day 3 of 7) |
