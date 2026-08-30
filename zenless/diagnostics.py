from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sys
import threading
import traceback
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import Any, Callable

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+"),
    re.compile(r"(?i)((?:token|password|passwd|secret|cookie|webhook_url)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9._-]+", re.IGNORECASE),
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def redact(value: Any) -> str:
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(r"\1<redacted>", text)
        else:
            text = pattern.sub("<redacted-webhook>", text)
    return text


@dataclass(slots=True)
class DiagnosticEvent:
    id: str
    timestamp: str
    severity: str
    source: str
    component: str
    message: str
    error_type: str = ""
    job_id: str = ""
    request_id: str = ""
    operation_id: str = ""
    file: str = ""
    line: int = 0
    function: str = ""
    stack_trace: str = ""
    probable_cause: str = ""
    impact: str = ""
    recovery_action: str = ""
    occurrence_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Subscriber = Callable[[DiagnosticEvent], None]


class ErrorBus:
    def __init__(self, log_root: Path, *, max_recent: int = 200) -> None:
        self.log_root = log_root
        self.log_root.mkdir(parents=True, exist_ok=True)
        self._recent: deque[DiagnosticEvent] = deque(maxlen=max(20, max_recent))
        self._fingerprints: dict[str, DiagnosticEvent] = {}
        self._subscribers: list[Subscriber] = []
        self._lock = threading.RLock()
        self._logger = logging.getLogger(f"zenless.{id(self)}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        handler = RotatingFileHandler(
            self.log_root / "zenless.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(handler)
        self._installed = False
        self._previous_hooks: dict[str, Any] = {}

    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def recent(self, limit: int = 50) -> list[DiagnosticEvent]:
        with self._lock:
            return list(self._recent)[-max(1, min(200, limit)) :]

    def report(
        self,
        *,
        severity: str,
        source: str,
        component: str,
        message: str,
        exc: BaseException | None = None,
        job_id: str = "",
        request_id: str = "",
        operation_id: str = "",
        probable_cause: str = "",
        impact: str = "",
        recovery_action: str = "",
    ) -> DiagnosticEvent:
        location_file = ""
        location_line = 0
        location_function = ""
        stack_trace = ""
        error_type = type(exc).__name__ if exc is not None else ""
        if exc is not None:
            stack_trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
            if frames:
                frame = frames[-1]
                location_file = frame.filename
                location_line = int(frame.lineno or 0)
                location_function = frame.name

        safe_message = redact(message)
        safe_trace = redact(stack_trace)
        fingerprint_payload = "|".join(
            (
                source,
                component,
                error_type,
                safe_message,
                location_file,
                str(location_line),
                location_function,
            )
        )
        fingerprint = hashlib.sha256(fingerprint_payload.encode("utf-8", "replace")).hexdigest()
        with self._lock:
            existing = self._fingerprints.get(fingerprint)
            if existing is not None:
                existing.occurrence_count += 1
                existing.timestamp = _utc_now()
                event = existing
            else:
                event = DiagnosticEvent(
                    id=uuid.uuid4().hex,
                    timestamp=_utc_now(),
                    severity=severity.upper()[:16],
                    source=source[:80],
                    component=component[:120],
                    message=safe_message[:4000],
                    error_type=error_type,
                    job_id=job_id[:128],
                    request_id=request_id[:128],
                    operation_id=operation_id[:128],
                    file=location_file,
                    line=location_line,
                    function=location_function,
                    stack_trace=safe_trace[-20_000:],
                    probable_cause=redact(probable_cause)[:2000],
                    impact=redact(impact)[:2000],
                    recovery_action=redact(recovery_action)[:2000],
                )
                self._fingerprints[fingerprint] = event
                self._recent.append(event)
            subscribers = list(self._subscribers)

        self._logger.info(json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")))
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                self._logger.exception("Diagnostic subscriber failed")
        return event

    def install_global_hooks(self, root: Any | None = None) -> None:
        if self._installed:
            if root is not None:
                root.report_callback_exception = self._tk_exception
            return
        self._installed = True
        self._previous_hooks = {
            "sys": sys.excepthook,
            "threading": threading.excepthook,
            "unraisable": sys.unraisablehook,
        }
        sys.excepthook = self._sys_exception
        threading.excepthook = self._thread_exception
        sys.unraisablehook = self._unraisable_exception
        if root is not None:
            root.report_callback_exception = self._tk_exception
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.set_exception_handler(self._asyncio_exception)

    def close(self) -> None:
        if self._installed:
            sys.excepthook = self._previous_hooks.get("sys", sys.__excepthook__)
            threading.excepthook = self._previous_hooks.get("threading", threading.__excepthook__)
            sys.unraisablehook = self._previous_hooks.get("unraisable", sys.__unraisablehook__)
            self._installed = False
        handlers = list(self._logger.handlers)
        for handler in handlers:
            handler.flush()
            handler.close()
            self._logger.removeHandler(handler)

    def _sys_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        if exc_value.__traceback__ is None and exc_traceback is not None:
            exc_value = exc_value.with_traceback(exc_traceback)
        self.report(
            severity="CRITICAL",
            source="python",
            component="main-thread",
            message=str(exc_value),
            exc=exc_value,
            impact="The current operation or application may stop.",
            recovery_action="Review crash.log and zenless.log, then restart Zenless.",
        )

    def _thread_exception(self, args: threading.ExceptHookArgs) -> None:
        self.report(
            severity="ERROR",
            source="python",
            component=f"thread:{getattr(args.thread, 'name', 'unknown')}",
            message=str(args.exc_value),
            exc=args.exc_value,
            impact="A background operation stopped unexpectedly.",
            recovery_action="Retry the affected operation; restart only if it remains unavailable.",
        )

    def _unraisable_exception(self, args: sys.UnraisableHookArgs) -> None:
        self.report(
            severity="ERROR",
            source="python",
            component="unraisable",
            message=str(args.err_msg or args.exc_value),
            exc=args.exc_value,
            impact="Cleanup may be incomplete.",
        )

    def _tk_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        if exc_value.__traceback__ is None and exc_traceback is not None:
            exc_value = exc_value.with_traceback(exc_traceback)
        self.report(
            severity="ERROR",
            source="ui",
            component="tk-callback",
            message=str(exc_value),
            exc=exc_value,
            impact="The requested UI action did not finish.",
            recovery_action="Retry the control. The main process remains isolated from the callback failure.",
        )

    def _asyncio_exception(self, loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exception = context.get("exception")
        self.report(
            severity="ERROR",
            source="python",
            component="asyncio",
            message=str(context.get("message") or exception or "Async operation failed"),
            exc=exception if isinstance(exception, BaseException) else None,
        )
