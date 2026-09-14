from __future__ import annotations

import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from zenless.agent_gateway import AgentGateway
from zenless.attachments import ArchiveExtractor, ArchivePolicy, AttachmentError
from zenless.core import ZenlessCore
from zenless.models import TaskOptions
from zenless.orchestrator import ZenlessOrchestrator
from zenless.provider_registry import (
    BUILTIN_MANIFESTS,
    EXPERT_HINT,
    AuthSignals,
    AuthState,
    ProviderSpec,
    evaluate_auth,
    normalize_capabilities,
)
from zenless.provider_sessions import ProviderSessionStore
from zenless.research_broker import ResearchBroker, ResearchError
from zenless.scenario_qa import ScenarioCompiler, ScenarioExecutor
from zenless.storage import StorageManager
from zenless.store import SQLiteStore
from zenless.studio_discovery import StudioDiscoveryManager, StudioReadiness
from zenless.studio_mcp import MCPToolResult, StudioTarget, find_studio_mcp
from zenless.uninstall import UninstallError, UninstallManager


class _RouteTransport:
    def __init__(self, data_root: Path, *, ready: bool, state: str) -> None:
        self.data_root = data_root
        self.provider_specs = {"chatgpt": object(), "deepseek": object(), "hunyuan": object()}
        self.ready = ready
        self.state = state
        self.running = False
        self.wait_calls: list[str] = []

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def wait_for_provider(self, provider: str, _timeout: float) -> bool:
        self.wait_calls.append(provider)
        return self.ready

    def provider_status(self) -> dict[str, dict[str, str]]:
        return {"chatgpt": {"state": self.state, "transport": "test"}}

    def request(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        return {"status": "ok", "capabilities": {"send_text": True}}


class _DiscoveryClient:
    def __init__(self, responses: list[list[StudioTarget]]) -> None:
        self.responses = responses
        self.running = False
        self.tools = {"list_roblox_studios": object()}
        self.calls = 0

    def start(self) -> None:
        self.running = True

    def list_studios(self) -> list[StudioTarget]:
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


class _ScenarioStudio:
    def __init__(self) -> None:
        self.tools = {"start_stop_play": object(), "get_console_output": object(), "screen_capture": object()}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        studio_id: str,
        timeout: float,
    ) -> MCPToolResult:
        del studio_id, timeout
        self.calls.append((name, arguments))
        content = ("image",) if name == "screen_capture" else ("text",)
        return MCPToolResult(name, "clean output", False, content)


class _BatchBridge:
    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def request(
        self,
        _provider: str,
        action: str,
        payload: dict[str, object],
        *,
        task_id: str,
        timeout: float,
    ) -> dict[str, object]:
        del task_id, timeout
        if action == "capabilities":
            return {"capabilities": {"upload_files": True, "max_image_inputs": 2}}
        self.batches.append(list(payload["files"]))
        return {"status": "ok"}


class _ResearchTransport:
    def __init__(self) -> None:
        self.calls = 0

    def send_prompt(self, provider: str, prompt: str, *, task_id: str, timeout: float = 360) -> str:
        del timeout
        self.calls += 1
        return f"{provider}:{task_id}:{prompt[:8]}"


class BackendVNextTests(unittest.TestCase):
    def test_login_signals_take_priority_over_composer_signals(self) -> None:
        spec = ProviderSpec(
            "hunyuan",
            "https://example.invalid/",
            ("textarea",),
            ("button[type='submit']",),
            (),
            (),
            login_url_patterns=("/login",),
            authenticated_url_patterns=("/create",),
            composer_markers=("textarea",),
            account_markers=("[class*='avatar']",),
        )
        state = evaluate_auth(
            spec,
            AuthSignals("https://example.invalid/login", unauthenticated=True, composer=False, send=True),
        )
        self.assertEqual(state, AuthState.LOGIN_REQUIRED)
        self.assertEqual(
            evaluate_auth(spec, AuthSignals("https://example.invalid/create", composer=True, send=True)),
            AuthState.AUTHENTICATED,
        )

    def test_chatgpt_public_composer_does_not_impersonate_an_authenticated_session(self) -> None:
        spec = ProviderSpec(
            "chatgpt",
            "https://example.invalid/",
            ("textarea",),
            ("button[type='submit']",),
            (),
            (),
            composer_markers=("textarea",),
            account_markers=("[data-testid='profile-button']",),
        )

        self.assertEqual(
            evaluate_auth(spec, AuthSignals("https://example.invalid/", composer=True, send=True)),
            AuthState.UNKNOWN,
        )
        self.assertEqual(
            evaluate_auth(spec, AuthSignals("https://example.invalid/", composer=True, account=True, send=True)),
            AuthState.AUTHENTICATED,
        )

    def test_provider_catalog_and_mode_capabilities_are_explicit(self) -> None:
        self.assertEqual({manifest.id for manifest in BUILTIN_MANIFESTS}, {"chatgpt", "deepseek", "hunyuan"})
        self.assertFalse(EXPERT_HINT.supports_files)
        normalized = normalize_capabilities(
            {"get_models": True, "max_image_inputs": 6, "file_types": ["image/png", ".lua"]}
        )
        self.assertTrue(normalized["select_model"])
        self.assertTrue(normalized["get_models"])
        self.assertEqual(normalized["maxFiles"], 6)
        self.assertEqual(normalized["acceptedExtensions"], [".lua"])
        malformed = normalize_capabilities(
            {"upload_files": True, "max_image_inputs": "unknown", "acceptedMimeTypes": "image/png"}
        )
        self.assertEqual(malformed["maxFiles"], 0)
        self.assertEqual(malformed["acceptedMimeTypes"], [])

    def test_task_intent_does_not_force_3d_for_code(self) -> None:
        plain = TaskOptions.from_api({}).resolve("Fix the ragdoll service script")
        loader = TaskOptions.from_api({}).resolve("Fix the texture loader and mesh cache code")
        model = TaskOptions.from_api({}).resolve("Create a 3D mesh for the bomb")
        self.assertFalse(plain.create_3d_asset)
        self.assertFalse(plain.visual_first)
        self.assertFalse(loader.create_3d_asset)
        self.assertFalse(loader.visual_first)
        self.assertTrue(model.create_3d_asset)
        self.assertTrue(model.visual_first)

    def test_transitional_auth_states_are_not_ready_routes(self) -> None:
        self.assertFalse(AgentGateway._status_ready({"state": "Authenticated"}))
        self.assertFalse(AgentGateway._status_ready({"state": "Verifying Persistence"}))
        self.assertTrue(AgentGateway._status_ready({"state": "Ready"}))

    def test_selected_transitional_route_is_not_hidden_by_idle_alternate(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            gateway = AgentGateway(
                managed=_RouteTransport(root, ready=False, state="Verifying Persistence"),
                embedded=_RouteTransport(root, ready=False, state="Login Required"),
            )
            gateway.select_route("chatgpt", "playwright")
            status = gateway.provider_status()["chatgpt"]
            self.assertEqual(status["state"], "Verifying Persistence")
            self.assertEqual(status["route"], "playwright")

    def test_quota_state_is_not_hidden_by_an_idle_alternate_route(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            gateway = AgentGateway(
                managed=_RouteTransport(root, ready=True, state="Ready"),
                embedded=_RouteTransport(root, ready=False, state="Quota Exhausted"),
            )
            gateway.select_route("chatgpt", "webview2")

            status = gateway.provider_status()["chatgpt"]

            self.assertEqual(status["state"], "Quota Exhausted")
            self.assertEqual(status["route"], "webview2")

    def test_route_selection_persists_and_valid_managed_route_wins(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = AgentGateway(
                managed=_RouteTransport(root, ready=True, state="Ready"),
                embedded=_RouteTransport(root, ready=False, state="Standby"),
            )
            first.select_route("chatgpt", "playwright")
            managed = _RouteTransport(root, ready=True, state="Ready")
            embedded = _RouteTransport(root, ready=False, state="Standby")
            restored = AgentGateway(managed=managed, embedded=embedded)
            self.assertEqual(restored.selected_route("chatgpt"), "playwright")
            self.assertTrue(restored.wait_for_provider("chatgpt", 1))
            self.assertEqual(managed.wait_calls, ["chatgpt"])
            self.assertEqual(embedded.wait_calls, [])
            restored.select_route("chatgpt", "webview2")
            status = restored.provider_status()["chatgpt"]
            self.assertEqual(status["route"], "playwright")

    def test_provider_session_metadata_survives_restart_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "provider-sessions.json"
            sessions = ProviderSessionStore(path)
            sessions.mark_ready("deepseek", "playwright", "browser-profile")
            sessions.update_selection("deepseek", model="current", mode="expert")
            sessions.update_capabilities("deepseek", {"supportsText": True, "supportsFiles": False})
            restored = ProviderSessionStore(path).get("deepseek").public()
            self.assertEqual(restored["healthState"], "READY")
            self.assertEqual(restored["lastSuccessfulRoute"], "playwright")
            self.assertEqual(restored["selectedMode"], "expert")
            raw = path.read_text(encoding="utf-8").casefold()
            self.assertNotIn("password", raw)
            self.assertNotIn("cookie", raw)

    def test_corrupt_provider_metadata_does_not_block_startup(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "provider-sessions.json").write_bytes(b"\xff")
            (root / "provider-routes.json").write_bytes(b"\xff")
            sessions = ProviderSessionStore(root / "provider-sessions.json")
            self.assertEqual(sessions.get("chatgpt").health_state, "UNKNOWN")
            gateway = AgentGateway(
                managed=_RouteTransport(root, ready=False, state="Login Required"),
                embedded=_RouteTransport(root, ready=False, state="Login Required"),
            )
            self.assertEqual(gateway.selected_route("chatgpt"), "")

    def test_live_provider_health_replaces_stale_ready_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ProviderSessionStore(root / "provider-sessions.json").mark_ready("chatgpt", "playwright", "browser-profile")
            gateway = AgentGateway(
                managed=_RouteTransport(root, ready=False, state="Login Required"),
                embedded=_RouteTransport(root, ready=False, state="Login Required"),
            )
            gateway.provider_status()
            self.assertEqual(gateway.session_metadata("chatgpt")["healthState"], "LOGIN_REQUIRED")

    def test_research_broker_uses_only_advertised_routes(self) -> None:
        transport = _ResearchTransport()
        broker = ResearchBroker(transport)
        self.assertEqual(broker.routes({}, ()), ["DIRECT_OFFICIAL_FETCH"])
        with self.assertRaises(ResearchError):
            broker.provider_search("chatgpt", "current API", "decision", {}, task_id="job")
        evidence = broker.provider_search(
            "chatgpt",
            "current API",
            "decision",
            {"supportsSearch": True},
            task_id="job",
        )
        self.assertEqual(evidence.evidence_type, "PROVIDER_BUILTIN_SEARCH")
        self.assertEqual(transport.calls, 1)
        with self.assertRaises(ResearchError):
            broker.fetch_official("https://example.invalid/", "decision")

    def test_studio_discovery_retries_and_never_picks_first_when_ambiguous(self) -> None:
        one = StudioTarget("one", "One", {"placeId": 1})
        two = StudioTarget("two", "Two", {"placeId": 2})
        client = _DiscoveryClient([[], [one, two]])
        manager = StudioDiscoveryManager(client, sleeper=lambda _delay: None, retry_delays=(0.0, 0.0))
        result = manager.discover()
        self.assertEqual(result.state, StudioReadiness.MULTIPLE_STUDIOS)
        self.assertIsNone(result.selected)
        selected = manager.select("two")
        self.assertEqual(selected.selected, two)

    def test_running_studio_directory_controls_mcp_pairing(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"LOCALAPPDATA": folder}):
            versions = Path(folder) / "Roblox" / "Versions"
            old = versions / "version-old"
            new = versions / "version-new"
            for directory in (old, new):
                directory.mkdir(parents=True)
                (directory / "StudioMCP.exe").write_bytes(b"mcp")
                (directory / "RobloxStudioBeta.exe").write_bytes(b"studio")
            with patch("zenless.studio_mcp._running_studio_directories", return_value={old.resolve()}):
                self.assertEqual(find_studio_mcp(), old / "StudioMCP.exe")

    def test_scenario_compiler_reaches_bounded_executor(self) -> None:
        studio = _ScenarioStudio()
        scenario = ScenarioCompiler().compile(["Moving player near the wall with visual capture"], maximum=4)[0]
        result = ScenarioExecutor(studio).execute(
            scenario,
            studio_id="studio-1",
            cancel=threading.Event(),
            deadline=10**12,
        )
        self.assertEqual(result.status, "SKIPPED")
        self.assertEqual(studio.calls[0], ("start_stop_play", {"is_start": True}))
        self.assertEqual(studio.calls[-1], ("start_stop_play", {"is_start": False}))
        self.assertTrue(any(name == "get_console_output" for name, _ in studio.calls))

    def test_role_swaps_drive_preflight_and_attachment_routing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.store = SQLiteStore(Path(folder) / "state.db")
            core.store.set_setting(
                "provider.roles",
                {"deepseek": ["BUILDER", "VISUAL"], "chatgpt": ["REVIEWER"], "hunyuan": ["3D"]},
            )
            core._connections_lock = threading.Lock()
            core._connections = {
                "chatgpt": "READY",
                "deepseek": "READY",
                "hunyuan": "LOGIN",
                "studio": "OFF",
            }
            bridge = _RouteTransport(Path(folder), ready=False, state="Login Required")
            core.bridge = bridge
            core._preflight_providers(TaskOptions(chat_mode="TEMP"))
            self.assertEqual(bridge.wait_calls, [])
            routed: list[str] = []
            core._preflight_providers = lambda _options: core._resolved_role_providers()
            core._prepare_attachment_delivery = lambda paths, provider: (routed.append(provider) or paths, "")
            core.create_job = lambda *_args, **_kwargs: {"id": "job"}
            core.messages = lambda _job_id: [{"id": "message", "role": "user"}]
            result = core.send_chat("Review this", None, (Path(folder) / "input.txt",), {"chatMode": "TEMP"})
            self.assertEqual(result, {"messageId": "message", "jobId": "job"})
            self.assertEqual(routed, ["deepseek"])

    def test_provider_file_batches_preserve_every_file(self) -> None:
        bridge = _BatchBridge()
        orchestrator = object.__new__(ZenlessOrchestrator)
        orchestrator.bridge = bridge
        orchestrator._emit = lambda *_args, **_kwargs: None
        paths = tuple(Path(f"file-{index}.txt") for index in range(5))
        orchestrator._upload_attachments("chatgpt", "job", paths)
        self.assertEqual([len(batch) for batch in bridge.batches], [2, 2, 1])
        self.assertEqual([item for batch in bridge.batches for item in batch], [str(path) for path in paths])

    def test_archive_path_traversal_and_bomb_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            traversal = root / "traversal.zip"
            with zipfile.ZipFile(traversal, "w") as archive:
                archive.writestr("../escape.txt", "blocked")
            with self.assertRaises(AttachmentError) as traversal_error:
                ArchiveExtractor().inspect(traversal)
            self.assertEqual(traversal_error.exception.code, "ARCHIVE_PATH_TRAVERSAL")
            bomb = root / "bomb.zip"
            with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("zeros.bin", b"0" * 1024 * 1024)
            with self.assertRaises(AttachmentError) as bomb_error:
                ArchiveExtractor(ArchivePolicy(max_compression_ratio=10)).inspect(bomb)
            self.assertEqual(bomb_error.exception.code, "ARCHIVE_RATIO_LIMIT")

    def test_storage_budget_evicts_disposable_files_and_preserves_state(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch.object(StorageManager, "MIN_BUDGET_BYTES", 1):
            root = Path(folder)
            (root / "zenless.db").write_bytes(b"database")
            profile = root / "browser-profile"
            profile.mkdir()
            (profile / "session.dat").write_bytes(b"session")
            temporary = root / "tmp"
            temporary.mkdir()
            (temporary / "old.part").write_bytes(b"x" * 1024)
            cache = profile / "Default" / "Cache"
            cache.mkdir(parents=True)
            (cache / "entry.bin").write_bytes(b"x" * 1024)
            manager = StorageManager(root, budget_bytes=16)
            result = manager.cleanup_to_budget()
            self.assertGreater(result.bytes_removed, 0)
            self.assertTrue((root / "zenless.db").is_file())
            self.assertTrue((profile / "session.dat").is_file())
            self.assertFalse((cache / "entry.bin").exists())

    def test_test_evidence_becomes_stale_after_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            store.create_task("job", "Fix", TaskOptions())
            store.create_test_run("run", "job", "STANDARD", 1)
            store.finish_test_run("run", "PASSED", {})
            self.assertEqual(store.invalidate_test_runs("job"), 1)
            self.assertEqual(store.latest_test_run("job")["status"], "STALE")

    def test_model_contract_never_returns_pending_state(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.store = SQLiteStore(Path(folder) / "state.db")
            core.store.create_task("job", "Fix code", TaskOptions())
            payload = core.model("job")
            self.assertEqual(payload["state"], "IDLE")
            self.assertEqual(payload["geometryStatus"], "IDLE")
            self.assertNotIn("PENDING", payload.values())

    def test_uninstall_scope_cannot_escape_owned_directories(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"LOCALAPPDATA": folder}):
            local = Path(folder)
            manager = UninstallManager(local / "Programs" / "Zenless", local / "Zenless")
            plan = manager.plan("FULL_REMOVE")
            self.assertEqual(plan.owned_targets, (local / "Programs" / "Zenless", local / "Zenless"))
            with self.assertRaises(UninstallError):
                manager._validate_root(local, local / "Zenless")

    def test_uninstall_modes_schedule_only_the_requested_data_scope(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"LOCALAPPDATA": folder}):
            local = Path(folder)
            install = local / "Programs" / "Zenless"
            install.mkdir(parents=True)
            (install / "Uninstall Zenless.exe").write_bytes(b"uninstaller")
            manager = UninstallManager(install, local / "Zenless")
            with patch("zenless.uninstall.os.getpid", return_value=4242), patch(
                "zenless.uninstall.subprocess.Popen"
            ) as launch:
                manager.execute("KEEP_SETTINGS")
                keep_command = launch.call_args.args[0]
                self.assertEqual(
                    keep_command,
                    [str(install / "Uninstall Zenless.exe"), "/S", "/KEEPDATA", "/WAITPID=4242"],
                )
                self.assertEqual(launch.call_args.kwargs["cwd"], str(local))
                repeated = manager.execute("KEEP_SETTINGS")
                self.assertTrue(repeated["alreadyScheduled"])
                self.assertEqual(launch.call_count, 1)
            manager = UninstallManager(install, local / "Zenless")
            with patch("zenless.uninstall.os.getpid", return_value=4242), patch(
                "zenless.uninstall.subprocess.Popen"
            ) as launch:
                manager.execute("FULL_REMOVE")
                remove_command = launch.call_args.args[0]
                self.assertEqual(
                    remove_command,
                    [str(install / "Uninstall Zenless.exe"), "/S", "/REMOVEDATA", "/WAITPID=4242"],
                )
            manager = UninstallManager(install, local / "Zenless")
            with patch("zenless.uninstall.subprocess.Popen", side_effect=OSError("blocked")):
                with self.assertRaises(UninstallError):
                    manager.execute("FULL_REMOVE")

    def test_frozen_portable_path_cannot_schedule_installed_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"LOCALAPPDATA": folder}):
            local = Path(folder)
            portable = local / "Portable" / "Zenless.exe"
            with (
                patch("zenless.uninstall.sys.frozen", True, create=True),
                patch("zenless.uninstall.sys.executable", str(portable)),
            ):
                manager = UninstallManager(local / "Programs" / "Zenless", local / "Zenless")
            with self.assertRaises(UninstallError):
                manager.plan("FULL_REMOVE")


if __name__ == "__main__":
    unittest.main()
