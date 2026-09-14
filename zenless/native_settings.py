from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .native_chat import NativeChat


class NativeSettings(QDialog):
    def __init__(self, chat: NativeChat, parent: QWidget) -> None:
        super().__init__(parent)
        self.chat = chat
        self.core = chat.core
        self.setWindowTitle("Zenless · Controls")
        self.resize(500, 540)
        self.setMinimumSize(440, 400)
        self.key = f"controls:{id(self)}:"
        self.fields: dict[str, Any] = {}
        self.provider_fields: dict[str, tuple[QLabel, QComboBox, QComboBox]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        tabs = QTabWidget()
        task = QWidget()
        form = QFormLayout(task)
        for key, label, values in (
            ("effort", "Effort", ["AUTO", "MIN", "MED", "MAX"]),
            ("research", "Research", ["AUTO", "ON", "OFF"]),
            ("chatMode", "Conversation", ["PROJECT", "TEMP"]),
            ("visualMode", "Concept images", ["AUTO", "ON", "OFF"]),
            ("create3DMode", "3D generation", ["AUTO", "ON", "OFF"]),
            ("risk", "Risk", ["low", "medium", "high"]),
        ):
            field = QComboBox()
            field.addItems(values)
            field.setCurrentText(str(chat.options.get(key, "medium" if key == "risk" else values[0])))
            form.addRow(label, field)
            self.fields[key] = field
        for key, label in (("review", "Independent review"), ("autoTest", "Automatic tests"), ("autoFix", "Automatic fixes"), ("approval", "Require approval")):
            field = QCheckBox(label)
            field.setChecked(bool(chat.options.get(key, True)))
            form.addRow(field)
            self.fields[key] = field
        for key, label in (("revisions", "Revision limit"), ("fixAttempts", "Fix limit")):
            field = QSpinBox()
            field.setRange(1, 5)
            field.setValue(int(chat.options.get(key, 3)))
            form.addRow(label, field)
            self.fields[key] = field
        tabs.addTab(task, "TASK")
        providers = QWidget()
        provider_layout = QVBoxLayout(providers)
        for provider in ("chatgpt", "deepseek", "hunyuan"):
            group = QGroupBox(provider.upper())
            group_layout = QFormLayout(group)
            status = QLabel("CHECKING")
            status.setWordWrap(True)
            group_layout.addRow(status)
            model, mode = QComboBox(), QComboBox()
            group_layout.addRow("Model", model)
            group_layout.addRow("Mode", mode)
            actions = QHBoxLayout()
            login = QPushButton("LOGIN")
            login.clicked.connect(lambda checked=False, code=provider: self.request("login:" + code, lambda: self.core.login_provider(code)))
            apply = QPushButton("SELECT")
            apply.clicked.connect(lambda checked=False, code=provider: self.select_provider(code))
            actions.addWidget(login)
            actions.addWidget(apply)
            group_layout.addRow(actions)
            self.provider_fields[provider] = status, model, mode
            provider_layout.addWidget(group)
        refresh = QPushButton("REFRESH PROVIDERS")
        refresh.clicked.connect(self.refresh)
        provider_layout.addWidget(refresh)
        provider_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(providers)
        tabs.addTab(scroll, "PROVIDERS")
        layout.addWidget(tabs)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        footer.addStretch()
        save = QPushButton("APPLY")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save)
        close = QPushButton("CLOSE")
        close.clicked.connect(self.close)
        footer.addWidget(save)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.chat.signals.result.connect(self.result)
        self.finished.connect(self.disconnect_results)
        self.refresh()

    def disconnect_results(self, _: int) -> None:
        self.chat.signals.result.disconnect(self.result)

    def request(self, key: str, action: Any) -> None:
        self.status.setText("WORKING")
        self.chat.dispatch(self.key + key, action)

    def refresh(self) -> None:
        self.request("catalog", lambda: (self.core.providers(refresh=True), self.core.model_catalog(refresh=True)))

    def result(self, key: str, value: Any, error: Any) -> None:
        if not key.startswith(self.key):
            return
        if error:
            self.status.setText(str(error))
            return
        self.status.setText("UPDATED")
        if key != self.key + "catalog":
            if "login:" in key:
                self.status.setText("Complete login in the provider window, then refresh.")
            else:
                self.refresh()
            return
        providers, catalog = value
        for provider in providers:
            code = provider["providerId"]
            if code not in self.provider_fields:
                continue
            status, model, mode = self.provider_fields[code]
            status.setText(f'{provider.get("availabilityState", provider.get("authState", "UNKNOWN"))} · {", ".join(provider.get("roles", []))}')
            detail = catalog.get(code, {})
            model.clear()
            for option in detail.get("models", detail.get("versions", [])):
                if option.get("source") == "LIVE":
                    model.addItem(option["label"], option["id"])
            model.setEnabled(model.count() > 0)
            mode.clear()
            capabilities = detail.get("liveCapabilities") or {}
            if capabilities.get("supportsModeSelection"):
                for option in detail.get("modes", []):
                    mode.addItem(option["label"], option["id"])
            mode.setEnabled(mode.count() > 0)
            selection = detail.get("selection") or {}
            for field, selected in ((model, selection.get("model")), (mode, selection.get("mode"))):
                index = field.findData(selected)
                if index >= 0:
                    field.setCurrentIndex(index)

    def select_provider(self, code: str) -> None:
        _, model, mode = self.provider_fields[code]
        selection = {key: str(field.currentData()) for key, field in (("model", model), ("mode", mode)) if field.isEnabled() and field.currentData()}
        if not selection:
            self.status.setText("No verified selector is available. Choose the model on the provider site.")
            return
        self.request("select:" + code, lambda: self.core.select_provider(code, selection))

    def save(self) -> None:
        options = {}
        for key, field in self.fields.items():
            options[key] = field.isChecked() if isinstance(field, QCheckBox) else field.value() if isinstance(field, QSpinBox) else field.currentText()
        self.chat.options = options
        self.chat.update_option_controls()
        self.status.setText("Task options updated.")
