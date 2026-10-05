from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Stage(StrEnum):
    NEW = "NEW"
    COLLECTING_CONTEXT = "COLLECTING_CONTEXT"
    PLANNING = "PLANNING"
    GENERATING_CONCEPT = "GENERATING_CONCEPT"
    WAITING_IMAGE_APPROVAL = "WAITING_IMAGE_APPROVAL"
    GENERATING_3D = "GENERATING_3D"
    BUILDING = "BUILDING"
    REVIEWING = "REVIEWING"
    REVISING = "REVISING"
    WAITING_3D_APPROVAL = "WAITING_3D_APPROVAL"
    WAITING_CHANGE_APPROVAL = "WAITING_CHANGE_APPROVAL"
    APPLYING = "APPLYING"
    TESTING = "TESTING"
    FIXING = "FIXING"
    FINAL_REVIEW = "FINAL_REVIEW"
    COMPLETE = "COMPLETE"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"

    CREATING = "PLANNING"
    WAITING_VISUAL_APPROVAL = "WAITING_IMAGE_APPROVAL"
    REPAIRING = "FIXING"


TERMINAL_STAGES = {Stage.COMPLETE, Stage.BLOCKED, Stage.FAILED}


class InvalidStageTransition(ValueError):
    pass


_COMMON_FAILURES = {Stage.BLOCKED, Stage.FAILED}
_STAGE_TRANSITIONS: dict[Stage, set[Stage]] = {
    Stage.NEW: {Stage.COLLECTING_CONTEXT, Stage.PAUSED, *_COMMON_FAILURES},
    Stage.COLLECTING_CONTEXT: {
        Stage.PLANNING,
        Stage.REVIEWING,
        Stage.COMPLETE,
        Stage.PAUSED,
        *_COMMON_FAILURES,
    },
    Stage.PLANNING: {
        Stage.TESTING,
        Stage.COLLECTING_CONTEXT,
        Stage.REVIEWING,
        Stage.GENERATING_CONCEPT,
        Stage.WAITING_IMAGE_APPROVAL,
        Stage.GENERATING_3D,
        Stage.WAITING_CHANGE_APPROVAL,
        Stage.APPLYING,
        Stage.COMPLETE,
        Stage.PAUSED,
        *_COMMON_FAILURES,
    },
    Stage.GENERATING_CONCEPT: {
        Stage.WAITING_IMAGE_APPROVAL,
        Stage.GENERATING_3D,
        Stage.BUILDING,
        Stage.PAUSED,
        *_COMMON_FAILURES,
    },
    Stage.WAITING_IMAGE_APPROVAL: {
        Stage.GENERATING_CONCEPT,
        Stage.GENERATING_3D,
        Stage.BUILDING,
        Stage.WAITING_CHANGE_APPROVAL,
        Stage.COMPLETE,
        Stage.PAUSED,
        *_COMMON_FAILURES,
    },
    Stage.GENERATING_3D: {
        Stage.WAITING_3D_APPROVAL,
        Stage.BUILDING,
        Stage.PAUSED,
        *_COMMON_FAILURES,
    },
    Stage.WAITING_3D_APPROVAL: {
        Stage.GENERATING_3D,
        Stage.BUILDING,
        Stage.WAITING_CHANGE_APPROVAL,
        Stage.COMPLETE,
        Stage.PAUSED,
        *_COMMON_FAILURES,
    },
    Stage.BUILDING: {
        Stage.REVIEWING,
        Stage.REVISING,
        Stage.WAITING_CHANGE_APPROVAL,
        Stage.APPLYING,
        Stage.PAUSED,
        *_COMMON_FAILURES,
    },
    Stage.REVIEWING: {
        Stage.TESTING,
        Stage.REVISING,
        Stage.GENERATING_CONCEPT,
        Stage.GENERATING_3D,
        Stage.WAITING_IMAGE_APPROVAL,
        Stage.WAITING_3D_APPROVAL,
        Stage.WAITING_CHANGE_APPROVAL,
        Stage.APPLYING,
        Stage.COMPLETE,
        Stage.PAUSED,
        *_COMMON_FAILURES,
    },
    Stage.REVISING: {
        Stage.REVIEWING,
        Stage.COLLECTING_CONTEXT,
        Stage.WAITING_CHANGE_APPROVAL,
        Stage.APPLYING,
        Stage.PAUSED,
        *_COMMON_FAILURES,
    },
    Stage.WAITING_CHANGE_APPROVAL: {
        Stage.REVISING,
        Stage.APPLYING,
        Stage.PAUSED,
        *_COMMON_FAILURES,
    },
    Stage.APPLYING: {
        Stage.TESTING,
        Stage.FINAL_REVIEW,
        Stage.COMPLETE,
        Stage.PAUSED,
        *_COMMON_FAILURES,
    },
    Stage.TESTING: {
        Stage.FIXING,
        Stage.FINAL_REVIEW,
        Stage.COMPLETE,
        Stage.PAUSED,
        *_COMMON_FAILURES,
    },
    Stage.FIXING: {
        Stage.REVIEWING,
        Stage.WAITING_CHANGE_APPROVAL,
        Stage.APPLYING,
        Stage.TESTING,
        Stage.PAUSED,
        *_COMMON_FAILURES,
    },
    Stage.FINAL_REVIEW: {Stage.COMPLETE, Stage.FIXING, Stage.PAUSED, *_COMMON_FAILURES},
    Stage.PAUSED: set(Stage) - TERMINAL_STAGES - {Stage.PAUSED},
    Stage.BLOCKED: set(),
    Stage.FAILED: set(),
    Stage.COMPLETE: set(),
}


def validate_stage_transition(previous: Stage | str, next_stage: Stage | str) -> None:
    before = previous if isinstance(previous, Stage) else Stage(previous)
    after = next_stage if isinstance(next_stage, Stage) else Stage(next_stage)
    if before == after:
        return
    if after not in _STAGE_TRANSITIONS.get(before, set()):
        raise InvalidStageTransition(f"Invalid pipeline transition: {before.value} -> {after.value}")


@dataclass(slots=True)
class TaskOptions:
    visual_first: bool = False
    create_3d_asset: bool = False
    independent_review: bool = True
    automatic_play_test: bool = True
    auto_fix_errors: bool = True
    require_approval: bool = True
    approval_mode: str = "ask"
    max_revisions: int = 3
    max_test_fixes: int = 3
    continuous_verification: bool = True
    effort_level: str = "auto"
    research_mode: str = "auto"
    smart_routing: bool = True
    risk_level: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_ui(cls, raw: dict[str, Any]) -> "TaskOptions":
        def bounded_int(key: str, default: int) -> int:
            try:
                return max(1, min(64, int(raw.get(key, default))))
            except TypeError, ValueError:
                return default

        create_3d_asset = cls._boolean(raw.get("Create 3D Asset"), False)
        require_approval = cls._boolean(raw.get("Require Approval Before Studio Changes"), True)
        return cls(
            visual_first=cls._boolean(raw.get("Visual First"), False) or create_3d_asset,
            create_3d_asset=create_3d_asset,
            independent_review=cls._boolean(raw.get("Independent Review"), True),
            automatic_play_test=cls._boolean(raw.get("Automatic Play Test"), True),
            auto_fix_errors=cls._boolean(raw.get("Auto Fix Errors"), True),
            require_approval=require_approval,
            approval_mode=cls._approval_mode(
                raw.get("Approval Mode"),
                "ask" if require_approval else "full_auto",
            ),
            max_revisions=bounded_int("Max Revisions", 3),
            max_test_fixes=bounded_int("Max Test Fixes", 3),
            continuous_verification=cls._boolean(raw.get("Continuous Verification"), True),
            effort_level=cls._effort(raw.get("Effort", "auto")),
            research_mode=cls._research(raw.get("Research", "auto")),
            smart_routing=cls._boolean(raw.get("Smart Routing"), True),
            risk_level=cls._risk(raw.get("Risk", raw.get("Risk Level", "medium"))),
        )

    @classmethod
    def from_api(cls, raw: dict[str, Any] | None) -> "TaskOptions":
        source = raw or {}

        def bounded_int(key: str, default: int) -> int:
            try:
                return max(1, min(64, int(source.get(key, default))))
            except TypeError, ValueError:
                return default

        create_3d_asset = cls._boolean(source.get("create3D"), False)
        legacy_approval = cls._boolean(source.get("approval"), True)
        approval_mode = cls._approval_mode(
            source.get("approvalMode"),
            "ask" if legacy_approval else "full_auto",
        )
        return cls(
            visual_first=cls._boolean(source.get("visualFirst"), False) or create_3d_asset,
            create_3d_asset=create_3d_asset,
            independent_review=cls._boolean(source.get("review"), True),
            automatic_play_test=cls._boolean(source.get("autoTest"), True),
            auto_fix_errors=cls._boolean(source.get("autoFix"), True),
            require_approval=approval_mode != "full_auto",
            approval_mode=approval_mode,
            max_revisions=bounded_int("revisions", 3),
            max_test_fixes=bounded_int("fixAttempts", 3),
            continuous_verification=cls._boolean(source.get("continuousVerification"), True),
            effort_level=cls._effort(source.get("effort", "auto")),
            research_mode=cls._research(source.get("research", "auto")),
            smart_routing=cls._boolean(source.get("smartRouting"), True),
            risk_level=cls._risk(source.get("risk", "medium")),
        )

    @staticmethod
    def _boolean(value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, int | float):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        return default

    @staticmethod
    def _risk(value: Any) -> str:
        normalized = str(value).strip().casefold()
        return normalized if normalized in {"low", "medium", "high"} else "medium"

    @staticmethod
    def _effort(value: Any) -> str:
        normalized = str(value or "auto").strip().casefold()
        aliases = {"minimum": "min", "medium": "med", "maximum": "max"}
        normalized = aliases.get(normalized, normalized)
        return normalized if normalized in {"auto", "min", "med", "max"} else "auto"

    @staticmethod
    def _research(value: Any) -> str:
        normalized = str(value or "auto").strip().casefold()
        return normalized if normalized in {"auto", "on", "off"} else "auto"

    @staticmethod
    def _approval_mode(value: Any, fallback: str = "ask") -> str:
        normalized = str(value or fallback).strip().casefold().replace("-", "_").replace(" ", "_")
        aliases = {
            "manual": "ask",
            "always_ask": "ask",
            "safe": "safe_auto",
            "automatic": "full_auto",
            "auto": "full_auto",
            "full": "full_auto",
        }
        normalized = aliases.get(normalized, normalized)
        return normalized if normalized in {"ask", "safe_auto", "full_auto"} else fallback


@dataclass(slots=True)
class ProposalAction:
    tool: str
    arguments: dict[str, Any]
    reason: str = ""
    risk: str = "medium"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ProposalAction":
        raw_arguments = raw.get("arguments")
        risk = str(raw.get("risk", "medium")).strip().casefold()
        return cls(
            tool=str(raw.get("tool", "")).strip()[:160],
            arguments=dict(raw_arguments) if isinstance(raw_arguments, dict) else {},
            reason=str(raw.get("reason", "")).strip()[:4000],
            risk=risk if risk in {"low", "medium", "high", "critical"} else "medium",
        )


@dataclass(slots=True)
class AgentProposal:
    summary: str
    actions: list[ProposalAction] = field(default_factory=list)
    final_message: str = ""
    visual_prompt: str = ""
    model_3d_prompt: str = ""
    tests: list[str] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any], raw_text: str = "") -> "AgentProposal":
        actions_raw = raw.get("actions")
        actions = [
            ProposalAction.from_dict(item)
            for item in (actions_raw[:64] if isinstance(actions_raw, list) else [])
            if isinstance(item, dict)
        ]
        tests_raw = raw.get("tests")
        tests = [
            str(item).strip()[:1000]
            for item in (tests_raw[:64] if isinstance(tests_raw, list) else [])
            if str(item).strip()
        ]
        return cls(
            summary=str(raw.get("summary", "")).strip()[:12_000],
            actions=actions,
            final_message=str(raw.get("final_message", "")).strip()[:20_000],
            visual_prompt=str(raw.get("visual_prompt", "")).strip()[:12_000],
            model_3d_prompt=str(raw.get("model_3d_prompt", "")).strip()[:12_000],
            tests=tests,
            raw_text=raw_text[:120_000],
        )


@dataclass(slots=True)
class ReviewResult:
    verdict: str
    summary: str
    issues: list[str] = field(default_factory=list)
    required_changes: list[str] = field(default_factory=list)
    tests_required: list[str] = field(default_factory=list)
    risk: str = "medium"
    confidence: float = 0.0
    raw_text: str = ""

    @property
    def approved(self) -> bool:
        return self.verdict in {"approve", "approved"}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], raw_text: str = "") -> "ReviewResult":
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
        except TypeError, ValueError:
            confidence = 0.0
        def strings(key: str) -> list[str]:
            value = raw.get(key)
            if not isinstance(value, list):
                return []
            return [str(item).strip()[:2000] for item in value[:64] if str(item).strip()]

        risk = str(raw.get("risk", "medium")).strip().casefold()
        verdict = str(raw.get("verdict", "revise")).strip().casefold()
        return cls(
            verdict=verdict if verdict in {"approve", "approved", "revise", "block"} else "revise",
            summary=str(raw.get("summary", "")).strip()[:12_000],
            issues=strings("issues"),
            required_changes=strings("required_changes"),
            tests_required=strings("tests_required"),
            risk=risk if risk in {"low", "medium", "high", "critical"} else "medium",
            confidence=confidence,
            raw_text=raw_text[:120_000],
        )


@dataclass(slots=True)
class PipelineEvent:
    task_id: str
    stage: Stage
    message: str
    kind: str = "info"
    detail: str = ""
    created_at: str = ""
