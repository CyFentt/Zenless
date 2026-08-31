from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ProjectIndex:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries = self._load()

    def refresh(self, payload_text: str) -> int:
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            return 0
        changed = 0
        for raw in self._walk(payload):
            path = str(raw.get("fullPath") or raw.get("path") or raw.get("name") or "").strip()
            if not path:
                continue
            class_name = str(raw.get("className") or raw.get("class") or "Instance")
            source = str(raw.get("source") or raw.get("content") or "")
            compact = " ".join(source.split())[:20_000]
            digest = hashlib.sha256(compact.encode("utf-8", "replace")).hexdigest() if compact else ""
            keywords = sorted(set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", f"{path} {compact}")))[:120]
            prior = self._entries.get(path, {})
            entry = {
                "path": path,
                "class": class_name,
                "hash": digest or prior.get("hash", ""),
                "lastSeen": self._now(),
                "references": self._references(compact),
                "keywords": keywords,
                "dependencies": self._dependencies(compact),
                "services": self._services(compact),
                "remotes": self._remotes(compact),
                "moduleLinks": self._module_links(compact),
                "lastMutation": prior.get("lastMutation", ""),
            }
            if prior != entry:
                changed += 1
            self._entries[path] = entry
        if changed:
            self._save()
        return changed

    def relevant(self, keywords: tuple[str, ...], *, limit: int = 80) -> list[dict[str, Any]]:
        terms = {value.casefold() for value in keywords if value}
        ranked = []
        for entry in self._entries.values():
            haystack = " ".join(
                [
                    str(entry.get("path", "")),
                    *[str(item) for item in entry.get("keywords", [])],
                    *[str(item) for item in entry.get("references", [])],
                ]
            ).casefold()
            score = sum(1 for term in terms if term in haystack)
            if score:
                ranked.append((score, entry))
        ranked.sort(key=lambda item: (-item[0], str(item[1].get("path", ""))))
        return [dict(entry) for _, entry in ranked[: max(1, min(500, limit))]]

    def mark_mutation(self, paths: list[str]) -> None:
        timestamp = self._now()
        changed = False
        for path in paths:
            if path in self._entries:
                self._entries[path]["lastMutation"] = timestamp
                changed = True
        if changed:
            self._save()

    def public(self) -> dict[str, Any]:
        return {"entries": len(self._entries), "updatedAt": self._now()}

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            return {}
        return (
            {str(key): dict(value) for key, value in raw.items() if isinstance(value, dict)}
            if isinstance(raw, dict)
            else {}
        )

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @classmethod
    def _walk(cls, value: Any) -> list[dict[str, Any]]:
        result = []
        if isinstance(value, dict):
            if any(key in value for key in ("fullPath", "path", "className")):
                result.append(value)
            for item in value.values():
                result.extend(cls._walk(item))
        elif isinstance(value, list):
            for item in value:
                result.extend(cls._walk(item))
        return result

    @staticmethod
    def _references(source: str) -> list[str]:
        return sorted(set(re.findall(r"(?:game|workspace)(?:\.[A-Za-z_][A-Za-z0-9_]*)+", source)))[:80]

    @staticmethod
    def _dependencies(source: str) -> list[str]:
        return sorted(set(re.findall(r"require\s*\(([^\n\r]{1,180})\)", source)))[:80]

    @staticmethod
    def _services(source: str) -> list[str]:
        return sorted(set(re.findall(r"GetService\s*\(\s*[\"']([^\"']+)[\"']\s*\)", source)))[:80]

    @staticmethod
    def _remotes(source: str) -> list[str]:
        return sorted(set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*(?:RemoteEvent|RemoteFunction))\b", source)))[:80]

    @staticmethod
    def _module_links(source: str) -> list[str]:
        return sorted(set(re.findall(r"\b(?:ModuleScript|ReplicatedStorage)\.([A-Za-z_][A-Za-z0-9_.]*)", source)))[:80]

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")
