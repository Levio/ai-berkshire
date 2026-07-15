"""Skill discovery and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_SKILL_RE = re.compile(r"^[a-z0-9-]+$")
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


@dataclass(frozen=True)
class SkillInfo:
    name: str
    title: str
    description: str
    path: str


class SkillRegistry:
    """Scans canonical Claude Code skill markdown files."""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir

    def list_skills(self) -> list[SkillInfo]:
        skills: list[SkillInfo] = []
        if not self.skills_dir.exists():
            return skills

        for path in sorted(self.skills_dir.glob("*.md")):
            name = path.stem
            if not _SKILL_RE.fullmatch(name):
                continue
            skills.append(self._parse_skill(path, name))
        return skills

    def get(self, name: str) -> SkillInfo | None:
        if not self.is_valid_name(name):
            return None
        path = self.skills_dir / f"{name}.md"
        if not path.is_file():
            return None
        return self._parse_skill(path, name)

    def require(self, name: str) -> SkillInfo:
        skill = self.get(name)
        if skill is None:
            raise KeyError(f"Unknown skill: {name}")
        return skill

    @staticmethod
    def is_valid_name(name: str) -> bool:
        return bool(_SKILL_RE.fullmatch(name))

    def _parse_skill(self, path: Path, name: str) -> SkillInfo:
        text = path.read_text(encoding="utf-8", errors="replace")
        title = name
        description = ""

        frontmatter = _FRONTMATTER_RE.match(text)
        body = text
        if frontmatter:
            metadata = self._parse_frontmatter(frontmatter.group(1))
            title = metadata.get("name", title)
            description = metadata.get("description", description)
            body = text[frontmatter.end() :]

        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped.removeprefix("# ").strip() or title
                break

        if not description:
            for line in body.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or stripped.startswith("---"):
                    continue
                description = stripped[:240]
                break

        return SkillInfo(name=name, title=title, description=description, path=str(path.relative_to(self.skills_dir.parent)))

    @staticmethod
    def _parse_frontmatter(text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            value = value.strip().strip('"').strip("'")
            result[key.strip()] = value
        return result
