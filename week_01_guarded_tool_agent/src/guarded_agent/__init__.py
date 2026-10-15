"""Guarded Tool Agent: a local Ollama agent whose tool calls are policy checked."""

from .agent import Agent, AgentResult
from .llm import FakeClient, LLMResponse, OllamaClient, ToolCall
from .tools import Tool, ToolRegistry, default_tools

__all__ = [
    "Agent", "AgentResult", "FakeClient", "LLMResponse", "OllamaClient",
    "ToolCall", "Tool", "ToolRegistry", "default_tools",
]
__version__ = "0.1.0"
