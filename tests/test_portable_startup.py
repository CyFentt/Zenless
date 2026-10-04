from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import main as application
from zenless.webview2_browser import WebView2BrowserController


class PortableStartupTests(unittest.TestCase):
    def test_toolchain_failure_is_logged_and_closes_startup_resources(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            diagnostics = MagicMock()
            splash = MagicMock()
            toolchain = MagicMock()
            toolchain.ensure_default.side_effect = RuntimeError("Pinned runtime download failed")
            stream = MagicMock()
            with (
                patch.object(application, "_data_root", return_value=root),
                patch.object(application, "_enable_crash_log", return_value=stream),
                patch("main.sys.argv", ["Rubra.exe"]),
                patch("zenless.diagnostics.ErrorBus", return_value=diagnostics),
                patch("zenless.bootstrap.NativeSplash", return_value=splash),
                patch("zenless.toolchain.ToolchainManager", return_value=toolchain),
                patch("zenless.web_app.run_web_app") as run_web_app,
                patch("ctypes.windll", create=True),
            ):
                self.assertEqual(application.main(), 1)

            self.assertIn("Pinned runtime download failed", (root / "startup-error.log").read_text())
            diagnostics.report.assert_called_once()
            diagnostics.close.assert_called_once()
            splash.close.assert_called_once()
            stream.close.assert_called_once()
            run_web_app.assert_not_called()

    def test_windowed_interpreter_uses_console_helper_for_protocol_pipes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            controller = WebView2BrowserController(data_root=root / "data")
            with (
                patch("zenless.webview2_browser.sys.platform", "win32"),
                patch("zenless.webview2_browser.sys.executable", str(root / "pythonw.exe")),
                patch("zenless.webview2_browser.sys.frozen", False, create=True),
            ):
                command = controller._command(root / "providers.json")
            self.assertEqual(command[:3], [str(root / "python.exe"), "-m", "zenless.webview_host"])
            self.assertIn(str(root / "providers.json"), command)
            self.assertNotIn("--webview-host", command)


if __name__ == "__main__":
    unittest.main()
