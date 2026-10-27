"""Command line interface: list, validate, inspect, run and doctor (decision.md D31 to D34).

    python3 -m skills_agent list      [--skills-dir DIR ...] [--json]
    python3 -m skills_agent validate  [--strict] [--json]
    python3 -m skills_agent inspect   NAME [--body] [--json]
    python3 -m skills_agent run       [--budget N] [--model M] [--max-steps N] [--json] TASK...
    python3 -m skills_agent doctor    [--model M] [--offline] [--json]
    python3 -m skills_agent "task"    # short form of run, kept from day 1

`--skills-dir` can be given more than once; roots are searched in order and the
first skill with a given name wins (D11). Without it the shipped skills/ folder
is used.

Exit codes (EXIT_* below): 0 ok, 1 a check failed, 2 usage error, 3 the run
stopped without a final answer, 4 Ollama not reachable or model not pulled,
5 skill not found.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .agent import Agent
from .budget import estimate_tokens, skill_costs
from .llm import DEFAULT_HOST, DEFAULT_MODEL, OllamaClient, check_ollama
from .routing import lint_description, lint_library
from .scripts import INTERPRETERS, list_scripts
from .skills import SkillLibrary, list_resources

DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
EXIT_OK, EXIT_CHECK, EXIT_USAGE, EXIT_STOPPED, EXIT_OLLAMA, EXIT_NOT_FOUND = 0, 1, 2, 3, 4, 5
COMMANDS = ("list", "validate", "inspect", "run", "doctor")
MIN_PYTHON = (3, 10)


def positive_int(text: str) -> int:
    if not text.isdigit() or int(text) <= 0:
        raise argparse.ArgumentTypeError(f"needs a positive whole number, got {text!r}")
    return int(text)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--skills-dir", action="append", metavar="DIR",
                        help="skills root; repeat for several, first one wins on a name clash")
    common.add_argument("--json", action="store_true", help="machine readable output")
    ap = argparse.ArgumentParser(prog="python3 -m skills_agent",
                                 description="Agent Skills on a local Ollama model.")
    sub = ap.add_subparsers(dest="command", required=True, metavar="COMMAND")
    sub.add_parser("list", parents=[common], help="valid skills and what was rejected")
    p = sub.add_parser("validate", parents=[common],
                       help="spec errors (exit 1); --strict also fails on warnings and lint")
    p.add_argument("--strict", action="store_true")
    p = sub.add_parser("inspect", parents=[common], help="one skill: fields, files, cost")
    p.add_argument("name")
    p.add_argument("--body", action="store_true", help="also print the SKILL.md body")
    p = sub.add_parser("run", parents=[common], help="answer a task with the agent")
    p.add_argument("--budget", type=positive_int, help="context budget in estimated tokens")
    p.add_argument("--model", default=None, help=f"Ollama model, default {DEFAULT_MODEL}")
    p.add_argument("--max-steps", type=positive_int, default=6)
    p.add_argument("task", nargs="+")
    p = sub.add_parser("doctor", parents=[common], help="check Python, skills and Ollama")
    p.add_argument("--model", default=None, help=f"Ollama model, default {DEFAULT_MODEL}")
    p.add_argument("--offline", action="store_true", help="skip the Ollama check")
    return ap


def _roots(args) -> list[Path]:
    return [Path(d) for d in (args.skills_dir or [DEFAULT_SKILLS_DIR])]


def _emit(args, data, text: str) -> None:
    print(json.dumps(data, indent=2) if args.json else text)


def _skill_row(skill) -> dict:
    return {"name": skill.name, "description": skill.description, "path": str(skill.path),
            "files": list_resources(skill), "scripts": list_scripts(skill),
            "allowed_tools": skill.allowed_tools, "warnings": skill.warnings}


def cmd_list(args) -> int:
    lib = SkillLibrary.discover(*_roots(args))
    rows = [_skill_row(lib.skills[n]) for n in lib.names()]
    width = max([4] + [len(r["name"]) for r in rows])
    lines = [f"{r['name'].ljust(width)}  {len(r['files'])} files  {len(r['scripts'])} scripts  "
             + (r["description"][:70] + ("..." if len(r["description"]) > 70 else ""))
             for r in rows]
    lines.append(f"{len(rows)} skills, {len(lib.rejected)} rejected"
                 + "".join(f"\n  rejected: {p}" for p in lib.rejected))
    _emit(args, {"skills": rows, "rejected": lib.rejected}, "\n".join(lines))
    return EXIT_OK  # listing is not a check; rejected skills are shown, validate fails on them


def cmd_validate(args) -> int:
    lib = SkillLibrary.discover(*_roots(args))
    warnings = [f"{n}: {w}" for n in lib.names() for w in lib.skills[n].warnings]
    lint = [str(i) for i in lint_library(lib)]
    failed = bool(lib.rejected) or (args.strict and bool(warnings or lint))
    lines = [f"ERROR   {p}" for p in lib.rejected] + [f"WARNING {w}" for w in warnings]
    lines += [f"LINT    {i}" for i in lint]
    lines.append(f"{len(lib.names())} valid, {len(lib.rejected)} errors, {len(warnings)} "
                 f"warnings, {len(lint)} lint issues{' (strict)' if args.strict else ''}: "
                 + ("FAIL" if failed else "OK"))
    _emit(args, {"valid": lib.names(), "errors": lib.rejected, "warnings": warnings,
                 "lint": lint, "strict": args.strict, "ok": not failed}, "\n".join(lines))
    return EXIT_CHECK if failed else EXIT_OK


def cmd_inspect(args) -> int:
    lib = SkillLibrary.discover(*_roots(args))
    skill = lib.get(args.name)
    if skill is None:
        print(f"no skill named {args.name!r}; known: {', '.join(lib.names()) or 'none'}",
              file=sys.stderr)
        return EXIT_NOT_FOUND
    cost = next(c for c in skill_costs(lib) if c.name == skill.name)
    row = _skill_row(skill)
    row.update(license=skill.license, compatibility=skill.compatibility,
               metadata=skill.metadata,
               lint=[str(i) for i in lint_description(skill.name, skill.description)],
               tokens={"catalog": cost.catalog, "body": cost.body, "files": cost.files,
                       "full": cost.full})
    if args.body:
        row["body"] = skill.body
    lines = [f"name:          {skill.name}", f"path:          {skill.path}",
             f"description:   {skill.description}"]
    for key in ("license", "compatibility"):
        if row[key]:
            lines.append(f"{key + ':':<15}{row[key]}")
    if skill.metadata:
        lines.append("metadata:      " + ", ".join(f"{k}={v}" for k, v in skill.metadata.items()))
    lines += [f"allowed-tools: {' '.join(skill.allowed_tools) or 'none'}",
              f"files:         {', '.join(row['files']) or 'none'}",
              f"scripts:       {', '.join(row['scripts']) or 'none'} (runnable)",
              f"tokens:        catalog {cost.catalog}, body {cost.body}, files "
              f"{sum(cost.files.values())}, full {cost.full}"]
    lines += [f"warning:       {w}" for w in skill.warnings]
    lines += [f"lint:          {i}" for i in row["lint"]]
    if args.body:
        lines += ["", skill.body.rstrip()]
    _emit(args, row, "\n".join(lines))
    return EXIT_OK


def cmd_run(args, client=None) -> int:
    lib = SkillLibrary.discover(*_roots(args))
    for problem in lib.rejected:
        print(f"skipped skill: {problem}", file=sys.stderr)
    llm = client or OllamaClient(model=args.model or DEFAULT_MODEL)
    try:
        result = Agent(llm, lib, max_steps=args.max_steps,
                       budget_tokens=args.budget).run(" ".join(args.task))
    except ConnectionError as exc:
        print(exc, file=sys.stderr)
        return EXIT_OLLAMA
    data = {"answer": result.answer, "stopped_reason": result.stopped_reason,
            "loaded_skills": result.loaded_skills, "read_files": result.read_files,
            "ran_scripts": result.ran_scripts, "context": result.context}
    text = (f"[skills loaded: {', '.join(result.loaded_skills) or 'none'}]"
            + (f" [files read: {', '.join(result.read_files)}]" if result.read_files else "")
            + (f" [scripts run: {', '.join(result.ran_scripts)}]" if result.ran_scripts else "")
            + f" [context: ~{result.context['spent']} tokens"
            + (f" of {args.budget}" if args.budget else "") + "]\n" + result.answer)
    _emit(args, data, text)
    return EXIT_OK if result.stopped_reason == "final_answer" else EXIT_STOPPED


def doctor_checks(roots: list[Path], model: str, offline: bool, fetch=None,
                  version=None) -> list[dict]:
    """Each check is {name, status: ok|warn|fail, detail}. Only fail changes the exit code."""
    checks = []

    def add(name, status, detail):
        checks.append({"name": name, "status": status, "detail": detail})

    v = tuple(version or sys.version_info[:3])
    add("python", "ok" if v[:2] >= MIN_PYTHON else "fail",
        f"{'.'.join(map(str, v))} (needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)")
    missing = [str(r) for r in roots if not Path(r).is_dir()]
    add("skills roots", "fail" if missing else "ok",
        f"missing: {', '.join(missing)}" if missing else ", ".join(str(r) for r in roots))
    lib = SkillLibrary.discover(*[r for r in roots if Path(r).is_dir()])
    add("valid skills", "ok" if lib.skills else "fail",
        f"{len(lib.skills)}: {', '.join(lib.names())}" if lib.skills else "no valid skill found")
    add("rejected skills", "warn" if lib.rejected else "ok",
        "; ".join(lib.rejected) if lib.rejected else "none")
    lint = lint_library(lib)
    add("descriptions", "warn" if lint else "ok",
        f"{len(lint)} lint issues, see validate" if lint else "lint clean")
    needs_sh = [f"{n}/{s}" for n in lib.names() for s in list_scripts(lib.skills[n])
                if s.endswith(".sh")]
    sh_ok = os.path.exists(INTERPRETERS[".sh"][0])
    add("script runners", "fail" if needs_sh and not sh_ok else "ok",
        f"python {sys.executable}; /bin/sh {'found' if sh_ok else 'missing'}")
    if offline:
        add("ollama", "warn", "skipped (--offline)")
    else:
        ok, msg = check_ollama(model, DEFAULT_HOST, fetch=fetch)
        add("ollama", "ok" if ok else "fail", msg)
    return checks


def cmd_doctor(args, fetch=None) -> int:
    checks = doctor_checks(_roots(args), args.model or DEFAULT_MODEL, args.offline, fetch)
    failed = any(c["status"] == "fail" for c in checks)
    lines = [f"[{c['status'].upper():<4}] {c['name']}: {c['detail']}" for c in checks]
    lines.append("doctor: " + ("FAIL" if failed else "OK"))
    _emit(args, {"checks": checks, "ok": not failed}, "\n".join(lines))
    failing = {c["name"] for c in checks if c["status"] == "fail"}
    if failing == {"ollama"}:  # everything else is fine: a distinct code for scripts (D33)
        return EXIT_OLLAMA
    return EXIT_CHECK if failed else EXIT_OK


def normalize(argv: list[str]) -> list[str]:
    """Keep the day 1 short form: anything that is not a command or help is a task."""
    if argv and argv[0] not in COMMANDS and argv[0] not in ("-h", "--help"):
        return ["run"] + argv
    return argv


def main(argv: list[str] | None = None, client=None, fetch=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        build_parser().print_usage()
        return EXIT_USAGE
    try:
        args = build_parser().parse_args(normalize(argv))
    except SystemExit as exc:  # argparse: 0 for --help, 2 for usage errors
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    if args.command == "run":
        return cmd_run(args, client=client)
    if args.command == "doctor":
        return cmd_doctor(args, fetch=fetch)
    return {"list": cmd_list, "validate": cmd_validate, "inspect": cmd_inspect}[
        args.command](args)
