from __future__ import annotations

import faulthandler
import os
import sys
import traceback
from pathlib import Path
from typing import TextIO


def _data_root() -> Path:
    override = os.environ.get("ZENLESS_DATA_ROOT", "").strip()
    if override:
        path = Path(override).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(base) / "Zenless"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _enable_crash_log() -> TextIO:
    stream = (_data_root() / "crash.log").open("a", encoding="utf-8")
    faulthandler.enable(stream)
    return stream


def _resource_root() -> Path:
    bundled = getattr(sys, "_MEIPASS", "")
    return Path(bundled) if bundled else Path(__file__).resolve().parent


def main() -> int:
    crash_stream = _enable_crash_log()
    from zenless.diagnostics import ErrorBus

    diagnostics = ErrorBus(_data_root() / "logs")
    diagnostics.install_global_hooks()
    splash = None
    try:
        if "--webview-host" in sys.argv:
            from zenless.webview_host import main as webview_host_main

            return webview_host_main()
        from zenless.bootstrap import NativeSplash

        splash = NativeSplash()
        splash.show()
        splash.update("CORE", "initializing local runtime")
        from zenless.web_app import run_web_app

        try:
            return run_web_app(
                data_root=_data_root(),
                resource_root=_resource_root(),
                diagnostics=diagnostics,
                smoke_test="--smoke-test" in sys.argv,
                provision="--no-provision" not in sys.argv,
                boot_status=splash.update,
                ui_ready=splash.close,
            )
        except Exception as exc:
            diagnostics.report(
                severity="CRITICAL",
                source="startup",
                component="web-app",
                message=str(exc),
                exc=exc,
                impact="Zenless não conseguiu abrir a interface WebView2.",
                recovery_action="Consulte startup-error.log; o provisionamento automático pode ser repetido.",
            )
            (_data_root() / "startup-error.log").write_text(traceback.format_exc(), encoding="utf-8")
            try:
                import ctypes

                ctypes.windll.user32.MessageBoxW(0, f"Falha ao iniciar Zenless:\n{exc}", "Zenless", 0x10)
            except Exception:
                pass
            return 1
    finally:
        if splash is not None:
            splash.close()
        diagnostics.close()
        crash_stream.close()


if __name__ == "__main__":
    raise SystemExit(main())
