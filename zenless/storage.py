from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StorageUsage:
    database: int = 0
    logs: int = 0
    runs: int = 0
    job_snapshots: int = 0
    generated_images: int = 0
    generated_3d: int = 0
    downloads: int = 0
    temporary: int = 0
    browser_cache: int = 0
    browser_profile: int = 0
    browser_runtime: int = 0
    optional_tools: int = 0
    tool_cache: int = 0
    test_artifacts: int = 0
    other: int = 0

    @property
    def total(self) -> int:
        return sum(asdict(self).values())

    def public(self) -> dict[str, int]:
        return {**asdict(self), "total": self.total}


@dataclass(frozen=True, slots=True)
class CleanupResult:
    bytes_before: int
    bytes_after: int
    bytes_removed: int
    categories: tuple[str, ...]
    items_removed: int

    def public(self) -> dict[str, object]:
        return {
            "bytesBefore": self.bytes_before,
            "bytesAfter": self.bytes_after,
            "bytesRemoved": self.bytes_removed,
            "categories": list(self.categories),
            "itemsRemoved": self.items_removed,
        }


class StorageManager:
    DEFAULT_BUDGET_BYTES = 10 * 1024 * 1024 * 1024
    MIN_BUDGET_BYTES = 1024 * 1024 * 1024
    MAX_BUDGET_BYTES = 100 * 1024 * 1024 * 1024
    _TEMP_SUFFIXES = {".tmp", ".part", ".download", ".crdownload"}
    _CACHE_NAMES = {"Cache", "Code Cache", "GPUCache", "DawnCache", "GrShaderCache", "ShaderCache"}
    _PROTECTED_NAMES = {
        "zenless.db",
        "zenless.db-wal",
        "zenless.db-shm",
        "browser-runtime",
        "provider-routes.json",
        "provider-sessions.json",
    }

    def __init__(self, data_root: Path, *, budget_bytes: int = DEFAULT_BUDGET_BYTES) -> None:
        self.data_root = data_root.resolve()
        self.temp_root = self.data_root / "tmp"
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.budget_bytes = self._bounded_budget(budget_bytes)

    def set_budget(self, budget_bytes: int) -> int:
        self.budget_bytes = self._bounded_budget(budget_bytes)
        return self.budget_bytes

    def cleanup_temporary(self, *, older_than_seconds: float = 24 * 60 * 60) -> tuple[int, int]:
        cutoff = time.time() - max(60.0, older_than_seconds)
        removed = 0
        bytes_removed = 0
        for path in self.temp_root.rglob("*"):
            if not path.is_file() or path.suffix.casefold() not in self._TEMP_SUFFIXES:
                continue
            try:
                stat = path.stat()
                if stat.st_mtime > cutoff:
                    continue
                size = stat.st_size
                path.unlink()
                removed += 1
                bytes_removed += size
            except OSError:
                continue
        return removed, bytes_removed

    def cleanup_browser_cache(self, profile_root: Path) -> tuple[int, int]:
        profile = profile_root.resolve()
        if not self._is_within(profile, self.data_root):
            raise ValueError("Browser profile must remain inside the Zenless data directory.")
        files = 0
        bytes_removed = 0
        for target in self._cache_directories(profile):
            for item in sorted(target.rglob("*"), key=lambda value: len(value.parts), reverse=True):
                try:
                    if item.is_file() or item.is_symlink():
                        bytes_removed += item.stat().st_size
                        item.unlink()
                        files += 1
                    elif item.is_dir():
                        item.rmdir()
                except OSError:
                    continue
        return files, bytes_removed

    def cleanup_to_budget(
        self,
        *,
        budget_bytes: int | None = None,
        protected_paths: tuple[Path, ...] = (),
    ) -> CleanupResult:
        budget = self._bounded_budget(budget_bytes if budget_bytes is not None else self.budget_bytes)
        before = self.usage().total
        if before <= budget:
            return CleanupResult(before, before, 0, (), 0)
        protected = {path.resolve() for path in protected_paths}
        candidates = self._eviction_candidates(protected)
        removed = 0
        categories = set()
        current = before
        for _mtime, category, path, size in candidates:
            if current <= budget:
                break
            try:
                path.unlink()
            except OSError:
                continue
            removed += 1
            current -= size
            categories.add(category)
        after = self.usage().total
        return CleanupResult(before, after, max(0, before - after), tuple(sorted(categories)), removed)

    def usage(self) -> StorageUsage:
        browser_profiles = (self.data_root / "browser-profile", self.data_root / "webview-profile")
        cache_roots = [directory for profile in browser_profiles for directory in self._cache_directories(profile)]
        categories = {
            "database": self._size_matching(("zenless.db", "zenless.db-wal", "zenless.db-shm")),
            "logs": self._dir_size(self.data_root / "logs") + self._size_matching(("crash.log",)),
            "runs": self._dir_size(self.data_root / "runs"),
            "job_snapshots": self._dir_size(self.data_root / "snapshots"),
            "generated_images": self._dir_size(self.data_root / "visuals"),
            "generated_3d": self._dir_size(self.data_root / "models"),
            "downloads": self._dir_size(self.data_root / "downloads"),
            "temporary": self._dir_size(self.temp_root) + self._dir_size(self.data_root / "uploads"),
            "browser_cache": sum(self._dir_size(path) for path in cache_roots),
            "browser_profile": sum(self._dir_size_excluding(path, set(cache_roots)) for path in browser_profiles),
            "browser_runtime": self._dir_size(self.data_root / "browser-runtime"),
            "optional_tools": self._dir_size(self.data_root / "tools"),
            "tool_cache": self._dir_size(self.data_root / "tool-cache"),
            "test_artifacts": self._dir_size(self.data_root / "test-artifacts"),
        }
        known_names = {
            "zenless.db",
            "zenless.db-wal",
            "zenless.db-shm",
            "crash.log",
            "logs",
            "runs",
            "snapshots",
            "visuals",
            "models",
            "downloads",
            "tmp",
            "uploads",
            "browser-profile",
            "webview-profile",
            "browser-runtime",
            "tools",
            "tool-cache",
            "test-artifacts",
        }
        other = 0
        try:
            entries = list(self.data_root.iterdir())
        except OSError:
            entries = []
        for entry in entries:
            if entry.name in known_names:
                continue
            other += self._dir_size(entry) if entry.is_dir() else self._file_size(entry)
        return StorageUsage(**categories, other=other)

    def _eviction_candidates(self, protected: set[Path]) -> list[tuple[float, str, Path, int]]:
        roots = {
            "TEMP": (self.temp_root, self.data_root / "uploads"),
            "BROWSER_CACHE": tuple(
                directory
                for profile in (self.data_root / "browser-profile", self.data_root / "webview-profile")
                for directory in self._cache_directories(profile)
            ),
            "DOWNLOADS": (self.data_root / "downloads",),
            "TOOL_CACHE": (self.data_root / "tool-cache",),
            "TEST_ARTIFACTS": (self.data_root / "test-artifacts",),
        }
        candidates = []
        for category, category_roots in roots.items():
            for root in category_roots:
                resolved_root = root.resolve(strict=False)
                if not self._is_within(resolved_root, self.data_root):
                    continue
                for path in root.rglob("*") if root.exists() else ():
                    try:
                        resolved = path.resolve()
                        if not path.is_file() or self._protected(resolved, protected):
                            continue
                        stat = path.stat()
                    except OSError:
                        continue
                    candidates.append((stat.st_atime or stat.st_mtime, category, path, stat.st_size))
        candidates.sort(key=lambda item: (item[0], item[1], str(item[2])))
        return candidates

    def _protected(self, path: Path, protected: set[Path]) -> bool:
        if not self._is_within(path, self.data_root):
            return True
        relative = path.relative_to(self.data_root)
        if relative.parts and relative.parts[0] in self._PROTECTED_NAMES:
            return True
        return any(path == item or self._is_within(path, item) for item in protected)

    def _size_matching(self, names: tuple[str, ...]) -> int:
        return sum(self._file_size(self.data_root / name) for name in names)

    @classmethod
    def _cache_directories(cls, profile: Path) -> list[Path]:
        if not profile.exists():
            return []
        return [path for path in profile.rglob("*") if path.is_dir() and path.name in cls._CACHE_NAMES]

    @staticmethod
    def _file_size(path: Path) -> int:
        try:
            return path.stat().st_size if path.is_file() else 0
        except OSError:
            return 0

    @classmethod
    def _dir_size(cls, root: Path) -> int:
        if not root.exists():
            return 0
        if root.is_file():
            return cls._file_size(root)
        total = 0
        for current_root, _directories, filenames in os.walk(root):
            base = Path(current_root)
            for filename in filenames:
                total += cls._file_size(base / filename)
        return total

    @classmethod
    def _dir_size_excluding(cls, root: Path, excluded: set[Path]) -> int:
        if not root.exists():
            return 0
        total = 0
        for current_root, directories, filenames in os.walk(root):
            base = Path(current_root).resolve()
            directories[:] = [name for name in directories if (base / name).resolve() not in excluded]
            for filename in filenames:
                total += cls._file_size(base / filename)
        return total

    @classmethod
    def _bounded_budget(cls, value: int) -> int:
        return max(cls.MIN_BUDGET_BYTES, min(cls.MAX_BUDGET_BYTES, int(value)))

    @staticmethod
    def _is_within(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False
