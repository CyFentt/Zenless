from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class UninstallMode(StrEnum):
    KEEP_SETTINGS = "KEEP_SETTINGS"
    FULL_REMOVE = "FULL_REMOVE"


class UninstallError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class UninstallPlan:
    mode: UninstallMode
    install_root: Path
    data_root: Path
    uninstaller: Path
    owned_targets: tuple[Path, ...]

    def public(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "available": self.uninstaller.is_file(),
            "scope": "Zenless-owned application files and data"
            if self.mode == UninstallMode.FULL_REMOVE
            else "Installed application files",
        }


class UninstallManager:
    def __init__(self, install_root: Path, data_root: Path) -> None:
        self.install_root = (
            Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else install_root.resolve()
        )
        self.data_root = data_root.resolve()
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if not local_app_data:
            raise UninstallError("Windows Local AppData is unavailable.")
        self.local_app_data = Path(local_app_data).resolve()
        self.allowed_install_root = (self.local_app_data / "Programs" / "Zenless").resolve()
        self.allowed_data_root = (self.local_app_data / "Zenless").resolve()
        self._lock = threading.Lock()
        self._scheduled = False

    def plan(self, mode: str) -> UninstallPlan:
        try:
            selected = UninstallMode(mode.strip().upper())
        except ValueError as exc:
            raise UninstallError("Invalid uninstall mode.") from exc
        self._validate_root(self.install_root, self.allowed_install_root)
        self._validate_root(self.data_root, self.allowed_data_root)
        install = self.install_root
        data = self.data_root
        targets = (install,) if selected == UninstallMode.KEEP_SETTINGS else (install, data)
        return UninstallPlan(selected, install, data, install / "Uninstall Zenless.exe", targets)

    def execute(self, mode: str) -> dict[str, object]:
        plan = self.plan(mode)
        with self._lock:
            if self._scheduled:
                return {"scheduled": True, "alreadyScheduled": True, **plan.public()}
            if not plan.uninstaller.is_file():
                raise UninstallError(
                    "The installed Zenless uninstaller is unavailable. Use Windows Apps repair or reinstall setup."
                )
            arguments = ["/S"]
            arguments.append("/KEEPDATA" if plan.mode == UninstallMode.KEEP_SETTINGS else "/REMOVEDATA")
            arguments.append(f"/WAITPID={os.getpid()}")
            try:
                subprocess.Popen(
                    [str(plan.uninstaller), *arguments],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(self.local_app_data),
                    close_fds=True,
                )
            except OSError as exc:
                raise UninstallError("The Zenless uninstaller could not be scheduled.") from exc
            self._scheduled = True
            return {"scheduled": True, "alreadyScheduled": False, **plan.public()}

    @staticmethod
    def _validate_root(path: Path, expected: Path) -> None:
        if path != expected or path.name != "Zenless":
            raise UninstallError("Uninstall is available only from the exact per-user Zenless installation.")
