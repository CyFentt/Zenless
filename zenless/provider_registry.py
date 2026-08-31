from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse


class AuthState(StrEnum):
    UNKNOWN = "UNKNOWN"
    CHECKING = "CHECKING"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    LOGIN_WINDOW_OPEN = "LOGIN_WINDOW_OPEN"
    AUTHENTICATING = "AUTHENTICATING"
    CHALLENGE = "CHALLENGE"
    AUTHENTICATED = "AUTHENTICATED"
    VERIFYING_PERSISTENCE = "VERIFYING_PERSISTENCE"
    READY = "READY"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"


class ProviderSupport(StrEnum):
    VERIFIED = "VERIFIED"
    BETA = "BETA"
    EXPERIMENTAL = "EXPERIMENTAL"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    code: str
    url: str
    inputs: tuple[str, ...]
    sends: tuple[str, ...]
    stops: tuple[str, ...]
    responses: tuple[str, ...]
    authenticated_markers: tuple[str, ...] = ()
    unauthenticated_markers: tuple[str, ...] = ()
    challenge_markers: tuple[str, ...] = ()
    login_url_patterns: tuple[str, ...] = ()
    authenticated_url_patterns: tuple[str, ...] = ()
    composer_markers: tuple[str, ...] = ()
    account_markers: tuple[str, ...] = ()
    generation_markers: tuple[str, ...] = ()
    model_markers: tuple[str, ...] = ("[data-model]", "[role='option']", "[role='menuitem']")
    mode_markers: tuple[str, ...] = ("[role='tab']", "[aria-pressed='true']", "[aria-selected='true']")

    @property
    def auth_composers(self) -> tuple[str, ...]:
        return self.composer_markers or self.inputs


@dataclass(frozen=True, slots=True)
class AuthSignals:
    url: str
    authenticated: bool = False
    unauthenticated: bool = False
    challenge: bool = False
    composer: bool = False
    account: bool = False
    generation: bool = False
    send: bool = False


@dataclass(frozen=True, slots=True)
class ModeCapabilities:
    supports_text: bool = True
    supports_reasoning: bool = False
    reasoning_levels: tuple[str, ...] = ()
    supports_search: bool = False
    supports_files: bool = False
    accepted_mime_types: tuple[str, ...] = ()
    accepted_extensions: tuple[str, ...] = ()
    max_files: int = 0
    max_bytes_per_file: int = 0
    supports_images: bool = False
    supports_vision: bool = False
    supports_audio: bool = False
    supports_archives: bool = False
    supports_code_execution: bool = False
    supports_tools: bool = False
    supports_image_generation: bool = False
    supports_3d_generation: bool = False
    supports_geometry: bool = False
    supports_texture: bool = False
    supports_download: bool = False
    supports_cancel: bool = False
    supports_streaming: bool = True

    def public(self) -> dict[str, Any]:
        values = asdict(self)
        return {
            "supportsText": values["supports_text"],
            "supportsReasoning": values["supports_reasoning"],
            "reasoningLevels": list(values["reasoning_levels"]),
            "supportsSearch": values["supports_search"],
            "supportsFiles": values["supports_files"],
            "acceptedMimeTypes": list(values["accepted_mime_types"]),
            "acceptedExtensions": list(values["accepted_extensions"]),
            "maxFiles": values["max_files"],
            "maxBytesPerFile": values["max_bytes_per_file"],
            "supportsImages": values["supports_images"],
            "supportsVision": values["supports_vision"],
            "supportsAudio": values["supports_audio"],
            "supportsArchives": values["supports_archives"],
            "supportsCodeExecution": values["supports_code_execution"],
            "supportsTools": values["supports_tools"],
            "supportsImageGeneration": values["supports_image_generation"],
            "supports3DGeneration": values["supports_3d_generation"],
            "supportsGeometry": values["supports_geometry"],
            "supportsTexture": values["supports_texture"],
            "supportsDownload": values["supports_download"],
            "supportsCancel": values["supports_cancel"],
            "supportsStreaming": values["supports_streaming"],
        }


@dataclass(frozen=True, slots=True)
class ProviderMode:
    id: str
    label: str
    capabilities: ModeCapabilities
    source: str = "COMPATIBILITY_HINT"

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "source": self.source,
            "capabilities": self.capabilities.public(),
        }


@dataclass(frozen=True, slots=True)
class ProviderManifest:
    id: str
    display_name: str
    web_url: str
    support: ProviderSupport
    adapter: str
    roles: tuple[str, ...] = ()
    modes: tuple[ProviderMode, ...] = ()
    enabled: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "providerId": self.id,
            "displayName": self.display_name,
            "webUrl": self.web_url,
            "support": self.support.value,
            "adapter": self.adapter,
            "roles": list(self.roles),
            "modes": [mode.public() for mode in self.modes],
            "enabled": self.enabled,
        }


class ProviderRegistry:
    def __init__(self, manifests: tuple[ProviderManifest, ...] = ()) -> None:
        self._manifests = {manifest.id: manifest for manifest in manifests}

    def register(self, manifest: ProviderManifest) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", manifest.id):
            raise ValueError("Provider identifier is invalid.")
        parsed = urlparse(manifest.web_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Provider URL must use HTTPS.")
        self._manifests[manifest.id] = manifest

    def register_custom(self, provider_id: str, display_name: str, web_url: str) -> ProviderManifest:
        manifest = ProviderManifest(
            id=provider_id,
            display_name=display_name.strip() or provider_id,
            web_url=web_url,
            support=ProviderSupport.UNSUPPORTED,
            adapter="custom",
        )
        self.register(manifest)
        return manifest

    def get(self, provider_id: str) -> ProviderManifest:
        try:
            return self._manifests[provider_id]
        except KeyError as exc:
            raise KeyError(f"Unknown provider: {provider_id}") from exc

    def catalog(self) -> list[dict[str, Any]]:
        return [self._manifests[key].public() for key in sorted(self._manifests)]


def evaluate_auth(spec: ProviderSpec, signals: AuthSignals) -> AuthState:
    normalized_url = signals.url.casefold()
    if signals.challenge:
        return AuthState.CHALLENGE
    if signals.unauthenticated or any(pattern.casefold() in normalized_url for pattern in spec.login_url_patterns):
        return AuthState.LOGIN_REQUIRED
    if signals.authenticated:
        return AuthState.AUTHENTICATED
    if signals.account and (signals.composer or signals.generation):
        return AuthState.AUTHENTICATED
    if signals.composer and signals.send and not spec.login_url_patterns:
        return AuthState.AUTHENTICATED
    return AuthState.UNKNOWN


def normalize_capabilities(raw: dict[str, Any], *, source: str = "LIVE") -> dict[str, Any]:
    def strings(value: Any) -> list[str]:
        if not isinstance(value, (list, tuple, set)):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def integer(value: Any, default: int = 0) -> int:
        try:
            return max(0, int(value))
        except TypeError, ValueError, OverflowError:
            return default

    file_types = strings(raw.get("file_types", raw.get("acceptedMimeTypes", [])))
    mime_types = list(
        dict.fromkeys(
            [*strings(raw.get("acceptedMimeTypes", [])), *(item for item in file_types if not item.startswith("."))]
        )
    )
    extensions = list(
        dict.fromkeys(
            [*strings(raw.get("acceptedExtensions", [])), *(item for item in file_types if item.startswith("."))]
        )
    )
    advertised_max_files = integer(raw.get("max_image_inputs", raw.get("maxFiles", 0)))
    supports_files = bool(raw.get("upload_files", raw.get("supportsFiles", False)) or advertised_max_files > 0)
    max_files = min(1_000, advertised_max_files) if supports_files else 0
    supports_cancel = bool(raw.get("cancel", raw.get("supportsCancel", False)))
    supports_geometry = bool(raw.get("geometry", raw.get("supportsGeometry", False)))
    supports_texture = bool(raw.get("texture", raw.get("supportsTexture", False)))
    supports_download = bool(raw.get("download_artifact", raw.get("supportsDownload", False)))
    supports_text = bool(raw.get("send_text", raw.get("supportsText", False)))
    supports_models = bool(raw.get("select_model", raw.get("get_models", False)))
    supports_modes = bool(raw.get("select_mode", False))
    capabilities = ModeCapabilities(
        supports_text=supports_text,
        supports_reasoning=bool(raw.get("supportsReasoning", raw.get("reasoning", False))),
        reasoning_levels=tuple(strings(raw.get("reasoningLevels", []))),
        supports_search=bool(raw.get("supportsSearch", raw.get("search", False))),
        supports_files=supports_files,
        accepted_mime_types=tuple(mime_types),
        accepted_extensions=tuple(extensions),
        max_files=max_files,
        max_bytes_per_file=min(
            2 * 1024 * 1024 * 1024,
            integer(raw.get("maxBytesPerFile"), 128 * 1024 * 1024 if supports_files else 0),
        ),
        supports_images=bool(raw.get("supportsImages", any(item.startswith("image/") for item in mime_types))),
        supports_vision=bool(raw.get("supportsVision", any(item.startswith("image/") for item in mime_types))),
        supports_audio=bool(raw.get("supportsAudio", any(item.startswith("audio/") for item in mime_types))),
        supports_archives=bool(raw.get("supportsArchives", any("zip" in item for item in mime_types + extensions))),
        supports_code_execution=bool(raw.get("supportsCodeExecution", False)),
        supports_tools=bool(raw.get("supportsTools", False)),
        supports_image_generation=bool(raw.get("supportsImageGeneration", raw.get("image_generation", False))),
        supports_3d_generation=bool(raw.get("supports3DGeneration", supports_geometry or supports_texture)),
        supports_geometry=supports_geometry,
        supports_texture=supports_texture,
        supports_download=supports_download,
        supports_cancel=supports_cancel,
        supports_streaming=bool(raw.get("supportsStreaming", raw.get("responses", False))),
    ).public()
    return {
        **raw,
        "send_text": supports_text,
        "upload_files": supports_files,
        "file_types": file_types,
        "max_image_inputs": max_files,
        "cancel": supports_cancel,
        "select_model": supports_models,
        "get_models": supports_models,
        "select_mode": supports_modes,
        "geometry": supports_geometry,
        "texture": supports_texture,
        "download_artifact": supports_download,
        "source": source,
        **capabilities,
    }


TEXT = ModeCapabilities(supports_text=True, supports_cancel=True, supports_streaming=True)
TEXT_REASONING = ModeCapabilities(
    supports_text=True,
    supports_reasoning=True,
    reasoning_levels=("AUTO", "MINIMUM", "MEDIUM", "MAXIMUM"),
    supports_cancel=True,
    supports_streaming=True,
)
INSTANT_HINT = ModeCapabilities(
    supports_text=True,
    supports_reasoning=True,
    reasoning_levels=("AUTO", "MINIMUM", "MEDIUM", "MAXIMUM"),
    supports_search=True,
    supports_files=True,
    max_files=1,
    max_bytes_per_file=128 * 1024 * 1024,
    supports_images=True,
    supports_vision=True,
    supports_cancel=True,
    supports_streaming=True,
)
EXPERT_HINT = ModeCapabilities(
    supports_text=True,
    supports_reasoning=True,
    reasoning_levels=("AUTO", "MEDIUM", "MAXIMUM"),
    supports_cancel=True,
    supports_streaming=True,
)
THREE_D_HINT = ModeCapabilities(
    supports_text=True,
    supports_files=True,
    accepted_mime_types=("image/png", "image/jpeg"),
    accepted_extensions=(".png", ".jpg", ".jpeg"),
    max_files=6,
    max_bytes_per_file=128 * 1024 * 1024,
    supports_images=True,
    supports_vision=True,
    supports_3d_generation=True,
    supports_geometry=True,
    supports_texture=True,
    supports_download=True,
    supports_cancel=True,
    supports_streaming=True,
)


BUILTIN_MANIFESTS = (
    ProviderManifest(
        "chatgpt",
        "ChatGPT",
        "https://chatgpt.com/",
        ProviderSupport.BETA,
        "web",
        ("BUILDER", "VISUAL", "RESEARCH"),
        (ProviderMode("default", "Default", TEXT_REASONING),),
        True,
    ),
    ProviderManifest(
        "deepseek",
        "DeepSeek",
        "https://chat.deepseek.com/",
        ProviderSupport.BETA,
        "web",
        ("REVIEWER",),
        (ProviderMode("instant", "Instant", INSTANT_HINT), ProviderMode("expert", "Expert", EXPERT_HINT)),
        True,
    ),
    ProviderManifest(
        "hunyuan",
        "Hunyuan 3D",
        "https://3d.hunyuan.tencent.com/",
        ProviderSupport.BETA,
        "web",
        ("3D",),
        (ProviderMode("3d", "3D", THREE_D_HINT),),
        True,
    ),
    ProviderManifest("claude", "Claude", "https://claude.ai/", ProviderSupport.UNSUPPORTED, "none"),
    ProviderManifest("gemini", "Gemini", "https://gemini.google.com/", ProviderSupport.UNSUPPORTED, "none"),
    ProviderManifest("grok", "Grok", "https://grok.com/", ProviderSupport.UNSUPPORTED, "none"),
    ProviderManifest("copilot", "Copilot", "https://copilot.microsoft.com/", ProviderSupport.UNSUPPORTED, "none"),
    ProviderManifest("perplexity", "Perplexity", "https://www.perplexity.ai/", ProviderSupport.UNSUPPORTED, "none"),
    ProviderManifest("mistral", "Le Chat", "https://chat.mistral.ai/", ProviderSupport.UNSUPPORTED, "none"),
    ProviderManifest("qwen", "Qwen", "https://chat.qwen.ai/", ProviderSupport.UNSUPPORTED, "none"),
    ProviderManifest("kimi", "Kimi", "https://www.kimi.com/", ProviderSupport.UNSUPPORTED, "none"),
    ProviderManifest("poe", "Poe", "https://poe.com/", ProviderSupport.UNSUPPORTED, "none"),
    ProviderManifest("meta", "Meta AI", "https://www.meta.ai/", ProviderSupport.UNSUPPORTED, "none"),
    ProviderManifest("yuanbao", "Yuanbao", "https://yuanbao.tencent.com/", ProviderSupport.UNSUPPORTED, "none"),
    ProviderManifest("doubao", "Doubao", "https://www.doubao.com/", ProviderSupport.UNSUPPORTED, "none"),
    ProviderManifest("huggingchat", "HuggingChat", "https://huggingface.co/chat/", ProviderSupport.UNSUPPORTED, "none"),
    ProviderManifest("you", "You.com", "https://you.com/", ProviderSupport.UNSUPPORTED, "none"),
    ProviderManifest("duck", "Duck.ai", "https://duck.ai/", ProviderSupport.UNSUPPORTED, "none"),
)


REGISTRY = ProviderRegistry(BUILTIN_MANIFESTS)
