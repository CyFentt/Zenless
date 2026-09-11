from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zenless.auth_profiles import AUTH_DIRECTORIES, AUTH_FILES, BUILD_ID_FILE, MARKER_FILE, prepare_auth_profiles


class AuthenticationProfileTests(unittest.TestCase):
    def test_new_build_clears_authentication_and_preserves_application_data(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data_root = root / "data"
            resource_root = root / "resources"
            data_root.mkdir()
            resource_root.mkdir()
            (resource_root / BUILD_ID_FILE).write_text("1" * 32, encoding="ascii")
            for name in AUTH_DIRECTORIES:
                target = data_root / name
                target.mkdir()
                (target / "session.bin").write_bytes(b"secret")
            for name in AUTH_FILES:
                (data_root / name).write_text("secret", encoding="utf-8")
            database = data_root / "zenless.db"
            database.write_bytes(b"state")

            self.assertTrue(prepare_auth_profiles(data_root, resource_root))
            self.assertEqual(database.read_bytes(), b"state")
            self.assertEqual((data_root / MARKER_FILE).read_text(encoding="ascii"), "1" * 32)
            self.assertTrue(all(not (data_root / name).exists() for name in (*AUTH_DIRECTORIES, *AUTH_FILES)))

    def test_same_build_preserves_session_and_changed_build_clears_it(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data_root = root / "data"
            resource_root = root / "resources"
            resource_root.mkdir()
            build_id = resource_root / BUILD_ID_FILE
            build_id.write_text("a" * 32, encoding="ascii")
            self.assertTrue(prepare_auth_profiles(data_root, resource_root))
            cookie = data_root / "webview-profile" / "Default" / "Cookies"
            cookie.parent.mkdir(parents=True)
            cookie.write_bytes(b"session")

            self.assertFalse(prepare_auth_profiles(data_root, resource_root))
            self.assertEqual(cookie.read_bytes(), b"session")

            build_id.write_text("b" * 32, encoding="ascii")
            self.assertTrue(prepare_auth_profiles(data_root, resource_root))
            self.assertFalse(cookie.exists())

    def test_missing_or_invalid_build_identity_never_clears_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data_root = root / "data"
            resource_root = root / "resources"
            cookie = data_root / "browser-profile" / "Default" / "Cookies"
            cookie.parent.mkdir(parents=True)
            cookie.write_bytes(b"session")
            resource_root.mkdir()

            self.assertFalse(prepare_auth_profiles(data_root, resource_root))
            (resource_root / BUILD_ID_FILE).write_text("invalid", encoding="ascii")
            self.assertFalse(prepare_auth_profiles(data_root, resource_root))
            self.assertEqual(cookie.read_bytes(), b"session")


if __name__ == "__main__":
    unittest.main()
