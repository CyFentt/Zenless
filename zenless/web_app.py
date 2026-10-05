from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from .core import ZenlessCore
from .desktop_instance import DesktopInstance
from .diagnostics import ErrorBus
from .provisioning import ensure_webview2
from .web_bridge import LocalWebBridge
from .windows_tray import WindowsTray, set_app_identity


class DesktopAPI:
    def __init__(self) -> None:
        self._window: Any = None
        self._maximized = False
        self._tray: WindowsTray | None = None
        self._quitting = False

    def _bind(self, window: Any) -> None:
        self._window = window
        self._maximized = bool(getattr(window, "maximized", False))
        events = getattr(window, "events", None)
        if events is not None:
            events.maximized += self._on_maximized
            events.restored += self._on_restored
            events.closing += self._on_closing

    def _on_maximized(self) -> None:
        self._maximized = True

    def _on_restored(self) -> None:
        self._maximized = False

    def minimize_window(self) -> None:
        if self._window is not None:
            self._window.minimize()

    def toggle_maximize(self) -> None:
        if self._window is not None:
            if self._maximized:
                self._window.restore()
            else:
                self._window.maximize()

    def close_window(self) -> None:
        if self._window is not None:
            if self._tray is not None and self._tray.available and not self._quitting:
                self._window.hide()
            else:
                self._window.destroy()

    def _on_closing(self) -> bool:
        if self._tray is not None and self._tray.available and not self._quitting:
            self._window.hide()
            return False
        return True

    def _show(self) -> None:
        if self._window is not None:
            self._window.show()
            if not self._maximized:
                self._window.restore()

    def _quit(self) -> None:
        self._quitting = True
        try:
            if self._tray is not None:
                self._tray.stop()
        finally:
            if self._window is not None:
                self._window.destroy()

    def select_project_folder(self, current: str = "") -> str:
        window = self._window
        if window is None:
            return ""
        try:
            import webview

            directory = str(Path(current).expanduser()) if current else ""
            selected = window.create_file_dialog(
                webview.FileDialog.FOLDER,
                directory=directory,
                allow_multiple=False,
            )
            return str(selected[0]) if selected else ""
        except Exception:
            return ""


def run_web_app(
    *,
    data_root: Path,
    resource_root: Path,
    diagnostics: ErrorBus,
    smoke_test: bool = False,
    provision: bool = True,
    boot_status: Callable[[str, str], None] | None = None,
    ui_ready: Callable[[], None] | None = None,
) -> int:
    instance = DesktopInstance(data_root)
    if not instance.acquire():
        if ui_ready is not None:
            ui_ready()
        return 0
    try:
        return _run_owned_web_app(
            data_root=data_root,
            resource_root=resource_root,
            diagnostics=diagnostics,
            smoke_test=smoke_test,
            provision=provision,
            boot_status=boot_status,
            ui_ready=ui_ready,
        )
    finally:
        instance.close()


def _run_owned_web_app(
    *,
    data_root: Path,
    resource_root: Path,
    diagnostics: ErrorBus,
    smoke_test: bool,
    provision: bool,
    boot_status: Callable[[str, str], None] | None,
    ui_ready: Callable[[], None] | None,
) -> int:
    status = boot_status or (lambda _stage, _detail: None)
    set_app_identity()
    status("BROWSER", "checking WebView2 runtime")
    if provision:
        ensure_webview2(resource_root, data_root)
    status("STATE", "opening durable local state")
    frontend_root = resource_root / "frontend" / "dist"
    core = ZenlessCore(
        data_root=data_root,
        resource_root=resource_root,
        diagnostics=diagnostics,
    )
    bridge = LocalWebBridge(core=core, frontend_root=frontend_root)
    try:
        status("BRIDGE", "binding authenticated loopback")
        url = bridge.start()
        core.start()
        status("UI", "starting React WebView2 shell")
        import webview

        desktop_api = DesktopAPI()
        window = webview.create_window(
            "Rubra",
            url=url,
            js_api=desktop_api,
            width=1420,
            height=880,
            min_size=(1000, 650),
            resizable=True,
            frameless=True,
            easy_drag=False,
            shadow=True,
            background_color="#090405",
            text_select=True,
        )
        if window is None:
            raise RuntimeError("The embedded browser did not create the main window.")
        desktop_api._bind(window)

        def after_start() -> None:
            if not smoke_test and window.events.shown.wait(8):
                tray = WindowsTray(window, resource_root / "assets" / "rubra.ico", desktop_api._show, desktop_api._quit)
                try:
                    if tray.start():
                        desktop_api._tray = tray
                except Exception as exc:
                    diagnostics.report(
                        severity="WARNING",
                        source="desktop",
                        component="tray",
                        message=str(exc),
                        recovery_action="The window remains available. Close exits Rubra if the tray is unavailable.",
                    )
            if ui_ready is not None:
                ui_ready()
            if smoke_test:
                threading.Timer(6.0, window.destroy).start()

        icon = resource_root / "assets" / "rubra.ico"
        webview.start(
            after_start,
            gui="edgechromium",
            debug=False,
            private_mode=False,
            storage_path=str(data_root / "ui-profile"),
            icon=str(icon) if icon.is_file() else None,
        )
        return 0
    finally:
        try:
            if "desktop_api" in locals() and desktop_api._tray is not None:
                desktop_api._tray.stop()
        finally:
            try:
                bridge.stop()
            finally:
                core.close()
