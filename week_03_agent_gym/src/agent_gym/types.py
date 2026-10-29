"""Core types, shaped after OpenEnv's Action, Observation and State, as stdlib dataclasses (D4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SUBMIT = "submit"


@dataclass
class Action:
    """One tool call the agent sends to the environment."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"tool": self.tool, "arguments": dict(self.arguments)}


@dataclass
class Observation:
    """What the environment returns after reset() or step().

    As in OpenEnv, `done` and `reward` ride on the observation instead of a
    (obs, reward, done, info) tuple. `ok` is False when the action was refused
    (unknown tool, bad arguments, a tool error); the step still counts.
    """

    content: str
    ok: bool = True
    done: bool = False
    reward: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class State:
    """Episode bookkeeping, readable at any time through Environment.state."""

    episode_id: str = ""
    task_id: str = ""
    step_count: int = 0
    done: bool = False
    reward: float | None = None
    end_reason: str = ""
    problems: list[str] = field(default_factory=list)
