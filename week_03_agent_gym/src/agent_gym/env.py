"""Environment base class: reset / step / state, in process (D3, D4).

Rewards are computed inside the environment from its final state (D7) and its
recorded steps, through the task's rubric (D13), never from what the agent says it did.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable

from .rubrics import Rubric, RubricContext, StepLog, default_rubric
from .types import SUBMIT, Action, Observation, State

# (initial data, final data) -> list of problems. Empty list means success.
Check = Callable[[dict, dict], list[str]]

TYPES = {"string": str, "integer": int}


class EpisodeOver(RuntimeError):
    """step() was called before reset() or after the episode ended."""


class ToolError(Exception):
    """A tool refused its input. The message goes back to the agent."""


@dataclass
class Param:
    type: str  # "string" or "integer"
    description: str
    required: bool = True


@dataclass
class ToolSpec:
    name: str
    description: str
    params: dict[str, Param]
    handler: Callable[..., str]

    def schema(self) -> dict:
        """Ollama /api/chat tool schema."""
        return {"type": "function", "function": {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {k: {"type": p.type, "description": p.description}
                               for k, p in self.params.items()},
                "required": [k for k, p in self.params.items() if p.required],
            }}}


@dataclass
class Task:
    id: str
    prompt: str
    reference: list[Action]  # a known good solution, without the final submit
    check: Check
    tags: tuple[str, ...] = ()
    rubric: Rubric | None = None  # None means default_rubric(check) (D14)

    def get_rubric(self) -> Rubric:
        return self.rubric if self.rubric is not None else default_rubric(self.check)


SUBMIT_SPEC_PARAMS = {"summary": Param("string", "One sentence on what you did.", required=False)}


def _as_dict(args: Any) -> dict:
    return dict(args) if isinstance(args, dict) else {"_raw": args}


def validate_args(spec: ToolSpec, args: Any) -> str | None:
    """Return a problem string, or None if the arguments fit the spec."""
    if not isinstance(args, dict):
        return f"arguments for {spec.name} must be an object"
    extra = sorted(set(args) - set(spec.params))
    if extra:
        return f"unexpected argument(s) for {spec.name}: {', '.join(extra)}"
    for key, p in spec.params.items():
        if key not in args:
            if p.required:
                return f"missing required argument '{key}' for {spec.name}"
            continue
        want = TYPES[p.type]
        value = args[key]
        if isinstance(value, bool) or not isinstance(value, want):
            return f"argument '{key}' for {spec.name} must be a {p.type}"
    return None


class Environment:
    """Subclasses set name, description and tasks, and implement seed_data and tool_specs."""

    name = "base"
    description = ""
    tasks: dict[str, Task] = {}

    def __init__(self, max_steps: int = 20):
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.max_steps = max_steps
        self.data: dict = {}
        self._initial: dict = {}
        self._task: Task | None = None
        self._state = State()
        self._episodes = 0
        self._steps: list[StepLog] = []

    # ----- to implement in subclasses -----
    def seed_data(self, seed: int | None) -> dict:
        raise NotImplementedError

    def tool_specs(self) -> dict[str, ToolSpec]:
        raise NotImplementedError

    # ----- public API -----
    @property
    def state(self) -> State:
        return copy.deepcopy(self._state)

    def tools(self) -> list[dict]:
        specs = list(self.tool_specs().values())
        submit = ToolSpec(SUBMIT, "Call this once when the task is finished. Ends the episode.",
                          SUBMIT_SPEC_PARAMS, handler=lambda **_: "")
        return [s.schema() for s in specs + [submit]]

    def reset(self, task_id: str | None = None, seed: int | None = None,
              episode_id: str | None = None) -> Observation:
        if not self.tasks:
            raise KeyError(f"environment {self.name} has no tasks")
        if task_id is None:
            task_id = next(iter(self.tasks))
        if task_id not in self.tasks:
            raise KeyError(f"unknown task '{task_id}' for {self.name}; "
                           f"tasks: {', '.join(self.tasks)}")
        self._task = self.tasks[task_id]
        self.data = self.seed_data(seed)
        self._initial = copy.deepcopy(self.data)
        self._episodes += 1
        self._steps = []
        self._state = State(episode_id=episode_id or f"{self.name}-{self._episodes}",
                            task_id=task_id)
        return Observation(content=self._task.prompt,
                           metadata={"tools": list(self.tool_specs()) + [SUBMIT],
                                     "max_steps": self.max_steps})

    def step(self, action: Action) -> Observation:
        if self._task is None:
            raise EpisodeOver("call reset() before step()")
        if self._state.done:
            raise EpisodeOver(f"episode {self._state.episode_id} is over; call reset()")
        self._state.step_count += 1
        if action.tool == SUBMIT:
            self._steps.append(StepLog(SUBMIT, _as_dict(action.arguments), True))
            return self.finish("submitted")
        obs = self._call(action)
        self._steps.append(StepLog(action.tool, _as_dict(action.arguments), obs.ok))
        if self._state.step_count >= self.max_steps:
            end = self.finish("step_limit")
            obs.done, obs.reward = True, end.reward
            obs.metadata.update(end.metadata)
            obs.content += f"\n{end.content}"
        return obs

    def finish(self, reason: str) -> Observation:
        """End the episode now and score it with the task's rubric.

        `problems` are always the task's state check problems; `passed` means
        there were none. `reward` is the rubric score and `breakdown` its tree.
        """
        if self._task is None:
            raise EpisodeOver("call reset() before finish()")
        if self._state.done:
            raise EpisodeOver(f"episode {self._state.episode_id} is over; call reset()")
        problems = list(self._task.check(self._initial, self.data))
        ctx = RubricContext(self._initial, self.data, list(self._steps),
                            list(self._task.reference), reason)
        result = self._task.get_rubric().score(ctx)
        reward = result.score
        self._state.done = True
        self._state.reward = reward
        self._state.passed = not problems
        self._state.end_reason = reason
        self._state.problems = problems
        self._state.breakdown = result.to_dict()
        # The agent is not told the reward, the breakdown or the problems (D8).
        return Observation(content=f"episode over ({reason})", done=True, reward=reward,
                           metadata={"end_reason": reason, "problems": list(problems),
                                     "passed": not problems,
                                     "breakdown": result.to_dict()})

    # ----- internals -----
    def _call(self, action: Action) -> Observation:
        specs = self.tool_specs()
        spec = specs.get(action.tool)
        if spec is None:
            return Observation(f"error: unknown tool '{action.tool}'. "
                               f"Tools: {', '.join(list(specs) + [SUBMIT])}", ok=False)
        problem = validate_args(spec, action.arguments)
        if problem:
            return Observation(f"error: {problem}", ok=False)
        try:
            return Observation(spec.handler(**action.arguments))
        except ToolError as exc:
            return Observation(f"error: {exc}", ok=False)
