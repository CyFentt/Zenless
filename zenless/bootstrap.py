from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable


class BootstrapStatus(StrEnum):
    WAITING = "WAITING"
    RUNNING = "RUNNING"
    READY = "READY"
    WARNING = "WARNING"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(slots=True)
class BootstrapEvent:
    stage_id: str
    label: str
    status: BootstrapStatus
    detail: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0


BootstrapListener = Callable[[BootstrapEvent], None]


class BootstrapBus:
    def __init__(self) -> None:
        self._events: dict[str, BootstrapEvent] = {}
        self._listeners: list[BootstrapListener] = []

    def subscribe(self, callback: BootstrapListener) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return unsubscribe

    def emit(
        self,
        stage_id: str,
        label: str,
        status: BootstrapStatus,
        detail: str = "",
    ) -> BootstrapEvent:
        previous = self._events.get(stage_id)
        started_at = previous.started_at if previous else 0.0
        if status == BootstrapStatus.RUNNING and not started_at:
            started_at = time.time()
        finished_at = 0.0
        if status in {
            BootstrapStatus.READY,
            BootstrapStatus.WARNING,
            BootstrapStatus.FAILED,
            BootstrapStatus.SKIPPED,
        }:
            started_at = started_at or time.time()
            finished_at = time.time()
        event = BootstrapEvent(stage_id, label, status, detail, started_at, finished_at)
        self._events[stage_id] = event
        for listener in tuple(self._listeners):
            listener(event)
        return event

    def snapshot(self) -> list[BootstrapEvent]:
        return list(self._events.values())


class NativeSplash:
    _WM_REDRAW = 0x8001
    _WM_CLOSE_SPLASH = 0x8002

    def __init__(self) -> None:
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._stage = "CORE · starting"
        self._hwnd = 0
        self._thread: threading.Thread | None = None
        self._wndproc: object | None = None

    def show(self) -> None:
        if sys.platform != "win32" or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="Zenless-NativeSplash", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)

    def update(self, stage: str, detail: str = "") -> None:
        text = stage.strip().upper()
        if detail.strip():
            text += " · " + detail.strip()
        with self._lock:
            self._stage = text[:180]
            hwnd = self._hwnd
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, self._WM_REDRAW, 0, 0)

    def close(self) -> None:
        with self._lock:
            hwnd = self._hwnd
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, self._WM_CLOSE_SPLASH, 0, 0)
        self._closed.wait(2.0)

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        kernel32 = ctypes.windll.kernel32
        lresult = ctypes.c_ssize_t
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = lresult
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        user32.LoadCursorW.restype = wintypes.HANDLE
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.UpdateWindow.argtypes = [wintypes.HWND]
        user32.UpdateWindow.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = lresult
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
        gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
        gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
        gdi32.SetBkMode.restype = ctypes.c_int
        gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
        gdi32.SetTextColor.restype = wintypes.DWORD
        wndproc_type = ctypes.WINFUNCTYPE(
            lresult,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", wndproc_type),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class PAINTSTRUCT(ctypes.Structure):
            _fields_ = [
                ("hdc", wintypes.HDC),
                ("fErase", wintypes.BOOL),
                ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL),
                ("fIncUpdate", wintypes.BOOL),
                ("rgbReserved", ctypes.c_byte * 32),
            ]

        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.UnregisterClassW.restype = wintypes.BOOL
        user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
        user32.BeginPaint.restype = wintypes.HDC
        user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
        user32.EndPaint.restype = wintypes.BOOL
        user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetClientRect.restype = wintypes.BOOL
        user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
        user32.FillRect.restype = ctypes.c_int
        user32.DrawTextW.argtypes = [
            wintypes.HDC,
            wintypes.LPCWSTR,
            ctypes.c_int,
            ctypes.POINTER(wintypes.RECT),
            wintypes.UINT,
        ]
        user32.DrawTextW.restype = ctypes.c_int
        user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT), wintypes.BOOL]
        user32.InvalidateRect.restype = wintypes.BOOL

        background = gdi32.CreateSolidBrush(0x000C0909)
        accent = gdi32.CreateSolidBrush(0x00B76184)

        def draw(hwnd: int) -> None:
            paint = PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(paint))
            rect = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            user32.FillRect(hdc, ctypes.byref(rect), background)
            accent_rect = wintypes.RECT(0, 0, rect.right, 5)
            user32.FillRect(hdc, ctypes.byref(accent_rect), accent)
            gdi32.SetBkMode(hdc, 1)
            gdi32.SetTextColor(hdc, 0x00F7F5F5)
            title_rect = wintypes.RECT(34, 70, rect.right - 34, 150)
            user32.DrawTextW(hdc, "ZENLESS", -1, ctypes.byref(title_rect), 0x00000001 | 0x00000020)
            gdi32.SetTextColor(hdc, 0x00C97294)
            with self._lock:
                stage = self._stage
            stage_rect = wintypes.RECT(34, 175, rect.right - 34, 235)
            user32.DrawTextW(hdc, stage, -1, ctypes.byref(stage_rect), 0x00000001 | 0x00000020)
            user32.EndPaint(hwnd, ctypes.byref(paint))

        @wndproc_type
        def wndproc(hwnd: int, message: int, wparam: int, lparam: int) -> int:
            if message == 0x000F:
                draw(hwnd)
                return 0
            if message == self._WM_REDRAW:
                user32.InvalidateRect(hwnd, None, True)
                return 0
            if message in {self._WM_CLOSE_SPLASH, 0x0010}:
                user32.DestroyWindow(hwnd)
                return 0
            if message == 0x0002:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        self._wndproc = wndproc
        instance = kernel32.GetModuleHandleW(None)
        class_name = f"ZenlessSplash{id(self):x}"
        arrow_cursor = ctypes.cast(ctypes.c_void_p(32512), wintypes.LPCWSTR)
        window_class = WNDCLASSW(
            0,
            wndproc,
            0,
            0,
            instance,
            0,
            user32.LoadCursorW(None, arrow_cursor),
            background,
            None,
            class_name,
        )
        atom = user32.RegisterClassW(ctypes.byref(window_class))
        if not atom:
            self._ready.set()
            self._closed.set()
            return
        width, height = 560, 300
        x = max(0, (user32.GetSystemMetrics(0) - width) // 2)
        y = max(0, (user32.GetSystemMetrics(1) - height) // 2)
        hwnd = user32.CreateWindowExW(
            0x00000008,
            class_name,
            "Zenless",
            0x80000000 | 0x10000000,
            x,
            y,
            width,
            height,
            None,
            None,
            instance,
            None,
        )
        with self._lock:
            self._hwnd = int(hwnd or 0)
        self._ready.set()
        if hwnd:
            user32.ShowWindow(hwnd, 5)
            user32.UpdateWindow(hwnd)
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        with self._lock:
            self._hwnd = 0
        gdi32.DeleteObject(background)
        gdi32.DeleteObject(accent)
        user32.UnregisterClassW(class_name, instance)
        self._closed.set()
