from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Iterable

_WORD = re.compile(r"[a-z0-9_]{2,}")
_STOPWORDS = {
    "the",
    "and",
    "this",
    "from",
    "roblox",
    "studio",
    "make",
    "create",
    "want",
}


@dataclass(frozen=True, slots=True)
class BrainAnalysis:
    fingerprint: str
    intents: tuple[str, ...]
    keywords: tuple[str, ...]
    scopes: tuple[str, ...]
    providers: tuple[str, ...]
    requires_mutation: bool
    review_blocks: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ZenlessBrain:
    _INTENTS = {
        "debug": ("error", "bug", "failure", "correct", "fix", "crash", "output"),
        "test": ("test", "playtest", "validate", "verify"),
        "visual": ("ui", "hud", "visual", "interface", "image", "design"),
        "3d": ("3d", "mesh", "model", "asset", "object"),
        "audit": ("audit", "review", "security", "performance", "optimize"),
        "explain": ("explain", "how it works", "document", "summarize"),
        "code": ("script", "luau", "code", "program", "implement", "system"),
    }
    _SCOPES = {
        "ServerScriptService": ("server", "authority", "datastore", "remote"),
        "ReplicatedStorage": ("shared", "replicated", "remote", "types", "module"),
        "StarterPlayer": ("client", "camera", "input", "movement", "controller"),
        "StarterGui": ("ui", "hud", "interface", "menu"),
        "Workspace": ("map", "world", "workspace", "part", "model", "physics"),
    }

    def analyze(self, objective: str, *, independent_review: bool = True, create_3d: bool = False) -> BrainAnalysis:
        normalized = self._normalize(objective)
        tokens = [token for token in _WORD.findall(normalized) if token not in _STOPWORDS]
        frequencies: dict[str, int] = {}
        for token in tokens:
            frequencies[token] = frequencies.get(token, 0) + 1
        keywords = tuple(
            token for token, _ in sorted(frequencies.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))[:16]
        )
        intents = tuple(
            name for name, markers in self._INTENTS.items() if any(marker in normalized for marker in markers)
        ) or ("code",)
        scopes = tuple(
            name for name, markers in self._SCOPES.items() if any(marker in normalized for marker in markers)
        )
        providers = ["chatgpt"]
        if independent_review:
            providers.append("deepseek")
        if create_3d or "3d" in intents:
            providers.append("hunyuan")
        read_only_markers = ("read only", "only read", "explain", "audit", "analyze without changes")
        requires_mutation = not any(marker in normalized for marker in read_only_markers)
        blocks = []
        if any(intent in intents for intent in ("debug", "test")):
            blocks.append("A")
        if requires_mutation and any(intent in intents for intent in ("visual", "3d", "code", "audit")):
            blocks.append("B")
        if not blocks:
            blocks.append("B" if requires_mutation else "A")
        canonical = json.dumps(
            {"objective": " ".join(tokens), "intents": intents, "scopes": scopes},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = hashlib.blake2b(canonical.encode("utf-8"), digest_size=16).hexdigest()
        return BrainAnalysis(fingerprint, intents, keywords, scopes, tuple(providers), requires_mutation, tuple(blocks))

    def compact_context(self, context: dict[str, Any], *, max_chars: int = 96_000) -> dict[str, Any]:
        result = dict(context)
        reads = context.get("reads")
        if not isinstance(reads, dict):
            return result
        ranked = sorted(
            ((str(key), str(value)) for key, value in reads.items()),
            key=lambda item: (self._read_priority(item[0]), len(item[1])),
        )
        budget = max(8_000, max_chars)
        compact: dict[str, str] = {}
        for key, value in ranked:
            if budget <= 0:
                break
            clipped = value[: min(len(value), budget, 28_000)]
            compact[key] = clipped
            budget -= len(clipped)
        result["reads"] = compact
        return result

    @staticmethod
    def deduplicate(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        output: list[dict[str, Any]] = []
        for item in items:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
            digest = hashlib.blake2b(key.encode("utf-8"), digest_size=16).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            output.append(item)
        return output

    @staticmethod
    def _normalize(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value.casefold())
        return "".join(character for character in decomposed if not unicodedata.combining(character))

    @staticmethod
    def _read_priority(key: str) -> int:
        lowered = key.casefold()
        if "get_studio_state" in lowered:
            return 0
        if "get_console_output" in lowered:
            return 1
        if "basescript" in lowered or "script" in lowered:
            return 2
        return 3
