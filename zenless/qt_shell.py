from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from .core import ZenlessCore
from .native_chat import NativeChat
from .native_feedback import NativeFeedback
from .native_widgets import OpticalTextLabel, WindowControlButton


class LocalPage(QWebEnginePage):
    def __init__(self, profile: QWebEngineProfile, origin: QUrl, parent: QWidget) -> None:
        super().__init__(profile, parent)
        self.origin = origin
        self.setBackgroundColor(QColor("#050505"))

    def acceptNavigationRequest(self, url: QUrl, navigation_type: QWebEnginePage.NavigationType, main: bool) -> bool:
        return url.scheme() == self.origin.scheme() and url.host() == self.origin.host() and url.port() == self.origin.port()


class TitleBar(QFrame):
    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self.owner = window
        self.setObjectName("titleBar")
        self.setFixedHeight(28)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 3, 0)
        layout.setSpacing(2)
        brand = OpticalTextLabel("ZENLESS")
        brand.setObjectName("brand")
        brand.setFixedHeight(18)
        brand.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(brand)
        layout.addStretch()
        for kind, description, action in (
            ("minimize", "Minimize", window.showMinimized),
            ("maximize", "Maximize or restore", self.toggle_maximized),
            ("close", "Close", window.close),
        ):
            button = WindowControlButton(kind)
            button.setToolTip(description)
            button.setAccessibleName(description)
            button.clicked.connect(action)
            layout.addWidget(button)

    def toggle_maximized(self) -> None:
        if self.owner.isMaximized():
            self.owner.showNormal()
        else:
            self.owner.showMaximized()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        handle = self.owner.windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None:
            handle.startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
        super().mouseDoubleClickEvent(event)


class NativeWindow(QMainWindow):
    shutdown_requested = Signal()

    def __init__(self, url: str, core: ZenlessCore, resource_root: Path) -> None:
        super().__init__()
        self.setWindowTitle("Zenless")
        self.feedback = NativeFeedback(self, resource_root / "frontend" / "dist" / "sounds")
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self.feedback)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.resize(1000, 680)
        self.setMinimumSize(680, 450)
        root = QWidget()
        root.setObjectName("windowRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(TitleBar(self))
        self.tabs = QTabBar()
        self.tabs.setObjectName("workspaceTabs")
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.addTab("THREAD")
        self.tabs.addTab("WORKSPACE")
        layout.addWidget(self.tabs)
        self.pages = QStackedWidget()
        self.chat = NativeChat(core, self)
        self.pages.addWidget(self.chat)
        self.profile = QWebEngineProfile(self)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setHttpCacheMaximumSize(16 * 1024 * 1024)
        self.view = QWebEngineView(self)
        self.page = LocalPage(self.profile, QUrl(url), self.view)
        self.view.setPage(self.page)
        self.chat.selected.connect(self.select_job)
        self.view.loadFinished.connect(lambda success: self.select_job(self.chat.job_id) if success else None)
        self.pages.addWidget(self.view)
        layout.addWidget(self.pages)
        self.tabs.currentChanged.connect(self.pages.setCurrentIndex)
        self.tabs.currentChanged.connect(lambda _: self.feedback.play("select"))
        self.chat.composer.submit.connect(lambda: self.feedback.play("send"))
        self.chat.details.connect(lambda: self.tabs.setCurrentIndex(1))
        self.shutdown_requested.connect(self.close)
        self.setStyleSheet("""
            QWidget { background: #050505; color: #d8d8d8; font-family: 'Segoe UI'; font-size: 10px; }
            #windowRoot { border: 1px solid #202020; }
            #titleBar { background: #030303; border-bottom: 1px solid #181818; }
            #brand { font-family: Consolas; font-size: 9px; font-weight: 800; color: #b8b8b8; }
            QToolButton { border: none; background: transparent; padding: 0; }
            QToolButton:hover { background: #121212; color: #ffffff; }
            QToolButton:pressed { background: #d8d8d8; color: #050505; }
            QTabBar::tab { background: #070707; color: #737373; border: 1px solid #202020; border-bottom: none; min-width: 74px; height: 22px; padding: 0 8px; margin-right: 2px; font-family: Consolas; font-size: 9px; font-weight: 700; }
            QTabBar::tab:selected { color: #f0f0f0; background: #0b0b0b; border-color: #505050; border-top-color: #d8d8d8; }
            QPlainTextEdit, QTextBrowser, QListWidget { background: #070707; color: #e0e0e0; border: 1px solid #252525; padding: 3px; selection-background-color: #303030; }
            #transcript { background: transparent; border: none; }
            #history { background: #060606; border: none; border-right: 1px solid #1a1a1a; }
            QListWidget::item { padding: 4px 5px; color: #a0a0a0; }
            QListWidget::item:selected { background: #121212; color: #ffffff; border-left: 2px solid #d8d8d8; }
            QPushButton { background: #080808; color: #c2c2c2; border: 1px solid #292929; padding: 2px 6px; }
            QPushButton:hover { background: #101010; border-color: #505050; }
            QPushButton:pressed, #primaryButton { background: #dedede; color: #050505; border-color: #ededed; }
        """)
        self.view.load(QUrl(url))

    def select_job(self, job_id: str) -> None:
        self.page.runJavaScript("window.dispatchEvent(new CustomEvent('zenless-native-selection', {detail: " + json.dumps(job_id) + "}));")


def run_native_shell(
    url: str,
    core: ZenlessCore,
    resource_root: Path,
    ready: Callable[[], None],
    register_shutdown: Callable[[Callable[[], None]], None],
    smoke_test: bool = False,
) -> int:
    app = QApplication.instance() or QApplication([])
    window = NativeWindow(url, core, resource_root)
    register_shutdown(window.shutdown_requested.emit)

    def loaded(success: bool) -> None:
        if success:
            ready()
            if smoke_test:
                QTimer.singleShot(6000, window.close)

    window.view.loadFinished.connect(loaded)
    window.show()
    result = app.exec()
    window.chat.shutdown()
    window.view.setPage(QWebEnginePage(window.view))
    window.page.deleteLater()
    app.processEvents()
    window.profile.deleteLater()
    app.processEvents()
    return result
