"""Guarded Tool Agent: a local Ollama agent whose tool calls are policy checked."""

from .agent import Agent, AgentResult
from .audit import AuditLog, load_events, replay
from .files import SandboxError, Workspace, file_tools
from .llm import FakeClient, LLMResponse, OllamaClient, ToolCall
from .policy import Policy, PolicyDecision, console_approver
from .tools import Tool, ToolRegistry, default_tools

__all__ = [
    "Agent", "AgentResult", "FakeClient", "LLMResponse", "OllamaClient",
    "ToolCall", "Tool", "ToolRegistry", "default_tools",
    "Policy", "PolicyDecision", "console_approver",
    "SandboxError", "Workspace", "file_tools",
    "AuditLog", "load_events", "replay",
]
__version__ = "0.4.0"
