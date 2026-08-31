from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(frozen=True, slots=True)
class ProviderSessionMetadata:
    provider_id: str
    adapter: str = ""
    profile_path: str = ""
    last_successful_route: str = ""
    last_authenticated_at: str = ""
    last_verified_at: str = ""
    selected_model: str = ""
    selected_mode: str = ""
    capability_version: str = ""
    health_state: str = "UNKNOWN"

    def public(self) -> dict[str, str]:
        raw = asdict(self)
        return {
            "providerId": raw["provider_id"],
            "adapter": raw["adapter"],
            "lastSuccessfulRoute": raw["last_successful_route"],
            "lastAuthenticatedAt": raw["last_authenticated_at"],
            "lastVerifiedAt": raw["last_verified_at"],
            "selectedModel": raw["selected_model"],
            "selectedMode": raw["selected_mode"],
            "capabilityVersion": raw["capability_version"],
            "healthState": raw["health_state"],
        }


class ProviderSessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self._lock = threading.RLock()
        self._records = self._load()
        self._last_verified_write: dict[str, float] = {}

    def get(self, provider_id: str) -> ProviderSessionMetadata:
        with self._lock:
            raw = dict(self._records.get(provider_id, {}))
        return ProviderSessionMetadata(provider_id=provider_id, **self._known(raw))

    def all(self) -> list[dict[str, str]]:
        with self._lock:
            providers = tuple(sorted(self._records))
        return [self.get(provider).public() for provider in providers]

    def mark_ready(self, provider_id: str, route: str, profile_path: str) -> ProviderSessionMetadata:
        now = _now()
        monotonic = time.monotonic()
        current = self.get(provider_id)
        authenticated = current.last_authenticated_at or now
        should_write = (
            current.health_state != "READY"
            or current.last_successful_route != route
            or monotonic - self._last_verified_write.get(provider_id, 0.0) >= 10.0
        )
        if not should_write:
            return current
        self._last_verified_write[provider_id] = monotonic
        return self._update(
            provider_id,
            adapter=route,
            profile_path=profile_path,
            last_successful_route=route,
            last_authenticated_at=authenticated,
            last_verified_at=now,
            health_state="READY",
        )

    def mark_health(self, provider_id: str, state: str) -> ProviderSessionMetadata:
        normalized = state.strip().upper() or "UNKNOWN"
        monotonic = time.monotonic()
        current = self.get(provider_id)
        if current.health_state == normalized and monotonic - self._last_verified_write.get(provider_id, 0.0) < 10.0:
            return current
        self._last_verified_write[provider_id] = monotonic
        return self._update(provider_id, health_state=normalized, last_verified_at=_now())

    def update_selection(self, provider_id: str, *, model: str = "", mode: str = "") -> ProviderSessionMetadata:
        patch: dict[str, str] = {}
        if model:
            patch["selected_model"] = model
        if mode:
            patch["selected_mode"] = mode
        return self._update(provider_id, **patch)

    def update_capabilities(self, provider_id: str, capabilities: dict[str, Any]) -> ProviderSessionMetadata:
        canonical = json.dumps(capabilities, sort_keys=True, separators=(",", ":"), default=str)
        version = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        return self._update(provider_id, capability_version=version, last_verified_at=_now())

    def _update(self, provider_id: str, **patch: str) -> ProviderSessionMetadata:
        with self._lock:
            current = dict(self._records.get(provider_id, {}))
            changed = False
            for key, value in patch.items():
                if current.get(key) != value:
                    current[key] = value
                    changed = True
            self._records[provider_id] = current
            if changed:
                self._save()
        return ProviderSessionMetadata(provider_id=provider_id, **self._known(current))

    def _load(self) -> dict[str, dict[str, str]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError, UnicodeError, json.JSONDecodeError:
            return {}
        if not isinstance(raw, dict):
            return {}
        return {
            str(provider): {str(key): str(value) for key, value in record.items()}
            for provider, record in raw.items()
            if isinstance(record, dict)
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._records, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _known(raw: dict[str, str]) -> dict[str, str]:
        fields = ProviderSessionMetadata.__dataclass_fields__
        return {key: value for key, value in raw.items() if key in fields and key != "provider_id"}
