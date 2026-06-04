from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from ..paths import SKILLS_DIR
from .registry import json_result, registry

VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
ALLOWED_SUBDIRS = {"references", "templates", "scripts", "assets"}


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    match = re.search(r"\n---\s*\n", text[3:])
    if not match:
        return {}, text
    end = match.start() + 3
    data = yaml.safe_load(text[3:end]) or {}
    body = text[match.end() + 3 :]
    return data if isinstance(data, dict) else {}, body


def _iter_skill_files() -> list[Path]:
    if not SKILLS_DIR.exists():
        return []
    return sorted(SKILLS_DIR.rglob("SKILL.md"))


def _find_skill(name: str) -> Path | None:
    for skill_md in _iter_skill_files():
        if skill_md.parent.name == name:
            return skill_md.parent
        try:
            frontmatter, _ = _parse_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
            if frontmatter.get("name") == name:
                return skill_md.parent
        except OSError:
            continue
    return None


def _validate_skill_name(name: str) -> str | None:
    if not name:
        return "name is required"
    if len(name) > 64 or not VALID_NAME_RE.match(name):
        return "name must be lowercase letters/numbers plus . _ -, starting with a letter or digit"
    return None


def _validate_skill_content(content: str) -> str | None:
    if not content.strip():
        return "content cannot be empty"
    frontmatter, body = _parse_frontmatter(content)
    if not frontmatter:
        return "SKILL.md must start with YAML frontmatter"
    if "name" not in frontmatter or "description" not in frontmatter:
        return "frontmatter must include name and description"
    if not body.strip():
        return "SKILL.md body cannot be empty"
    return None


def _safe_support_path(skill_dir: Path, file_path: str) -> Path:
    raw = Path(file_path)
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError("supporting file path must be relative and cannot contain ..")
    if not raw.parts or raw.parts[0] not in ALLOWED_SUBDIRS or len(raw.parts) < 2:
        raise ValueError(f"file_path must be under one of: {', '.join(sorted(ALLOWED_SUBDIRS))}")
    target = (skill_dir / raw).resolve()
    if skill_dir.resolve() not in target.parents:
        raise ValueError("file_path escapes skill directory")
    return target


def _skills_list(args: dict, runtime: dict) -> str:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    category = args.get("category")
    skills: list[dict[str, str | None]] = []
    for skill_md in _iter_skill_files():
        try:
            text = skill_md.read_text(encoding="utf-8", errors="replace")
            frontmatter, body = _parse_frontmatter(text)
            name = str(frontmatter.get("name") or skill_md.parent.name)
            description = str(frontmatter.get("description") or "").strip()
            rel = skill_md.parent.relative_to(SKILLS_DIR)
            cat = rel.parts[0] if len(rel.parts) > 1 else None
            if category and cat != category:
                continue
            skills.append({"name": name, "description": description[:1024], "category": cat})
        except OSError:
            continue
    return json_result(success=True, skills=skills, count=len(skills))


def _skill_view(args: dict, runtime: dict) -> str:
    name = str(args.get("name") or "")
    skill_dir = _find_skill(name)
    if not skill_dir:
        return json_result(success=False, error=f"Skill not found: {name}")
    file_path = args.get("file_path")
    target = _safe_support_path(skill_dir, file_path) if file_path else skill_dir / "SKILL.md"
    if not target.exists():
        return json_result(success=False, error=f"File not found: {file_path or 'SKILL.md'}")
    content = target.read_text(encoding="utf-8", errors="replace")
    linked_files = []
    if not file_path:
        for subdir in ALLOWED_SUBDIRS:
            root = skill_dir / subdir
            if root.exists():
                linked_files.extend(str(p.relative_to(skill_dir)) for p in root.rglob("*") if p.is_file())
    return json_result(success=True, name=name, path=str(target), content=content, linked_files=linked_files)


def _skill_manage(args: dict, runtime: dict) -> str:
    action = str(args.get("action") or "")
    name = str(args.get("name") or "")
    err = _validate_skill_name(name)
    if err:
        return json_result(success=False, error=err)

    if action == "create":
        content = str(args.get("content") or "")
        err = _validate_skill_content(content)
        if err:
            return json_result(success=False, error=err)
        if _find_skill(name):
            return json_result(success=False, error=f"Skill already exists: {name}")
        category = str(args.get("category") or "").strip()
        skill_dir = (SKILLS_DIR / category / name) if category else (SKILLS_DIR / name)
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        return json_result(success=True, message=f"Skill '{name}' created", path=str(skill_dir))

    skill_dir = _find_skill(name)
    if not skill_dir:
        return json_result(success=False, error=f"Skill not found: {name}")

    if action == "edit":
        content = str(args.get("content") or "")
        err = _validate_skill_content(content)
        if err:
            return json_result(success=False, error=err)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        return json_result(success=True, message=f"Skill '{name}' updated")

    if action == "patch":
        file_path = args.get("file_path")
        target = _safe_support_path(skill_dir, file_path) if file_path else skill_dir / "SKILL.md"
        old = str(args.get("old_text") or "")
        new = args.get("new_text")
        if not old or new is None:
            return json_result(success=False, error="old_text and new_text are required")
        text = target.read_text(encoding="utf-8", errors="replace")
        count = text.count(old)
        replace_all = bool(args.get("replace_all"))
        if count != 1 and not replace_all:
            return json_result(success=False, error=f"Expected one match, found {count}")
        target.write_text(text.replace(old, str(new), -1 if replace_all else 1), encoding="utf-8")
        return json_result(success=True, message=f"Patched {target.name}", replacements=count if replace_all else 1)

    if action == "write_file":
        file_path = str(args.get("file_path") or "")
        content = args.get("file_content")
        if content is None:
            return json_result(success=False, error="file_content is required")
        target = _safe_support_path(skill_dir, file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        return json_result(success=True, message=f"Wrote {file_path}", path=str(target))

    if action == "remove_file":
        target = _safe_support_path(skill_dir, str(args.get("file_path") or ""))
        if target.exists():
            target.unlink()
        return json_result(success=True, message=f"Removed {target.name}")

    return json_result(success=False, error="action must be create, edit, patch, write_file, or remove_file")


registry.register(
    "skills_list",
    {
        "description": "List available skills with brief descriptions.",
        "parameters": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
            "required": [],
        },
    },
    _skills_list,
)
registry.register(
    "skill_view",
    {
        "description": "Read a skill's SKILL.md or a supporting file.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "file_path": {"type": "string"}},
            "required": ["name"],
        },
    },
    _skill_view,
)
registry.register(
    "skill_manage",
    {
        "description": (
            "Create or update project-local skills for reusable task classes. "
            "Use patch for small SKILL.md changes; edit for full rewrites. "
            "Use write_file for supporting files under references/, templates/, scripts/, or assets/."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "edit", "patch", "write_file", "remove_file"],
                },
                "name": {"type": "string"},
                "category": {"type": "string"},
                "content": {"type": "string"},
                "file_path": {"type": "string"},
                "file_content": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "replace_all": {"type": "boolean", "default": False},
            },
            "required": ["action", "name"],
        },
    },
    _skill_manage,
)
