from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class DiscordStatus:
    configured: bool
    state: str
    detail: str


class DiscordIntegration:
    """Optional webhook notifications. Zenless never bundles a token or self-bots."""

    def __init__(
        self,
        webhook_url: str = "",
        *,
        error_callback: Callable[[BaseException], None] | None = None,
    ) -> None:
        self._webhook_url = webhook_url.strip()
        self._error_callback = error_callback

    @property
    def enabled(self) -> bool:
        return self._webhook_url.startswith("https://discord.com/api/webhooks/") or self._webhook_url.startswith(
            "https://discordapp.com/api/webhooks/"
        )

    def status(self) -> DiscordStatus:
        if not self.enabled:
            return DiscordStatus(False, "Not Configured", "Optional; Zenless works normally without Discord.")
        return DiscordStatus(True, "Ready", "Webhook notifications enabled.")

    def notify_async(self, title: str, message: str) -> bool:
        if not self.enabled:
            return False
        worker = threading.Thread(
            target=self._send,
            args=(title[:120], message[:1600]),
            name="Zenless-DiscordWebhook",
            daemon=True,
        )
        worker.start()
        return True

    def _send(self, title: str, message: str) -> None:
        payload = json.dumps({"content": f"**{title}**\n{message}"}, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._webhook_url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Zenless/1.0"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=8) as response:
                response.read(256)
        except (OSError, URLError) as exc:
            if self._error_callback is not None:
                self._error_callback(exc)

