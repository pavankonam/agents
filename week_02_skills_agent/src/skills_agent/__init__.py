"""Skills Agent: Agent Skills with progressive disclosure on a local Ollama model."""

from .agent import LOAD_SKILL, Agent, AgentResult
from .llm import FakeClient, LLMResponse, OllamaClient, ToolCall, check_ollama
from .skills import Skill, SkillError, SkillLibrary, load_skill_dir, parse_frontmatter, validate

__all__ = [
    "Agent", "AgentResult", "FakeClient", "LLMResponse", "LOAD_SKILL", "OllamaClient", "Skill",
    "SkillError", "SkillLibrary", "ToolCall", "check_ollama", "load_skill_dir",
    "parse_frontmatter", "validate",
]
