from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StorageUsage:
    database: int = 0
    logs: int = 0
    runs: int = 0
    browser_profile: int = 0
    browser_runtime: int = 0
    temporary: int = 0
    other: int = 0

    @property
    def total(self) -> int:
        return (
            self.database
            + self.logs
            + self.runs
            + self.browser_profile
            + self.browser_runtime
            + self.temporary
            + self.other
        )


class StorageManager:
    _TEMP_SUFFIXES = {".tmp", ".part", ".download", ".crdownload"}
    _CACHE_NAMES = {"Cache", "Code Cache", "GPUCache", "DawnCache", "GrShaderCache"}

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root.resolve()
        self.temp_root = self.data_root / "tmp"
        self.temp_root.mkdir(parents=True, exist_ok=True)

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
        targets = [path for path in profile.rglob("*") if path.is_dir() and path.name in self._CACHE_NAMES]
        files = 0
        bytes_removed = 0
        for target in targets:
            if not self._is_within(target.resolve(), profile):
                continue
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

    def usage(self) -> StorageUsage:
        categories = {
            "database": self._size_matching(("zenless.db", "zenless.db-wal", "zenless.db-shm")),
            "logs": self._dir_size(self.data_root / "logs") + self._size_matching(("crash.log",)),
            "runs": self._dir_size(self.data_root / "runs"),
            "browser_profile": self._dir_size(self.data_root / "browser-profile"),
            "browser_runtime": self._dir_size(self.data_root / "browser-runtime"),
            "temporary": self._dir_size(self.temp_root),
        }
        known_names = {
            "zenless.db",
            "zenless.db-wal",
            "zenless.db-shm",
            "crash.log",
            "logs",
            "runs",
            "browser-profile",
            "browser-runtime",
            "tmp",
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

    def _size_matching(self, names: tuple[str, ...]) -> int:
        return sum(self._file_size(self.data_root / name) for name in names)

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

    @staticmethod
    def _is_within(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False
