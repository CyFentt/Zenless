from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
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
        for listener in list(self._listeners):
            listener(event)
        return event

    def snapshot(self) -> list[BootstrapEvent]:
        return list(self._events.values())


class SplashScreen:
    """Immediate, event-driven splash. It never invents percentages."""

    def __init__(self, root, bus: BootstrapBus, logo_path: Path | None = None) -> None:
        import tkinter as tk

        self._tk = tk
        self.root = root
        self.bus = bus
        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.configure(bg="#09090C")
        width, height = 540, 300
        x = max(0, (self.window.winfo_screenwidth() - width) // 2)
        y = max(0, (self.window.winfo_screenheight() - height) // 2)
        self.window.geometry(f"{width}x{height}+{x}+{y}")
        self.window.attributes("-topmost", True)
        outer = tk.Frame(
            self.window,
            bg="#09090C",
            highlightthickness=1,
            highlightbackground="#8461B7",
        )
        outer.pack(fill="both", expand=True)
        header = tk.Frame(outer, bg="#09090C")
        header.pack(fill="x", padx=26, pady=(24, 10))
        self._logo = None
        if logo_path is not None and logo_path.is_file():
            try:
                image = tk.PhotoImage(file=str(logo_path))
                scale = max(1, image.width() // 56)
                self._logo = image.subsample(scale, scale)
                tk.Label(header, image=self._logo, bg="#09090C").pack(side="left", padx=(0, 14))
            except tk.TclError:
                self._logo = None
        title_box = tk.Frame(header, bg="#09090C")
        title_box.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_box,
            text="ZENLESS",
            bg="#09090C",
            fg="#F5F5F7",
            font=("Segoe UI Semibold", 22),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            title_box,
            text="BY FENTALWARE  •  SAFE BOOT",
            bg="#09090C",
            fg="#9472C9",
            font=("Consolas", 9),
            anchor="w",
        ).pack(fill="x", pady=(2, 0))
        self.stage_label = tk.Label(
            outer,
            text="Starting Core",
            bg="#09090C",
            fg="#F5F5F7",
            font=("Segoe UI", 12),
            anchor="w",
        )
        self.stage_label.pack(fill="x", padx=28, pady=(14, 4))
        self.detail_label = tk.Label(
            outer,
            text="Initializing the local runtime",
            bg="#09090C",
            fg="#9C99A5",
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.detail_label.pack(fill="x", padx=28)
        self.track = tk.Canvas(outer, height=4, bg="#16131D", highlightthickness=0)
        self.track.pack(fill="x", padx=28, pady=(24, 0))
        self.pulse = self.track.create_rectangle(0, 0, 120, 4, fill="#8F68C7", outline="")
        self._pulse_offset = 0
        self._unsubscribe = bus.subscribe(self._on_event)
        self._animate()
        self.window.update_idletasks()
        self.window.update()

    def _on_event(self, event: BootstrapEvent) -> None:
        prefix = {
            BootstrapStatus.READY: "✓",
            BootstrapStatus.WARNING: "!",
            BootstrapStatus.FAILED: "×",
            BootstrapStatus.SKIPPED: "–",
        }.get(event.status, "●")
        self.stage_label.configure(text=f"{prefix}  {event.label}")
        self.detail_label.configure(text=event.detail or event.status.value.title())
        self.window.update_idletasks()
        self.window.update()

    def _animate(self) -> None:
        try:
            width = max(1, self.track.winfo_width())
            self._pulse_offset = (self._pulse_offset + 9) % (width + 120)
            x = self._pulse_offset - 120
            self.track.coords(self.pulse, x, 0, x + 120, 4)
            self.window.after(30, self._animate)
        except self._tk.TclError:
            return

    def pump(self) -> None:
        try:
            self.window.update_idletasks()
            self.window.update()
        except self._tk.TclError:
            return

    def close(self) -> None:
        self._unsubscribe()
        try:
            self.window.destroy()
        except self._tk.TclError:
            pass
