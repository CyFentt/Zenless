from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SkillSelection:
    names: tuple[str, ...]
    text: str


class SkillLibrary:
    def __init__(self, portable_root: Path) -> None:
        self.sources = portable_root.resolve() / "runtime" / "sources"
        self._catalog = {
            "architecture": [
                ("roblox-best-practices", "roblox-best-practices/SKILL.md"),
                ("roblox-dev-skill", "SKILL.md"),
            ],
            "security": [
                ("roblox-best-practices", "roblox-best-practices/references/security.md"),
                ("roblox-best-practices", "roblox-best-practices/references/server-authority.md"),
                ("roblox-dev-skill", "references/security-hardening.md"),
                ("roblox-dev-skill", "references/networking.md"),
            ],
            "ui": [
                ("roblox-dev-skills", ".claude/skills/roblox-ui-mastery/SKILL.md"),
                ("roblox-best-practices", "roblox-best-practices/references/ui-crossplatform.md"),
                ("roblox-dev-skill", "references/ui-systems.md"),
            ],
            "world": [
                ("roblox-dev-skills", ".claude/skills/building-maps/SKILL.md"),
                ("roblox-dev-skills", ".claude/skills/building-3d-objects/SKILL.md"),
                ("roblox-best-practices", "roblox-best-practices/references/patterns/world.md"),
            ],
            "performance": [
                ("roblox-best-practices", "roblox-best-practices/references/performance.md"),
                ("roblox-best-practices", "roblox-best-practices/references/device-performance.md"),
                ("roblox-dev-skill", "references/performance-optimization.md"),
            ],
            "data": [
                ("roblox-best-practices", "roblox-best-practices/references/patterns/data.md"),
                ("roblox-dev-skill", "references/datastore-persistence.md"),
            ],
            "testing": [
                ("roblox-best-practices", "roblox-best-practices/references/verification.md"),
                ("roblox-best-practices", "roblox-best-practices/references/review-checklist.md"),
                ("roblox-dev-skills", ".claude/rules/quality-gate.md"),
            ],
            "animation": [
                ("roblox-dev-skill", "references/file-formats-and-assets.md"),
                ("roblox-dev-skill", "references/studio-plugins-and-limits.md"),
            ],
            "assets": [
                ("roblox-dev-skill", "references/file-formats-and-assets.md"),
                ("roblox-best-practices", "roblox-best-practices/references/community-libraries.md"),
            ],
        }

    def select(self, objective: str, *, limit: int = 24000) -> SkillSelection:
        categories = self._categories(objective)
        if "architecture" not in categories:
            categories.insert(0, "architecture")
        if "testing" not in categories:
            categories.append("testing")
        names: list[str] = []
        sections: list[str] = []
        remaining = max(4000, limit)
        seen: set[tuple[str, str]] = set()
        for category in categories:
            for source_id, relative in self._catalog.get(category, []):
                key = (source_id, relative)
                if key in seen:
                    continue
                seen.add(key)
                path = self.sources / source_id / relative
                if not path.is_file():
                    continue
                source = path.read_text(encoding="utf-8", errors="replace").strip()
                if not source:
                    continue
                excerpt = source[: min(7000, remaining)]
                sections.append(f"SKILL {category.upper()} | {source_id}/{relative}\n{excerpt}")
                names.append(f"{category}:{source_id}/{relative}")
                remaining -= len(excerpt)
                if remaining <= 1000:
                    break
            if remaining <= 1000:
                break
        return SkillSelection(tuple(names), "\n\n".join(sections))

    @staticmethod
    def _categories(objective: str) -> list[str]:
        text = objective.casefold()
        mapping = [
            ("security", ("remote", "exploit", "security", "anti-cheat", "validation", "server authority")),
            ("ui", ("ui", "gui", "hud", "menu", "screen", "interface", "inventory")),
            ("world", ("map", "world", "terrain", "building", "environment", "obby", "level")),
            ("performance", ("performance", "optimize", "lag", "fps", "memory", "streaming")),
            ("data", ("datastore", "profile", "save", "inventory", "progression", "currency")),
            ("animation", ("animation", "animate", "rig", "emote", "movement")),
            ("assets", ("texture", "material", "mesh", "model", "image", "icon", "thumbnail", "vfx", "effect")),
        ]
        result = [name for name, terms in mapping if any(term in text for term in terms)]
        return result or ["architecture"]
