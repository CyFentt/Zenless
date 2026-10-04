from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from zenless.local_ai import LocalAIService
from zenless.project_index import ProjectIndexService
from zenless.tool_registry import ToolRegistry
from zenless.toolchain import ToolchainManager


class RubraRuntimeTests(unittest.TestCase):
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
