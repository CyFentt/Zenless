from __future__ import annotations

import hashlib
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .bootstrap import BootstrapBus, BootstrapStatus
from .diagnostics import ErrorBus

WEBVIEW2_APP_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_BOOTSTRAPPER_SHA256 = "94314d8b20c8a370df81c5cc3d8d7a3e23fe5de14ef5e988229ff3208e449146"
TickCallback = Callable[[], None]


@dataclass(frozen=True, slots=True)
class ComponentStatus:
    name: str
    ready: bool
    version: str = ""
    detail: str = ""


class WebView2Runtime:
    REGISTRY_PATHS = (
        rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_APP_ID}",
        rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_APP_ID}",
    )

    def detect(self) -> ComponentStatus:
        version = self._registry_version()
        if self._valid_version(version):
            return ComponentStatus("WebView2", True, version, "Microsoft Evergreen Runtime")
        executable = self._runtime_executable()
        if executable is not None:
            return ComponentStatus("WebView2", True, executable.parent.name, str(executable))
        return ComponentStatus("WebView2", False, detail="Runtime unavailable")

    def ensure(self, installer: Path, *, tick: TickCallback | None = None) -> ComponentStatus:
        current = self.detect()
        if current.ready:
            return current
        self.verify_installer(installer)
        process = subprocess.Popen(
            [str(installer), "/silent", "/install"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + 360.0
        while process.poll() is None:
            if time.monotonic() >= deadline:
                process.terminate()
                raise TimeoutError("Secure WebView2 installation exceeded six minutes.")
            if tick is not None:
                tick()
            time.sleep(0.1)
        if process.returncode not in {0, 2147747880}:
            raise RuntimeError(f"The official WebView2 installer returned {process.returncode}.")
        for _attempt in range(60):
            current = self.detect()
            if current.ready:
                return current
            if tick is not None:
                tick()
            time.sleep(0.25)
        raise RuntimeError("WebView2 installation completed, but the runtime was not detected.")

    @staticmethod
    def verify_installer(installer: Path) -> None:
        if not installer.is_file():
            raise FileNotFoundError("The official WebView2 bootstrapper is not included.")
        digest = hashlib.sha256(installer.read_bytes()).hexdigest()
        if digest != WEBVIEW2_BOOTSTRAPPER_SHA256:
            raise RuntimeError("WebView2 bootstrapper integrity verification failed; installation cancelled.")

    @staticmethod
    def _valid_version(version: str) -> bool:
        return bool(
            version and version != "0.0.0.0" and any(character.isdigit() and character != "0" for character in version)
        )

    def _registry_version(self) -> str:
        if os.name != "nt":
            return ""
        import winreg

        roots = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
        for root in roots:
            for path in self.REGISTRY_PATHS:
                try:
                    with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
                        value, _kind = winreg.QueryValueEx(key, "pv")
                except OSError:
                    continue
                version = str(value or "").strip()
                if self._valid_version(version):
                    return version
        return ""

    @staticmethod
    def _runtime_executable() -> Path | None:
        roots = [
            Path(os.environ.get("PROGRAMFILES(X86)", "")),
            Path(os.environ.get("PROGRAMFILES", "")),
            Path(os.environ.get("LOCALAPPDATA", "")),
        ]
        candidates: list[Path] = []
        for root in roots:
            if not str(root):
                continue
            base = root / "Microsoft" / "EdgeWebView" / "Application"
            if not base.is_dir():
                continue
            candidates.extend(base.glob("*/msedgewebview2.exe"))
        return max(candidates, key=lambda item: item.parent.name, default=None)


class ComponentBootstrap:
    def __init__(
        self,
        *,
        data_root: Path,
        resource_root: Path,
        bus: BootstrapBus,
        diagnostics: ErrorBus,
        tick: TickCallback | None = None,
    ) -> None:
        self.data_root = data_root
        self.resource_root = resource_root
        self.bus = bus
        self.diagnostics = diagnostics
        self.tick = tick
        self.webview2 = WebView2Runtime()

    def prepare(self) -> list[ComponentStatus]:
        statuses: list[ComponentStatus] = []
        self.bus.emit("workspace", "Preparing Workspace", BootstrapStatus.RUNNING, "Creating local Zenless storage")
        for folder in ("logs", "runs", "downloads", "temp", "webview-profile", "browser-profile"):
            (self.data_root / folder).mkdir(parents=True, exist_ok=True)
        self.bus.emit("workspace", "Preparing Workspace", BootstrapStatus.READY, "Local folders are writable")

        self.bus.emit("webview2", "Checking Embedded Browser", BootstrapStatus.RUNNING, "Detecting Microsoft WebView2")
        try:
            status = self.webview2.ensure(
                self.resource_root / "vendor" / "MicrosoftEdgeWebview2Setup.exe",
                tick=self.tick,
            )
            statuses.append(status)
            self.bus.emit(
                "webview2",
                "Checking Embedded Browser",
                BootstrapStatus.READY,
                f"WebView2 {status.version or 'ready'}",
            )
        except Exception as exc:
            status = ComponentStatus("WebView2", False, detail=str(exc))
            statuses.append(status)
            self.bus.emit("webview2", "Checking Embedded Browser", BootstrapStatus.WARNING, str(exc))
            self.diagnostics.report(
                severity="WARNING",
                source="bootstrap",
                component="webview2-runtime",
                message=str(exc),
                exc=exc,
                impact="The embedded browser is unavailable; Playwright or the extension may still work.",
                recovery_action="Retry Zenless with an internet connection or repair WebView2 from Windows Apps.",
            )
        return statuses
