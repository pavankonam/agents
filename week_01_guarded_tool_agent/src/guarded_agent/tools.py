"""Tool definitions and the registry (see decisions D6, D7, D8)."""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict]:
        return [self._tools[n].schema() for n in self.names()]

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        """Run a tool. Never raises: problems come back as 'error: ...' strings."""
        tool = self._tools.get(name)
        if tool is None:
            return f"error: unknown tool '{name}'. Available: {', '.join(self.names())}"
        try:
            return str(tool.func(**arguments))
        except TypeError as exc:
            return f"error: bad arguments for '{name}': {exc}"
        except Exception as exc:  # tool bugs must not crash the agent
            return f"error: {name} failed: {exc}"


# ---------- built in tools ----------

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def safe_eval(expression: str) -> float | int:
    """Evaluate arithmetic only. Names, calls and attributes are rejected."""

    def _eval(node: ast.AST):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("exponent too large")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](_eval(node.operand))
        raise ValueError(f"unsupported expression element: {type(node).__name__}")

    return _eval(ast.parse(expression, mode="eval"))


def _calculator(expression: str) -> str:
    result = safe_eval(expression)
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return str(result)


def _current_time(tz: str = "UTC") -> str:
    if tz.upper() != "UTC":
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz)).isoformat(timespec="seconds")
        except Exception:
            return f"error: unknown timezone '{tz}'"
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


calculator = Tool(
    name="calculator",
    description="Evaluate an arithmetic expression such as '(12 + 3) * 4'. "
                "Supports + - * / // % ** and parentheses.",
    parameters={
        "type": "object",
        "properties": {"expression": {"type": "string", "description": "Arithmetic expression"}},
        "required": ["expression"],
    },
    func=_calculator,
)

current_time = Tool(
    name="current_time",
    description="Get the current date and time in ISO format for an IANA timezone, e.g. 'America/Chicago'.",
    parameters={
        "type": "object",
        "properties": {"tz": {"type": "string", "description": "IANA timezone, default UTC"}},
        "required": [],
    },
    func=_current_time,
)


def default_tools() -> list[Tool]:
    return [calculator, current_time]
