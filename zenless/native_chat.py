from __future__ import annotations

import html
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .core import ZenlessCore
from .event_bus import CoreEvent
from .native_widgets import PromptComposer, SymbolButton


class NativeSignals(QObject):
    result = Signal(str, object, object)
    core_event = Signal(object)


class NativeChat(QWidget):
    selected = Signal(str)
    details = Signal()

    def __init__(self, core: ZenlessCore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        self.job_id = ""
        self.generation = 0
        self.send_generation = 0
        self.attachments: tuple[Path, ...] = ()
        self.closed = False
        self.pending: set[str] = set()
        self.workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ZenlessNative")
        self.signals = NativeSignals(self)
        self.signals.result.connect(self.on_result)
        self.signals.core_event.connect(self.on_event)
        self.unsubscribe = core.events.subscribe(self.signals.core_event.emit)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(150)
        self.refresh_timer.timeout.connect(self.refresh)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.history = QListWidget()
        self.history.setFixedWidth(184)
        self.history.setObjectName("history")
        self.history.itemClicked.connect(self.select_item)
        outer.addWidget(self.history)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self.status = QLabel("READY")
        header.addWidget(self.status)
        header.addStretch()
        new = SymbolButton("add")
        new.setToolTip("New conversation")
        new.clicked.connect(lambda: self.select_job(""))
        header.addWidget(new)
        detail = SymbolButton("external")
        detail.setToolTip("Open approvals, task options and full evidence")
        detail.clicked.connect(self.details.emit)
        header.addWidget(detail)
        layout.addLayout(header)
        self.transcript = QTextBrowser()
        self.transcript.setOpenLinks(False)
        self.transcript.setObjectName("transcript")
        layout.addWidget(self.transcript, 1)
        self.composer = PromptComposer()
        self.composer.setPlaceholderText("Describe what you want to build or fix...")
        self.composer.setFixedHeight(72)
        self.composer.submit.connect(self.send)
        layout.addWidget(self.composer)
        controls = QHBoxLayout()
        attach = SymbolButton("attach")
        attach.setToolTip("Attach project context")
        attach.clicked.connect(self.attach)
        controls.addWidget(attach)
        self.attachment_label = QLabel("")
        controls.addWidget(self.attachment_label)
        controls.addStretch()
        self.stop = QPushButton("STOP")
        self.stop.clicked.connect(self.cancel)
        controls.addWidget(self.stop)
        self.send_button = QPushButton("SEND")
        self.send_button.setObjectName("primaryButton")
        self.send_button.clicked.connect(self.send)
        controls.addWidget(self.send_button)
        layout.addLayout(controls)
        outer.addWidget(content, 1)
        self.refresh()

    def dispatch(self, key: str, operation: Any) -> None:
        if self.closed or key in self.pending:
            return
        self.pending.add(key)
        future = self.workers.submit(operation)

        def finished(result: Future[Any]) -> None:
            try:
                value, error = result.result(), None
            except Exception as exc:
                value, error = None, str(exc)
            if not self.closed:
                self.signals.result.emit(key, value, error)

        future.add_done_callback(finished)

    def select_item(self, item: QListWidgetItem) -> None:
        self.select_job(str(item.data(Qt.ItemDataRole.UserRole)))

    def select_job(self, job_id: str) -> None:
        self.generation += 1
        self.job_id = job_id
        self.transcript.clear()
        self.status.setText("LOADING" if job_id else "READY")
        self.selected.emit(job_id)
        self.refresh()

    def refresh(self) -> None:
        self.dispatch("jobs", self.core.jobs)
        job_id, generation = self.job_id, self.generation
        if job_id:
            self.dispatch(f"timeline:{generation}", lambda: self.core.timeline(job_id))

    def on_result(self, key: str, value: Any, error: Any) -> None:
        self.pending.discard(key)
        if key.startswith("timeline:") and key != f"timeline:{self.generation}":
            return
        if error:
            self.status.setText(str(error))
            self.status.setWordWrap(True)
            if key == "send":
                self.send_button.setEnabled(True)
            return
        if key == "jobs":
            self.history.clear()
            for job in value[:100]:
                item = QListWidgetItem(str(job.get("title") or "Conversation"))
                item.setData(Qt.ItemDataRole.UserRole, job["id"])
                self.history.addItem(item)
                if job["id"] == self.job_id:
                    self.history.setCurrentItem(item)
        elif key.startswith("timeline:"):
            self.render_timeline(value)
        elif key == "send":
            self.composer.clear()
            self.attachments = ()
            self.attachment_label.clear()
            self.send_button.setEnabled(True)
            if self.generation == self.send_generation:
                self.select_job(value["jobId"])
            else:
                self.refresh()
        else:
            self.refresh()

    def render_timeline(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("jobId") != self.job_id:
            return
        rows: list[tuple[int, str]] = []
        for message in snapshot.get("messages", []):
            label = html.escape(str(message.get("role", "Zenless")).upper())
            text = html.escape(str(message.get("content", ""))).replace("\n", "<br>")
            rows.append((int(message.get("timestamp") or 0), f'<p><b>{label}</b><br>{text}</p>'))
        for activity in snapshot.get("activities", []):
            text = html.escape(f'{activity.get("phase", "")} · {activity.get("status", "")} · {activity.get("title", "")}')
            rows.append((int(activity.get("startedAt") or 0), f'<p style="color:#888">{text}</p>'))
        scrollbar = self.transcript.verticalScrollBar()
        bottom = scrollbar.value() >= scrollbar.maximum() - 12
        position = scrollbar.value()
        self.transcript.setHtml('<div style="font-family:Segoe UI;font-size:11px;color:#d8d8d8">' + "".join(row[1] for row in sorted(rows, key=lambda row: row[0])) + "</div>")
        scrollbar.setValue(scrollbar.maximum() if bottom else position)
        self.status.setText("CONVERSATION")

    def on_event(self, event: CoreEvent) -> None:
        if event.type == "JOB_UPDATED":
            self.dispatch("jobs", self.core.jobs)
        if event.data.get("jobId") != self.job_id or not self.job_id:
            return
        if event.type == "CHAT_STREAM_DELTA":
            self.status.setText("RESPONDING")
            return
        if not self.refresh_timer.isActive():
            self.refresh_timer.start()

    def attach(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Attach project context")
        if files:
            self.attachments = tuple(Path(file) for file in files[:50])
            self.attachment_label.setText(f"{len(self.attachments)} FILES")

    def send(self) -> None:
        content = self.composer.toPlainText().strip()
        if not content and not self.attachments:
            return
        if "send" in self.pending:
            return
        job_id, attachments = self.job_id, self.attachments
        self.send_generation = self.generation
        self.send_button.setEnabled(False)
        self.status.setText("CHECKING PROVIDERS")
        self.dispatch("send", lambda: self.core.send_chat(content, job_id or None, attachments))

    def cancel(self) -> None:
        if self.job_id:
            job_id = self.job_id
            self.dispatch("cancel", lambda: self.core.cancel_generation(job_id))

    def shutdown(self) -> None:
        self.closed = True
        self.refresh_timer.stop()
        self.unsubscribe()
        self.workers.shutdown(wait=False, cancel_futures=True)
