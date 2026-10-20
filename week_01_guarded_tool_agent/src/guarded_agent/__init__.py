"""Guarded Tool Agent: a local Ollama agent whose tool calls are policy checked."""

from .agent import Agent, AgentResult
from .audit import AuditLog, load_events, replay
from .files import SandboxError, Workspace, file_tools
from .llm import FakeClient, LLMResponse, OllamaClient, ToolCall, check_ollama
from .mcp import MCPClient, MCPError, connect as connect_mcp
from .policy import Policy, PolicyDecision, console_approver
from .tools import Tool, ToolRegistry, default_tools

__all__ = [
    "Agent", "AgentResult", "FakeClient", "LLMResponse", "OllamaClient",
    "ToolCall", "check_ollama", "Tool", "ToolRegistry", "default_tools",
    "Policy", "PolicyDecision", "console_approver",
    "SandboxError", "Workspace", "file_tools",
    "AuditLog", "load_events", "replay",
    "MCPClient", "MCPError", "connect_mcp",
]
__version__ = "0.6.0"
