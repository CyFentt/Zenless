from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field, replace
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


class FeatureMode(StrEnum):
    AUTO = "AUTO"
    ON = "ON"
    OFF = "OFF"


class EffortProfile(StrEnum):
    AUTO = "AUTO"
    MINIMUM = "MINIMUM"
    MEDIUM = "MEDIUM"
    MAXIMUM = "MAXIMUM"


class ChatMode(StrEnum):
    PROJECT = "PROJECT"
    TEMP = "TEMP"


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
    max_revisions: int = 3
    max_test_fixes: int = 3
    risk_level: str = "medium"
    research: str = "auto"
    visual_mode: str = FeatureMode.AUTO.value
    create_3d_mode: str = FeatureMode.AUTO.value
    effort: str = EffortProfile.AUTO.value
    chat_mode: str = ChatMode.PROJECT.value
    deadline_minutes: int = 60

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_ui(cls, raw: dict[str, Any]) -> "TaskOptions":
        def bounded_int(key: str, default: int) -> int:
            try:
                return max(1, min(5, int(raw.get(key, default))))
            except TypeError, ValueError:
                return default

        visual_mode = cls._feature_mode(raw.get("Visual First", FeatureMode.AUTO.value))
        create_3d_mode = cls._feature_mode(raw.get("Create 3D Asset", FeatureMode.AUTO.value))
        create_3d_asset = create_3d_mode == FeatureMode.ON
        raw_research = str(raw.get("Research", "auto")).strip().lower()
        research = raw_research if raw_research in {"auto", "on", "off"} else "auto"
        return cls(
            visual_first=visual_mode == FeatureMode.ON or create_3d_asset,
            create_3d_asset=create_3d_asset,
            independent_review=bool(raw.get("Independent Review", True)),
            automatic_play_test=bool(raw.get("Automatic Play Test", True)),
            auto_fix_errors=bool(raw.get("Auto Fix Errors", True)),
            require_approval=bool(raw.get("Require Approval Before Studio Changes", True)),
            max_revisions=bounded_int("Max Revisions", 3),
            max_test_fixes=bounded_int("Max Test Fixes", 3),
            risk_level=cls._risk(raw.get("Risk", raw.get("Risk Level", "medium"))),
            research=research,
            visual_mode=visual_mode.value,
            create_3d_mode=create_3d_mode.value,
            effort=cls._effort(raw.get("Effort", EffortProfile.AUTO.value)).value,
            chat_mode=cls._chat_mode(raw.get("Chat Mode", ChatMode.PROJECT.value)).value,
            deadline_minutes=cls._deadline(raw.get("Deadline Minutes", 60)),
        )

    @classmethod
    def from_api(cls, raw: dict[str, Any] | None) -> "TaskOptions":
        source = raw or {}

        def bounded_int(key: str, default: int) -> int:
            try:
                return max(1, min(5, int(source.get(key, default))))
            except TypeError, ValueError:
                return default

        raw_research = str(source.get("research", "auto")).strip().lower()
        research = raw_research if raw_research in {"auto", "on", "off"} else "auto"
        visual_mode = cls._feature_mode(source.get("visualMode", source.get("visualFirst", FeatureMode.AUTO.value)))
        create_3d_mode = cls._feature_mode(source.get("create3DMode", source.get("create3D", FeatureMode.AUTO.value)))
        create_3d_asset = create_3d_mode == FeatureMode.ON
        return cls(
            visual_first=visual_mode == FeatureMode.ON or create_3d_asset,
            create_3d_asset=create_3d_asset,
            independent_review=bool(source.get("review", True)),
            automatic_play_test=bool(source.get("autoTest", True)),
            auto_fix_errors=bool(source.get("autoFix", True)),
            require_approval=bool(source.get("approval", True)),
            max_revisions=bounded_int("revisions", 3),
            max_test_fixes=bounded_int("fixAttempts", 3),
            risk_level=cls._risk(source.get("risk", "medium")),
            research=research,
            visual_mode=visual_mode.value,
            create_3d_mode=create_3d_mode.value,
            effort=cls._effort(source.get("effort", EffortProfile.AUTO.value)).value,
            chat_mode=cls._chat_mode(source.get("chatMode", source.get("chat_mode", ChatMode.PROJECT.value))).value,
            deadline_minutes=cls._deadline(source.get("deadlineMinutes", source.get("deadline_minutes", 60))),
        )

    def resolve(self, objective: str) -> "TaskOptions":
        normalized = self._normalize(objective)
        three_d_intent = self._matches(
            normalized,
            (
                r"\b3d\b",
                r"\b(glb|gltf|fbx)\b",
                r"\b(3d model|3d mesh|3d object|3d asset)\b",
                r"\b(generate|create|import)\b.{0,28}\b(3d model|mesh|texture|geometry)\b",
            ),
        )
        visual_intent = three_d_intent or self._matches(
            normalized,
            (
                r"\b(concept art|visual concept|reference image|six views|orthographic)\b",
                r"\b(generate|create)\b.{0,24}\b(image|logo|icon|sprite|texture)\b",
            ),
        )
        create_mode = self._coerce_feature_mode(self.create_3d_mode)
        visual_mode = self._coerce_feature_mode(self.visual_mode)
        create_3d = (
            self.create_3d_asset
            or create_mode == FeatureMode.ON
            or (create_mode == FeatureMode.AUTO and three_d_intent)
        )
        visual_first = (
            self.visual_first
            or visual_mode == FeatureMode.ON
            or (visual_mode == FeatureMode.AUTO and visual_intent)
            or create_3d
        )
        return replace(self, visual_first=visual_first, create_3d_asset=create_3d)

    @property
    def review_rounds(self) -> int:
        effort = self._coerce_effort(self.effort)
        if effort == EffortProfile.MINIMUM:
            return min(2, self.max_revisions)
        if effort == EffortProfile.MAXIMUM:
            return min(5, self.max_revisions)
        return min(3, self.max_revisions)

    @property
    def qa_profile(self) -> str:
        effort = self._coerce_effort(self.effort)
        if effort == EffortProfile.MINIMUM:
            return "SMOKE"
        if effort == EffortProfile.MAXIMUM or self.risk_level == "high":
            return "DEEP"
        return "STANDARD"

    @staticmethod
    def _risk(value: Any) -> str:
        normalized = str(value).strip().casefold()
        return normalized if normalized in {"low", "medium", "high"} else "medium"

    @classmethod
    def _feature_mode(cls, value: Any) -> FeatureMode:
        if isinstance(value, (bool, int)) and value in {0, 1}:
            return FeatureMode.ON if value else FeatureMode.OFF
        return cls._coerce_feature_mode(value)

    @staticmethod
    def _coerce_feature_mode(value: Any) -> FeatureMode:
        try:
            return FeatureMode(str(value).strip().upper())
        except ValueError:
            return FeatureMode.AUTO

    @staticmethod
    def _effort(value: Any) -> EffortProfile:
        return TaskOptions._coerce_effort(value)

    @staticmethod
    def _coerce_effort(value: Any) -> EffortProfile:
        normalized = str(value).strip().upper()
        aliases = {"MIN": EffortProfile.MINIMUM, "MED": EffortProfile.MEDIUM, "MAX": EffortProfile.MAXIMUM}
        if normalized in aliases:
            return aliases[normalized]
        try:
            return EffortProfile(normalized)
        except ValueError:
            return EffortProfile.AUTO

    @staticmethod
    def _chat_mode(value: Any) -> ChatMode:
        return TaskOptions._coerce_chat_mode(value)

    @staticmethod
    def _coerce_chat_mode(value: Any) -> ChatMode:
        try:
            return ChatMode(str(value).strip().upper())
        except ValueError:
            return ChatMode.PROJECT

    @staticmethod
    def _deadline(value: Any) -> int:
        try:
            return max(5, min(240, int(value)))
        except TypeError, ValueError:
            return 60

    @staticmethod
    def _normalize(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value.casefold())
        return "".join(character for character in decomposed if not unicodedata.combining(character))

    @staticmethod
    def _matches(value: str, patterns: tuple[str, ...]) -> bool:
        return any(re.search(pattern, value) for pattern in patterns)


@dataclass(slots=True)
class ProposalAction:
    tool: str
    arguments: dict[str, Any]
    reason: str = ""
    risk: str = "medium"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ProposalAction":
        return cls(
            tool=str(raw.get("tool", "")).strip(),
            arguments=dict(raw.get("arguments") or {}),
            reason=str(raw.get("reason", "")).strip(),
            risk=str(raw.get("risk", "medium")).strip().lower(),
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
        actions_raw = raw.get("actions") or []
        actions = [ProposalAction.from_dict(item) for item in actions_raw if isinstance(item, dict)]
        return cls(
            summary=str(raw.get("summary", "")).strip(),
            actions=actions,
            final_message=str(raw.get("final_message", "")).strip(),
            visual_prompt=str(raw.get("visual_prompt", "")).strip(),
            model_3d_prompt=str(raw.get("model_3d_prompt", "")).strip(),
            tests=[str(item).strip() for item in raw.get("tests", []) if str(item).strip()],
            raw_text=raw_text,
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
        return cls(
            verdict=str(raw.get("verdict", "revise")).strip().lower(),
            summary=str(raw.get("summary", "")).strip(),
            issues=[str(item).strip() for item in raw.get("issues", []) if str(item).strip()],
            required_changes=[str(item).strip() for item in raw.get("required_changes", []) if str(item).strip()],
            tests_required=[str(item).strip() for item in raw.get("tests_required", []) if str(item).strip()],
            risk=str(raw.get("risk", "medium")).strip().lower(),
            confidence=confidence,
            raw_text=raw_text,
        )


@dataclass(slots=True)
class PipelineEvent:
    task_id: str
    stage: Stage
    message: str
    kind: str = "info"
    detail: str = ""
    created_at: str = ""
