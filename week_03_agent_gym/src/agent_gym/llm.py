"""LLM clients. All runtime specific code lives here (see decision D5. Copied from week 02 on purpose, see D6)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = os.environ.get("AGENT_GYM_MODEL", "qwen3:4b")
DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse: ...


class OllamaClient:
    """Calls Ollama's /api/chat with native tool support, using only the stdlib."""

    def __init__(self, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST,
                 temperature: float = 0.0, timeout: float = 120.0):
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        body = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.URLError as exc:
            raise ConnectionError(
                f"Could not reach Ollama at {self.host}. Is `ollama serve` running?"
            ) from exc
        return parse_ollama_message(data.get("message", {}))


def _model_matches(wanted: str, have: str) -> bool:
    """'qwen3' matches 'qwen3:latest'; 'qwen3:4b' must match exactly."""
    if ":" not in wanted:
        wanted += ":latest"
    if ":" not in have:
        have += ":latest"
    return wanted == have


def check_ollama(model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST,
                 timeout: float = 5.0, fetch=None) -> tuple[bool, str]:
    """Preflight: is Ollama reachable and is the model pulled? Returns (ok, message).

    Uses GET /api/tags, which lists local models and never loads one, so it is
    fast. `fetch(url, timeout) -> dict` is injectable for tests.
    """
    host = host.rstrip("/")
    if fetch is None:
        def fetch(url, timeout):
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read())
    try:
        data = fetch(f"{host}/api/tags", timeout)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, (f"Ollama is not reachable at {host} ({exc}). "
                       "Start it with `ollama serve` or open the Ollama app.")
    names = [m.get("name") or m.get("model", "") for m in data.get("models") or []]
    if any(_model_matches(model, n) for n in names):
        return True, f"Ollama at {host} is up and model '{model}' is pulled."
    have = ", ".join(sorted(names)) or "none"
    return False, (f"Model '{model}' is not pulled (local models: {have}). "
                   f"Run `ollama pull {model}`.")


def parse_ollama_message(message: dict) -> LLMResponse:
    calls = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function", {})
        args = fn.get("arguments") or {}
        if isinstance(args, str):  # some models return a JSON string
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_raw": args}
        calls.append(ToolCall(name=fn.get("name", ""), arguments=args))
    return LLMResponse(content=message.get("content", "") or "", tool_calls=calls)


class FakeClient:
    """Replays scripted responses. Records what it was sent, for assertions."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        self.calls.append([dict(m) for m in messages])
        if not self._responses:
            return LLMResponse(content="(fake client has no more responses)")
        return self._responses.pop(0)
