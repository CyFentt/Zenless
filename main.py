from __future__ import annotations

import faulthandler
import os
import sys
import traceback
from pathlib import Path
from typing import TextIO


def _portable_root() -> Path:
    override = os.environ.get("RUBRA_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _data_root() -> Path:
    override = os.environ.get("RUBRA_DATA_ROOT", "").strip()
    path = Path(override).expanduser().resolve() if override else _portable_root() / "data"
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
        splash.update("CORE", "initializing portable runtime")
        from zenless.toolchain import ToolchainManager
        from zenless.web_app import run_web_app

        if "--no-toolchain" not in sys.argv:
            toolchain = ToolchainManager(
                resource_root=_resource_root(),
                portable_root=_portable_root(),
                status_callback=splash.update,
            )
            toolchain.ensure_default()
            os.environ.update(toolchain.environment())

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
            component="bootstrap",
            message=str(exc),
            exc=exc,
            impact="Rubra could not finish startup.",
            recovery_action="Review data/startup-error.log and retry startup.",
        )
        (_data_root() / "startup-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, f"Rubra failed to start:\n{exc}", "Rubra", 0x10)
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
