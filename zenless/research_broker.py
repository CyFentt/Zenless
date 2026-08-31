from __future__ import annotations

import ipaddress
import json
import socket
import time
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Any, Callable, Protocol
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ResearchError(RuntimeError):
    pass


class ResearchTransport(Protocol):
    def send_prompt(self, provider: str, prompt: str, *, task_id: str, timeout: float = 360.0) -> str: ...


@dataclass(frozen=True, slots=True)
class ResearchEvidence:
    source: str
    captured_at: str
    evidence_type: str
    supports: str
    content: str

    def public(self) -> dict[str, str]:
        return asdict(self)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


class _SafeRedirectHandler(HTTPRedirectHandler):
    def __init__(self, validator: Callable[[str], None]) -> None:
        self.validator = validator

    def redirect_request(
        self,
        request: Request,
        fp: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Request | None:
        self.validator(new_url)
        return super().redirect_request(request, fp, code, message, headers, new_url)


class ResearchBroker:
    MAX_RESPONSE_BYTES = 2 * 1024 * 1024
    OFFICIAL_DOMAINS = (
        "create.roblox.com",
        "roblox.com",
        "luau.org",
        "openai.com",
        "deepseek.com",
        "tencent.com",
        "github.com",
        "githubusercontent.com",
        "microsoft.com",
    )

    def __init__(self, transport: ResearchTransport | None = None) -> None:
        self.transport = transport

    def routes(self, capabilities: dict[str, Any], studio_tools: tuple[str, ...] = ()) -> list[str]:
        routes = ["DIRECT_OFFICIAL_FETCH"]
        if bool(capabilities.get("supportsSearch") or capabilities.get("search")):
            routes.append("PROVIDER_SEARCH")
        if self._documentation_tool(studio_tools):
            routes.append("STUDIO_DOCUMENTATION")
        return routes

    def fetch_official(self, url: str, supports: str, *, timeout: float = 20.0) -> ResearchEvidence:
        self._validate_url(url)
        opener = build_opener(_SafeRedirectHandler(self._validate_url))
        request = Request(url, headers={"User-Agent": "Zenless/2.1", "Accept": "text/html,text/plain,application/json"})
        with opener.open(request, timeout=max(1.0, min(timeout, 30.0))) as response:
            final_url = str(response.geturl())
            self._validate_url(final_url)
            content_type = str(response.headers.get_content_type()).casefold()
            if content_type not in {"text/html", "text/plain", "application/json", "application/ld+json"}:
                raise ResearchError("The official source returned an unsupported content type.")
            declared = int(response.headers.get("Content-Length") or 0)
            if declared > self.MAX_RESPONSE_BYTES:
                raise ResearchError("The official source exceeded the research response limit.")
            raw = response.read(self.MAX_RESPONSE_BYTES + 1)
        if len(raw) > self.MAX_RESPONSE_BYTES:
            raise ResearchError("The official source exceeded the research response limit.")
        charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, "replace")
        if content_type == "text/html":
            parser = _TextExtractor()
            parser.feed(text)
            text = "\n".join(parser.parts)
        elif content_type in {"application/json", "application/ld+json"}:
            try:
                text = json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))
            except json.JSONDecodeError as exc:
                raise ResearchError("The official source returned invalid JSON.") from exc
        return ResearchEvidence(final_url, self._now(), "OFFICIAL_DIRECT_FETCH", supports, text[:120_000])

    def provider_search(
        self,
        provider: str,
        query: str,
        supports: str,
        capabilities: dict[str, Any],
        *,
        task_id: str,
        timeout: float = 180.0,
    ) -> ResearchEvidence:
        if self.transport is None:
            raise ResearchError("No provider transport is available.")
        if not bool(capabilities.get("supportsSearch") or capabilities.get("search")):
            raise ResearchError("The selected provider mode does not expose web search.")
        prompt = (
            "Research the request using the web-search capability currently exposed by this mode. "
            "Prefer official current sources, include source URLs and publication or access dates, distinguish facts from "
            "inference, and do not claim access to unavailable tools.\n\n"
            f"QUESTION:\n{query}\n\nDECISION SUPPORTED:\n{supports}"
        )
        content = self.transport.send_prompt(provider, prompt, task_id=task_id, timeout=timeout)
        return ResearchEvidence(provider, self._now(), "PROVIDER_BUILTIN_SEARCH", supports, content[:120_000])

    def studio_documentation(
        self,
        query: str,
        supports: str,
        studio_tools: tuple[str, ...],
        call_tool: Callable[[str, dict[str, Any]], Any],
    ) -> ResearchEvidence:
        tool = self._documentation_tool(studio_tools)
        if not tool:
            raise ResearchError("Studio did not advertise a documentation lookup capability.")
        result = call_tool(tool, {"query": query})
        return ResearchEvidence(f"studio:{tool}", self._now(), "STUDIO_DOCUMENTATION", supports, str(result)[:120_000])

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
            raise ResearchError("Research URLs must be public HTTPS sources without credentials.")
        if not any(hostname == domain or hostname.endswith("." + domain) for domain in self.OFFICIAL_DOMAINS):
            raise ResearchError("The source is outside the official research allowlist.")
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise ResearchError("The official research source could not be resolved.") from exc
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ResearchError("The research source did not resolve to a public address.")

    @staticmethod
    def _documentation_tool(tools: tuple[str, ...]) -> str:
        return next(
            (
                tool
                for tool in tools
                if "doc" in tool.casefold()
                and any(marker in tool.casefold() for marker in ("search", "lookup", "read"))
            ),
            "",
        )

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
