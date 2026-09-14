from pathlib import Path

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from zenless.event_bus import EventBus
from zenless.qt_shell import NativeWindow


class ShellCore:
    def __init__(self):
        self.events = EventBus()

    def jobs(self):
        return []


def test_native_geometry_and_workspace_navigation():
    app = QApplication.instance() or QApplication([])
    window = NativeWindow("http://127.0.0.1:1", ShellCore(), Path(__file__).resolve().parents[1])
    try:
        window.show()
        app.processEvents()
        assert window.width() == 900
        assert window.height() == 590
        assert window.chat.composer_frame.height() >= 68
        assert window.chat.sidebar.maximumWidth() == 0
        window.open_workspace("visual")
        assert window.pages.currentIndex() == 1
        assert window.tabs.tabData(window.tabs.currentIndex()) == "visual"
        window.open_workspace("logs")
        assert window.tabs.count() == 3
        window.close_workspace("logs")
        window.close_workspace("visual")
        assert window.pages.currentIndex() == 0
        window.resize(680, 450)
        app.processEvents()
        assert window.chat.composer_frame.width() <= window.width()
        assert window.chat.send_button.isVisible()
        output = Path(__file__).resolve().parents[1] / "artifacts" / "native-shell.png"
        output.parent.mkdir(exist_ok=True)
        assert window.grab().save(str(output))
    finally:
        window.chat.shutdown()
        window.close()
        window.page.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        window.profile.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
