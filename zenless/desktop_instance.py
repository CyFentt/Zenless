from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
from typing import Any


class DesktopInstance:
    def __init__(self, data_root: Path) -> None:
        self.name = "Local\\Rubra." + hashlib.sha256(str(data_root.resolve()).casefold().encode()).hexdigest()[:24]
        self.handle: Any = None
        self.kernel: Any = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        from ctypes import wintypes

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        ctypes.set_last_error(0)
        self.handle = self.kernel.CreateMutexW(None, False, self.name)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "Rubra could not acquire its desktop instance lock.")
        if ctypes.get_last_error() == 183:
            user = ctypes.WinDLL("user32")
            user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user.FindWindowW.restype = wintypes.HWND
            user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user.SetForegroundWindow.argtypes = [wintypes.HWND]
            window = user.FindWindowW(None, "Rubra")
            if window:
                user.ShowWindow(window, 9)
                user.SetForegroundWindow(window)
            self.close()
            return False
        return True

    def close(self) -> None:
        if self.handle is not None and self.kernel is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
