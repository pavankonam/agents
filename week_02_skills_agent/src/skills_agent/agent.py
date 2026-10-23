"""Agent loop with progressive skill disclosure (see flow.md).

The model starts with the skill catalog only. When a task matches a skill it
calls the `load_skill` tool, and the full SKILL.md body comes back as a tool
message together with the list of files bundled with the skill. If the body
points to one of those files, the model calls `read_skill_file` to read it
(level 3). That tool only works for skills that are already loaded (D14).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .llm import LLMClient, ToolCall
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


@dataclass
class AgentResult:
    answer: str
    stopped_reason: str  # "final_answer" or "max_steps"
    loaded_skills: list[str] = field(default_factory=list)
    read_files: list[str] = field(default_factory=list)  # "skill/path" for each level 3 read
    tool_calls: list[ToolCall] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)


class Agent:
    def __init__(self, llm: LLMClient, library: SkillLibrary, max_steps: int = 6):
        self.llm = llm
        self.library = library
        self.max_steps = max_steps

    def system_prompt(self) -> str:
        return SYSTEM_TEMPLATE.format(catalog=self.library.catalog(), tool=LOAD_SKILL,
                                      read_tool=READ_SKILL_FILE)

    def _skills_with_files(self) -> list[str]:
        return [n for n in self.library.names() if list_resources(self.library.skills[n], 1)]

    def tools(self) -> list[dict]:
        """load_skill always; read_skill_file only if some skill bundles files (D17)."""
        if not self.library.skills:
            return []
        tools = [load_skill_schema(self.library.names())]
        with_files = self._skills_with_files()
        if with_files:
            tools.append(read_skill_file_schema(with_files))
        return tools

    def _dispatch(self, call: ToolCall, loaded: list[str], read: list[str]) -> str:
        if call.name == LOAD_SKILL:
            return self._load(call, loaded)
        if call.name == READ_SKILL_FILE:
            return self._read(call, loaded, read)
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
        if key not in read:
            read.append(key)
        note = "\n[truncated: file is larger than the read limit]" if truncated else ""
        return f'<skill_file skill="{skill.name}" path="{rel}">\n{text}{note}\n</skill_file>'

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
        loaded.append(skill.name)
        files = list_resources(skill)
        listing = ("\n<skill_files>\n" + "\n".join(files) + "\n</skill_files>") if files else ""
        return f'<skill name="{skill.name}">\n{skill.body}{listing}\n</skill>'

    def run(self, task: str) -> AgentResult:
        messages = [{"role": "system", "content": self.system_prompt()},
                    {"role": "user", "content": task}]
        loaded: list[str] = []
        read: list[str] = []
        calls: list[ToolCall] = []
        tools = self.tools()
        for _ in range(self.max_steps):
            reply = self.llm.chat(messages, tools)
            msg: dict = {"role": "assistant", "content": reply.content}
            if reply.tool_calls:
                msg["tool_calls"] = [{"function": {"name": c.name, "arguments": c.arguments}}
                                     for c in reply.tool_calls]
            messages.append(msg)
            if not reply.tool_calls:
                return AgentResult(reply.content, "final_answer", loaded, read, calls, messages)
            for call in reply.tool_calls:
                calls.append(call)
                messages.append({"role": "tool", "tool_name": call.name,
                                 "content": self._dispatch(call, loaded, read)})
        return AgentResult("Stopped: step limit reached before a final answer.",
                           "max_steps", loaded, read, calls, messages)
