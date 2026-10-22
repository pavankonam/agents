"""Agent loop with progressive skill disclosure (see flow.md).

The model starts with the skill catalog only. When a task matches a skill it
calls the `load_skill` tool, and the full SKILL.md body comes back as a tool
message. Day 1 has exactly one tool on purpose (D9).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .llm import LLMClient, ToolCall
from .skills import SkillLibrary

LOAD_SKILL = "load_skill"

SYSTEM_TEMPLATE = """You are a helpful assistant that can use skills.
A skill is a set of instructions for a specific kind of task. Below is the list of
available skills with a short description of each. Only the descriptions are shown.

{catalog}

Rules:
- If the user's task matches a skill's description, call the {tool} tool with that
  skill's exact name BEFORE answering, then follow the instructions it returns.
- Load only the skills you need. Never guess what a skill says.
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


@dataclass
class AgentResult:
    answer: str
    stopped_reason: str  # "final_answer" or "max_steps"
    loaded_skills: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)


class Agent:
    def __init__(self, llm: LLMClient, library: SkillLibrary, max_steps: int = 6):
        self.llm = llm
        self.library = library
        self.max_steps = max_steps

    def system_prompt(self) -> str:
        return SYSTEM_TEMPLATE.format(catalog=self.library.catalog(), tool=LOAD_SKILL)

    def tools(self) -> list[dict]:
        return [load_skill_schema(self.library.names())] if self.library.skills else []

    def _load(self, call: ToolCall, loaded: list[str]) -> str:
        if call.name != LOAD_SKILL:
            return (f"error: unknown tool {call.name!r}. The only tool is {LOAD_SKILL}.")
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
        return f'<skill name="{skill.name}">\n{skill.body}\n</skill>'

    def run(self, task: str) -> AgentResult:
        messages = [{"role": "system", "content": self.system_prompt()},
                    {"role": "user", "content": task}]
        loaded: list[str] = []
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
                return AgentResult(reply.content, "final_answer", loaded, calls, messages)
            for call in reply.tool_calls:
                calls.append(call)
                messages.append({"role": "tool", "tool_name": call.name,
                                 "content": self._load(call, loaded)})
        return AgentResult("Stopped: step limit reached before a final answer.",
                           "max_steps", loaded, calls, messages)
