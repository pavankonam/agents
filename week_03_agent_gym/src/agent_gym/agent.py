"""Runs one episode: an LLM drives an environment through its tools (D10, D11)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .env import Environment
from .llm import LLMClient
from .types import SUBMIT, Action

SYSTEM_TEMPLATE = """You are an agent working inside the '{env}' environment. {description}
Complete the user's task by calling the tools. Look ids up with the tools instead of guessing them.
Every tool call is one step and you have at most {max_steps} steps.
When the task is done, call {submit} with a one sentence summary. Do not call {submit} before the work is done."""


@dataclass
class StepRecord:
    index: int
    tool: str
    arguments: dict
    content: str
    ok: bool


@dataclass
class Episode:
    env: str
    task_id: str
    episode_id: str
    reward: float
    end_reason: str
    problems: list[str]
    steps: list[StepRecord] = field(default_factory=list)
    turns: int = 0
    final_text: str = ""
    messages: list[dict] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.reward == 1.0

    def to_dict(self, with_messages: bool = False) -> dict:
        d = asdict(self)
        if not with_messages:
            d.pop("messages")
        return d


def system_prompt(env: Environment) -> str:
    return SYSTEM_TEMPLATE.format(env=env.name, description=env.description,
                                  max_steps=env.max_steps, submit=SUBMIT)


def run_episode(env: Environment, client: LLMClient, task_id: str | None = None,
                max_turns: int = 12, episode_id: str | None = None) -> Episode:
    """Reset the env, loop model -> tool calls -> env.step until the episode ends.

    Ends when the model calls submit, the env hits its step limit, the model
    answers with text and no tool call (end reason no_submit), or max_turns
    model calls pass (turn_limit). The env scores the final state in all cases.
    """
    obs = env.reset(task_id, episode_id=episode_id)
    messages = [{"role": "system", "content": system_prompt(env)},
                {"role": "user", "content": obs.content}]
    tools = env.tools()
    steps: list[StepRecord] = []
    final_text = ""
    turns = 0
    end = None
    while turns < max_turns and end is None:
        turns += 1
        resp = client.chat(messages, tools)
        if not resp.tool_calls:
            messages.append({"role": "assistant", "content": resp.content})
            final_text = resp.content
            end = env.finish("no_submit")
            break
        messages.append({"role": "assistant", "content": resp.content, "tool_calls": [
            {"function": {"name": tc.name, "arguments": tc.arguments}}
            for tc in resp.tool_calls]})
        for tc in resp.tool_calls:
            obs = env.step(Action(tc.name, dict(tc.arguments)))
            steps.append(StepRecord(len(steps) + 1, tc.name, dict(tc.arguments),
                                    obs.content, obs.ok))
            if tc.name == SUBMIT:
                final_text = str(tc.arguments.get("summary", ""))
            messages.append({"role": "tool", "tool_name": tc.name, "content": obs.content})
            if obs.done:
                end = obs
                break
    if end is None:
        end = env.finish("turn_limit")
    st = env.state
    return Episode(env=env.name, task_id=st.task_id, episode_id=st.episode_id,
                   reward=st.reward if st.reward is not None else 0.0,
                   end_reason=st.end_reason, problems=st.problems, steps=steps,
                   turns=turns, final_text=final_text, messages=messages)
