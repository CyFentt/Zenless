from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from zenless.brain import BrainAnalysis
from zenless.core import ZenlessCore
from zenless.event_bus import EventBus
from zenless.models import PipelineEvent, Stage, TaskOptions
from zenless.orchestrator import ZenlessOrchestrator
from zenless.qa_breaker import QABreaker
from zenless.qa_breaker import TestPlan as _TestPlan
from zenless.store import SQLiteStore
from zenless.studio_discovery import StudioDiscoveryManager
from zenless.studio_mcp import MCPToolResult, StudioTarget


class _ContractBridge:
    def __init__(self, capabilities: dict[str, Any] | None = None) -> None:
        self.capabilities = capabilities or {}
        self.capability_calls: list[tuple[str, str]] = []
        self.search_calls: list[tuple[str, str]] = []

    def wait_for_provider(self, _provider: str, timeout: float = 0.0) -> bool:
        del timeout
        return True

    def request(
        self,
        provider: str,
        action: str,
        _payload: dict[str, Any],
        *,
        task_id: str,
        timeout: float,
    ) -> dict[str, Any]:
        del timeout
        if action == "capabilities":
            self.capability_calls.append((provider, task_id))
            return {"status": "ok", "capabilities": dict(self.capabilities)}
        return {"status": "ok"}

    def send_prompt(
        self,
        provider: str,
        prompt: str,
        *,
        task_id: str,
        timeout: float = 360.0,
        stream_callback: Any = None,
    ) -> str:
        del prompt, timeout, stream_callback
        self.search_calls.append((provider, task_id))
        return "Authoritative provider research evidence"


class _ContractStudio:
    def __init__(self, target: StudioTarget | None = None) -> None:
        self.target = target or StudioTarget("studio-main", "Active Studio", {})
        self.running = True
        self.tools = {
            "list_roblox_studios": object(),
            "get_studio_state": object(),
            "search_game_tree": object(),
            "get_console_output": object(),
        }
        self.calls: list[tuple[str, str]] = []

    def start(self) -> None:
        self.running = True

    def list_studios(self) -> list[StudioTarget]:
        return [self.target]

    def call_tool(
        self,
        name: str,
        _arguments: dict[str, Any],
        *,
        studio_id: str,
        timeout: float,
    ) -> MCPToolResult:
        del timeout
        self.calls.append((name, studio_id))
        text = "[]" if name == "search_game_tree" else '{"state":"Edit"}'
        return MCPToolResult(name, text, False, ("text",))


class _ApprovalOrchestrator:
    def approve_active(self, *_args: Any, **_kwargs: Any) -> bool:
        return True


def _analysis(
    *intents: str,
    scopes: tuple[str, ...] = (),
    requires_mutation: bool = True,
) -> BrainAnalysis:
    return BrainAnalysis(
        fingerprint="contract",
        intents=intents or ("code",),
        keywords=("contract",),
        scopes=scopes,
        providers=("chatgpt",),
        requires_mutation=requires_mutation,
        review_blocks=("A",),
    )


def _make_core(root: Path) -> ZenlessCore:
    core = object.__new__(ZenlessCore)
    core.data_root = root.resolve()
    core.store = SQLiteStore(root / "state.db")
    core.events = EventBus()
    core._active_activities = {}
    core._connections_lock = threading.RLock()
    core._connections = {"studio": "READY"}
    core._studio_tree = []
    core.orchestrator = _ApprovalOrchestrator()
    return core


class BackendContractTests(unittest.TestCase):
    def test_generation_failures_publish_terminal_states_and_survive_reload(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = _make_core(root)
            core.store.create_task("visual-fail", "Generate visual", TaskOptions())
            core.store.update_context_section("visual-fail", "visual", {"status": "GENERATING", "version": 1})
            core._publish_visual_generation("visual-fail", 1)
            core.store.update_task("visual-fail", stage=Stage.BLOCKED, status="blocked")
            core._on_pipeline_event(PipelineEvent("visual-fail", Stage.BLOCKED, "Provider connection lost"))

            visual_events = [event for event in core.events.recent(50) if event.type == "VISUAL_GENERATION_CHANGED"]
            self.assertEqual([event.data["state"] for event in visual_events[-6:]], ["FAILED"] * 6)
            reopened = _make_core(root)
            self.assertEqual(reopened.visual("visual-fail")["concept"]["status"], "FAILED")
            self.assertEqual({item["state"] for item in reopened.visual("visual-fail")["views"]}, {"FAILED"})

            core.store.create_task("model-fail", "Generate model", TaskOptions())
            geometry_path = root / "geometry.glb"
            geometry_path.write_bytes(b"glTF")
            core.store.register_asset(
                "geometry-v1", job_id="model-fail", name=geometry_path.name, kind="GLB",
                path=geometry_path, mime="model/gltf-binary", metadata={"phase": "geometry", "version": 1},
            )
            core._publish_model_generation("model-fail", 1)
            core.store.update_task("model-fail", stage=Stage.BLOCKED, status="blocked")
            core._on_pipeline_event(PipelineEvent("model-fail", Stage.BLOCKED, "Texture generation failed"))

            model_events = [event for event in core.events.recent(50) if event.type == "MODEL_GENERATION_CHANGED"]
            self.assertEqual({event.data["target"] for event in model_events[-2:]}, {"geometry", "texture"})
            self.assertEqual([event.data["state"] for event in model_events[-2:]], ["FAILED", "FAILED"])
            self.assertEqual(reopened.model("model-fail")["state"], "FAILED")
            self.assertNotIn("modelUrl", reopened.model("model-fail"))

    def test_partial_geometry_never_becomes_a_ready_final_model(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = _make_core(root)
            core.store.create_task("partial-model", "Generate model", TaskOptions())
            core.store.update_task("partial-model", stage=Stage.GENERATING_3D, status="running")
            geometry_path = root / "geometry.glb"
            geometry_path.write_bytes(b"glTF")
            core.store.register_asset(
                "geometry-v1", job_id="partial-model", name=geometry_path.name, kind="GLB",
                path=geometry_path, mime="model/gltf-binary", metadata={"phase": "geometry", "version": 1},
            )

            model = core.model("partial-model")

            self.assertEqual(model["state"], "GENERATING")
            self.assertNotIn("modelUrl", model)

    def test_job_scoped_events_expose_top_level_job_id(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = _make_core(root)
            job_id = "job-contract"
            core.store.create_task(job_id, "Implement the contract", TaskOptions())
            core.store.update_task(
                job_id,
                proposal_json={
                    "actions": [
                        {
                            "tool": "multi_edit",
                            "arguments": {"file_path": "game.ServerScriptService.Main", "edits": []},
                        }
                    ]
                },
                review_json={"verdict": "approve", "summary": "Verified", "risk": "low"},
            )
            core.store.replace_context_items(
                job_id,
                [
                    {
                        "id": "context-item",
                        "job_id": job_id,
                        "name": "ServerScriptService",
                        "type": "Service",
                        "path": "game.ServerScriptService",
                        "relevance": 1.0,
                        "state": "included",
                        "raw": {},
                    }
                ],
            )

            core._on_pipeline_event(PipelineEvent(job_id, Stage.NEW, "Queued", "stream_start", "chatgpt"))
            core._on_pipeline_event(PipelineEvent(job_id, Stage.NEW, "Queued", "stream_delta", "delta"))
            core._on_pipeline_event(PipelineEvent(job_id, Stage.NEW, "Queued", "stream_finish"))
            core._on_pipeline_event(PipelineEvent(job_id, Stage.NEW, "Queued"))
            core._on_pipeline_event(PipelineEvent(job_id, Stage.WAITING_CHANGE_APPROVAL, "Review ready"))
            core._on_pipeline_event(PipelineEvent(job_id, Stage.GENERATING_3D, "Generating model"))
            core._on_pipeline_event(PipelineEvent(job_id, Stage.COMPLETE, "Complete"))
            core._on_pipeline_event(PipelineEvent(job_id, Stage.FAILED, "Failed"))
            core.set_context_state("context-item", "locked")
            core.approve_model(job_id)

            core.store.create_test_run("run-contract", job_id, "SMOKE", 7)
            qa = QABreaker(store=core.store, studio=object(), bridge=object(), events=core.events)
            with (
                patch.object(
                    qa,
                    "_make_plan",
                    return_value=_TestPlan("SMOKE", "Contract", [], [], [], [], 7),
                ),
                patch.object(qa, "_check_edit_mode", return_value=("PASSED", "Edit mode", "Edit mode")),
                patch.object(qa, "_run_play_case", return_value=("", "PASSED")),
                patch.object(qa, "_review_results", return_value=""),
            ):
                qa.run(
                    job_id,
                    studio_id="studio-main",
                    profile_name="SMOKE",
                    evidence=[],
                    cancel_event=threading.Event(),
                )
            failures: list[Any] = []
            logs: list[str] = []
            qa._run_case(
                "run-contract",
                job_id,
                "failure",
                "Failure contract",
                "UNIT",
                lambda: ("FAILED", "Expected", "Actual"),
                failures,
                logs,
                7,
            )
            counts = qa._outcome_counts(["FAILED"])
            qa._publish_finished(job_id, "run-contract", "FAILED", counts)

            expected = {
                "CHAT_ACTIVITY",
                "CHAT_ARTIFACT",
                "CHAT_MESSAGE",
                "CHAT_STREAM_DELTA",
                "CHAT_STREAM_FINISHED",
                "CHAT_STREAM_STARTED",
                "CHANGES_UPDATED",
                "CONTEXT_UPDATED",
                "JOB_COMPLETE",
                "JOB_CREATED",
                "JOB_FAILED",
                "JOB_UPDATED",
                "MODEL_APPROVED",
                "MODEL_GENERATION_CHANGED",
                "PIPELINE_STATE_CHANGED",
                "REVIEW_READY",
                "TEST_CASE_FINISHED",
                "TEST_CASE_STARTED",
                "TEST_FAILURE",
                "TEST_FINISHED",
                "TEST_LOG",
                "TEST_STARTED",
            }
            observed = {event.type for event in core.events.recent(500) if event.type in expected}
            self.assertEqual(observed, expected)
            for event in core.events.recent(500):
                if event.type in expected:
                    self.assertEqual(event.data.get("jobId"), job_id, event.type)

    def test_repeated_activity_phases_preserve_cycles_and_close_previous_phase(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = _make_core(Path(folder))
            job_id = "job-activity"
            core.store.create_task(job_id, "Revise the implementation", TaskOptions())
            job = core.job(job_id)

            core._record_activity(PipelineEvent(job_id, Stage.BUILDING, "Build one"), job)
            core._record_activity(PipelineEvent(job_id, Stage.REVIEWING, "Review one"), job)
            core._record_activity(PipelineEvent(job_id, Stage.BUILDING, "Build two"), job)

            activities = core.store.list_activities(job_id)
            builds = [item for item in activities if item["phase"] == "BUILD"]
            reviews = [item for item in activities if item["phase"] == "REVIEW"]
            self.assertEqual([item["cycle"] for item in builds], [1, 2])
            self.assertEqual(len({item["id"] for item in builds}), 2)
            self.assertEqual(builds[0]["status"], "DONE")
            self.assertEqual(builds[1]["status"], "RUNNING")
            self.assertEqual(reviews[0]["status"], "DONE")
            self.assertGreater(builds[0]["finishedAt"], 0)
            self.assertGreater(reviews[0]["finishedAt"], 0)

    def test_artifact_versions_preserve_history_and_state_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = _make_core(Path(folder))
            job_id = "job-artifact"
            core.store.create_task(job_id, "Generate visual history", TaskOptions())
            first = {
                "id": "artifact-image-v1",
                "jobId": job_id,
                "type": "IMAGE",
                "name": "Visual V1",
                "state": "GENERATING",
                "version": 1,
                "revision": 1,
                "createdAt": 100,
            }
            core._publish_artifact(first)
            core._publish_artifact({**first, "state": "READY", "createdAt": 500})
            core._publish_artifact({**first, "state": "APPROVED", "createdAt": 999})
            core._publish_artifact(
                {
                    "id": "artifact-image-v2",
                    "jobId": job_id,
                    "type": "IMAGE",
                    "name": "Visual V2",
                    "state": "READY",
                    "version": 2,
                    "revision": 2,
                    "createdAt": 200,
                }
            )

            artifacts = core.store.list_artifacts(job_id)
            self.assertEqual([item["id"] for item in artifacts], ["artifact-image-v1", "artifact-image-v2"])
            self.assertEqual([item["version"] for item in artifacts], [1, 2])
            self.assertEqual([item["revision"] for item in artifacts], [1, 2])
            self.assertEqual(artifacts[0]["state"], "APPROVED")
            self.assertEqual(artifacts[0]["createdAt"], 100)
            self.assertEqual(core._next_artifact_version(job_id, "IMAGE"), 3)
            artifact_events = [event for event in core.events.recent(20) if event.type == "CHAT_ARTIFACT"]
            self.assertEqual(len(artifact_events), 4)
            self.assertTrue(all(event.data["jobId"] == job_id for event in artifact_events))
            self.assertEqual(
                [event.data["artifact"]["state"] for event in artifact_events[:3]],
                ["GENERATING", "READY", "APPROVED"],
            )

    def test_six_ready_views_emit_generation_and_ready_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = _make_core(root)
            job_id = "job-visual"
            core.store.create_task(job_id, "Generate six views", TaskOptions())
            visual: dict[str, Any] = {"version": 3, "status": "READY", "prompt": "Six views"}
            for view in ("front", "back", "left", "right", "top", "bottom"):
                asset_id = f"asset-{view}"
                path = root / f"{view}.png"
                path.write_bytes(b"png")
                core.store.register_asset(
                    asset_id,
                    job_id=job_id,
                    name=path.name,
                    kind="VIEW",
                    path=path,
                    mime="image/png",
                )
                visual[view] = {"asset_id": asset_id}
            core.store.update_context_section(job_id, "visual", visual)

            core._publish_visual_state(job_id)

            generation = [event for event in core.events.recent(20) if event.type == "VISUAL_GENERATION_CHANGED"]
            ready = [event for event in core.events.recent(20) if event.type == "VISUAL_READY"]
            expected_views = {"FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM"}
            self.assertEqual({event.data["view"] for event in generation}, expected_views)
            self.assertEqual({event.data["view"] for event in ready}, expected_views)
            self.assertEqual(len(generation), 6)
            self.assertEqual(len(ready), 6)
            for event in generation:
                self.assertEqual(event.data["jobId"], job_id)
                self.assertEqual(event.data["state"], "READY")
                self.assertEqual(event.data["conceptVersion"], 3)
                self.assertTrue(event.data["assetId"])
            for event in ready:
                self.assertEqual(event.data["jobId"], job_id)
                self.assertEqual(event.data["conceptVersion"], 3)
                self.assertTrue(event.data["assetId"])
                self.assertEqual(event.data["imageUrl"], f"/api/assets/{event.data['assetId']}/content")

            core.approve_visual(job_id)
            approved = [event for event in core.events.recent(20) if event.type == "VISUAL_APPROVED"]
            self.assertEqual(len(approved), 1)
            self.assertEqual(approved[0].data["jobId"], job_id)
            self.assertEqual(approved[0].data["conceptVersion"], 3)
            self.assertEqual(set(approved[0].data["views"]), expected_views)
            artifacts = [item for item in core.store.list_artifacts(job_id) if item["type"] == "IMAGE"]
            self.assertEqual(artifacts[-1]["state"], "APPROVED")
            self.assertEqual({view["state"] for view in core.visual(job_id)["views"]}, {"APPROVED"})

    def test_model_ready_requires_a_real_asset_and_malformed_version_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = _make_core(root)
            job_id = "job-model"
            core.store.create_task(job_id, "Generate a model", TaskOptions())

            core._register_model_from_event(
                PipelineEvent(job_id, Stage.WAITING_3D_APPROVAL, "Model result", detail='{"version":2}')
            )
            self.assertFalse(any(event.type == "MODEL_READY" for event in core.events.recent(20)))

            model_path = root / "model.glb"
            model_path.write_bytes(b"glTF")
            core._register_model_from_event(
                PipelineEvent(
                    job_id,
                    Stage.WAITING_3D_APPROVAL,
                    "Model result",
                    detail=json.dumps({"path": str(model_path), "version": "invalid"}),
                )
            )

            ready = [event for event in core.events.recent(20) if event.type == "MODEL_READY"]
            self.assertEqual(len(ready), 1)
            self.assertEqual(ready[0].data["jobId"], job_id)
            self.assertEqual(ready[0].data["version"], 1)
            self.assertTrue(ready[0].data["assetId"])
            self.assertEqual(ready[0].data["modelUrl"], f"/api/assets/{ready[0].data['assetId']}/content")
            artifacts = core.store.list_artifacts(job_id)
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(artifacts[0]["type"], "MODEL_3D")
            self.assertEqual(artifacts[0]["state"], "READY")

            core.approve_model(job_id)
            approved = [event for event in core.events.recent(20) if event.type == "MODEL_APPROVED"]
            self.assertEqual(len(approved), 1)
            self.assertEqual(approved[0].data["jobId"], job_id)
            self.assertEqual(core.store.list_artifacts(job_id)[-1]["state"], "APPROVED")

    def test_studio_identity_comes_from_selected_target_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = StudioTarget(
                "studio-authoritative",
                "Window label",
                {
                    "project": "Authoritative Project",
                    "placeId": 123,
                    "universeId": 456,
                },
            )
            studio = _ContractStudio(target)
            discovery = StudioDiscoveryManager(studio, sleeper=lambda _delay: None, retry_delays=(0.0,))
            discovery.discover()
            core = _make_core(Path(folder))
            core.studio_discovery = discovery
            core._studio_tree = [{"name": "Misleading Tree Root"}]

            state = core.studio_state()

            self.assertEqual(state["state"], "ONLINE")
            self.assertEqual(state["studioId"], "studio-authoritative")
            self.assertEqual(state["selectedStudioId"], "studio-authoritative")
            self.assertEqual(state["projectName"], "Authoritative Project")
            self.assertEqual(state["placeId"], 123)
            self.assertEqual(state["universeId"], 456)
            self.assertNotEqual(state["projectName"], core._studio_tree[0]["name"])

    def test_research_modes_execute_only_truthful_available_routes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = _ContractBridge({"supportsSearch": True})
            studio = _ContractStudio()
            orchestrator = ZenlessOrchestrator(
                store=SQLiteStore(Path(folder) / "state.db"),
                bridge=bridge,
                studio=studio,
                run_root=Path(folder) / "runs",
            )
            emitted: list[tuple[Any, ...]] = []
            orchestrator._emit = lambda *args: emitted.append(args)
            supported = {"studio_id": "studio-main", "research": {"capabilities": {"supportsSearch": True}}}
            unsupported = {"studio_id": "studio-main", "research": {"capabilities": {}}}

            off = orchestrator._perform_research(
                "job-off", "Explain the system", TaskOptions(research="OFF"), _analysis("explain"), supported
            )
            on = orchestrator._perform_research(
                "job-on", "Verify the current API", TaskOptions(research="ON"), _analysis("audit"), supported
            )
            unavailable = orchestrator._perform_research(
                "job-unavailable",
                "Verify the current API",
                TaskOptions(research="ON"),
                _analysis("audit"),
                unsupported,
            )
            auto_skipped = orchestrator._perform_research(
                "job-auto-skip",
                "Explain the module",
                TaskOptions(research="AUTO"),
                _analysis("explain", requires_mutation=False),
                supported,
            )
            auto_run = orchestrator._perform_research(
                "job-auto-run",
                "Audit the current API",
                TaskOptions(research="AUTO"),
                _analysis("audit"),
                supported,
            )

            self.assertEqual(off["state"], "DISABLED")
            self.assertEqual(on["state"], "DONE")
            self.assertEqual(on["evidence"][0]["evidence_type"], "PROVIDER_BUILTIN_SEARCH")
            self.assertEqual(unavailable["state"], "UNAVAILABLE")
            self.assertEqual(unavailable["warning"], "RESEARCH UNAVAILABLE")
            self.assertEqual(auto_skipped["state"], "NOT_REQUIRED")
            self.assertEqual(auto_run["state"], "DONE")
            self.assertEqual(bridge.search_calls, [("chatgpt", "job-on"), ("chatgpt", "job-auto-run")])
            lifecycle = [(args[0], args[3]) for args in emitted]
            self.assertEqual(
                lifecycle,
                [
                    ("job-on", "research_running"),
                    ("job-on", "research_done"),
                    ("job-auto-run", "research_running"),
                    ("job-auto-run", "research_done"),
                ],
            )

    def test_auto_effort_resolves_to_distinct_profiles(self) -> None:
        low = ZenlessOrchestrator._resolve_effort(
            TaskOptions(effort="AUTO", risk_level="low"),
            _analysis("explain", requires_mutation=False),
            {"project_index": []},
        )
        medium = ZenlessOrchestrator._resolve_effort(
            TaskOptions(effort="AUTO", risk_level="medium"),
            _analysis("code", scopes=("ServerScriptService",)),
            {"project_index": []},
        )
        maximum = ZenlessOrchestrator._resolve_effort(
            TaskOptions(effort="AUTO", risk_level="high"),
            _analysis("debug", scopes=("ServerScriptService", "ReplicatedStorage")),
            {"project_index": [{} for _ in range(24)]},
        )
        explicit = ZenlessOrchestrator._resolve_effort(
            TaskOptions(effort="MINIMUM", risk_level="high"),
            _analysis("debug"),
            {"project_index": [{} for _ in range(24)]},
        )

        self.assertEqual(low.effort, "MINIMUM")
        self.assertEqual(medium.effort, "MEDIUM")
        self.assertEqual(maximum.effort, "MAXIMUM")
        self.assertEqual(explicit.effort, "MINIMUM")

    def test_project_and_temp_contexts_differ_without_skipping_fresh_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = SQLiteStore(root / "state.db")
            store.create_task("prior-job", "Repair movement authority", TaskOptions())
            store.update_task(
                "prior-job",
                studio_id="studio-main",
                final_text="Movement authority was repaired and verified with a server-side check.",
            )
            bridge = _ContractBridge({"supportsSearch": True})
            studio = _ContractStudio()
            orchestrator = ZenlessOrchestrator(
                store=store,
                bridge=bridge,
                studio=studio,
                run_root=root / "runs",
            )
            orchestrator._emit = lambda *_args: None

            project = orchestrator._conversation_context(
                "project-job", "studio-main", "Extend movement authority", "PROJECT"
            )
            temporary = orchestrator._conversation_context(
                "temp-job", "studio-main", "Extend movement authority", "TEMP"
            )
            project_snapshot = orchestrator._collect_context(
                "project-job", "studio-main", _analysis("code", scopes=("ServerScriptService",))
            )
            temp_snapshot = orchestrator._collect_context(
                "temp-job", "studio-main", _analysis("code", scopes=("ServerScriptService",))
            )

            self.assertEqual(project["mode"], "PROJECT")
            self.assertEqual(project["parentJobId"], "prior-job")
            self.assertIn("Movement authority", project["handoffSummary"])
            self.assertEqual(temporary["mode"], "TEMP")
            self.assertEqual(temporary["conversationId"], "temp-job")
            self.assertEqual(temporary["parentJobId"], "")
            self.assertEqual(temporary["handoffSummary"], "")
            self.assertEqual(project_snapshot["studio_id"], "studio-main")
            self.assertEqual(temp_snapshot["studio_id"], "studio-main")
            self.assertEqual(bridge.capability_calls, [("chatgpt", "project-job"), ("chatgpt", "temp-job")])
            names = [name for name, _studio_id in studio.calls]
            self.assertEqual(names.count("get_studio_state"), 2)
            self.assertEqual(names.count("search_game_tree"), 4)
            self.assertEqual(names.count("get_console_output"), 2)


if __name__ == "__main__":
    unittest.main()
