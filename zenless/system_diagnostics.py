from __future__ import annotations

import ctypes
import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .provisioning import find_webview2_runtime


@dataclass(frozen=True, slots=True)
class SetupIssue:
    code: str
    severity: str
    message: str
    recovery: str

    def public(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "recovery": self.recovery,
        }


class SystemDiagnostics:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root.resolve()

    def inspect(self) -> dict[str, Any]:
        disk = shutil.disk_usage(self.data_root)
        architecture = platform.machine().lower()
        windows = platform.system() == "Windows"
        memory = self._memory()
        studio = self._studio_paths()
        webview = find_webview2_runtime()
        issues = []
        if not windows:
            issues.append(
                SetupIssue(
                    "WINDOWS_REQUIRED",
                    "ERROR",
                    "Zenless targets Windows 11 x64.",
                    "Use a supported Windows 11 x64 system.",
                )
            )
        if architecture not in {"amd64", "x86_64"}:
            issues.append(
                SetupIssue("X64_REQUIRED", "ERROR", "The current process is not x64.", "Install the Windows x64 build.")
            )
        if disk.free < 2 * 1024 * 1024 * 1024:
            issues.append(
                SetupIssue(
                    "LOW_DISK",
                    "WARNING",
                    "Less than 2 GB of free disk space is available.",
                    "Free disk space or reduce the Zenless storage budget.",
                )
            )
        if memory and memory["available"] < 1024 * 1024 * 1024:
            issues.append(
                SetupIssue(
                    "LOW_MEMORY",
                    "WARNING",
                    "Less than 1 GB of memory is currently available.",
                    "Close memory-intensive applications before large Studio tasks.",
                )
            )
        if webview is None:
            issues.append(
                SetupIssue(
                    "WEBVIEW2_MISSING",
                    "ERROR",
                    "The WebView2 runtime is unavailable.",
                    "Run component repair to install the official runtime.",
                )
            )
        if not studio:
            issues.append(
                SetupIssue(
                    "STUDIO_NOT_FOUND",
                    "WARNING",
                    "Roblox Studio was not found.",
                    "Install or update Studio, then enable its MCP server.",
                )
            )
        return {
            "platform": platform.platform(),
            "architecture": architecture,
            "disk": {"free": disk.free, "total": disk.total},
            "memory": memory,
            "webView2": str(webview) if webview else None,
            "studioInstallations": [str(path) for path in studio],
            "issues": [issue.public() for issue in issues],
        }

    @staticmethod
    def _memory() -> dict[str, int] | None:
        if os.name != "nt":
            return None

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memoryLoad", ctypes.c_ulong),
                ("total", ctypes.c_ulonglong),
                ("available", ctypes.c_ulonglong),
                ("totalPage", ctypes.c_ulonglong),
                ("availablePage", ctypes.c_ulonglong),
                ("totalVirtual", ctypes.c_ulonglong),
                ("availableVirtual", ctypes.c_ulonglong),
                ("availableExtended", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return {"total": int(status.total), "available": int(status.available), "loadPercent": int(status.memoryLoad)}

    @staticmethod
    def _studio_paths() -> list[Path]:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            return []
        versions = Path(local) / "Roblox" / "Versions"
        if not versions.is_dir():
            return []
        return sorted(
            [
                candidate
                for version in versions.glob("version-*")
                for candidate in (version / "RobloxStudioBeta.exe", version / "RobloxStudio.exe")
                if candidate.is_file()
            ],
            reverse=True,
        )
