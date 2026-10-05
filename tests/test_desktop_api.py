from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from webview.util import inject_pywebview

from zenless.web_app import DesktopAPI


def test_desktop_api_does_not_expose_or_walk_native_window() -> None:
    api = DesktopAPI()
    native = SimpleNamespace(create_file_dialog=Mock(return_value=["C:/Projects/Game"]))
    api._bind(native)
    scripts: list[str] = []
    loaded = threading.Event()
    window = SimpleNamespace(
        _js_api=api,
        _functions={},
        _expose_lock=threading.Lock(),
        run_js=scripts.append,
        events=SimpleNamespace(before_load=threading.Event(), _pywebviewready=threading.Event(), loaded=loaded),
    )
    with patch("webview.util.load_js_files", return_value=("", "%(functions)s")):
        inject_pywebview("edgechromium", window)
        assert loaded.wait(2)
    exposed = json.loads(scripts[-1])
    assert [item["func"] for item in exposed] == [
        "close_window",
        "minimize_window",
        "select_project_folder",
        "toggle_maximize",
    ]
    assert api.select_project_folder() == "C:/Projects/Game"
    native.create_file_dialog.assert_called_once()


def test_window_controls_follow_native_maximize_and_restore_events():
    api = DesktopAPI()
    native = SimpleNamespace(maximize=Mock(), restore=Mock(), minimize=Mock(), destroy=Mock())
    api._bind(native)
    api.toggle_maximize()
    native.maximize.assert_called_once()
    api._on_maximized()
    api.toggle_maximize()
    native.restore.assert_called_once()
    api._on_restored()
    api.minimize_window()
    api.close_window()
    native.minimize.assert_called_once()
    native.destroy.assert_called_once()
