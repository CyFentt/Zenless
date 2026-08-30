from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1
MAX_ENVELOPE_BYTES = 2 * 1024 * 1024
MESSAGE_TYPE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
PROVIDERS = {"chatgpt", "deepseek", "hunyuan", "bridge"}


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Envelope:
    id: str
    type: str
    source: str
    provider: str
    payload: dict[str, Any]
    task_id: str = ""
    reply_to: str = ""
    version: int = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "id": self.id,
            "type": self.type,
            "source": self.source,
            "provider": self.provider,
            "task_id": self.task_id,
            "reply_to": self.reply_to,
            "payload": self.payload,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


def make_envelope(
    message_type: str,
    *,
    source: str,
    provider: str = "bridge",
    payload: dict[str, Any] | None = None,
    task_id: str = "",
    reply_to: str = "",
) -> Envelope:
    return Envelope(
        id=uuid.uuid4().hex,
        type=message_type,
        source=source,
        provider=provider,
        payload=payload or {},
        task_id=task_id,
        reply_to=reply_to,
    )


def parse_envelope(raw: str | bytes) -> Envelope:
    if isinstance(raw, bytes):
        if len(raw) > MAX_ENVELOPE_BYTES:
            raise ProtocolError("Envelope exceeds the 2 MiB limit.")
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("Envelope is not UTF-8 encoded.") from exc
    elif len(raw.encode("utf-8", errors="ignore")) > MAX_ENVELOPE_BYTES:
        raise ProtocolError("Envelope exceeds the 2 MiB limit.")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError("Invalid JSON envelope.") from exc
    if not isinstance(data, dict):
        raise ProtocolError("Envelope must be a JSON object.")

    version = data.get("version")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"Unsupported protocol version: {version!r}.")
    message_id = str(data.get("id", ""))
    if not message_id or len(message_id) > 128:
        raise ProtocolError("Envelope has no valid ID.")
    message_type = str(data.get("type", ""))
    if not MESSAGE_TYPE.fullmatch(message_type):
        raise ProtocolError("Invalid envelope type.")
    source = str(data.get("source", ""))
    if source not in {"zenless", "extension", "native-host", "content"}:
        raise ProtocolError("Invalid envelope source.")
    provider = str(data.get("provider", "bridge"))
    if provider not in PROVIDERS:
        raise ProtocolError("Unknown service.")
    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        raise ProtocolError("Payload must be an object.")
    task_id = str(data.get("task_id", ""))[:128]
    reply_to = str(data.get("reply_to", ""))[:128]
    return Envelope(message_id, message_type, source, provider, payload, task_id, reply_to, version)


def extract_json_object(text: str) -> dict[str, Any]:
    candidates: list[str] = []
    for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.IGNORECASE | re.DOTALL):
        candidates.append(match.group(1))
    candidates.append(text)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    raise ProtocolError("The model did not return the expected structured JSON object.")
