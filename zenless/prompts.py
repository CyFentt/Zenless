from __future__ import annotations

import json
from typing import Any

from .models import AgentProposal, ReviewResult

_RUBRA_POLICY_TEXT = """
All generated game content, identifiers, user-facing development artifacts, plans, tests and source code must be written in English.
Generated Luau must be production-quality and contain no comments. Do not emit tutorial comments, explanatory comments, TODO comments or version suffixes such as v2, v3, final2 or new.
Prefer existing project architecture and proven upstream libraries over reimplementing infrastructure.
Read the relevant existing scripts and project state before proposing changes.
The objective may ask to create, inspect, review, debug, or repair an existing game. Follow that intent instead of assuming every request is a new build. Use the live Studio inventory, properties, sources, console, and QA evidence. Inventory coverage and source coverage are different: never claim unread scripts or unseen gameplay were reviewed.
Treat server authority, remote validation, bounded work, cleanup, cancellation, deterministic state and measurable performance as default requirements.
Use the supplied Rubra skill excerpts as authoritative project guidance when they apply.
Do not claim a capability was tested unless there is direct evidence from Studio, a static tool, a runtime test, a screenshot, a log, a read-back or an independent reviewer.
After implementation, run the strongest available static, structural, runtime, visual, security and regression checks. Repair failures and re-run the affected checks.
When continuous verification is enabled, continue until the verification matrix is green, progress has converged, a capability is genuinely unavailable, or the user cancels.
"""

RUBRA_ENGINEERING_POLICY = _RUBRA_POLICY_TEXT.strip()



PRINCIPAL_CONTRACT = RUBRA_ENGINEERING_POLICY + "\n" + """
You are the principal implementation agent inside Rubra for the live Roblox Studio project.
Rubra, not the browser page, is the authority that executes MCP tools. You may only PROPOSE tool calls.

Rules:
- Inspect and extend the existing Studio architecture. Never assume the project is only local files.
- Server owns game state. Validate every remote argument server-side. Never use InvokeClient.
- Use strict Luau for new modules, task APIs, connection cleanup, and streaming-aware design.
- Never invent Roblox APIs. If current API evidence is missing, propose an official-doc read action first.
- Prefer multi_edit for persistent source changes. For scene, UI instances, lighting, geometry or other object/property changes, execute_luau is available in Edit mode with bounded code and _zenless_expected_instances: exact game paths mapped to all properties that should change, with expected JSON values. Rubra snapshots those properties, checks concurrent changes, applies once, and reads them back. Do not use it for background loops. Do not propose keyboard/mouse input or play controls; Rubra owns the test lifecycle.
- Use Roblox's rbx-docs-search skill/http_get when an API needs current verification.
- For a 3D asset that must land directly in Studio, prefer the available Roblox generate_mesh or
  generate_procedural_model tool. Treat those as persistent actions that require user approval.
- Use model_3d_prompt only when an external Hunyuan3D artifact/preview materially helps the task.
- Do not claim a test passed; Rubra runs and records tests after approval.
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


REVIEW_CONTRACT = RUBRA_ENGINEERING_POLICY + "\n" + """
You are the independent DeepSeek reviewer. Review the proposed Roblox Studio block against the objective,
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


FINAL_REVIEW_CONTRACT = RUBRA_ENGINEERING_POLICY + "\n" + """
You are the independent DeepSeek FINAL reviewer. This review happens only after approved mutations,
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


VISUAL_MASTER_CONTRACT = RUBRA_ENGINEERING_POLICY + "\n" + """
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
    text = json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str)
    if len(text) <= limit:
        return text

    def clip(item: Any, string_limit: int, list_limit: int, depth: int = 0) -> Any:
        if depth > 16:
            return '[nested context omitted]'
        if isinstance(item, str):
            return item if len(item) <= string_limit else item[:string_limit] + '\n[excerpt; additional evidence required]'
        if isinstance(item, list):
            return [clip(child, string_limit, list_limit, depth + 1) for child in item[:list_limit]]
        if isinstance(item, dict):
            return {str(key): clip(child, string_limit, list_limit, depth + 1) for key, child in item.items()}
        return item

    for scale in (4096, 2048, 1024, 512, 256, 128, 64, 16):
        clipped = clip(value, scale, max(1, scale // 32))
        text = json.dumps(clipped, ensure_ascii=False, separators=(',', ':'), default=str)
        if len(text) <= limit:
            return text
    return json.dumps({'rubra_context_omitted': True, 'reason': 'Request narrower live evidence.'})


def principal_prompt(
    objective: str,
    context: dict[str, Any],
    tools: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    round_index: int,
) -> str:
    return (
        f"{PRINCIPAL_CONTRACT}\n\n"
        f"USER OBJECTIVE:\n{objective}\n\n"
        f"RESEARCH ROUND: {round_index}\n\n"
        f"LIVE STUDIO CONTEXT:\n{compact_json(context, 44_000)}\n\n"
        f"AVAILABLE MCP TOOLS:\n{compact_json(tools, 38_000)}\n\n"
        f"EVIDENCE FROM PRIOR READ ACTIONS:\n{compact_json(evidence, 40_000)}"
    )



def research_prompt(objective: str, context: dict[str, Any]) -> str:
    return (
        RUBRA_ENGINEERING_POLICY
        + "\nYou are Rubra's independent research and visual-reasoning agent. "
        + "Investigate the Roblox-specific objective, challenge assumptions, identify current API or design risks, "
        + "and return concise implementation evidence for the builder. Do not invent APIs and do not propose unsafe "
        + "client-authoritative game logic.\n\nUSER OBJECTIVE:\n"
        + objective
        + "\n\nLIVE CONTEXT:\n"
        + compact_json(context, 36000)
    )

def review_prompt(
    objective: str,
    context: dict[str, Any],
    proposal: AgentProposal,
    evidence: list[dict[str, Any]],
) -> str:
    return (
        f"{REVIEW_CONTRACT}\n\n"
        f"USER OBJECTIVE:\n{objective}\n\n"
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
    return (
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
) -> str:
    return (
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
) -> str:
    return (
        f"{FINAL_REVIEW_CONTRACT}\n\n"
        f"USER OBJECTIVE:\n{objective}\n\n"
        f"FINAL STUDIO STATE AND RELEVANT SOURCE:\n{compact_json(final_state, 52_000)}\n\n"
        f"MUTATION AND READ-BACK EVIDENCE:\n{compact_json(mutation_evidence, 42_000)}\n\n"
        f"QA RESULT:\n{compact_json(qa_result, 24_000)}\n\n"
        f"REMAINING WARNINGS:\n{compact_json(remaining_warnings, 10_000)}"
    )


def visual_master_prompt(objective: str, visual_prompt: str, user_note: str = "") -> str:
    note = user_note.strip() or "No additional revision note."
    return (
        f"{VISUAL_MASTER_CONTRACT}\n\n"
        f"USER OBJECTIVE:\n{objective}\n\n"
        f"DESIGN DIRECTION:\n{visual_prompt}\n\n"
        f"REVISION NOTE:\n{note}"
    )


def visual_view_prompt(master_spec: dict[str, Any], view: str) -> str:
    return (
        "Generate exactly ONE production concept image, not a contact sheet and not multiple variants. "
        f"Show the {view.upper()} orthographic view of the SAME object defined below. "
        "Use no perspective, no isometric angle, no labels, no dimensions, no text, and no extra objects. "
        "Keep neutral background, centered framing, scale, materials, colors, proportions, and details "
        "consistent with the other five views. The image must be a clean square PNG suitable as a "
        "multi-view 3D reference.\n\nMASTER SPECIFICATION:\n" + compact_json(master_spec, 16_000)
    )


def visual_qa_prompt(master_spec: dict[str, Any], version: int) -> str:
    return (
        "Inspect the six attached PNG files named front, back, left, right, top, and bottom. They must show "
        "the same object from six distinct orthographic directions and match the master specification. "
        "Reject duplicated directions, perspective/isometric framing, contact sheets, inconsistent geometry, "
        "materials, colors, proportions, or missing files. Return JSON only: "
        '{"approved":true,"failed_views":[],"warnings":[],"summary":"..."}. '
        f"Concept version: {version}.\nMASTER SPECIFICATION:\n{compact_json(master_spec, 16_000)}"
    )
