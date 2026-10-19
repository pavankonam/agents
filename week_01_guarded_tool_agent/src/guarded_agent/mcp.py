"""MCP client over stdio, standard library only (see decisions D26 to D31).

Starts an MCP server as a subprocess, does the initialize handshake, lists its
tools (following pagination) and wraps each one as a normal `Tool`. The agent
does not know a tool came from MCP: every call still goes through
Agent._guarded_call, so the policy, the approver and the audit log apply
exactly as they do to built in tools.

Transport (MCP stdio): one JSON-RPC 2.0 message per line on stdin / stdout.
The server's stderr is not part of the protocol and is discarded by default.

mcp_servers.json shape (relative cwd and args paths resolve against the file):
{
  "servers": {
    "demo": {"command": "python3", "args": ["src/guarded_agent/demo_mcp_server.py"],
             "cwd": ".", "env": {}, "timeout": 30}
  }
}
Each server's tools are registered as "<server>__<tool>", e.g. demo__word_count.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from .tools import Tool

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "guarded-agent", "version": "0.5.0"}
DEFAULT_TIMEOUT = 30.0
MAX_OUTPUT_CHARS = 20_000      # MCP results are untrusted and can be huge
MAX_PAGES = 50                 # a server that never stops paginating is cut off
SEPARATOR = "__"               # server__tool
# Only these variables from our environment reach a server, plus its own "env".
PASS_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")


class MCPError(RuntimeError):
    """Protocol failure: server died, timed out, or answered with a JSON-RPC error."""


def safe_name(text: str) -> str:
    """Tool names sent to the model: letters, digits, _ and - only."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", text).strip("_")
    return cleaned or "tool"


def minimal_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: os.environ[k] for k in PASS_ENV if k in os.environ}
    env.update({str(k): str(v) for k, v in (extra or {}).items()})
    return env


class MCPClient:
    """One stdio MCP server. Use as a context manager or call close()."""

    def __init__(self, name: str, command: list[str], cwd: str | Path | None = None,
                 env: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT,
                 stderr: Any = subprocess.DEVNULL):
        if not command:
            raise ValueError(f"MCP server '{name}' has an empty command")
        self.name = safe_name(name)
        self.command = [str(c) for c in command]
        self.timeout = timeout
        self.server_info: dict = {}
        self.sent: list[dict] = []  # every request sent, for tests and debugging
        self._next_id = 1
        self._lock = threading.Lock()
        self._inbox: queue.Queue = queue.Queue()
        self._proc = subprocess.Popen(
            self.command, cwd=str(cwd) if cwd else None, env=minimal_env(env),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
            text=True, encoding="utf-8", bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # ---------- transport ----------

    def _read_loop(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._inbox.put(json.loads(line))
            except json.JSONDecodeError:
                continue  # stray output on stdout is ignored, not fatal
        self._inbox.put(None)  # EOF marker: the server closed stdout or died

    def _send(self, msg: dict) -> None:
        if self._proc.poll() is not None:
            raise MCPError(f"MCP server '{self.name}' is not running "
                           f"(exit code {self._proc.returncode})")
        assert self._proc.stdin is not None
        try:
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise MCPError(f"MCP server '{self.name}' closed its input: {exc}") from exc

    def request(self, method: str, params: dict | None = None) -> dict:
        with self._lock:  # one request in flight at a time keeps ids simple
            mid = self._next_id
            self._next_id += 1
            msg = {"jsonrpc": "2.0", "id": mid, "method": method}
            if params is not None:
                msg["params"] = params
            self.sent.append(msg)
            self._send(msg)
            while True:
                try:
                    reply = self._inbox.get(timeout=self.timeout)
                except queue.Empty:
                    raise MCPError(f"MCP server '{self.name}' timed out after "
                                   f"{self.timeout:g}s on {method}") from None
                if reply is None:
                    self._inbox.put(None)  # keep the EOF marker for later calls
                    code = self._proc.wait(timeout=5)
                    raise MCPError(f"MCP server '{self.name}' exited (code {code}) during {method}")
                if "method" in reply:  # a request or notification from the server
                    if "id" in reply:  # we offer no client features (sampling, roots...)
                        self._send({"jsonrpc": "2.0", "id": reply["id"],
                                    "error": {"code": -32601, "message": "not supported"}})
                    continue
                if reply.get("id") != mid:
                    continue  # a late answer to a request that already timed out
                if "error" in reply:
                    err = reply["error"] or {}
                    raise MCPError(f"MCP server '{self.name}' error on {method}: "
                                   f"{err.get('message', err)}")
                return reply.get("result") or {}

    def notify(self, method: str, params: dict | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        with self._lock:
            self._send(msg)

    # ---------- MCP ----------

    def initialize(self) -> dict:
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        self.server_info = result
        self.notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict]:
        tools, cursor = [], None
        for _ in range(MAX_PAGES):
            page = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(t for t in page.get("tools") or [] if isinstance(t, dict) and t.get("name"))
            cursor = page.get("nextCursor")
            if not cursor:
                return tools
        raise MCPError(f"MCP server '{self.name}' returned more than {MAX_PAGES} pages of tools")

    def call_tool(self, name: str, arguments: dict) -> str:
        """Return the result as text for the model. Tool errors start with 'error:'."""
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        text = result_text(result)
        if result.get("isError"):
            text = f"error: {self.name}{SEPARATOR}{name}: {text}"
        if len(text) > MAX_OUTPUT_CHARS:
            text = text[:MAX_OUTPUT_CHARS] + f"\n[truncated: showed {MAX_OUTPUT_CHARS} of {len(text)} chars]"
        return text

    def tools(self) -> list[Tool]:
        """Wrap every server tool as a Tool named '<server>__<tool>'."""
        wrapped = []
        for spec in self.list_tools():
            remote = spec["name"]
            schema = spec.get("inputSchema")
            if not isinstance(schema, dict) or schema.get("type") != "object":
                schema = {"type": "object", "properties": {}}
            desc = (spec.get("description") or remote).strip()
            wrapped.append(Tool(
                name=f"{self.name}{SEPARATOR}{safe_name(remote)}",
                description=f"[MCP server '{self.name}'] {desc}",
                parameters=schema,
                func=self._caller(remote),
            ))
        return wrapped

    def _caller(self, remote: str):
        def call(**arguments: Any) -> str:
            return self.call_tool(remote, arguments)
        return call

    # ---------- lifecycle ----------

    def close(self) -> None:
        if self._proc.poll() is None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()  # the spec's polite shutdown: close stdin
                self._proc.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()
        for stream in (self._proc.stdin, self._proc.stdout):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass

    @property
    def running(self) -> bool:
        return self._proc.poll() is None

    def __enter__(self) -> "MCPClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def result_text(result: dict) -> str:
    """Flatten MCP content items into text. Non text items are described, not inlined."""
    parts = []
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text", "")))
        elif kind == "resource" and isinstance(item.get("resource"), dict):
            res = item["resource"]
            parts.append(str(res.get("text", f"[resource {res.get('uri', '?')}]")))
        else:
            parts.append(f"[{kind} content omitted]")
    if not parts and "structuredContent" in result:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
    return "\n".join(parts) if parts else "(no content)"


def load_servers(path: str | Path) -> dict[str, dict]:
    """Read mcp_servers.json into {name: {command, cwd, env, timeout}}."""
    path = Path(path)
    data = json.loads(path.read_text())
    base = path.parent.resolve()
    servers = {}
    for name, spec in (data.get("servers") or {}).items():
        if not isinstance(spec, dict) or not spec.get("command"):
            raise ValueError(f"MCP server '{name}' needs a command")
        cmd = spec["command"]
        cmd = [cmd] if isinstance(cmd, str) else list(cmd)
        if cmd[0] in ("python", "python3"):
            cmd[0] = sys.executable  # same interpreter as the agent
        args = [str(a) for a in spec.get("args", [])]
        cwd = (base / spec.get("cwd", ".")).resolve()
        servers[name] = {"command": cmd + args, "cwd": cwd, "env": spec.get("env") or {},
                         "timeout": float(spec.get("timeout", DEFAULT_TIMEOUT))}
    return servers


def connect(path: str | Path) -> tuple[list[MCPClient], list[Tool]]:
    """Start every server in a config file and return (clients, wrapped tools).
    If any server fails to start, the ones already started are closed."""
    clients: list[MCPClient] = []
    tools: list[Tool] = []
    try:
        for name, spec in load_servers(path).items():
            client = MCPClient(name, spec["command"], cwd=spec["cwd"], env=spec["env"],
                               timeout=spec["timeout"])
            clients.append(client)
            client.initialize()
            tools.extend(client.tools())
    except Exception:
        for c in clients:
            c.close()
        raise
    return clients, tools
