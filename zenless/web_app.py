from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from .core import ZenlessCore
from .diagnostics import ErrorBus
from .provisioning import ensure_webview2
from .web_bridge import LocalWebBridge


class DesktopAPI:
    def __init__(self) -> None:
        self._window: Any = None
        self._maximized = False

    def _bind(self, window: Any) -> None:
        self._window = window
        self._maximized = bool(getattr(window, "maximized", False))
        events = getattr(window, "events", None)
        if events is not None:
            events.maximized += self._on_maximized
            events.restored += self._on_restored

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
    status = boot_status or (lambda _stage, _detail: None)
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
        bridge.stop()
        core.close()
