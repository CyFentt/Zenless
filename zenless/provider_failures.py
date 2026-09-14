from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class ProviderAvailability(StrEnum):
    UNKNOWN = "UNKNOWN"
    READY = "READY"
    BUSY = "BUSY"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    TEMP_UNAVAILABLE = "TEMP_UNAVAILABLE"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    state: ProviderAvailability
    message: str

    def bridge_message(self) -> str:
        return f"{self.state.value}: {self.message}"


_PATTERNS = (
    (
        ProviderAvailability.QUOTA_EXHAUSTED,
        re.compile(r"\b(quota|usage limit|message limit|credits? exhausted|out of credits|no credits remaining)\b", re.I),
        "The provider quota is exhausted. Select another available model or disable its optional task step.",
    ),
    (
        ProviderAvailability.RATE_LIMITED,
        re.compile(r"\b(rate limit|too many requests|request limit|try again in \d+)\b", re.I),
        "The provider is rate limited. Wait for the provider window or select another available model.",
    ),
    (
        ProviderAvailability.MODEL_UNAVAILABLE,
        re.compile(r"\b(model (?:is )?(?:currently )?(?:unavailable|not available)|unsupported model|model access)\b", re.I),
        "The selected model is unavailable. Select a model currently offered by the provider.",
    ),
    (
        ProviderAvailability.TEMP_UNAVAILABLE,
        re.compile(r"\b(service unavailable|temporarily unavailable|something went wrong|server error|please try again later)\b", re.I),
        "The provider is temporarily unavailable. Retry or disable its optional task step.",
    ),
)


def classify_provider_failure(text: str) -> ProviderFailure | None:
    normalized = " ".join(text.split())[:2_000]
    if not normalized:
        return None
    for state, pattern, message in _PATTERNS:
        if pattern.search(normalized):
            return ProviderFailure(state, message)
    return None


def failure_from_error(text: str) -> ProviderFailure | None:
    normalized = text.strip()
    for state in ProviderAvailability:
        prefix = f"{state.value}:"
        if normalized.startswith(prefix):
            message = normalized[len(prefix) :].strip()
            return ProviderFailure(state, message or "The provider requires attention.")
    return classify_provider_failure(normalized)
