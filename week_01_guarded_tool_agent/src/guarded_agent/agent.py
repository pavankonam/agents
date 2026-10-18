"""The agent loop (see flow.md)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .audit import AuditLog
from .llm import LLMClient, ToolCall
from .policy import Approver, Policy, PolicyDecision, denial_message
from .tools import ToolRegistry

SYSTEM_PROMPT = (
    "You are a careful assistant that can call tools. "
    "Use a tool when it gives a more reliable answer than guessing, "
    "for example arithmetic, the current time, or the contents of a file. "
    "File paths are relative to the workspace folder; do not try paths outside it. "
    "If a tool returns an error, explain it or try a corrected call. "
    "If a call is denied by policy, do not repeat it; tell the user it was blocked. "
    "When you have the answer, reply with plain text and no tool calls."
)


@dataclass
class AgentResult:
    answer: str
    messages: list[dict]
    tool_calls: list[ToolCall] = field(default_factory=list)
    decisions: list[PolicyDecision] = field(default_factory=list)  # one per tool call
    steps: int = 0
    stopped_reason: str = "final_answer"  # or "max_steps"


class Agent:
    def __init__(self, llm: LLMClient, registry: ToolRegistry,
                 max_steps: int = 6, system_prompt: str = SYSTEM_PROMPT,
                 policy: Policy | None = None, approver: Approver | None = None,
                 audit: AuditLog | None = None):
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.llm = llm
        self.registry = registry
        # No policy given means deny everything (fail closed, decision D11).
        self.policy = policy if policy is not None else Policy(default="deny")
        self.approver = approver
        self.max_steps = max_steps
        self.system_prompt = system_prompt
        self.audit = audit  # None means no log file; decisions are still in AgentResult

    def _log(self, type: str, **fields) -> None:
        if self.audit is not None:
            self.audit.write(type, **fields)

    def run(self, task: str) -> AgentResult:
        if self.audit is not None:
            self.audit.start_run(
                task=task,
                model=getattr(self.llm, "model", type(self.llm).__name__),
                max_steps=self.max_steps,
                policy_default=self.policy.default,
                tools=self.registry.names(),
            )
        try:
            result = self._run(task)
        except Exception as exc:  # log, then let the caller see the real error
            self._log("run_error", error=f"{type(exc).__name__}: {exc}")
            raise
        self._log("run_end", answer=result.answer, stopped_reason=result.stopped_reason,
                  steps=result.steps, tool_calls=len(result.tool_calls),
                  blocked=sum(1 for d in result.decisions if not d.approved))
        return result

    def _run(self, task: str) -> AgentResult:
        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task},
        ]
        made: list[ToolCall] = []
        decisions: list[PolicyDecision] = []
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
            self._log("model_reply", step=step, content=reply.content,
                      tool_calls=[{"name": c.name, "arguments": c.arguments}
                                  for c in reply.tool_calls])

            if not reply.tool_calls:
                return AgentResult(reply.content, messages, made, decisions, step)

            for call in reply.tool_calls:
                made.append(call)
                output, decision = self._guarded_call(call, step)
                decisions.append(decision)
                self._log("tool_result", step=step, tool=call.name, ran=decision.approved,
                          output=output)
                messages.append({"role": "tool", "tool_name": call.name, "content": output})

        return AgentResult(
            answer=f"Stopped: step limit reached ({self.max_steps} steps).",
            messages=messages, tool_calls=made, decisions=decisions, steps=self.max_steps,
            stopped_reason="max_steps",
        )

    def _guarded_call(self, call: ToolCall, step: int = 0) -> tuple[str, PolicyDecision]:
        """The only place a tool runs. Every call leaves a PolicyDecision behind,
        and with an audit log the verdict is written to disk before the tool runs."""
        args = call.arguments if isinstance(call.arguments, dict) else {"_raw": call.arguments}
        if call.name not in self.registry:
            d = PolicyDecision(call.name, args, "deny", "unknown tool")
        else:
            d = self.policy.decide(call.name, args, self.approver)
        self._log("tool_decision", step=step, tool=d.tool, arguments=d.arguments,
                  verdict=d.verdict, reason=d.reason, approved=d.approved)
        if call.name not in self.registry:
            return self.registry.call(call.name, args), d
        if not d.approved:
            return denial_message(d), d
        return self.registry.call(call.name, args), d
