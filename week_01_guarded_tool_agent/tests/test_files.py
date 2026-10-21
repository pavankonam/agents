import json
from pathlib import Path

import pytest

from guarded_agent import unwrap  # noqa: E402
from guarded_agent import (
    Agent, FakeClient, LLMResponse, Policy, SandboxError, ToolCall, ToolRegistry, Workspace,
    default_tools, file_tools,
)

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "notes.txt").write_text("hello heron\n")
    (root / "sub").mkdir()
    (tmp_path / "secret.txt").write_text("TOP SECRET")
    return root


def reg_for(root, **kw):
    return ToolRegistry(default_tools() + file_tools(root, **kw))


def policy_for(ws_root):
    """The shipped policy.json rules, rooted at a temp folder."""
    data = json.loads((PROJECT / "policy.json").read_text())
    return Policy.from_dict(data, base_dir=ws_root.parent)


def run_agent(root, calls, approver=None, policy=None):
    llm = FakeClient([LLMResponse(tool_calls=calls), LLMResponse(content="done")])
    agent = Agent(llm, reg_for(root), policy=policy or policy_for(root), approver=approver)
    result = agent.run("task")
    # read_file / list_dir output arrives in the untrusted envelope (D37); unwrap it
    outputs = [unwrap(m["content"]) for m in result.messages if m["role"] == "tool"]
    return result, outputs


# ---------- tool layer ----------

def test_read_list_write_inside_workspace(ws):
    reg = reg_for(ws)
    assert reg.call("read_file", {"path": "notes.txt"}) == "hello heron\n"
    listing = reg.call("list_dir", {})
    assert "notes.txt  (file)" in listing and "sub/  (dir)" in listing
    assert reg.call("write_file", {"path": "sub/new.md", "content": "hi"}) == \
        "created sub/new.md (2 bytes)"
    assert (ws / "sub" / "new.md").read_text() == "hi"
    assert reg.call("write_file", {"path": "sub/new.md", "content": "again"}).startswith("overwrote")


@pytest.mark.parametrize("path", ["../secret.txt", "sub/../../secret.txt", "/etc/passwd", ""])
def test_tool_layer_blocks_escape_even_with_allow_all(ws, path):
    result, outputs = run_agent(ws, [ToolCall("read_file", {"path": path})],
                                policy=Policy.allow_all())
    assert outputs[0].startswith("error: read_file:")
    assert "TOP SECRET" not in outputs[0]


def test_tool_layer_blocks_symlink_escape(ws):
    (ws / "escape").symlink_to(ws.parent)
    reg = reg_for(ws)
    assert reg.call("read_file", {"path": "escape/secret.txt"}).startswith("error: read_file:")
    assert reg.call("write_file", {"path": "escape/pwn.txt", "content": "x"}).startswith("error:")
    assert not (ws.parent / "pwn.txt").exists()
    assert "escape  (link outside workspace)" in reg.call("list_dir", {"path": "."})


def test_write_cannot_escape_through_new_parent_dirs(ws):
    reg = reg_for(ws)
    out = reg.call("write_file", {"path": "a/b/../../../out.txt", "content": "x"})
    assert out.startswith("error:")
    assert not (ws.parent / "out.txt").exists()


def test_read_truncates_large_files_and_refuses_binary(ws):
    (ws / "big.txt").write_text("x" * 50)
    (ws / "blob.bin").write_bytes(b"\x00\x01\x02")
    reg = reg_for(ws, max_read=10)
    out = reg.call("read_file", {"path": "big.txt"})
    assert out.startswith("x" * 10) and "[truncated: showed 10 of 50 bytes]" in out
    assert "binary" in reg.call("read_file", {"path": "blob.bin"})


def test_write_size_limit(ws):
    reg = reg_for(ws, max_write=5)
    assert "limit is 5" in reg.call("write_file", {"path": "x.txt", "content": "123456"})
    assert not (ws / "x.txt").exists()


def test_friendly_errors(ws):
    reg = reg_for(ws)
    assert reg.call("read_file", {"path": "nope.txt"}).startswith("error: file not found")
    assert "is a directory" in reg.call("read_file", {"path": "sub"})
    assert "is a file" in reg.call("list_dir", {"path": "notes.txt"})
    assert "is a directory" in reg.call("write_file", {"path": "sub", "content": "x"})


def test_workspace_resolve_rejects_nul():
    with pytest.raises(SandboxError):
        Workspace(".").resolve("a\x00b")


# ---------- policy layer with the shipped policy.json ----------

def test_shipped_policy_denies_escape_before_tool_runs(ws):
    result, outputs = run_agent(ws, [ToolCall("read_file", {"path": "../secret.txt"})])
    d = result.decisions[0]
    assert d.verdict == "deny" and d.reason.startswith("argument rule")
    assert outputs[0].startswith("error: denied by policy")


def test_shipped_policy_allows_read_and_list(ws):
    result, outputs = run_agent(ws, [ToolCall("read_file", {"path": "notes.txt"}),
                                     ToolCall("list_dir", {"path": "."})])
    assert [d.approved for d in result.decisions] == [True, True]
    assert outputs[0] == "hello heron\n"


def test_write_needs_approval(ws):
    call = ToolCall("write_file", {"path": "out.txt", "content": "hi"})
    result, outputs = run_agent(ws, [call])  # no approver
    assert result.decisions[0].verdict == "ask" and not result.decisions[0].approved
    assert not (ws / "out.txt").exists()

    seen = []
    result, outputs = run_agent(ws, [call], approver=lambda t, a, r: seen.append(t) or True)
    assert seen == ["write_file"] and result.decisions[0].approved
    assert (ws / "out.txt").read_text() == "hi"


def test_write_escape_never_reaches_the_human(ws):
    asked = []
    result, _ = run_agent(ws, [ToolCall("write_file", {"path": "../x.txt", "content": "x"})],
                          approver=lambda *a: asked.append(a) or True)
    assert asked == [] and result.decisions[0].verdict == "deny"
    assert not (ws.parent / "x.txt").exists()
