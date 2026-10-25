"""Skills Agent: Agent Skills with progressive disclosure on a local Ollama model."""

from .agent import LOAD_SKILL, READ_SKILL_FILE, Agent, AgentResult
from .budget import ContextBudget, context_report, estimate_tokens, format_report
from .scripts import (
    RUN_SKILL_SCRIPT, ScriptResult, list_scripts, resolve_script, run_script, script_permission,
)
from .llm import FakeClient, LLMResponse, OllamaClient, ToolCall, check_ollama
from .skills import (
    Skill, SkillError, SkillLibrary, list_resources, load_skill_dir, parse_frontmatter,
    read_resource, resolve_resource, validate,
)

__all__ = [
    "Agent", "AgentResult", "FakeClient", "LLMResponse", "LOAD_SKILL", "OllamaClient",
    "READ_SKILL_FILE", "Skill", "SkillError", "SkillLibrary", "ToolCall", "check_ollama",
    "list_resources", "load_skill_dir", "parse_frontmatter", "read_resource",
    "resolve_resource", "validate", "RUN_SKILL_SCRIPT", "ScriptResult", "list_scripts",
    "resolve_script", "run_script", "script_permission", "ContextBudget", "context_report",
    "estimate_tokens", "format_report",
]
