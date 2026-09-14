from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractButton, QWidget


class NativeFeedback(QObject):
    def __init__(self, window: QWidget, root: Path) -> None:
        super().__init__(window)
        self.owner = window
        self.root = root
        self.enabled = True

    def play(self, kind: str) -> None:
        if not self.enabled or not self.owner.isVisible() or self.owner.isMinimized() or sys.platform != "win32":
            return
        if kind not in {"click", "select", "send", "back", "apply", "error"}:
            return
        path = self.root / f"{kind}.wav"
        if path.is_file():
            import winsound

            try:
                winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            except RuntimeError:
                self.enabled = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QAbstractButton) and event.type() == QEvent.Type.MouseButtonPress:
            if watched.isEnabled() and watched.window() == self.owner:
                self.play(str(watched.property("soundKind") or "click"))
        return super().eventFilter(watched, event)
