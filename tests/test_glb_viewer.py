from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from zenless.glb_viewer import GLBError, load_glb, project_triangles


def make_triangle_glb(path: Path) -> None:
    positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    indices = struct.pack("<3H", 0, 1, 2)
    binary = positions + indices
    while len(binary) % 4:
        binary += b"\0"
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(indices)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "nodes": [{"mesh": 0, "translation": [2, 3, 4]}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    while len(encoded) % 4:
        encoded += b" "
    json_chunk = struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    bin_chunk = struct.pack("<II", len(binary), 0x004E4942) + binary
    total = 12 + len(json_chunk) + len(bin_chunk)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, total) + json_chunk + bin_chunk)


class GLBViewerTests(unittest.TestCase):
    def test_loads_transforms_and_projects_triangle(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "triangle.glb"
            make_triangle_glb(path)
            mesh = load_glb(path)
            self.assertEqual(len(mesh.vertices), 3)
            self.assertEqual(len(mesh.faces), 1)
            self.assertEqual(mesh.minimum, (2.0, 3.0, 4.0))
            self.assertEqual(mesh.maximum, (3.0, 4.0, 4.0))
            projected = project_triangles(mesh, 0.4, 800, 600)
            self.assertEqual(len(projected), 1)
            self.assertEqual(len(projected[0][1]), 6)

    def test_rejects_invalid_header(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invalid.glb"
            path.write_bytes(b"not-a-glb" * 3)
            with self.assertRaises(GLBError):
                load_glb(path)


if __name__ == "__main__":
    unittest.main()
