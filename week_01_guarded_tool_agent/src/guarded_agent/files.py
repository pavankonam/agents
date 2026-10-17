"""Sandboxed file tools: read_file, write_file, list_dir (see decisions D16 to D20).

Two layers keep the agent inside the workspace folder:

1. policy.json gives each file tool a `path_within` rule, so a call with a path
   outside the workspace is denied before it reaches the tool (and before any
   human is asked).
2. The tools themselves resolve every path against the workspace and refuse
   anything that lands outside it, symlinks and '..' included. This second
   layer holds even if someone ships a policy that forgets the rule or uses
   Policy.allow_all().
"""

from __future__ import annotations

from pathlib import Path

from .tools import Tool

MAX_READ_BYTES = 20_000     # longer files are truncated, with a note to the model
MAX_WRITE_BYTES = 100_000   # bigger writes are refused
MAX_LIST_ENTRIES = 200


class SandboxError(ValueError):
    """A path resolved outside the workspace."""


class Workspace:
    """A folder the file tools are confined to."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def resolve(self, path: str) -> Path:
        """Resolve a model supplied path. Raises SandboxError if it escapes."""
        if not isinstance(path, str) or path.strip() == "":
            raise SandboxError("path must be a non empty string")
        if "\x00" in path:
            raise SandboxError("path contains a NUL byte")
        p = Path(path)
        target = (p if p.is_absolute() else self.root / p).resolve()
        if target != self.root and self.root not in target.parents:
            raise SandboxError(f"path {path!r} is outside the workspace")
        return target

    def rel(self, target: Path) -> str:
        r = target.relative_to(self.root).as_posix()
        return r if r else "."


def file_tools(workspace: str | Path | Workspace,
               max_read: int = MAX_READ_BYTES,
               max_write: int = MAX_WRITE_BYTES) -> list[Tool]:
    ws = workspace if isinstance(workspace, Workspace) else Workspace(workspace)

    def read_file(path: str) -> str:
        target = ws.resolve(path)
        if not target.exists():
            return f"error: file not found: {path}"
        if target.is_dir():
            return f"error: {path} is a directory, use list_dir"
        data = target.read_bytes()
        if b"\x00" in data[:1024]:
            return f"error: {path} looks like a binary file"
        text = data[:max_read].decode("utf-8", errors="replace")
        if len(data) > max_read:
            text += f"\n[truncated: showed {max_read} of {len(data)} bytes]"
        return text

    def write_file(path: str, content: str) -> str:
        target = ws.resolve(path)
        if target == ws.root or target.is_dir():
            return f"error: {path} is a directory"
        encoded = str(content).encode("utf-8")
        if len(encoded) > max_write:
            return f"error: content is {len(encoded)} bytes, limit is {max_write}"
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_bytes(encoded)
        verb = "overwrote" if existed else "created"
        return f"{verb} {ws.rel(target)} ({len(encoded)} bytes)"

    def list_dir(path: str = ".") -> str:
        target = ws.resolve(path)
        if not target.exists():
            return f"error: directory not found: {path}"
        if not target.is_dir():
            return f"error: {path} is a file, use read_file"
        entries = sorted(target.iterdir(), key=lambda e: e.name)
        lines = []
        for e in entries[:MAX_LIST_ENTRIES]:
            # never follow a symlink out of the workspace just to label it
            try:
                ws.resolve(str(e))
                kind = "dir" if e.is_dir() else "file"
            except SandboxError:
                kind = "link outside workspace"
            lines.append(f"{e.name}{'/' if kind == 'dir' else ''}  ({kind})")
        if len(entries) > MAX_LIST_ENTRIES:
            lines.append(f"[{len(entries) - MAX_LIST_ENTRIES} more entries not shown]")
        return "\n".join(lines) if lines else "(empty directory)"

    path_prop = {"type": "string", "description": "Path relative to the workspace folder"}
    return [
        Tool("read_file",
             "Read a UTF-8 text file from the workspace folder. Paths are relative to the workspace.",
             {"type": "object", "properties": {"path": path_prop}, "required": ["path"]},
             read_file),
        Tool("write_file",
             "Create or overwrite a text file in the workspace folder. Needs human approval.",
             {"type": "object", "properties": {
                 "path": path_prop,
                 "content": {"type": "string", "description": "Full text to write"}},
              "required": ["path", "content"]},
             write_file),
        Tool("list_dir",
             "List files and folders in a workspace directory. Use '.' for the workspace root.",
             {"type": "object", "properties": {"path": path_prop}, "required": []},
             list_dir),
    ]
