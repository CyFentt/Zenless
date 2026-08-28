from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CoreEvent:
    type: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "data": self.data}


EventSubscriber = Callable[[CoreEvent], None]


class EventBus:
    """Thread-safe, bounded event fan-out used by the local WebSocket bridge."""

    def __init__(self, *, history_limit: int = 500) -> None:
        self._history: deque[CoreEvent] = deque(maxlen=max(20, history_limit))
        self._subscribers: dict[int, EventSubscriber] = {}
        self._lock = threading.RLock()
        self._next_id = 1

    def publish(self, event_type: str, data: dict[str, Any] | None = None) -> CoreEvent:
        event = CoreEvent(event_type, dict(data or {}))
        with self._lock:
            self._history.append(event)
            subscribers = tuple(self._subscribers.values())
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                # A broken UI client must not stop the authoritative core.
                continue
        return event

    def subscribe(self, callback: EventSubscriber) -> Callable[[], None]:
        with self._lock:
            subscription_id = self._next_id
            self._next_id += 1
            self._subscribers[subscription_id] = callback

        def unsubscribe() -> None:
            with self._lock:
                self._subscribers.pop(subscription_id, None)

        return unsubscribe

    def recent(self, limit: int = 100) -> list[CoreEvent]:
        with self._lock:
            return list(self._history)[-max(1, min(500, int(limit))) :]
