"""Run scripts bundled with a skill, safely (see decision.md D19 to D23).

A skill may ship helper programs in its `scripts/` folder. The model asks for one
with run_skill_script(skill, script, args). Guards, in order:

1. the skill must allow it in its frontmatter: `allowed-tools: run_skill_script`
   (any script) or `run_skill_script(scripts/x.py)` (one script, glob allowed)
2. the path goes through the same confinement as level 3 reads, and must be
   inside scripts/ with a known extension (.py or .sh); the interpreter comes
   from the extension, never from a shebang or the exec bit
3. args are a list of plain strings (no shell, so no quoting or injection)
4. the process gets no stdin, a minimal environment, the skill folder as cwd,
   a wall clock timeout, and its output is capped while it is being written
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .skills import Skill, SkillError, list_resources, resolve_resource

RUN_SKILL_SCRIPT = "run_skill_script"
SCRIPTS_DIR = "scripts"
SCRIPT_TIMEOUT = 10.0  # seconds of wall clock time per run
SCRIPT_OUTPUT_MAX = 8_000  # bytes kept per stream, about 2k tokens
MAX_ARGS = 16
MAX_ARG_LEN = 500
INTERPRETERS = {".py": [sys.executable, "-I", "-B"], ".sh": ["/bin/sh"]}


@dataclass
class ScriptResult:
    script: str  # path relative to the skill folder, e.g. scripts/check.py
    exit_code: int | None  # None when the run timed out
    stdout: str
    stderr: str
    timed_out: bool = False
    truncated: bool = False
    seconds: float = 0.0


def script_permission(skill: Skill, rel: str) -> bool:
    """True if the skill's allowed-tools grants run_skill_script for this script."""
    for entry in skill.allowed_tools:
        if entry == RUN_SKILL_SCRIPT:
            return True
        prefix = RUN_SKILL_SCRIPT + "("
        if entry.startswith(prefix) and entry.endswith(")"):
            if fnmatch.fnmatchcase(rel, entry[len(prefix):-1].strip()):
                return True
    return False


def list_scripts(skill: Skill) -> list[str]:
    """Runnable scripts of a skill: in scripts/, known extension, and permitted."""
    return [p for p in list_resources(skill)
            if p.startswith(SCRIPTS_DIR + "/") and Path(p).suffix in INTERPRETERS
            and script_permission(skill, p)]


def resolve_script(skill: Skill, script: str) -> tuple[Path, str]:
    """Return (real path, relative path) or raise SkillError with the reason."""
    real = resolve_resource(skill, script)  # abs, .., hidden, symlink escape (D15)
    rel = real.relative_to(skill.path.resolve()).as_posix()
    if not rel.startswith(SCRIPTS_DIR + "/"):
        raise SkillError(f"{rel!r} is not in the skill's {SCRIPTS_DIR}/ folder")
    if real.suffix not in INTERPRETERS:
        raise SkillError(f"{rel!r} has an unsupported type; only "
                         + ", ".join(sorted(INTERPRETERS)) + " scripts run")
    if not script_permission(skill, rel):
        raise SkillError(f"skill {skill.name!r} does not allow running {rel!r} "
                         f"(its allowed-tools has no {RUN_SKILL_SCRIPT} entry for it)")
    return real, rel


def check_args(args) -> list[str]:
    if args is None:
        return []
    if isinstance(args, str):
        # small models sometimes send the list as JSON text, or one bare string
        text = args.strip()
        if text.startswith("["):
            try:
                args = json.loads(text)
            except json.JSONDecodeError:
                args = [args]
        else:
            args = [args]
    if not isinstance(args, list):
        raise SkillError("args must be a list of strings")
    if len(args) > MAX_ARGS:
        raise SkillError(f"at most {MAX_ARGS} args are allowed, got {len(args)}")
    out = []
    for a in args:
        if isinstance(a, (int, float)) and not isinstance(a, bool):
            a = str(a)
        if not isinstance(a, str):
            raise SkillError("every arg must be a string")
        if "\x00" in a:
            raise SkillError("args may not contain NUL bytes")
        if len(a) > MAX_ARG_LEN:
            raise SkillError(f"an arg is {len(a)} chars, max {MAX_ARG_LEN}")
        out.append(a)
    return out


def _minimal_env() -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
           "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    return env


def _read_capped(fh, limit: int) -> tuple[str, bool]:
    fh.seek(0)
    data = fh.read(limit + 1)
    cut = len(data) > limit
    return data[:limit].decode("utf-8", errors="replace"), cut


def run_script(skill: Skill, script: str, args=None, timeout: float | None = None,
               max_output: int | None = None) -> ScriptResult:
    """Run one permitted script from the skill's scripts/ folder. Raises SkillError
    if the script or args are refused; a crash or timeout is a normal result."""
    timeout = SCRIPT_TIMEOUT if timeout is None else timeout
    max_output = SCRIPT_OUTPUT_MAX if max_output is None else max_output
    real, rel = resolve_script(skill, script)
    argv = INTERPRETERS[real.suffix] + [str(real)] + check_args(args)
    t0 = time.perf_counter()
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        timed_out = False
        proc = subprocess.Popen(argv, cwd=str(skill.path.resolve()), env=_minimal_env(),
                                stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                shell=False, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, 9)  # also kills children the script started
            except (ProcessLookupError, PermissionError, AttributeError):
                proc.kill()
            proc.wait()
            code = None
        stdout, cut_out = _read_capped(out, max_output)
        stderr, cut_err = _read_capped(err, max_output)
    return ScriptResult(rel, code, stdout, stderr, timed_out, cut_out or cut_err,
                        round(time.perf_counter() - t0, 3))


def format_result(skill: Skill, r: ScriptResult) -> str:
    """Tool message for the model. Script output is data, so it is wrapped."""
    status = "timeout" if r.timed_out else str(r.exit_code)
    parts = [f'<script_result skill="{skill.name}" script="{r.script}" exit_code="{status}">']
    parts.append("<stdout>\n" + r.stdout.rstrip("\n") + "\n</stdout>")
    if r.stderr.strip():
        parts.append("<stderr>\n" + r.stderr.rstrip("\n") + "\n</stderr>")
    if r.timed_out:
        parts.append(f"[stopped: the script ran longer than {SCRIPT_TIMEOUT:g} seconds]")
    if r.truncated:
        parts.append("[truncated: output is larger than the limit]")
    parts.append("</script_result>")
    return "\n".join(parts)
