"""Agent loop with progressive skill disclosure (see flow.md).

The model starts with the skill catalog only. When a task matches a skill it
calls the `load_skill` tool, and the full SKILL.md body comes back as a tool
message together with the list of files bundled with the skill. If the body
points to one of those files, the model calls `read_skill_file` to read it
(level 3). That tool only works for skills that are already loaded (D14).
If a skill allows it in `allowed-tools`, the model can also run one of the
skill's scripts with `run_skill_script` (D19 to D23).
Every run is metered by a ContextBudget; with `budget_tokens` set, a tool result
that would push the run past the limit is refused (D26, D27).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .budget import ContextBudget, estimate_tokens, tools_tokens
from .llm import LLMClient, ToolCall
from .scripts import RUN_SKILL_SCRIPT, format_result, list_scripts, run_script
from .skills import SkillError, SkillLibrary, list_resources, read_resource, resolve_resource

LOAD_SKILL = "load_skill"
READ_SKILL_FILE = "read_skill_file"

SYSTEM_TEMPLATE = """You are a helpful assistant that can use skills.
A skill is a set of instructions for a specific kind of task. Below is the list of
available skills with a short description of each. Only the descriptions are shown.

{catalog}

Rules:
- If the user's task matches a skill's description, call the {tool} tool with that
  skill's exact name BEFORE answering, then follow the instructions it returns.
- Load only the skills you need. Never guess what a skill says.
- If the loaded instructions point to a file in the skill (for example references/x.md),
  call {read_tool} with the skill name and that path before answering.
- If the loaded instructions tell you to run a script, call {run_tool} with the skill
  name, the script path and the args; use its output, do not compute it yourself.
- If no skill matches, answer directly without calling any tool."""


def load_skill_schema(names: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": LOAD_SKILL,
            "description": "Load the full instructions of one skill from the available skills list.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "enum": names,
                                        "description": "exact skill name"}},
                "required": ["name"],
            },
        },
    }


def read_skill_file_schema(names: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": READ_SKILL_FILE,
            "description": ("Read a file bundled with a skill you already loaded, "
                            "for example references/details.md."),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "enum": names, "description": "exact skill name"},
                    "path": {"type": "string",
                             "description": "file path relative to the skill folder"},
                },
                "required": ["skill", "path"],
            },
        },
    }


def run_skill_script_schema(names: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": RUN_SKILL_SCRIPT,
            "description": ("Run a script from the scripts/ folder of a skill you already "
                            "loaded, when its instructions say so. Returns its output."),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "enum": names, "description": "exact skill name"},
                    "script": {"type": "string",
                               "description": "script path, for example scripts/check.py"},
                    "args": {"type": "array", "items": {"type": "string"},
                             "description": "command line arguments, one string each"},
                },
                "required": ["skill", "script"],
            },
        },
    }


@dataclass
class AgentResult:
    answer: str
    stopped_reason: str  # "final_answer" or "max_steps"
    loaded_skills: list[str] = field(default_factory=list)
    read_files: list[str] = field(default_factory=list)  # "skill/path" for each level 3 read
    ran_scripts: list[str] = field(default_factory=list)  # "skill/script exit=N" per run
    tool_calls: list[ToolCall] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    context: dict = field(default_factory=dict)  # ContextBudget.summary() of the run (D26)


class Agent:
    def __init__(self, llm: LLMClient, library: SkillLibrary, max_steps: int = 6,
                 budget_tokens: int | None = None):
        self.llm = llm
        self.library = library
        self.max_steps = max_steps
        self.budget_tokens = budget_tokens
        self._budget = ContextBudget(budget_tokens)  # also validates the limit

    def system_prompt(self) -> str:
        return SYSTEM_TEMPLATE.format(catalog=self.library.catalog(), tool=LOAD_SKILL,
                                      read_tool=READ_SKILL_FILE, run_tool=RUN_SKILL_SCRIPT)

    def _skills_with_files(self) -> list[str]:
        return [n for n in self.library.names() if list_resources(self.library.skills[n], 1)]

    def _skills_with_scripts(self) -> list[str]:
        return [n for n in self.library.names() if list_scripts(self.library.skills[n])]

    def tools(self) -> list[dict]:
        """load_skill always; read_skill_file only if some skill bundles files (D17);
        run_skill_script only if some skill has a permitted script (D21)."""
        if not self.library.skills:
            return []
        tools = [load_skill_schema(self.library.names())]
        with_files = self._skills_with_files()
        if with_files:
            tools.append(read_skill_file_schema(with_files))
        with_scripts = self._skills_with_scripts()
        if with_scripts:
            tools.append(run_skill_script_schema(with_scripts))
        return tools

    def _over_budget(self, kind: str, what: str, content: str) -> str | None:
        """Charge `content` to the run budget, or return a refusal if it does not fit."""
        b = self._budget
        cost = estimate_tokens(content)
        if b.fits(cost):
            b.charge(kind, cost)
            return None
        b.refused.append(f"{what} needs {cost}")
        msg = (f"error: context budget: {what} needs about {cost} tokens but only "
               f"{b.remaining} of {b.limit} are left in this run. Answer with what you "
               "already have, or say which information is missing.")
        b.charge("other", estimate_tokens(msg))
        return msg

    def _dispatch(self, call: ToolCall, loaded: list[str], read: list[str],
                  ran: list[str]) -> str:
        if call.name == LOAD_SKILL:
            return self._load(call, loaded)
        if call.name == READ_SKILL_FILE:
            return self._read(call, loaded, read)
        if call.name == RUN_SKILL_SCRIPT:
            return self._run_script(call, loaded, ran)
        names = ", ".join(t["function"]["name"] for t in self.tools()) or "none"
        return f"error: unknown tool {call.name!r}. Available tools: {names}."

    def _read(self, call: ToolCall, loaded: list[str], read: list[str]) -> str:
        name, path = call.arguments.get("skill"), call.arguments.get("path")
        if not isinstance(name, str) or not name.strip():
            return f"error: {READ_SKILL_FILE} needs a 'skill' argument"
        if not isinstance(path, str) or not path.strip():
            return f"error: {READ_SKILL_FILE} needs a 'path' argument"
        skill = self.library.get(name.strip())
        if skill is None:
            return f"error: no skill named {name!r}"
        if skill.name not in loaded:
            return (f"error: skill {skill.name!r} is not loaded. "
                    f"Call {LOAD_SKILL} first, then read files it mentions.")
        try:
            real = resolve_resource(skill, path)
            text, truncated = read_resource(skill, path)
        except SkillError as exc:
            files = ", ".join(list_resources(skill)) or "none"
            return f"error: {exc}. Files in this skill: {files}"
        rel = real.relative_to(skill.path.resolve()).as_posix()
        key = f"{skill.name}/{rel}"
        note = "\n[truncated: file is larger than the read limit]" if truncated else ""
        content = f'<skill_file skill="{skill.name}" path="{rel}">\n{text}{note}\n</skill_file>'
        refusal = self._over_budget("read", f"{READ_SKILL_FILE} {key}", content)
        if refusal:
            return refusal
        if key not in read:
            read.append(key)
        return content

    def _run_script(self, call: ToolCall, loaded: list[str], ran: list[str]) -> str:
        name, script = call.arguments.get("skill"), call.arguments.get("script")
        if not isinstance(name, str) or not name.strip():
            return f"error: {RUN_SKILL_SCRIPT} needs a 'skill' argument"
        if not isinstance(script, str) or not script.strip():
            return f"error: {RUN_SKILL_SCRIPT} needs a 'script' argument"
        skill = self.library.get(name.strip())
        if skill is None:
            return f"error: no skill named {name!r}"
        if skill.name not in loaded:
            return (f"error: skill {skill.name!r} is not loaded. "
                    f"Call {LOAD_SKILL} first, then run scripts it mentions.")
        try:
            result = run_script(skill, script, call.arguments.get("args"))
        except SkillError as exc:
            runnable = ", ".join(list_scripts(skill)) or "none"
            return f"error: {exc}. Scripts this skill may run: {runnable}"
        except OSError as exc:
            return f"error: could not start {script!r}: {exc}"
        status = "timeout" if result.timed_out else str(result.exit_code)
        ran.append(f"{skill.name}/{result.script} exit={status}")
        content = format_result(skill, result)
        # the script already ran; only its output is withheld if it does not fit (D27)
        refusal = self._over_budget("script", f"output of {skill.name}/{result.script}", content)
        return refusal or content

    def _load(self, call: ToolCall, loaded: list[str]) -> str:
        name = call.arguments.get("name")
        if not isinstance(name, str) or not name:
            return "error: load_skill needs a 'name' argument"
        skill = self.library.get(name.strip())
        if skill is None:
            return (f"error: no skill named {name!r}. "
                    f"Available: {', '.join(self.library.names()) or 'none'}")
        if skill.name in loaded:
            return f"note: skill {skill.name!r} is already loaded above; follow those instructions."
        files = list_resources(skill)
        listing = ("\n<skill_files>\n" + "\n".join(files) + "\n</skill_files>") if files else ""
        content = f'<skill name="{skill.name}">\n{skill.body}{listing}\n</skill>'
        refusal = self._over_budget("load", f"{LOAD_SKILL} {skill.name}", content)
        if refusal:
            return refusal  # not loaded, so its files and scripts stay locked (D27)
        loaded.append(skill.name)
        return content

    def run(self, task: str) -> AgentResult:
        messages = [{"role": "system", "content": self.system_prompt()},
                    {"role": "user", "content": task}]
        self._budget = budget = ContextBudget(self.budget_tokens)
        tools = self.tools()
        # the prompt, task and tool schemas are always sent, even past the limit
        budget.charge("system", estimate_tokens(messages[0]["content"])
                      + estimate_tokens(task) + tools_tokens(tools))
        loaded: list[str] = []
        read: list[str] = []
        ran: list[str] = []
        calls: list[ToolCall] = []
        for _ in range(self.max_steps):
            reply = self.llm.chat(messages, tools)
            msg: dict = {"role": "assistant", "content": reply.content}
            if reply.tool_calls:
                msg["tool_calls"] = [{"function": {"name": c.name, "arguments": c.arguments}}
                                     for c in reply.tool_calls]
            messages.append(msg)
            if not reply.tool_calls:
                return AgentResult(reply.content, "final_answer", loaded, read, ran, calls,
                                   messages, budget.summary())
            for call in reply.tool_calls:
                calls.append(call)
                before = budget.spent
                content = self._dispatch(call, loaded, read, ran)
                if budget.spent == before:  # errors and notes are small, but still context
                    budget.charge("other", estimate_tokens(content))
                messages.append({"role": "tool", "tool_name": call.name, "content": content})
        return AgentResult("Stopped: step limit reached before a final answer.",
                           "max_steps", loaded, read, ran, calls, messages, budget.summary())
