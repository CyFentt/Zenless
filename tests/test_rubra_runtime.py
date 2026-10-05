from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zenless.local_ai import LocalAIService
from zenless.project_index import ProjectIndexService
from zenless.static_quality import StaticCheck, StaticQualityRunner
from zenless.tool_registry import ToolRegistry
from zenless.toolchain import ToolchainError, ToolchainManager


class RubraRuntimeTests(unittest.TestCase):
    def test_optional_npm_failure_does_not_stop_later_packages(self) -> None:
        class Process:
            def __init__(self, returncode: int, output: str) -> None:
                self.returncode = returncode
                self.output = output

            def communicate(self, timeout: float | None = None):
                return self.output, None

        with tempfile.TemporaryDirectory(prefix="rubra spaced path ") as folder:
            root = Path(folder)
            (root / "assets").mkdir()
            (root / "assets/toolchain.json").write_text(json.dumps({"npm": [
                {"id": "optional", "package": "optional@1.0.0"},
                {"id": "next", "package": "next@1.0.0"},
            ]}))
            node = root / "runtime/node/node.exe"
            npm = node.parent / "node_modules/npm/bin/npm-cli.js"
            npm.parent.mkdir(parents=True)
            node.write_bytes(b"node")
            npm.write_text("npm")
            manager = ToolchainManager(resource_root=root, portable_root=root)
            results = []
            with (
                patch.object(manager, "path", return_value=node),
                patch("zenless.toolchain.subprocess.Popen", side_effect=[
                    Process(1, "failed"),
                    Process(0, "installed"),
                ]) as execute,
            ):
                manager._ensure_npm_packages(results)
            self.assertEqual([result.state for result in results], ["failed", "ready"])
            self.assertEqual(execute.call_args.args[0][:2], [str(node), str(npm)])
            self.assertFalse((root / "runtime/npm/.rubra-packages/optional").exists())
            self.assertTrue((root / "runtime/npm/.rubra-packages/next").exists())

    def test_npm_provisioning_terminates_when_tool_preparation_is_cancelled(self) -> None:
        class CancellingProcess:
            returncode = -15

            def __init__(self, manager: ToolchainManager) -> None:
                self.manager = manager
                self.calls = 0
                self.terminated = False

            def communicate(self, timeout: float | None = None):
                self.calls += 1
                if self.calls == 1:
                    self.manager.cancel_event.set()
                    raise subprocess.TimeoutExpired("npm", timeout or 0)
                return "cancelled", None

            def terminate(self) -> None:
                self.terminated = True

            def kill(self) -> None:
                self.returncode = -9

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "assets").mkdir()
            (root / "assets/toolchain.json").write_text(json.dumps({"npm": [
                {"id": "required", "package": "required@1.0.0", "critical": True},
            ]}))
            node = root / "runtime/node/node.exe"
            npm = node.parent / "node_modules/npm/bin/npm-cli.js"
            npm.parent.mkdir(parents=True)
            node.write_bytes(b"node")
            npm.write_text("npm")
            manager = ToolchainManager(resource_root=root, portable_root=root)
            process = CancellingProcess(manager)
            with (
                patch.object(manager, "path", return_value=node),
                patch("zenless.toolchain.subprocess.Popen", return_value=process),
                self.assertRaises(ToolchainError),
            ):
                manager._ensure_npm_packages([])
            self.assertTrue(process.terminated)

    def test_static_quality_process_is_terminated_on_cancel(self) -> None:
        class Process:
            returncode = -15

            def __init__(self, cancel: threading.Event) -> None:
                self.cancel = cancel
                self.calls = 0
                self.terminated = False

            def communicate(self, timeout: float | None = None):
                self.calls += 1
                if self.calls == 1:
                    self.cancel.set()
                    raise subprocess.TimeoutExpired("stylua", timeout or 0)
                return "cancelled", None

            def terminate(self) -> None:
                self.terminated = True

            def kill(self) -> None:
                self.returncode = -9

        cancel = threading.Event()
        process = Process(cancel)
        with patch("zenless.static_quality.subprocess.Popen", return_value=process):
            result = StaticQualityRunner._run_command(
                "StyLua check",
                ["stylua.exe", "--check", "."],
                Path("."),
                60,
                cancel,
            )
        self.assertTrue(process.terminated)
        self.assertEqual(result.status, "FAILED")
        self.assertIn("Cancelled", result.output)

    def test_static_quality_timeout_kills_process(self) -> None:
        class Process:
            returncode = -9

            def __init__(self) -> None:
                self.killed = False

            def communicate(self, timeout: float | None = None):
                raise subprocess.TimeoutExpired("stylua", timeout or 0)

            def terminate(self) -> None:
                raise AssertionError("timeout must kill the process directly")

            def kill(self) -> None:
                self.killed = True

        process = Process()
        with (
            patch("zenless.static_quality.subprocess.Popen", return_value=process),
            patch("zenless.static_quality.time.monotonic", side_effect=[0.0, 11.0]),
        ):
            result = StaticQualityRunner._run_command("StyLua", ["stylua"], Path("."), 10)
        self.assertTrue(process.killed)
        self.assertEqual(result.status, "FAILED")
        self.assertIn("Timed out", result.output)

    def test_static_quality_pipeline_stops_after_cancelled_check(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "game.lua").write_text("return 1", encoding="utf-8")
            runner = StaticQualityRunner(root)
            cancel = threading.Event()

            def cancel_check(*_args, **_kwargs):
                cancel.set()
                return StaticCheck("StyLua", "FAILED", "Cancelled.")

            with (
                patch.object(runner, "_tool", return_value=Path("tool.exe")),
                patch.object(runner, "_run_command", side_effect=cancel_check) as execute,
            ):
                checks = runner.run(root, cancel_event=cancel)

            self.assertEqual(execute.call_count, 1)
            self.assertEqual(len(checks), 1)
            self.assertIn("Cancelled", checks[0].output)

    def test_project_metadata_is_scoped_to_known_nonsecret_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "default.project.json").write_text('{"name":"Game"}', encoding="utf-8")
            (root / "pesde.toml").write_text('[package]\nname = "game"\n', encoding="utf-8")
            (root / ".env").write_text("SECRET=value", encoding="utf-8")
            service = ProjectIndexService(root / "rubra")
            service.configure(str(root))

            metadata = service.project_metadata()

            self.assertIn("default.project.json", metadata)
            self.assertIn("pesde.toml", metadata)
            self.assertNotIn(".env", metadata)
            self.assertNotIn("SECRET", json.dumps(metadata))

    def test_static_quality_subprocess_is_terminated_on_cancel(self) -> None:
        class Process:
            returncode = -15

            def __init__(self) -> None:
                self.calls = 0
                self.terminated = False

            def communicate(self, timeout: float | None = None):
                self.calls += 1
                if self.calls == 1:
                    raise subprocess.TimeoutExpired("stylua", timeout or 0)
                return "cancelled", None

            def terminate(self) -> None:
                self.terminated = True

            def kill(self) -> None:
                self.returncode = -9

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            process = Process()
            cancel = threading.Event()
            cancel.set()
            with patch("zenless.static_quality.subprocess.Popen", return_value=process):
                check = StaticQualityRunner._run_command("StyLua", ["stylua"], root, 30, cancel)
            self.assertTrue(process.terminated)
            self.assertEqual(check.status, "FAILED")
            self.assertIn("Cancelled", check.output)

    def test_local_ai_prefers_vulkan_then_cpu(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            vulkan = root / "runtime" / "local-ai" / "llama-vulkan" / "llama-server.exe"
            cpu = root / "runtime" / "local-ai" / "llama-cpu" / "nested" / "llama-server.exe"
            vulkan.parent.mkdir(parents=True)
            cpu.parent.mkdir(parents=True)
            vulkan.write_bytes(b"vulkan")
            cpu.write_bytes(b"cpu")

            service = LocalAIService(root)
            candidates = service._server_candidates()

            self.assertEqual(candidates, [(vulkan, True), (cpu, False)])

    def test_toolchain_rejects_modified_installed_raw_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            assets = root / "assets"
            assets.mkdir()
            payload = b"verified-tool"
            digest = hashlib.sha256(payload).hexdigest()
            manifest = {
                "artifacts": [
                    {
                        "id": "fake",
                        "kind": "raw",
                        "target": "runtime/tools/fake.exe",
                        "marker": "fake.exe",
                        "sha256": digest,
                    }
                ],
                "sources": [],
                "npm": [],
            }
            (assets / "toolchain.json").write_text(json.dumps(manifest), encoding="utf-8")
            target = root / "runtime" / "tools" / "fake.exe"
            target.parent.mkdir(parents=True)
            target.write_bytes(payload)
            manager = ToolchainManager(resource_root=root, portable_root=root)
            manager._state["fake"] = {
                "sha256": digest,
                "target": str(target),
                "size": len(payload),
            }

            self.assertTrue(manager._artifact_ready(manifest["artifacts"][0], target))

            target.write_bytes(b"tampered")
            self.assertFalse(manager._artifact_ready(manifest["artifacts"][0], target))

    def test_tool_registry_has_unique_pinned_entries(self) -> None:
        root = Path(__file__).resolve().parents[1]
        registry = ToolRegistry(root, root)

        descriptors = registry.descriptors()
        identifiers = [item["id"] for item in descriptors]

        self.assertTrue(descriptors)
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertTrue(any(item["name"].startswith("Rojo ") for item in descriptors))
        self.assertTrue(any(item["id"] == "source:code-search" for item in descriptors))


if __name__ == "__main__":
    unittest.main()
