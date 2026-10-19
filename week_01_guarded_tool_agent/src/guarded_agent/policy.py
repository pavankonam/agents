"""Permission policy: every tool call gets a verdict before it runs (see D10 to D15).

Verdicts:
  allow  run the tool
  ask    run only if the approval callback says yes (no callback means no)
  deny   never run

Argument rules are checked first and can only make a verdict stricter: a call
that breaks a rule is denied even if the tool is marked allow.

policy.json shape:
{
  "default": "deny",
  "tools": {
    "calculator": "allow",
    "write_file": {"verdict": "ask",
                   "rules": [{"arg": "path", "type": "path_within", "value": "./workspace"}]},
    "demo__*": "ask"
  }
}

Tool names may be glob patterns (`*`, `?`, `[...]`), mainly for MCP tools named
"<server>__<tool>". An exact name always wins; otherwise the most specific
matching pattern (most literal characters) wins; otherwise `default` applies
(decision D29).
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

VERDICTS = ("allow", "ask", "deny")
RULE_TYPES = ("path_within", "pattern", "max_length", "one_of")

# approver(tool_name, arguments, reason) -> True to approve
Approver = Callable[[str, dict, str], bool]


@dataclass
class PolicyDecision:
    tool: str
    arguments: dict[str, Any]
    verdict: str            # verdict from the policy: allow / ask / deny
    reason: str
    approved: bool = False  # final outcome: did the tool actually run?


@dataclass
class ArgRule:
    arg: str
    type: str
    value: Any

    def __post_init__(self):
        if self.type not in RULE_TYPES:
            raise ValueError(f"unknown rule type '{self.type}', expected one of {RULE_TYPES}")
        if self.type == "pattern":
            re.compile(self.value)
        if self.type == "max_length" and not isinstance(self.value, int):
            raise ValueError("max_length rule needs an integer value")
        if self.type == "one_of" and not isinstance(self.value, list):
            raise ValueError("one_of rule needs a list value")

    def violation(self, arguments: dict[str, Any], base_dir: Path) -> str | None:
        """Return a reason string if the arguments break this rule, else None."""
        if self.arg not in arguments:
            return None  # missing args are the tool's problem, not the policy's
        val = arguments[self.arg]
        if self.type == "one_of":
            return None if val in self.value else f"'{self.arg}' must be one of {self.value}"
        text = str(val)
        if self.type == "max_length":
            return None if len(text) <= self.value else f"'{self.arg}' longer than {self.value} chars"
        if self.type == "pattern":
            return None if re.fullmatch(self.value, text) else f"'{self.arg}' does not match {self.value!r}"
        # path_within: resolve symlinks and '..' before comparing
        root = (base_dir / self.value).resolve()
        target = (root / text).resolve() if not os.path.isabs(text) else Path(text).resolve()
        if target == root or root in target.parents:
            return None
        return f"'{self.arg}' path {text!r} is outside {self.value}"


@dataclass
class ToolPolicy:
    verdict: str
    rules: list[ArgRule] = field(default_factory=list)


def _check_verdict(v: str, where: str) -> str:
    if v not in VERDICTS:
        raise ValueError(f"{where}: unknown verdict '{v}', expected one of {VERDICTS}")
    return v


class Policy:
    def __init__(self, tools: dict[str, ToolPolicy] | None = None, default: str = "deny",
                 base_dir: str | Path = "."):
        self.tools = tools or {}
        self.default = _check_verdict(default, "default")
        self.base_dir = Path(base_dir).resolve()

    # ---------- construction ----------

    @classmethod
    def from_dict(cls, data: dict, base_dir: str | Path = ".") -> "Policy":
        tools: dict[str, ToolPolicy] = {}
        for name, spec in (data.get("tools") or {}).items():
            if isinstance(spec, str):
                spec = {"verdict": spec}
            verdict = _check_verdict(spec.get("verdict", "deny"), f"tool '{name}'")
            rules = [ArgRule(r["arg"], r["type"], r["value"]) for r in spec.get("rules", [])]
            tools[name] = ToolPolicy(verdict, rules)
        return cls(tools, data.get("default", "deny"), base_dir)

    @classmethod
    def from_file(cls, path: str | Path) -> "Policy":
        """Load policy.json. Relative path rules resolve against the file's folder."""
        path = Path(path)
        return cls.from_dict(json.loads(path.read_text()), base_dir=path.parent)

    @classmethod
    def allow_all(cls) -> "Policy":
        """For tests and demos only. Every call is still recorded with a verdict."""
        return cls(default="allow")

    # ---------- checking ----------

    def lookup(self, tool: str) -> tuple[str | None, ToolPolicy | None]:
        """(matching key, its ToolPolicy): exact name first, then the longest glob."""
        if tool in self.tools:
            return tool, self.tools[tool]
        patterns = [k for k in self.tools if any(ch in k for ch in "*?[")]
        hits = [k for k in patterns if fnmatch.fnmatchcase(tool, k)]
        if not hits:
            return None, None
        best = max(hits, key=lambda k: (len(k.replace("*", "")), len(k)))
        return best, self.tools[best]

    def check(self, tool: str, arguments: dict[str, Any]) -> PolicyDecision:
        key, tp = self.lookup(tool)
        if tp is None:
            return PolicyDecision(tool, arguments, self.default, f"default policy ({self.default})")
        via = "" if key == tool else f" (via pattern '{key}')"
        if tp.verdict == "deny":
            return PolicyDecision(tool, arguments, "deny", f"tool '{tool}' is denied by policy{via}")
        for rule in tp.rules:
            why = rule.violation(arguments, self.base_dir)
            if why:
                return PolicyDecision(tool, arguments, "deny", f"argument rule: {why}")
        return PolicyDecision(tool, arguments, tp.verdict, f"tool '{tool}' is {tp.verdict}{via}")

    def decide(self, tool: str, arguments: dict[str, Any],
               approver: Approver | None = None) -> PolicyDecision:
        """check() plus the approval step. Sets decision.approved."""
        d = self.check(tool, arguments)
        if d.verdict == "allow":
            d.approved = True
        elif d.verdict == "ask":
            if approver is None:
                d.reason += "; no approver configured, treated as deny"
            else:
                try:
                    d.approved = bool(approver(tool, arguments, d.reason))
                except Exception as exc:  # a broken approver must fail closed
                    d.reason += f"; approver failed ({exc}), treated as deny"
                    d.approved = False
                if not d.approved and "treated as deny" not in d.reason:
                    d.reason += "; human declined"
        return d


def console_approver(tool: str, arguments: dict, reason: str) -> bool:
    """Ask on the terminal. Anything other than y/yes is a no."""
    try:
        ans = input(f"\n[approval] {tool}({json.dumps(arguments)})  ({reason})  allow? [y/N] ")
    except EOFError:
        return False
    return ans.strip().lower() in ("y", "yes")


def denial_message(decision: PolicyDecision) -> str:
    return (f"error: denied by policy: {decision.reason}. "
            "Do not retry the same call. Tell the user it was blocked or try a different approach.")
