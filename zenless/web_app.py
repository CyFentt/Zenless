from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Callable

from .core import ZenlessCore
from .diagnostics import ErrorBus
from .provisioning import ensure_webview2
from .web_bridge import LocalWebBridge


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
        if "--native-ui" in sys.argv:
            from .qt_shell import run_native_shell

            status("UI", "starting native workspace")
            return run_native_shell(url, core, resource_root, ui_ready or (lambda: None), core.set_shutdown_callback, smoke_test)
        status("UI", "starting React WebView2 shell")
        import webview

        window = webview.create_window(
            "Zenless",
            url=url,
            width=1420,
            height=880,
            min_size=(1000, 650),
            resizable=True,
            background_color="#050505",
            text_select=True,
        )
        if window is None:
            raise RuntimeError("The embedded browser did not create the main window.")
        core.set_shutdown_callback(window.destroy)

        def after_start() -> None:
            if ui_ready is not None:
                ui_ready()
            if smoke_test:
                threading.Timer(6.0, window.destroy).start()

        icon_path = resource_root / "assets" / "zenless.ico"
        kwargs = {
            "gui": "edgechromium",
            "debug": False,
            "private_mode": False,
            "storage_path": str(data_root / "ui-profile"),
        }
        if icon_path.is_file():
            kwargs["icon"] = str(icon_path)

        webview.start(after_start, **kwargs)
        return 0
    finally:
        bridge.stop()
        core.close()
