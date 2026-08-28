from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .models import ProposalAction

READ_ONLY_TOOLS = {
    "list_roblox_studios",
    "search_game_tree",
    "inspect_instance",
    "script_search",
    "script_grep",
    "script_read",
    "get_console_output",
    "get_studio_state",
    "screen_capture",
    "http_get",
    "search_asset",
    "skill",
}

ORCHESTRATOR_ONLY_TOOLS = {
    "start_stop_play",
    "user_keyboard_input",
    "user_mouse_input",
    "run_as_job",
    "wait_job_finished",
}

DISALLOWED_AUTOMATED_TOOLS = {
    "execute_luau",
    "character_navigation",
}

DESTRUCTIVE_PATTERNS = (
    r":\s*Destroy\s*\(",
    r"ClearAllChildren\s*\(",
    r"RemoveAsync\s*\(",
    r"SetAsync\s*\(",
    r"UpdateAsync\s*\(",
    r"BanAsync\s*\(",
    r":\s*Kick\s*\(",
    r"TeleportAsync\s*\(",
    r"\bshutdown\b",
    r"\bdelete\b",
)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    risk: str
    reasons: tuple[str, ...] = ()


def is_read_only(tool: str) -> bool:
    return tool in READ_ONLY_TOOLS or tool == "subagent"


def classify_action(action: ProposalAction, available_tools: set[str]) -> PolicyDecision:
    reasons: list[str] = []
    if action.tool not in available_tools:
        return PolicyDecision(False, "blocked", (f"Ferramenta MCP indisponível: {action.tool}",))
    if action.tool in ORCHESTRATOR_ONLY_TOOLS:
        return PolicyDecision(False, "blocked", (f"{action.tool} é controlada internamente pelo Zenless",))
    if action.tool in DISALLOWED_AUTOMATED_TOOLS:
        return PolicyDecision(False, "critical", (f"{action.tool} não pode ser proposta por uma IA web",))
    if not isinstance(action.arguments, dict):
        return PolicyDecision(False, "blocked", ("Argumentos não são um objeto JSON",))

    serialized = json.dumps(action.arguments, ensure_ascii=False, default=str)
    if len(serialized.encode("utf-8")) > 512_000:
        return PolicyDecision(False, "blocked", ("Ação excede 512 KiB",))

    if is_read_only(action.tool):
        return PolicyDecision(True, "low")

    risk = "medium"
    for pattern in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, serialized, flags=re.IGNORECASE):
            risk = "critical"
            reasons.append(f"Padrão destrutivo detectado: {pattern}")

    if action.tool == "multi_edit":
        file_path = str(action.arguments.get("file_path", ""))
        edits = action.arguments.get("edits")
        if not file_path.startswith(("game.", "Workspace.", "ServerScriptService.", "ReplicatedStorage.", "Starter")):
            reasons.append("Caminho de script inválido ou pouco específico")
        if not isinstance(edits, list) or not edits:
            reasons.append("multi_edit precisa de uma lista de edições")
        elif len(edits) > 40:
            reasons.append("multi_edit excede 40 substituições")
        for edit in edits if isinstance(edits, list) else []:
            if not isinstance(edit, dict):
                reasons.append("Edição não é um objeto")
                continue
            old = edit.get("old_string")
            new = edit.get("new_string")
            if not isinstance(old, str) or not isinstance(new, str) or old == new:
                reasons.append("Edição exige old_string/new_string distintos")
            if isinstance(old, str) and old and new == "":
                risk = "high"
                reasons.append("A edição remove conteúdo existente")

    if reasons:
        blocked = risk == "critical" or any(
            marker in reason
            for reason in reasons
            for marker in ("inválido", "precisa", "excede", "não é", "exige")
        )
        return PolicyDecision(not blocked, risk, tuple(dict.fromkeys(reasons)))
    return PolicyDecision(True, risk)


def validate_proposal(actions: list[ProposalAction], available_tools: set[str]) -> list[str]:
    errors: list[str] = []
    if len(actions) > 16:
        errors.append("A proposta excede 16 ações MCP.")
    for index, action in enumerate(actions[:16], start=1):
        decision = classify_action(action, available_tools)
        if not decision.allowed:
            detail = "; ".join(decision.reasons) or "bloqueada pela política"
            errors.append(f"Ação {index} ({action.tool}): {detail}")
    return errors
