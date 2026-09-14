from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from zenless.attachments import AttachmentError, AttachmentTextEncoder
from zenless.core import ZenlessCore


class _CapabilityBridge:
    def request(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        return {"capabilities": {"send_text": True, "upload_files": False}}


class AttachmentTextTests(unittest.TestCase):
    def test_text_files_are_encoded_with_identity_and_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "Controller.luau"
            source.write_text("return true", encoding="utf-8")

            result = AttachmentTextEncoder().encode((source,), extraction_root=root / "expanded")

            self.assertIn("untrusted project context", result.text)
            self.assertIn("FILE Controller.luau", result.text)
            self.assertIn("SHA256", result.text)
            self.assertIn("return true", result.text)
            self.assertEqual(result.files[0].path, source.resolve())

    def test_safe_zip_text_is_expanded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "project.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("src/Main.luau", "return 1")

            result = AttachmentTextEncoder().encode((source,), extraction_root=root / "expanded")

            self.assertIn("FILE Main.luau", result.text)
            self.assertIn("return 1", result.text)
            self.assertEqual(len(result.extraction_roots), 1)

    def test_binary_file_requires_a_file_capable_mode(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "image.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 64)

            with self.assertRaises(AttachmentError) as raised:
                AttachmentTextEncoder().encode((source,), extraction_root=root / "expanded")

            self.assertEqual(raised.exception.code, "ATTACHMENT_TEXT_FALLBACK_UNAVAILABLE")

    def test_inline_total_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "a.txt"
            second = root / "b.txt"
            first.write_text("a" * 10, encoding="utf-8")
            second.write_text("b" * 10, encoding="utf-8")

            with self.assertRaises(AttachmentError) as raised:
                AttachmentTextEncoder(max_total_bytes=15).encode(
                    (first, second),
                    extraction_root=root / "expanded",
                )

            self.assertEqual(raised.exception.code, "ATTACHMENT_TEXT_TOTAL_LIMIT")

    def test_core_routes_text_when_live_mode_has_no_file_upload(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "System.luau"
            source.write_text("return {}", encoding="utf-8")
            core = object.__new__(ZenlessCore)
            core.data_root = root
            core.bridge = _CapabilityBridge()
            core.attachment_text = AttachmentTextEncoder()

            files, context = core._prepare_attachment_delivery((source,), "chatgpt")

            self.assertEqual(files, ())
            self.assertIn("FILE System.luau", context)
            self.assertIn("return {}", context)


if __name__ == "__main__":
    unittest.main()
