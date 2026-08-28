from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .brain import BrainAnalysis, ZenlessBrain
from .browser_bridge import BridgeError
from .models import (
    TERMINAL_STAGES,
    AgentProposal,
    InvalidStageTransition,
    PipelineEvent,
    ProposalAction,
    ReviewResult,
    Stage,
    TaskOptions,
    validate_stage_transition,
)
from .policy import classify_action, is_read_only, validate_proposal
from .prompts import principal_prompt, repair_prompt, review_prompt, revision_prompt
from .protocol import ProtocolError, extract_json_object
from .store import SQLiteStore, now_iso
from .studio_mcp import MCPError, StudioMCPClient

EventCallback = Callable[[PipelineEvent], None]
QACallback = Callable[[str, str, threading.Event, list[dict[str, Any]], bool], str]


class AgentTransport(Protocol):
    def wait_for_provider(self, provider: str, timeout: float = 0.0) -> bool: ...

    def send_prompt(self, provider: str, prompt: str, *, task_id: str, timeout: float = 360.0) -> str: ...

    def request(
        self,
        provider: str,
        action: str,
        payload: dict[str, Any],
        *,
        task_id: str,
        timeout: float,
    ) -> dict[str, Any]: ...


class OrchestratorError(RuntimeError):
    pass


class TaskCancelled(OrchestratorError):
    pass


@dataclass(slots=True)
class _ApprovalGate:
    event: threading.Event = field(default_factory=threading.Event)
    decision: str = ""
    note: str = ""


class ZenlessOrchestrator:
    def __init__(
        self,
        *,
        store: SQLiteStore,
        bridge: AgentTransport,
        studio: StudioMCPClient,
        run_root: Path,
        event_callback: EventCallback | None = None,
        play_test_seconds: float = 5.0,
        brain: ZenlessBrain | None = None,
        qa_callback: QACallback | None = None,
    ) -> None:
        self.store = store
        self.bridge = bridge
        self.studio = studio
        self.run_root = run_root
        self.event_callback = event_callback
        self.play_test_seconds = max(1.0, min(30.0, play_test_seconds))
        self.brain = brain or ZenlessBrain()
        self.qa_callback = qa_callback
        self._run_lock = threading.Lock()
        self._tasks: dict[str, threading.Thread] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._pause: dict[str, threading.Event] = {}
        self._paused_from: dict[str, Stage] = {}
        self._gates: dict[tuple[str, str], _ApprovalGate] = {}
        self._state_lock = threading.RLock()
        self.current_task_id = ""

    def submit(
        self,
        prompt: str,
        options: TaskOptions,
        *,
        attachment_paths: tuple[Path, ...] = (),
    ) -> str:
        objective = prompt.strip()
        if not objective:
            raise ValueError("O pedido está vazio.")
        task_id = uuid.uuid4().hex
        cancel_event = threading.Event()
        pause_event = threading.Event()
        thread = threading.Thread(
            target=self._run_guarded,
            args=(task_id, objective, options, cancel_event, attachment_paths),
            name=f"Zenless-Task-{task_id[:8]}",
            daemon=True,
        )
        with self._state_lock:
            if self._tasks:
                raise OrchestratorError(
                    "Já existe uma tarefa ativa. Conclua, rejeite ou feche a etapa atual antes de enviar outro pedido."
                )
            try:
                self.store.create_task(task_id, objective, options)
                self._tasks[task_id] = thread
                self._cancel[task_id] = cancel_event
                self._pause[task_id] = pause_event
                self.current_task_id = task_id
                self.store.append_message(task_id, "User", "user", objective)
                self._emit(task_id, Stage.NEW, "Pedido recebido e colocado na fila.")
                thread.start()
            except Exception:
                self._tasks.pop(task_id, None)
                self._cancel.pop(task_id, None)
                self._pause.pop(task_id, None)
                raise
        return task_id

    def approve(self, task_id: str, gate: str, decision: str, note: str = "") -> bool:
        normalized = decision.strip().lower()
        if normalized not in {"approve", "reject", "edit"}:
            raise ValueError("Decisão de aprovação inválida.")
        with self._state_lock:
            target = self._gates.get((task_id, gate))
        if target is None:
            return False
        target.decision = normalized
        target.note = note.strip()
        self.store.record_approval(task_id, gate, normalized, target.note)
        target.event.set()
        return True

    def approve_active(self, task_id: str, prefixes: tuple[str, ...], decision: str, note: str = "") -> bool:
        with self._state_lock:
            names = [gate for owner, gate in self._gates if owner == task_id and gate.startswith(prefixes)]
        if not names:
            return False
        return self.approve(task_id, names[-1], decision, note)

    def cancel(self, task_id: str) -> bool:
        with self._state_lock:
            event = self._cancel.get(task_id)
        if event is None:
            return False
        event.set()
        with self._state_lock:
            pause_event = self._pause.get(task_id)
        if pause_event is not None:
            pause_event.clear()
        return True

    def pause(self, task_id: str) -> bool:
        with self._state_lock:
            pause_event = self._pause.get(task_id)
            task = self.store.load_task(task_id)
            if pause_event is None or task is None:
                return False
            current = Stage(str(task["stage"]))
            if current in TERMINAL_STAGES or current == Stage.PAUSED:
                return False
            self._paused_from[task_id] = current
            pause_event.set()
        self._emit(task_id, Stage.PAUSED, "Tarefa pausada em um checkpoint seguro.", "warning")
        return True

    def resume(self, task_id: str) -> bool:
        with self._state_lock:
            pause_event = self._pause.get(task_id)
            previous = self._paused_from.pop(task_id, None)
            if pause_event is None or previous is None:
                return False
            pause_event.clear()
        self._emit(task_id, previous, "Tarefa retomada.")
        return True

    def active_task(self) -> dict[str, Any] | None:
        task_id = self.current_task_id
        return self.store.load_task(task_id) if task_id else None

    @property
    def busy(self) -> bool:
        with self._state_lock:
            return bool(self._tasks)

    def wait_for_idle(self, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._state_lock:
                threads = list(self._tasks.values())
            if not threads:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if threads[0].is_alive():
                threads[0].join(timeout=min(0.1, remaining))
            else:
                time.sleep(min(0.01, remaining))

    def _run_guarded(
        self,
        task_id: str,
        objective: str,
        options: TaskOptions,
        cancel_event: threading.Event,
        attachment_paths: tuple[Path, ...],
    ) -> None:
        try:
            with self._run_lock:
                self._run(task_id, objective, options, cancel_event, attachment_paths)
        except TaskCancelled as exc:
            self._finish_error(task_id, Stage.BLOCKED, str(exc))
        except BridgeError as exc:
            self._finish_error(task_id, Stage.BLOCKED, str(exc))
        except (MCPError, ProtocolError, OrchestratorError) as exc:
            self._finish_error(task_id, Stage.FAILED, str(exc))
        except Exception as exc:
            self._finish_error(task_id, Stage.FAILED, f"Falha interna controlada: {exc}")
        finally:
            with self._state_lock:
                self._tasks.pop(task_id, None)
                self._cancel.pop(task_id, None)
                self._pause.pop(task_id, None)
                self._paused_from.pop(task_id, None)
                stale = [key for key in self._gates if key[0] == task_id]
                for key in stale:
                    self._gates.pop(key, None)

    def _run(
        self,
        task_id: str,
        objective: str,
        options: TaskOptions,
        cancel_event: threading.Event,
        attachment_paths: tuple[Path, ...],
    ) -> None:
        self._check_control(task_id, cancel_event)
        self._emit(task_id, Stage.COLLECTING_CONTEXT, "Lendo o projeto real no Roblox Studio.")
        if not self.studio.running:
            self.studio.start()
        studios = self.studio.list_studios()
        if not studios:
            raise OrchestratorError("Nenhuma instância do Roblox Studio está conectada ao StudioMCP.")
        target = studios[0]
        self.store.update_task(task_id, studio_id=target.studio_id)
        analysis = self.brain.analyze(
            objective,
            independent_review=options.independent_review,
            create_3d=options.create_3d_asset,
        )
        context = self._collect_context(task_id, target.studio_id, analysis)
        self.store.update_task(task_id, context_json=context)

        if not self.bridge.wait_for_provider("chatgpt", timeout=2):
            raise BridgeError("ChatGPT requer login no WebView2 ou Playwright interno.")
        if attachment_paths:
            self._emit(task_id, Stage.COLLECTING_CONTEXT, "Enviando anexos validados ao ChatGPT.")
            uploaded = self.bridge.request(
                "chatgpt",
                "upload_files",
                {"files": [str(path) for path in attachment_paths]},
                task_id=task_id,
                timeout=120,
            )
            if str(uploaded.get("status", "ok")).casefold() != "ok":
                raise BridgeError("O provedor recusou os anexos desta tarefa.")

        proposal, evidence = self._build_proposal(
            task_id,
            objective,
            context,
            target.studio_id,
            cancel_event,
        )
        proposal, review = self._review_and_revise(
            task_id,
            objective,
            context,
            proposal,
            evidence,
            options,
            cancel_event,
        )
        self.store.update_task(
            task_id,
            proposal_json=proposal.to_dict(),
            review_json=review.to_dict() if review else {},
        )

        self._handle_visual_and_3d(task_id, proposal, options, cancel_event)

        mutating = [action for action in proposal.actions if not is_read_only(action.tool)]
        if not mutating:
            final_text = proposal.final_message or proposal.summary or "Nenhuma alteração persistente foi necessária."
            self.store.append_message(task_id, "ChatGPT", "assistant", final_text)
            self.store.update_task(task_id, final_text=final_text)
            self._emit(task_id, Stage.COMPLETE, "Concluído sem alterações persistentes.", "success")
            return

        if options.require_approval:
            gate_round = 0
            while True:
                gate_round += 1
                gate_name = f"changes:{gate_round}"
                detail = self._proposal_detail(proposal, review)
                decision, note = self._wait_gate(
                    task_id,
                    gate_name,
                    Stage.WAITING_CHANGE_APPROVAL,
                    "Alterações prontas; aguardando sua aprovação antes do Studio.",
                    detail,
                    cancel_event,
                )
                if decision == "reject":
                    self._emit(task_id, Stage.BLOCKED, "Alterações rejeitadas pelo usuário.", "warning", note)
                    return
                if decision == "edit":
                    self._emit(task_id, Stage.REVISING, "ChatGPT ajustando a proposta conforme sua observação.")
                    proposal = self._request_revision(task_id, objective, context, proposal, review, note)
                    proposal, review = self._review_and_revise(
                        task_id,
                        objective,
                        context,
                        proposal,
                        evidence,
                        options,
                        cancel_event,
                        initial_review=False,
                    )
                    self.store.update_task(
                        task_id,
                        proposal_json=proposal.to_dict(),
                        review_json=review.to_dict() if review else {},
                    )
                    mutating = [action for action in proposal.actions if not is_read_only(action.tool)]
                    if not mutating:
                        self._emit(task_id, Stage.COMPLETE, "Revisão concluiu que nenhuma escrita era necessária.", "success")
                        return
                    continue
                break

        self._emit(task_id, Stage.APPLYING, "Aplicando o bloco aprovado via StudioMCP.")
        apply_evidence = self._apply_actions(task_id, target.studio_id, mutating)

        if options.automatic_play_test:
            console_output = self._run_quality_test(
                task_id, target.studio_id, cancel_event, apply_evidence, False
            )
            fix_count = 0
            while self._console_has_errors(console_output):
                if not options.auto_fix_errors or fix_count >= options.max_test_fixes:
                    raise OrchestratorError(
                        "O Play Test retornou erros e o limite de correções foi atingido.\n" + console_output[-6000:]
                    )
                fix_count += 1
                self._emit(
                    task_id,
                    Stage.REPAIRING,
                    f"ChatGPT preparando correção {fix_count}/{options.max_test_fixes} a partir do Output real.",
                    "warning",
                )
                repair = self._request_repair(task_id, objective, proposal, console_output, apply_evidence)
                repair, repair_review = self._review_and_revise(
                    task_id,
                    objective,
                    context,
                    repair,
                    apply_evidence,
                    options,
                    cancel_event,
                )
                self.store.update_task(
                    task_id,
                    proposal_json=repair.to_dict(),
                    review_json=repair_review.to_dict() if repair_review else {},
                )
                if options.require_approval:
                    decision, note = self._wait_gate(
                        task_id,
                        f"repair:{fix_count}",
                        Stage.WAITING_CHANGE_APPROVAL,
                        f"Correção {fix_count} pronta; aguardando aprovação.",
                        self._proposal_detail(repair, repair_review),
                        cancel_event,
                    )
                    if decision != "approve":
                        self._emit(task_id, Stage.BLOCKED, "Correção não aprovada.", "warning", note)
                        return
                repair_actions = [action for action in repair.actions if not is_read_only(action.tool)]
                apply_evidence.extend(self._apply_actions(task_id, target.studio_id, repair_actions))
                proposal = repair
                console_output = self._run_quality_test(
                    task_id, target.studio_id, cancel_event, apply_evidence, True
                )

        self._emit(task_id, Stage.FINAL_REVIEW, "Verificação final de segurança e estado concluída.")
        final_text = proposal.final_message or proposal.summary or "Alterações aplicadas e verificadas."
        self.store.append_message(task_id, "Orchestrator", "assistant", final_text)
        self.store.update_task(task_id, final_text=final_text)
        self._emit(task_id, Stage.COMPLETE, "Implementação concluída e liberada.", "success")

    def _collect_context(self, task_id: str, studio_id: str, analysis: BrainAnalysis) -> dict[str, Any]:
        calls: list[tuple[str, dict[str, Any]]] = [
            ("get_studio_state", {}),
            ("search_game_tree", {"datamodel_type": "Edit", "max_depth": 4, "head_limit": 350}),
            (
                "search_game_tree",
                {"datamodel_type": "Edit", "instance_type": "BaseScript", "max_depth": 8, "head_limit": 250},
            ),
            ("get_console_output", {}),
        ]
        context: dict[str, Any] = {
            "studio_id": studio_id,
            "captured_at": now_iso(),
            "brain": analysis.to_dict(),
            "reads": {},
        }
        for tool_name, arguments in calls:
            if tool_name not in self.studio.tools:
                continue
            result = self.studio.call_tool(tool_name, arguments, studio_id=studio_id, timeout=90)
            context["reads"][tool_name + f":{len(context['reads'])}"] = result.compact(28_000)
            self._emit(task_id, Stage.COLLECTING_CONTEXT, f"Contexto coletado: {tool_name}.", "success")
        context["tool_count"] = len(self.studio.tools)
        return self.brain.compact_context(context)

    def _build_proposal(
        self,
        task_id: str,
        objective: str,
        context: dict[str, Any],
        studio_id: str,
        cancel_event: threading.Event,
    ) -> tuple[AgentProposal, list[dict[str, Any]]]:
        tools = self._tool_catalog()
        evidence: list[dict[str, Any]] = []
        seen_reads: set[str] = set()
        proposal: AgentProposal | None = None
        for research_round in range(1, 3):
            self._check_control(task_id, cancel_event)
            self._emit(
                task_id,
                Stage.CREATING,
                f"ChatGPT criando o bloco estratégico (rodada {research_round}/2).",
            )
            prompt = principal_prompt(objective, context, tools, evidence, research_round)
            raw = self.bridge.send_prompt("chatgpt", prompt, task_id=task_id)
            self.store.append_message(task_id, "ChatGPT", "agent", raw)
            proposal = self._parse_proposal(raw)
            errors = validate_proposal(proposal.actions, set(self.studio.tools))
            if errors:
                raise OrchestratorError("Proposta bloqueada pela política: " + " | ".join(errors))
            reads = [action for action in proposal.actions if is_read_only(action.tool)]
            if not reads:
                break
            unique_reads: list[ProposalAction] = []
            for action in reads[:8]:
                key = json.dumps([action.tool, action.arguments], ensure_ascii=False, sort_keys=True, default=str)
                if key in seen_reads:
                    continue
                seen_reads.add(key)
                unique_reads.append(action)
            self._emit(task_id, Stage.COLLECTING_CONTEXT, "Executando leituras pedidas pelo agente principal.")
            evidence.extend(self._execute_read_actions(task_id, studio_id, unique_reads))
            if research_round == 2:
                proposal.actions = [action for action in proposal.actions if not is_read_only(action.tool)]
        if proposal is None:
            raise OrchestratorError("ChatGPT não gerou uma proposta.")
        return proposal, evidence

    def _execute_read_actions(
        self,
        task_id: str,
        studio_id: str,
        actions: list[ProposalAction],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for action in actions:
            key = json.dumps([action.tool, action.arguments], ensure_ascii=False, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            arguments = self._prepare_arguments(action.tool, action.arguments)
            result = self.studio.call_tool(action.tool, arguments, studio_id=studio_id, timeout=120)
            results.append(
                {
                    "tool": action.tool,
                    "arguments": arguments,
                    "is_error": result.is_error,
                    "result": result.compact(28_000),
                }
            )
            kind = "warning" if result.is_error else "success"
            self._emit(task_id, Stage.COLLECTING_CONTEXT, f"Leitura concluída: {action.tool}.", kind)
        return results

    def _review_and_revise(
        self,
        task_id: str,
        objective: str,
        context: dict[str, Any],
        proposal: AgentProposal,
        evidence: list[dict[str, Any]],
        options: TaskOptions,
        cancel_event: threading.Event,
        *,
        initial_review: bool = True,
    ) -> tuple[AgentProposal, ReviewResult | None]:
        if not options.independent_review:
            return proposal, None
        if not self.bridge.wait_for_provider("deepseek", timeout=2):
            raise BridgeError("DeepSeek requer login para a revisão independente.")

        review: ReviewResult | None = None
        revisions = 0
        while True:
            self._check_control(task_id, cancel_event)
            self._emit(task_id, Stage.REVIEWING, "DeepSeek revisando o bloco independentemente.")
            raw = self.bridge.send_prompt(
                "deepseek",
                review_prompt(objective, context, proposal, evidence),
                task_id=task_id,
            )
            self.store.append_message(task_id, "DeepSeek", "reviewer", raw)
            review = self._parse_review(raw)
            if review.approved:
                self._emit(task_id, Stage.REVIEWING, "Revisão independente aprovada.", "success", review.summary)
                return proposal, review
            if review.verdict == "block":
                raise OrchestratorError("DeepSeek bloqueou o bloco: " + (review.summary or "sem resumo"))
            if revisions >= options.max_revisions:
                raise OrchestratorError("Limite de revisões atingido sem aprovação independente.")
            revisions += 1
            self._emit(
                task_id,
                Stage.REVISING,
                f"ChatGPT corrigindo apontamentos ({revisions}/{options.max_revisions}).",
                "warning",
            )
            proposal = self._request_revision(task_id, objective, context, proposal, review, "")
            errors = validate_proposal(proposal.actions, set(self.studio.tools))
            if errors:
                raise OrchestratorError("Revisão gerou ações bloqueadas: " + " | ".join(errors))

    def _request_revision(
        self,
        task_id: str,
        objective: str,
        context: dict[str, Any],
        proposal: AgentProposal,
        review: ReviewResult | None,
        user_note: str,
    ) -> AgentProposal:
        effective_review = review or ReviewResult(
            verdict="revise",
            summary="O usuário pediu ajustes.",
            required_changes=[user_note] if user_note else [],
        )
        raw = self.bridge.send_prompt(
            "chatgpt",
            revision_prompt(objective, context, proposal, effective_review, user_note),
            task_id=task_id,
        )
        self.store.append_message(task_id, "ChatGPT", "agent", raw)
        return self._parse_proposal(raw)

    def _handle_visual_and_3d(
        self,
        task_id: str,
        proposal: AgentProposal,
        options: TaskOptions,
        cancel_event: threading.Event,
    ) -> None:
        if options.visual_first and proposal.visual_prompt:
            decision, note = self._wait_gate(
                task_id,
                "visual",
                Stage.WAITING_VISUAL_APPROVAL,
                "Conceito visual pronto; aguardando aprovação.",
                proposal.visual_prompt,
                cancel_event,
            )
            if decision != "approve":
                raise OrchestratorError("Conceito visual não aprovado: " + note)

        if options.create_3d_asset and proposal.model_3d_prompt:
            if not self.bridge.wait_for_provider("hunyuan", timeout=2):
                raise BridgeError("Hunyuan3D não está conectado para gerar o ativo solicitado.")
            self._emit(task_id, Stage.GENERATING_3D, "Hunyuan3D gerando o ativo aprovado.")
            response = self.bridge.request(
                "hunyuan",
                "generate_3d",
                {"prompt": proposal.model_3d_prompt, "timeout_ms": 600_000},
                task_id=task_id,
                timeout=615,
            )
            response_status = str(response.get("status", "ok")).strip().lower()
            if response_status != "ok":
                reason = str(response.get("error") or response.get("message") or "A geração 3D requer atenção.")
                raise BridgeError(reason)
            artifact_path = str(response.get("artifact_path") or "").strip()
            artifact_url = str(response.get("artifact_url") or "").strip()
            download_error = str(response.get("download_error") or "").strip()
            if download_error and not artifact_path:
                raise BridgeError("O modelo foi gerado, mas o download falhou: " + download_error)
            if not artifact_path and not artifact_url:
                raise BridgeError("Hunyuan3D concluiu sem expor um arquivo 3D para o Zenless.")
            if artifact_path and Path(artifact_path).suffix.casefold() != ".glb":
                raise BridgeError(
                    f"O modelo foi baixado como {Path(artifact_path).suffix or 'formato desconhecido'}; "
                    "a prévia integrada requer GLB."
                )
            context = {"hunyuan": response}
            task = self.store.load_task(task_id) or {}
            merged_context = dict(task.get("context") or {})
            merged_context.update(context)
            self.store.update_task(task_id, context_json=merged_context)
            detail = json.dumps(
                {
                    "name": str(response.get("artifact_name") or "Ativo 3D disponível"),
                    "path": str(response.get("artifact_path") or ""),
                    "url": str(response.get("artifact_url") or ""),
                    "download_error": str(response.get("download_error") or ""),
                },
                ensure_ascii=False,
            )
            decision, note = self._wait_gate(
                task_id,
                "3d",
                Stage.WAITING_3D_APPROVAL,
                "Modelo 3D pronto; aguardando aprovação.",
                detail,
                cancel_event,
            )
            if decision != "approve":
                raise OrchestratorError("Modelo 3D não aprovado: " + note)

    def _apply_actions(
        self,
        task_id: str,
        studio_id: str,
        actions: list[ProposalAction],
    ) -> list[dict[str, Any]]:
        run_dir = self.run_root / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        evidence: list[dict[str, Any]] = []
        for index, action in enumerate(actions, start=1):
            decision = classify_action(action, set(self.studio.tools))
            if not decision.allowed or decision.risk == "critical":
                raise OrchestratorError(
                    f"Ação {action.tool} bloqueada na aplicação: {'; '.join(decision.reasons)}"
                )
            arguments = self._prepare_arguments(action.tool, action.arguments)
            if action.tool == "multi_edit":
                self._snapshot_script(task_id, studio_id, arguments, run_dir, index)
            self._emit(
                task_id,
                Stage.APPLYING,
                f"StudioMCP aplicando {index}/{len(actions)}: {action.tool}.",
                detail=action.reason,
            )
            result = self.studio.call_tool(action.tool, arguments, studio_id=studio_id, timeout=240)
            item = {
                "tool": action.tool,
                "arguments": arguments,
                "is_error": result.is_error,
                "result": result.compact(24_000),
            }
            evidence.append(item)
            if result.is_error:
                raise OrchestratorError(f"StudioMCP falhou em {action.tool}: {result.compact(6000)}")
            if action.tool == "multi_edit":
                evidence.extend(self._verify_script(task_id, studio_id, arguments))
        (run_dir / "apply-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return evidence

    def _snapshot_script(
        self,
        task_id: str,
        studio_id: str,
        arguments: dict[str, Any],
        run_dir: Path,
        index: int,
    ) -> None:
        if arguments.get("className") or "script_read" not in self.studio.tools:
            return
        target = str(arguments.get("file_path", ""))
        if not target:
            return
        result = self.studio.call_tool(
            "script_read",
            {"target_file": target, "should_read_entire_file": True},
            studio_id=studio_id,
            timeout=90,
        )
        if result.is_error:
            raise OrchestratorError(f"Não foi possível criar snapshot de {target}: {result.compact(3000)}")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", target)[-100:] or "script"
        (run_dir / f"before-{index:02d}-{safe_name}.luau.txt").write_text(result.text, encoding="utf-8")
        self._emit(task_id, Stage.APPLYING, f"Snapshot criado antes de editar {target}.", "success")

    def _verify_script(
        self,
        task_id: str,
        studio_id: str,
        arguments: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if "script_read" not in self.studio.tools:
            return []
        target = str(arguments.get("file_path", ""))
        result = self.studio.call_tool(
            "script_read",
            {"target_file": target, "should_read_entire_file": True},
            studio_id=studio_id,
            timeout=90,
        )
        if result.is_error:
            raise OrchestratorError(f"A verificação pós-edição falhou para {target}: {result.compact(3000)}")
        self._emit(
            task_id,
            Stage.APPLYING,
            f"Fonte pós-edição relida: {target}.",
            "warning" if result.is_error else "success",
        )
        return [
            {
                "tool": "script_read",
                "arguments": {"target_file": target},
                "is_error": result.is_error,
                "result": result.compact(24_000),
            }
        ]

    def _play_test(
        self,
        task_id: str,
        studio_id: str,
        cancel_event: threading.Event,
    ) -> str:
        if "start_stop_play" not in self.studio.tools:
            raise OrchestratorError("A versão atual do StudioMCP não oferece start_stop_play.")
        self._emit(task_id, Stage.TESTING, "Iniciando Play Test real no Studio.")
        started = False
        console_output = ""
        try:
            result = self.studio.call_tool(
                "start_stop_play", {"is_start": True}, studio_id=studio_id, timeout=60
            )
            if result.is_error:
                raise OrchestratorError("Falha ao iniciar Play Test: " + result.compact(3000))
            started = True
            if cancel_event.wait(self.play_test_seconds):
                self._check_control(task_id, cancel_event)
            if "get_console_output" in self.studio.tools:
                console = self.studio.call_tool("get_console_output", {}, studio_id=studio_id, timeout=60)
                if console.is_error:
                    raise OrchestratorError("Falha ao ler o Output: " + console.compact(3000))
                console_output = console.text
        finally:
            if started:
                try:
                    stopped = self.studio.call_tool(
                        "start_stop_play", {"is_start": False}, studio_id=studio_id, timeout=60
                    )
                    if stopped.is_error:
                        raise OrchestratorError("O Studio recusou Stop: " + stopped.compact(3000))
                except MCPError as exc:
                    raise OrchestratorError(f"Falha ao parar o Play Test: {exc}") from exc
        kind = "warning" if self._console_has_errors(console_output) else "success"
        message = "Play Test retornou erros." if kind == "warning" else "Play Test concluído sem erros detectados."
        self._emit(task_id, Stage.TESTING, message, kind, console_output[-5000:])
        self.store.append_message(task_id, "Roblox Studio", "test", console_output or "[Output vazio]")
        return console_output

    def _run_quality_test(
        self,
        task_id: str,
        studio_id: str,
        cancel_event: threading.Event,
        evidence: list[dict[str, Any]],
        rerun: bool,
    ) -> str:
        self._emit(task_id, Stage.TESTING, "QA Breaker preparando testes baseados nas mudanças.")
        if self.qa_callback is not None:
            return self.qa_callback(task_id, studio_id, cancel_event, evidence, rerun)
        return self._play_test(task_id, studio_id, cancel_event)

    def _request_repair(
        self,
        task_id: str,
        objective: str,
        proposal: AgentProposal,
        console_output: str,
        source_evidence: list[dict[str, Any]],
    ) -> AgentProposal:
        raw = self.bridge.send_prompt(
            "chatgpt",
            repair_prompt(objective, proposal, console_output, source_evidence),
            task_id=task_id,
        )
        self.store.append_message(task_id, "ChatGPT", "agent", raw)
        repair = self._parse_proposal(raw)
        errors = validate_proposal(repair.actions, set(self.studio.tools))
        if errors:
            raise OrchestratorError("Correção bloqueada pela política: " + " | ".join(errors))
        return repair

    def _wait_gate(
        self,
        task_id: str,
        gate_name: str,
        stage: Stage,
        message: str,
        detail: str,
        cancel_event: threading.Event,
    ) -> tuple[str, str]:
        gate = _ApprovalGate()
        key = (task_id, gate_name)
        with self._state_lock:
            self._gates[key] = gate
        self._emit(task_id, stage, message, "warning", detail)
        try:
            while not gate.event.wait(0.25):
                self._check_control(task_id, cancel_event)
            return gate.decision, gate.note
        finally:
            with self._state_lock:
                self._gates.pop(key, None)

    def _prepare_arguments(self, tool_name: str, raw: dict[str, Any]) -> dict[str, Any]:
        arguments = dict(raw)
        arguments.pop("studio_id", None)
        tool = self.studio.tools.get(tool_name)
        if tool is None:
            return arguments
        properties = tool.input_schema.get("properties", {})
        if "datamodel_type" in properties and "datamodel_type" not in arguments:
            enum = properties["datamodel_type"].get("enum", []) if isinstance(properties["datamodel_type"], dict) else []
            arguments["datamodel_type"] = "Edit" if "Edit" in enum or not enum else enum[0]
        return arguments

    def _tool_catalog(self) -> list[dict[str, Any]]:
        catalog: list[dict[str, Any]] = []
        for tool in sorted(self.studio.tools.values(), key=lambda item: item.name):
            if tool.name in {"execute_luau", "user_keyboard_input", "user_mouse_input", "start_stop_play"}:
                continue
            catalog.append(
                {
                    "name": tool.name,
                    "description": tool.description[:1200],
                    "inputSchema": tool.input_schema,
                }
            )
        return catalog

    @staticmethod
    def _parse_proposal(raw: str) -> AgentProposal:
        data = extract_json_object(raw)
        proposal = AgentProposal.from_dict(data, raw)
        if not proposal.summary and not proposal.final_message:
            raise ProtocolError("A proposta não contém summary nem final_message.")
        if len(proposal.actions) > 16:
            raise ProtocolError("A proposta excede 16 ações.")
        if any(not action.tool for action in proposal.actions):
            raise ProtocolError("A proposta contém uma ação sem nome de ferramenta.")
        return proposal

    @staticmethod
    def _parse_review(raw: str) -> ReviewResult:
        data = extract_json_object(raw)
        review = ReviewResult.from_dict(data, raw)
        if review.verdict not in {"approve", "approved", "revise", "block"}:
            raise ProtocolError(f"Veredito de revisão inválido: {review.verdict}")
        if not review.summary:
            raise ProtocolError("A revisão não contém summary.")
        return review

    @staticmethod
    def _console_has_errors(output: str) -> bool:
        if not output.strip():
            return False
        return bool(re.search(r"(?im)(\bexception\b|\btraceback\b|stack begin|(^|\s)error[:\s])", output))

    @staticmethod
    def _proposal_detail(proposal: AgentProposal, review: ReviewResult | None) -> str:
        payload = {
            "summary": proposal.summary,
            "actions": [asdict(action) for action in proposal.actions if not is_read_only(action.tool)],
            "review": review.to_dict() if review else None,
            "tests": proposal.tests,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)[:80_000]

    def _check_control(self, task_id: str, cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise TaskCancelled("Tarefa cancelada pelo usuário.")
        with self._state_lock:
            pause_event = self._pause.get(task_id)
        while pause_event is not None and pause_event.is_set():
            if cancel_event.wait(0.1):
                raise TaskCancelled("Tarefa cancelada pelo usuário.")

    def _emit(
        self,
        task_id: str,
        stage: Stage,
        message: str,
        kind: str = "info",
        detail: str = "",
    ) -> None:
        event = PipelineEvent(task_id, stage, message, kind, detail, now_iso())
        waiting = stage in {
            Stage.WAITING_VISUAL_APPROVAL,
            Stage.WAITING_3D_APPROVAL,
            Stage.WAITING_CHANGE_APPROVAL,
            Stage.PAUSED,
        }
        status = "complete" if stage == Stage.COMPLETE else ("blocked" if stage == Stage.BLOCKED else ("failed" if stage == Stage.FAILED else ("waiting" if waiting else "running")))
        try:
            current = self.store.load_task(task_id)
            if current is not None:
                validate_stage_transition(str(current["stage"]), stage)
            self.store.update_task(task_id, stage=stage, status=status)
            self.store.append_event(event)
        except InvalidStageTransition:
            raise
        except KeyError:
            pass
        if self.event_callback is not None:
            self.event_callback(event)

    def _finish_error(self, task_id: str, stage: Stage, message: str) -> None:
        try:
            self.store.update_task(task_id, error=message)
            self.store.append_message(task_id, "Orchestrator", "error", message)
        except KeyError:
            return
        self._emit(task_id, stage, message, "error")
