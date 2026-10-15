"""The agent loop (see flow.md)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .llm import LLMClient, ToolCall
from .tools import ToolRegistry

SYSTEM_PROMPT = (
    "You are a careful assistant that can call tools. "
    "Use a tool when it gives a more reliable answer than guessing, "
    "for example arithmetic or the current time. "
    "If a tool returns an error, explain it or try a corrected call. "
    "When you have the answer, reply with plain text and no tool calls."
)


@dataclass
class AgentResult:
    answer: str
    messages: list[dict]
    tool_calls: list[ToolCall] = field(default_factory=list)
    steps: int = 0
    stopped_reason: str = "final_answer"  # or "max_steps"


class Agent:
    def __init__(self, llm: LLMClient, registry: ToolRegistry,
                 max_steps: int = 6, system_prompt: str = SYSTEM_PROMPT):
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.llm = llm
        self.registry = registry
        self.max_steps = max_steps
        self.system_prompt = system_prompt

    def run(self, task: str) -> AgentResult:
        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task},
        ]
        made: list[ToolCall] = []
        schemas = self.registry.schemas()

        for step in range(1, self.max_steps + 1):
            reply = self.llm.chat(messages, schemas)

            assistant_msg: dict = {"role": "assistant", "content": reply.content}
            if reply.tool_calls:
                assistant_msg["tool_calls"] = [
                    {"function": {"name": c.name, "arguments": c.arguments}}
                    for c in reply.tool_calls
                ]
            messages.append(assistant_msg)

            if not reply.tool_calls:
                return AgentResult(reply.content, messages, made, step)

            for call in reply.tool_calls:
                made.append(call)
                output = self.registry.call(call.name, call.arguments)
                messages.append({"role": "tool", "tool_name": call.name, "content": output})

        return AgentResult(
            answer=f"Stopped: step limit reached ({self.max_steps} steps).",
            messages=messages, tool_calls=made, steps=self.max_steps,
            stopped_reason="max_steps",
        )
