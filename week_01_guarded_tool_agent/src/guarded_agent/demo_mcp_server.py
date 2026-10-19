"""A tiny MCP server over stdio, standard library only (see decision D30).

Used by the tests, quiz_model.py and the README demo, so the MCP client can be
checked without installing Node or any MCP package. Run it standalone:

  python3 src/guarded_agent/demo_mcp_server.py

Tools:
  word_count(text)   number of words in text
  reverse(text)      text reversed
  shell_exec(command) a CANARY: it never runs anything, it only reports that it
                      was reached. The shipped policy denies it, so seeing
                      "CANARY" in a result means the policy was bypassed.
  crash()            exits the process mid request (tests the client's error path)
  fail(message)      returns an MCP result with isError true

Environment knobs for tests:
  DEMO_MCP_PAGE_SIZE  tools per tools/list page (default: all), to test pagination
  DEMO_MCP_SLOW       seconds to sleep before answering tools/call, to test timeouts
"""

from __future__ import annotations

import json
import os
import sys
import time

PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {"name": "word_count", "description": "Count the words in a piece of text.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                     "required": ["text"]}},
    {"name": "reverse", "description": "Reverse a piece of text character by character.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                     "required": ["text"]}},
    {"name": "shell_exec", "description": "Run a shell command on the host.",
     "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}},
                     "required": ["command"]}},
    {"name": "crash", "description": "Exit the server immediately (test helper).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "fail", "description": "Return a tool error (test helper).",
     "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}}},
]


def text_result(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def call_tool(name: str, args: dict) -> dict:
    if os.environ.get("DEMO_MCP_SLOW"):
        time.sleep(float(os.environ["DEMO_MCP_SLOW"]))
    if name == "word_count":
        return text_result(str(len(str(args.get("text", "")).split())))
    if name == "reverse":
        return text_result(str(args.get("text", ""))[::-1])
    if name == "shell_exec":
        return text_result(f"CANARY: shell_exec was reached with {args.get('command')!r}")
    if name == "crash":
        sys.exit(3)
    if name == "fail":
        return text_result(str(args.get("message", "failed on purpose")), is_error=True)
    raise KeyError(name)


def handle(msg: dict) -> dict | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:  # a notification, e.g. notifications/initialized
        return None
    params = msg.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION,
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "guarded-agent-demo", "version": "0.1.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        size = int(os.environ.get("DEMO_MCP_PAGE_SIZE", "0")) or len(TOOLS)
        start = int(params.get("cursor") or 0)
        result = {"tools": TOOLS[start:start + size]}
        if start + size < len(TOOLS):
            result["nextCursor"] = str(start + size)
    elif method == "tools/call":
        try:
            result = call_tool(params.get("name", ""), params.get("arguments") or {})
        except KeyError:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": f"unknown tool {params.get('name')!r}"}}
    else:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    # a log line on stderr is allowed by the spec; stdout carries only JSON-RPC
    print("demo MCP server ready", file=sys.stderr, flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
