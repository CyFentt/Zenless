from __future__ import annotations

import html
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
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
    controls = Signal()
    evidence = Signal(str)
    feedback = Signal(str)

    def __init__(self, core: ZenlessCore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        self.job_id = ""
        self.generation = 0
        self.send_generation = 0
        self.options: dict[str, Any] = {"effort": "AUTO", "research": "AUTO", "chatMode": "PROJECT"}
        self.snapshot: dict[str, Any] = {}
        self.stream_id = ""
        self.stream_text = ""
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
        self.stream_timer = QTimer(self)
        self.stream_timer.setSingleShot(True)
        self.stream_timer.setInterval(50)
        self.stream_timer.timeout.connect(lambda: self.render_timeline(self.snapshot))
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.history = QListWidget()
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(0)
        self.sidebar.setMaximumWidth(0)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search conversations")
        self.history_search.textChanged.connect(self.filter_history)
        sidebar_layout.addWidget(self.history_search)
        sidebar_layout.addWidget(self.history)
        self.sidebar_animation = QPropertyAnimation(self.sidebar, b"maximumWidth", self)
        self.sidebar_animation.setDuration(160)
        self.sidebar_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.history.itemClicked.connect(self.select_item)
        outer.addWidget(self.sidebar)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self.status = QLabel("READY")
        self.status.setObjectName("chatTitle")
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
        self.transcript.anchorClicked.connect(lambda url: self.evidence.emit(url.path()) if url.scheme() == "zenless" else None)
        self.approvals = QWidget()
        approval_layout = QHBoxLayout(self.approvals)
        approval_layout.setContentsMargins(0, 0, 0, 0)
        self.approval_label = QLabel()
        approval_layout.addWidget(self.approval_label, 1)
        approve = QPushButton("APPROVE")
        approve.setObjectName("primaryButton")
        approve.clicked.connect(lambda: self.approve(True))
        revise = QPushButton("REVISE")
        revise.clicked.connect(lambda: self.approve(False))
        approval_layout.addWidget(revise)
        approval_layout.addWidget(approve)
        self.approvals.hide()
        layout.addWidget(self.approvals)
        self.composer_frame = QFrame()
        self.composer_frame.setObjectName("composerFrame")
        composer_layout = QVBoxLayout(self.composer_frame)
        composer_layout.setContentsMargins(8, 6, 8, 6)
        composer_layout.setSpacing(4)
        self.composer = PromptComposer()
        self.composer.setObjectName("composer")
        self.composer.setPlaceholderText("Describe the result. Zenless investigates, builds, tests and reviews.")
        self.composer.setMaximumHeight(68)
        self.composer.setMinimumHeight(34)
        self.composer.submit.connect(self.send)
        self.composer.focus_state.connect(self.focus_composer)
        composer_layout.addWidget(self.composer)
        controls = QHBoxLayout()
        attach = SymbolButton("attach")
        attach.setToolTip("Attach project context")
        attach.clicked.connect(self.attach)
        controls.addWidget(attach)
        self.attachment_label = QLabel("")
        controls.addWidget(self.attachment_label)
        clear_files = SymbolButton("close", size=16)
        clear_files.setToolTip("Remove attachments")
        clear_files.clicked.connect(self.clear_attachments)
        controls.addWidget(clear_files)
        self.effort = QComboBox()
        self.effort.addItems(["AUTO", "MIN", "MED", "MAX"])
        self.effort.setToolTip("Reasoning effort")
        self.effort.setFixedHeight(24)
        self.effort.activated.connect(lambda _: self.options.update(effort=self.effort.currentText()))
        controls.addWidget(self.effort)
        more = SymbolButton("settings")
        more.setToolTip("Task options and provider connections")
        more.clicked.connect(self.controls.emit)
        controls.addWidget(more)
        controls.addStretch()
        self.stop = QPushButton("STOP")
        self.stop.setFixedSize(58, 24)
        self.stop.clicked.connect(self.cancel)
        controls.addWidget(self.stop)
        self.send_button = QPushButton("SEND")
        self.send_button.setObjectName("primaryButton")
        self.send_button.setFixedSize(58, 24)
        self.send_button.setProperty("soundKind", "none")
        self.send_button.clicked.connect(self.send)
        controls.addWidget(self.send_button)
        composer_layout.addLayout(controls)
        layout.addWidget(self.composer_frame)
        outer.addWidget(content, 1)
        self.refresh()

    def focus_composer(self, focused: bool) -> None:
        self.composer_frame.setProperty("focused", focused)
        self.composer_frame.style().unpolish(self.composer_frame)
        self.composer_frame.style().polish(self.composer_frame)

    def toggle_history(self) -> None:
        self.sidebar_animation.stop()
        self.sidebar_animation.setStartValue(self.sidebar.maximumWidth())
        self.sidebar_animation.setEndValue(0 if self.sidebar.maximumWidth() > 92 else 184)
        self.sidebar_animation.start()

    def filter_history(self, text: str) -> None:
        for index in range(self.history.count()):
            item = self.history.item(index)
            if item is not None:
                item.setHidden(text.casefold() not in item.text().casefold())

    def update_option_controls(self) -> None:
        self.effort.setCurrentText(str(self.options.get("effort", "AUTO")))

    def clear_attachments(self) -> None:
        self.attachments = ()
        self.attachment_label.clear()

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
        self.snapshot = {}
        self.stream_id = self.stream_text = ""
        self.approvals.hide()
        self.transcript.clear()
        self.status.setText("LOADING" if job_id else "READY")
        self.selected.emit(job_id)
        self.refresh()

    def refresh(self) -> None:
        self.dispatch("jobs", self.core.jobs)
        job_id, generation = self.job_id, self.generation
        if job_id:
            self.dispatch(f"timeline:{generation}", lambda: {**self.core.timeline(job_id), "job": self.core.job(job_id)})

    def on_result(self, key: str, value: Any, error: Any) -> None:
        self.pending.discard(key)
        if key.startswith("controls:"):
            return
        if key.startswith("timeline:") and key != f"timeline:{self.generation}":
            return
        if error:
            self.status.setText(str(error))
            self.status.setWordWrap(True)
            self.feedback.emit("error")
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
            self.filter_history(self.history_search.text())
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
            self.feedback.emit("apply")
            self.refresh()

    def render_timeline(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("jobId") != self.job_id:
            return
        self.snapshot = snapshot
        rows: list[tuple[int, str]] = []
        for message in snapshot.get("messages", []):
            label = html.escape(str(message.get("role", "Zenless")).upper())
            text = html.escape(str(message.get("content", ""))).replace("\n", "<br>")
            rows.append((int(message.get("timestamp") or 0), f'<p><b>{label}</b><br>{text}</p>'))
        for activity in snapshot.get("activities", []):
            text = html.escape(f'{activity.get("phase", "")} · {activity.get("status", "")} · {activity.get("title", "")}')
            rows.append((int(activity.get("startedAt") or 0), f'<p style="color:#888">{text}</p>'))
        for artifact in snapshot.get("artifacts", []):
            label = html.escape(f'{artifact.get("name", "Artifact")} · {artifact.get("state", "UNKNOWN")}')
            target = "visual" if artifact.get("type") in {"IMAGE", "MODEL_3D"} else "build"
            rows.append((int(artifact.get("createdAt") or 0), f'<p><a href="zenless:{target}" style="color:#ddd">{label}</a></p>'))
        scrollbar = self.transcript.verticalScrollBar()
        bottom = scrollbar.value() >= scrollbar.maximum() - 12
        position = scrollbar.value()
        stream = '<p><b>ZENLESS</b><br>' + html.escape(self.stream_text).replace("\n", "<br>") + " ▌</p>" if self.stream_id else ""
        self.transcript.setHtml('<div style="font-family:Segoe UI;font-size:11px;color:#d8d8d8">' + "".join(row[1] for row in sorted(rows, key=lambda row: row[0])) + stream + "</div>")
        scrollbar.setValue(scrollbar.maximum() if bottom else position)
        stage = str(snapshot.get("job", {}).get("stage", "CONVERSATION"))
        self.status.setText(stage.replace("_", " "))
        self.approvals.setVisible(stage in {"WAITING_CHANGE_APPROVAL", "WAITING_IMAGE_APPROVAL", "WAITING_3D_APPROVAL"})
        self.approval_label.setText(stage.replace("WAITING_", "").replace("_", " "))

    def on_event(self, event: CoreEvent) -> None:
        if event.type == "JOB_UPDATED":
            self.dispatch("jobs", self.core.jobs)
        if event.data.get("jobId") != self.job_id or not self.job_id:
            return
        if event.type == "CHAT_STREAM_STARTED":
            self.stream_id = str(event.data.get("messageId", ""))
            self.stream_text = ""
            return
        if event.type == "CHAT_STREAM_DELTA" and event.data.get("messageId") == self.stream_id:
            self.status.setText("RESPONDING")
            self.stream_text = (self.stream_text + str(event.data.get("delta", "")))[-512000:]
            if not self.stream_timer.isActive():
                self.stream_timer.start()
            return
        if event.type == "CHAT_STREAM_FINISHED" and event.data.get("messageId") == self.stream_id:
            self.stream_id = self.stream_text = ""
        if not self.refresh_timer.isActive():
            self.refresh_timer.start()

    def attach(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Attach project context")
        if files:
            if len(files) > 50:
                self.status.setText("Select at most 50 files.")
                return
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
        options = dict(self.options)
        self.feedback.emit("send")
        self.dispatch("send", lambda: self.core.send_chat(content, job_id or None, attachments, options))

    def approve(self, approved: bool) -> None:
        stage = self.snapshot.get("job", {}).get("stage")
        job_id = self.job_id
        if not job_id or "approval" in self.pending:
            return
        note = ""
        if not approved:
            note, accepted = QInputDialog.getMultiLineText(self, "Revision", "What should change?")
            if not accepted or not note.strip():
                return
        if stage == "WAITING_CHANGE_APPROVAL":
            self.dispatch("approval", lambda: self.core.approve_changes(job_id, True) if approved else self.core.edit_changes(job_id, "", note))
        elif stage == "WAITING_IMAGE_APPROVAL":
            self.dispatch("approval", lambda: self.core.approve_visual(job_id) if approved else self.core.edit_visual(job_id, note))
        elif stage == "WAITING_3D_APPROVAL":
            if not approved:
                self.evidence.emit("visual")
                return
            self.dispatch("approval", lambda: self.core.approve_model(job_id))

    def cancel(self) -> None:
        if self.job_id:
            job_id = self.job_id
            self.dispatch("cancel", lambda: self.core.cancel_generation(job_id))

    def shutdown(self) -> None:
        self.closed = True
        self.refresh_timer.stop()
        self.stream_timer.stop()
        self.unsubscribe()
        self.workers.shutdown(wait=False, cancel_futures=True)
