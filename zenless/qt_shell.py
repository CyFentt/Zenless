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
    QMenu,
    QSizeGrip,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from .core import ZenlessCore
from .native_chat import NativeChat
from .native_feedback import NativeFeedback
from .native_settings import NativeSettings
from .native_style import stylesheet
from .native_widgets import OpticalTextLabel, SymbolButton, WindowControlButton


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
        self.resize(900, 590)
        self.setMinimumSize(680, 450)
        root = QWidget()
        root.setObjectName("windowRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(TitleBar(self))
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(30)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 3, 5, 3)
        header_layout.setSpacing(4)
        history = SymbolButton("history")
        history.setToolTip("Conversation history")
        header_layout.addWidget(history)
        self.tabs = QTabBar()
        self.tabs.setObjectName("workspaceTabs")
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.addTab("THREAD")
        self.tabs.setTabData(0, "thread")
        self.tabs.setMovable(True)
        self.tabs.setUsesScrollButtons(True)
        header_layout.addWidget(self.tabs)
        add = SymbolButton("add")
        add.setToolTip("Open workspace")
        add.clicked.connect(self.workspace_menu)
        header_layout.addWidget(add)
        header_layout.addStretch()
        settings = SymbolButton("settings")
        settings.setToolTip("Task options and provider connections")
        settings.clicked.connect(self.open_settings)
        header_layout.addWidget(settings)
        layout.addWidget(header)
        self.pages = QStackedWidget()
        self.chat = NativeChat(core, self)
        history.clicked.connect(self.chat.toggle_history)
        self.chat.controls.connect(self.open_settings)
        self.chat.evidence.connect(self.open_workspace)
        self.chat.feedback.connect(self.feedback.play)
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
        resize_row = QHBoxLayout()
        resize_row.setContentsMargins(0, 0, 0, 0)
        resize_row.addStretch()
        grip = QSizeGrip(self)
        grip.setFixedSize(10, 10)
        resize_row.addWidget(grip)
        layout.addLayout(resize_row)
        self.tabs.currentChanged.connect(self.activate_workspace)
        self.tabs.currentChanged.connect(lambda _: self.feedback.play("select"))
        self.chat.details.connect(lambda: self.open_workspace("chat"))
        self.shutdown_requested.connect(self.close)
        self.view.load(QUrl(url))
        self.setStyleSheet(stylesheet())

    def open_settings(self) -> None:
        dialog = NativeSettings(self.chat, self)
        dialog.exec()
        dialog.deleteLater()

    def workspace_menu(self) -> None:
        menu = QMenu(self)
        for key, title in (("chat", "Approvals"), ("build", "Changes & context"), ("visual", "Visual & 3D"), ("studio", "Studio"), ("test", "Tests"), ("logs", "Logs")):
            action = menu.addAction(title)
            action.triggered.connect(lambda checked=False, target=key: self.open_workspace(target))
        menu.exec(self.cursor().pos())

    def open_workspace(self, key: str) -> None:
        if key not in {"chat", "build", "visual", "studio", "test", "logs"}:
            return
        for index in range(self.tabs.count()):
            if self.tabs.tabData(index) == key:
                self.tabs.setCurrentIndex(index)
                self.activate_workspace(index)
                return
        index = self.tabs.addTab("APPROVALS" if key == "chat" else key.upper())
        self.tabs.setTabData(index, key)
        close = SymbolButton("close", size=16)
        close.setObjectName("tabCloseButton")
        close.setToolTip("Close workspace")
        close.clicked.connect(lambda checked=False, target=key: self.close_workspace(target))
        self.tabs.setTabButton(index, QTabBar.ButtonPosition.RightSide, close)
        self.tabs.setCurrentIndex(index)

    def close_workspace(self, key: str) -> None:
        for index in range(self.tabs.count()):
            if self.tabs.tabData(index) == key:
                self.tabs.removeTab(index)
                break

    def activate_workspace(self, index: int) -> None:
        key = str(self.tabs.tabData(index) or "thread")
        self.pages.setCurrentIndex(0 if key == "thread" else 1)
        if key != "thread":
            self.page.runJavaScript("window.dispatchEvent(new CustomEvent('zenless-native-workspace', {detail: " + json.dumps(key) + "}));")

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
