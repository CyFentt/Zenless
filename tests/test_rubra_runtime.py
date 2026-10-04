from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zenless.local_ai import LocalAIService
from zenless.project_index import ProjectIndexService
from zenless.tool_registry import ToolRegistry


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
