"""Agent Skills: parse SKILL.md files, validate them, and build the catalog.

A skill is a folder with a SKILL.md file. The file starts with YAML frontmatter
(name, description, optional license / compatibility / metadata / allowed-tools)
followed by Markdown instructions. Progressive disclosure has three levels:

1. catalog: only name + description of every skill sit in the system prompt
2. body: the Markdown instructions, loaded when the model calls load_skill
3. resources: extra files in the folder, read on demand with read_resource

See decision.md D7 to D12 (levels 1 and 2) and D14 to D17 (level 3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

SKILL_FILE = "SKILL.md"
NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500
KNOWN_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RESOURCE_MAX_BYTES = 16_000  # level 3 cap per read, about 4k tokens (D16)
RESOURCE_LIST_MAX = 50


class SkillError(ValueError):
    """A SKILL.md that cannot be parsed or breaks a hard rule of the spec."""


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path  # the skill folder
    license: str = ""
    compatibility: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        return inner.replace("''", "'") if value[0] == "'" else inner.replace('\\"', '"')
    return value


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split SKILL.md text into (frontmatter dict, body).

    Supports the YAML subset skills use: `key: value`, quoted values, block
    scalars (`|` keeps newlines, `>` folds them), plain values continued on more
    indented lines, and one level nested mappings (for `metadata`). No PyYAML,
    so the agent keeps zero dependencies (D8).
    """
    text = text.lstrip("﻿")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError("SKILL.md must start with a '---' frontmatter line")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise SkillError("frontmatter is not closed with a '---' line") from None
    fm_lines, body = lines[1:end], "\n".join(lines[end + 1:]).strip("\n")

    data: dict = {}
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line[0] in " \t":
            raise SkillError(f"unexpected indentation on frontmatter line: {line.strip()!r}")
        if ":" not in line:
            raise SkillError(f"frontmatter line is not 'key: value': {line.strip()!r}")
        key, _, rest = line.partition(":")
        key, rest = key.strip(), rest.strip()
        if key in data:
            raise SkillError(f"duplicate frontmatter key {key!r}")
        i += 1
        block: list[str] = []
        while i < len(fm_lines) and (not fm_lines[i].strip() or fm_lines[i][0] in " \t"):
            block.append(fm_lines[i])
            i += 1
        while block and not block[-1].strip():
            block.pop()
        if rest in ("|", ">", "|-", ">-"):
            parts = [b.strip() for b in block]
            data[key] = "\n".join(parts).strip() if rest[0] == "|" else " ".join(
                p for p in parts if p)
        elif rest == "" and block:
            mapping = {}
            for b in block:
                if not b.strip():
                    continue
                if ":" not in b:
                    raise SkillError(f"nested line under {key!r} is not 'key: value'")
                k, _, v = b.strip().partition(":")
                mapping[k.strip()] = _unquote(v)
            data[key] = mapping
        else:
            value = _unquote(rest)
            if block:  # plain scalar continued on indented lines
                value = " ".join([value] + [b.strip() for b in block if b.strip()])
            data[key] = value
    return data, body


def validate(data: dict, folder_name: str | None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors make the skill unloadable."""
    errors: list[str] = []
    warnings: list[str] = []
    name = data.get("name")
    if not isinstance(name, str) or not name:
        errors.append("missing required field 'name'")
    else:
        if len(name) > NAME_MAX:
            errors.append(f"name is {len(name)} chars, max {NAME_MAX}")
        if not NAME_RE.match(name):
            errors.append("name must be lowercase letters, digits and single hyphens, "
                          "not starting or ending with a hyphen")
        if folder_name is not None and name != folder_name:
            errors.append(f"name {name!r} does not match folder {folder_name!r}")
    desc = data.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errors.append("missing required field 'description'")
    elif len(desc) > DESCRIPTION_MAX:
        errors.append(f"description is {len(desc)} chars, max {DESCRIPTION_MAX}")
    elif len(desc.split()) < 6:
        warnings.append("description is very short; say what the skill does and when to use it")
    comp = data.get("compatibility", "")
    if isinstance(comp, str) and len(comp) > COMPATIBILITY_MAX:
        errors.append(f"compatibility is {len(comp)} chars, max {COMPATIBILITY_MAX}")
    if "metadata" in data and not isinstance(data["metadata"], dict):
        errors.append("metadata must be a mapping of string keys to string values")
    for key in sorted(set(data) - KNOWN_FIELDS):
        warnings.append(f"unknown frontmatter field {key!r} is ignored")
    return errors, warnings


def load_skill_dir(folder: Path) -> Skill:
    folder = Path(folder)
    file = folder / SKILL_FILE
    if not file.is_file():
        raise SkillError(f"{folder.name}: no {SKILL_FILE}")
    try:
        data, body = parse_frontmatter(file.read_text(encoding="utf-8"))
    except SkillError as exc:
        raise SkillError(f"{folder.name}: {exc}") from None
    errors, warnings = validate(data, folder.name)
    if errors:
        raise SkillError(f"{folder.name}: " + "; ".join(errors))
    if not body.strip():
        warnings.append("SKILL.md has no instructions after the frontmatter")
    tools = data.get("allowed-tools", "")
    return Skill(
        name=data["name"], description=" ".join(data["description"].split()), body=body,
        path=folder, license=str(data.get("license", "")),
        compatibility=str(data.get("compatibility", "")),
        metadata=dict(data.get("metadata") or {}),
        allowed_tools=tools.split() if isinstance(tools, str) else [],
        warnings=warnings,
    )


def list_resources(skill: Skill, limit: int = RESOURCE_LIST_MAX) -> list[str]:
    """Relative POSIX paths of the files bundled with a skill, except SKILL.md.

    Hidden files and folders and symlinks are skipped, so the list only shows
    what read_resource would actually serve.
    """
    root = skill.path.resolve()
    found: list[str] = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part.startswith(".") for part in rel.parts) or p.is_symlink():
            continue
        if p.is_file() and rel.as_posix() != SKILL_FILE:
            found.append(rel.as_posix())
            if len(found) >= limit:
                break
    return found


def resolve_resource(skill: Skill, rel_path: str) -> Path:
    """Map a path the model asked for to a real file inside the skill folder.

    Refuses absolute paths, `..`, hidden parts, SKILL.md itself, anything whose
    resolved location (after following symlinks) is outside the folder, and
    anything that is not a regular file (D15).
    """
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise SkillError("path is empty")
    raw = rel_path.strip().replace("\\", "/")
    if raw.startswith("./"):
        raw = raw[2:]
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise SkillError(f"path {rel_path!r} must be relative to the skill folder")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts:
        raise SkillError("path is empty")
    if ".." in parts:
        raise SkillError(f"path {rel_path!r} may not contain '..'")
    if any(p.startswith(".") for p in parts):
        raise SkillError(f"path {rel_path!r} points to a hidden file")
    if parts == [SKILL_FILE]:
        raise SkillError("SKILL.md is the skill body; use load_skill for it")
    root = skill.path.resolve()
    target = root.joinpath(*parts)
    try:
        real = target.resolve(strict=True)
    except (FileNotFoundError, RuntimeError, OSError):
        raise SkillError(f"no file {raw!r} in skill {skill.name!r}") from None
    if real != root and root not in real.parents:
        raise SkillError(f"path {rel_path!r} resolves outside the skill folder")
    if not real.is_file():
        raise SkillError(f"{raw!r} is not a file")
    return real


def read_resource(skill: Skill, rel_path: str,
                  max_bytes: int = RESOURCE_MAX_BYTES) -> tuple[str, bool]:
    """Level 3 disclosure: return (text, truncated) for a file in the skill folder.

    Reads at most max_bytes. Binary files (NUL byte or invalid UTF-8) are refused.
    """
    real = resolve_resource(skill, rel_path)
    with real.open("rb") as fh:
        data = fh.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    data = data[:max_bytes]
    if b"\x00" in data:
        raise SkillError(f"{rel_path!r} is a binary file and cannot be read as text")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        if truncated and exc.start >= len(data) - 3:  # cut inside a multibyte char
            text = data[:exc.start].decode("utf-8")
        else:
            raise SkillError(f"{rel_path!r} is not UTF-8 text") from None
    return text, truncated


@dataclass
class SkillLibrary:
    """All valid skills found under one or more roots, plus what was rejected."""

    skills: dict[str, Skill] = field(default_factory=dict)
    rejected: list[str] = field(default_factory=list)

    @classmethod
    def discover(cls, *roots: Path | str) -> "SkillLibrary":
        lib = cls()
        for root in roots:
            root = Path(root)
            if not root.is_dir():
                lib.rejected.append(f"{root}: skills root does not exist")
                continue
            for folder in sorted(p for p in root.iterdir() if p.is_dir()):
                if folder.name.startswith("."):
                    continue
                try:
                    skill = load_skill_dir(folder)
                except SkillError as exc:
                    lib.rejected.append(str(exc))
                    continue
                if skill.name in lib.skills:  # first root wins (D11)
                    lib.rejected.append(f"{folder}: duplicate skill name {skill.name!r}, "
                                        f"kept {lib.skills[skill.name].path}")
                    continue
                lib.skills[skill.name] = skill
        return lib

    def names(self) -> list[str]:
        return sorted(self.skills)

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def catalog(self) -> str:
        """Level 1 disclosure: name and description only, as XML for the system prompt."""
        if not self.skills:
            return "<available_skills>\n</available_skills>"
        rows = []
        for name in self.names():
            s = self.skills[name]
            rows.append(f"  <skill>\n    <name>{escape(s.name)}</name>\n"
                        f"    <description>{escape(s.description)}</description>\n  </skill>")
        return "<available_skills>\n" + "\n".join(rows) + "\n</available_skills>"
