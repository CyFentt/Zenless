from __future__ import annotations

import json
from datetime import date
from typing import Any, Callable

from .models import AgentProposal, ReviewResult


class PromptPolicyEngine:
    def __init__(self, date_provider: Callable[[], date] = date.today) -> None:
        self.date_provider = date_provider

    def render(self, *, role: str, task: str, effort: str = "AUTO", block: str = "GLOBAL") -> str:
        return (
            "PRODUCT:\nZenless is modifying a live Roblox Studio game.\n\n"
            "LANGUAGE:\nLuau and current Roblox engine APIs.\n\n"
            "SOURCE OF TRUTH:\nThe selected live Roblox Studio project.\n\n"
            f"CURRENT DATE:\n{self.date_provider().isoformat()}\n\n"
            f"ROLE:\n{role}\n\n"
            f"TASK:\n{task}\n\n"
            f"EFFORT:\n{effort}\n\n"
            f"BLOCK:\n{block}\n\n"
            "POLICY:\nServer authority, validated remote inputs, mutation safety, evidence-based conclusions, "
            "no invented APIs, no fabricated tool results, and no private chain-of-thought."
        )


POLICY_ENGINE = PromptPolicyEngine()

PRINCIPAL_CONTRACT = """
You are the principal implementation agent inside Zenless for the live Roblox Studio project.
Zenless, not the browser page, is the authority that executes MCP tools. You may only PROPOSE tool calls.

Rules:
- Inspect and extend the existing Studio architecture. Never assume the project is only local files.
- Server owns game state. Validate every remote argument server-side. Never use InvokeClient.
- Use strict Luau for new modules, task APIs, connection cleanup, and streaming-aware design.
- Never invent Roblox APIs. If current API evidence is missing, propose an official-doc read action first.
- Prefer multi_edit for persistent source changes. Do not propose execute_luau, keyboard/mouse input, or play controls.
- Use only documentation or fetch capabilities that Zenless actually advertised. Record uncertainty when unavailable.
- For a 3D asset that must land directly in Studio, prefer the available Roblox generate_mesh or
  generate_procedural_model tool. Treat those as persistent actions that require user approval.
- Use model_3d_prompt only when an external Hunyuan3D artifact/preview materially helps the task.
- Do not claim a test passed; Zenless runs and records tests after approval.
- Return one consolidated JSON object only. No markdown outside the JSON.

Schema:
{
  "summary": "what this block accomplishes",
  "actions": [
    {"tool": "exact MCP tool name", "arguments": {}, "reason": "why", "risk": "low|medium|high"}
  ],
  "visual_prompt": "optional concept prompt or empty",
  "model_3d_prompt": "optional 3D prompt or empty",
  "tests": ["exact checks Zenless should run"],
  "final_message": "short user-facing result after successful execution"
}
""".strip()


REVIEW_CONTRACT = """
You are the assigned independent reviewer. Review the proposed Roblox Studio block against the objective,
live evidence, server authority, Luau correctness, API reality, regressions, performance, and test coverage.
Do not rewrite the implementation and do not approve based on confidence alone.
Return one JSON object only:
{
  "verdict": "approve|revise|block",
  "summary": "compact evidence-based assessment",
  "issues": ["concrete issue"],
  "required_changes": ["specific correction"],
  "tests_required": ["specific test"],
  "risk": "low|medium|high|critical",
  "confidence": 0.0
}
""".strip()


FINAL_REVIEW_CONTRACT = """
You are the assigned independent FINAL reviewer. This review happens only after approved mutations,
real QA execution, bounded fixes, and reruns. Judge the final Studio state rather than the earlier proposal.
Check the user objective, final relevant source, mutation/read-back evidence, QA results, remaining warnings,
server authority, regressions, and whether any claim lacks evidence. Never approve a failed or skipped
required check. Return one JSON object only using this exact schema:
{
  "verdict": "approve|revise|block",
  "summary": "compact evidence-based final assessment",
  "issues": ["concrete final-state issue"],
  "required_changes": ["smallest required correction"],
  "tests_required": ["specific rerun"],
  "risk": "low|medium|high|critical",
  "confidence": 0.0
}
""".strip()


VISUAL_MASTER_CONTRACT = """
You are the Visual Designer for one Roblox-ready object. Convert the request into one immutable master
specification shared by all six orthographic views. Do not generate an image yet. Return JSON only:
{
  "identity": "single object identity",
  "proportions": "dimensions and relative proportions",
  "materials": ["material and finish"],
  "colors": ["named color plus hex when useful"],
  "features": ["distinctive feature and exact placement"],
  "orientation": "front/back/left/right/top/bottom orientation rules",
  "background": "neutral background and consistent framing"
}
Every field must be concrete enough to reproduce the same object from every direction.
""".strip()


def compact_json(value: Any, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[context truncated by Zenless]"


def principal_prompt(
    objective: str,
    context: dict[str, Any],
    tools: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    round_index: int,
    effort: str = "AUTO",
) -> str:
    raw_brain = context.get("brain")
    brain: dict[str, Any] = raw_brain if isinstance(raw_brain, dict) else {}
    blocks = ", ".join(str(item) for item in brain.get("review_blocks", [])) or "GLOBAL"
    return (
        f"{POLICY_ENGINE.render(role='BUILDER', task=objective, effort=effort, block=blocks)}\n\n"
        f"{PRINCIPAL_CONTRACT}\n\n"
        f"REVIEW BLOCKS:\n{compact_json(brain.get('review_blocks', []), 2_000)}\n\n"
        f"RESEARCH ROUND: {round_index}\n\n"
        f"LIVE STUDIO CONTEXT:\n{compact_json(context, 44_000)}\n\n"
        f"AVAILABLE MCP TOOLS:\n{compact_json(tools, 38_000)}\n\n"
        f"EVIDENCE FROM PRIOR READ ACTIONS:\n{compact_json(evidence, 40_000)}"
    )


def review_prompt(
    objective: str,
    context: dict[str, Any],
    proposal: AgentProposal,
    evidence: list[dict[str, Any]],
) -> str:
    raw_brain = context.get("brain")
    brain: dict[str, Any] = raw_brain if isinstance(raw_brain, dict) else {}
    blocks = ", ".join(str(item) for item in brain.get("review_blocks", [])) or "GLOBAL"
    effort = str(context.get("effort") or "AUTO")
    return (
        f"{POLICY_ENGINE.render(role='REVIEWER', task=objective, effort=effort, block=blocks)}\n\n"
        f"{REVIEW_CONTRACT}\n\n"
        f"LIVE STUDIO CONTEXT:\n{compact_json(context, 30_000)}\n\n"
        f"PRINCIPAL PROPOSAL:\n{compact_json(proposal.to_dict(), 48_000)}\n\n"
        f"READ EVIDENCE:\n{compact_json(evidence, 36_000)}"
    )


def revision_prompt(
    objective: str,
    context: dict[str, Any],
    proposal: AgentProposal,
    review: ReviewResult,
    user_note: str = "",
) -> str:
    note = user_note.strip() or "No additional user note."
    raw_brain = context.get("brain")
    brain: dict[str, Any] = raw_brain if isinstance(raw_brain, dict) else {}
    blocks = ", ".join(str(item) for item in brain.get("review_blocks", [])) or "GLOBAL"
    effort = str(context.get("effort") or "AUTO")
    return (
        f"{POLICY_ENGINE.render(role='BUILDER', task=objective, effort=effort, block=blocks)}\n\n"
        f"{PRINCIPAL_CONTRACT}\n\n"
        "Revise the proposal once, addressing every required change. Do not repeat unchanged read calls.\n\n"
        f"USER OBJECTIVE:\n{objective}\n\n"
        f"LIVE CONTEXT:\n{compact_json(context, 28_000)}\n\n"
        f"PREVIOUS PROPOSAL:\n{compact_json(proposal.to_dict(), 42_000)}\n\n"
        f"INDEPENDENT REVIEW:\n{compact_json(review.to_dict(), 24_000)}\n\n"
        f"USER NOTE:\n{note}"
    )


def repair_prompt(
    objective: str,
    proposal: AgentProposal,
    console_output: str,
    source_evidence: list[dict[str, Any]],
    effort: str = "AUTO",
) -> str:
    return (
        f"{POLICY_ENGINE.render(role='BUILDER', task=objective, effort=effort, block='A')}\n\n"
        f"{PRINCIPAL_CONTRACT}\n\n"
        "The approved block was applied and the real Play Test produced errors. Propose the smallest repair block.\n\n"
        f"ORIGINAL OBJECTIVE:\n{objective}\n\n"
        f"APPLIED PROPOSAL:\n{compact_json(proposal.to_dict(), 30_000)}\n\n"
        f"REAL STUDIO OUTPUT:\n{console_output[:30_000]}\n\n"
        f"POST-APPLY SOURCE EVIDENCE:\n{compact_json(source_evidence, 30_000)}"
    )


def final_review_prompt(
    objective: str,
    final_state: dict[str, Any],
    mutation_evidence: list[dict[str, Any]],
    qa_result: dict[str, Any],
    remaining_warnings: list[str],
    effort: str = "AUTO",
) -> str:
    return (
        f"{POLICY_ENGINE.render(role='REVIEWER', task=objective, effort=effort, block='GLOBAL')}\n\n"
        f"{FINAL_REVIEW_CONTRACT}\n\n"
        f"FINAL STUDIO STATE AND RELEVANT SOURCE:\n{compact_json(final_state, 52_000)}\n\n"
        f"MUTATION AND READ-BACK EVIDENCE:\n{compact_json(mutation_evidence, 42_000)}\n\n"
        f"QA RESULT:\n{compact_json(qa_result, 24_000)}\n\n"
        f"REMAINING WARNINGS:\n{compact_json(remaining_warnings, 10_000)}"
    )


def visual_master_prompt(objective: str, visual_prompt: str, user_note: str = "") -> str:
    note = user_note.strip() or "No additional revision note."
    return (
        f"{POLICY_ENGINE.render(role='VISUAL', task=objective, block='B')}\n\n"
        f"{VISUAL_MASTER_CONTRACT}\n\n"
        f"DESIGN DIRECTION:\n{visual_prompt}\n\n"
        f"REVISION NOTE:\n{note}"
    )


def visual_view_prompt(master_spec: dict[str, Any], view: str) -> str:
    return (
        f"{POLICY_ENGINE.render(role='VISUAL', task=f'Generate the {view} view.', block='B')}\n\n"
        "Generate exactly ONE production concept image, not a contact sheet and not multiple variants. "
        f"Show the {view.upper()} orthographic view of the SAME object defined below. "
        "Use no perspective, no isometric angle, no labels, no dimensions, no text, and no extra objects. "
        "Keep neutral background, centered framing, scale, materials, colors, proportions, and details "
        "consistent with the other five views. The image must be a clean square PNG suitable as a "
        "multi-view 3D reference.\n\nMASTER SPECIFICATION:\n" + compact_json(master_spec, 16_000)
    )


def visual_qa_prompt(master_spec: dict[str, Any], version: int) -> str:
    return (
        f"{POLICY_ENGINE.render(role='VISUAL QA', task='Validate six orthographic views.', block='B')}\n\n"
        "Inspect the six attached PNG files named front, back, left, right, top, and bottom. They must show "
        "the same object from six distinct orthographic directions and match the master specification. "
        "Reject duplicated directions, perspective/isometric framing, contact sheets, inconsistent geometry, "
        "materials, colors, proportions, or missing files. Return JSON only: "
        '{"approved":true,"failed_views":[],"warnings":[],"summary":"..."}. '
        f"Concept version: {version}.\nMASTER SPECIFICATION:\n{compact_json(master_spec, 16_000)}"
    )
