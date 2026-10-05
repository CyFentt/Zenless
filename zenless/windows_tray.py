from __future__ import annotations

import ctypes
import importlib
import os
from pathlib import Path
from typing import Any, Callable


def set_app_identity(name: str = "Rubra.Desktop") -> None:
    if os.name == "nt":
        try:
            setter = ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID
            setter.argtypes = [ctypes.c_wchar_p]
            setter.restype = ctypes.c_long
            setter(name)
        except OSError:
            pass


class WindowsTray:
    def __init__(self, window: Any, icon: Path, on_open: Callable[[], None], on_quit: Callable[[], None]) -> None:
        self.window = window
        self.icon_path = icon
        self.on_open, self.on_quit = on_open, on_quit
        self._notify: Any = None
        self._menu: Any = None
        self._icon: Any = None

    @property
    def available(self) -> bool:
        return self._notify is not None

    def _dispatch(self, callback: Callable[[], None]) -> None:
        native = self.window.native
        if native.InvokeRequired:
            system = importlib.import_module("System")
            native.Invoke(system.Action(callback))
        else:
            callback()

    def start(self) -> bool:
        if os.name != "nt" or not self.icon_path.is_file():
            return False

        def create() -> None:
            forms = importlib.import_module("System.Windows.Forms")
            drawing = importlib.import_module("System.Drawing")
            icon = drawing.Icon(str(self.icon_path))
            self._icon = icon
            menu = forms.ContextMenuStrip()
            self._menu = menu
            open_item = forms.ToolStripMenuItem("Open Rubra")
            quit_item = forms.ToolStripMenuItem("Quit Rubra")
            open_item.Click += lambda _sender, _event: self.on_open()
            quit_item.Click += lambda _sender, _event: self.on_quit()
            menu.Items.Add(open_item)
            menu.Items.Add(quit_item)
            notify = forms.NotifyIcon()
            self._notify = notify
            notify.Icon = icon
            notify.Text = "Rubra — working in the background"
            notify.ContextMenuStrip = menu
            notify.DoubleClick += lambda _sender, _event: self.on_open()
            self.window.native.Icon = icon
            notify.Visible = True

        try:
            self._dispatch(create)
            return self.available
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        def dispose() -> None:
            for name in ("_notify", "_menu", "_icon"):
                value = getattr(self, name)
                setattr(self, name, None)
                if value is not None:
                    value.Dispose()

        if not self.available and self._icon is None and self._menu is None:
            return
        native = getattr(self.window, "native", None)
        if native is not None and not native.IsDisposed:
            self._dispatch(dispose)
        else:
            dispose()
