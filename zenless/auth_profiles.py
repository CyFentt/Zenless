from __future__ import annotations

import re
import shutil
from pathlib import Path

BUILD_ID_FILE = "zenless-build-id"
MARKER_FILE = "auth-build-id"
AUTH_DIRECTORIES = (
    "browser-profile",
    "webview-profile",
    "tmp",
    "temp",
    "uploads",
    "provisioning",
)
AUTH_FILES = (
    "provider-sessions.json",
    "provider-routes.json",
    "webview-provider-config.json",
)


def prepare_auth_profiles(data_root: Path, resource_root: Path) -> bool:
    build_id = _read_build_id(resource_root / BUILD_ID_FILE)
    if build_id is None:
        return False
    root = data_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / MARKER_FILE
    if _read_build_id(marker) == build_id:
        return False
    for name in (*AUTH_DIRECTORIES, *AUTH_FILES):
        _remove_direct_child(root, name)
    temporary = root / f".{MARKER_FILE}.tmp"
    temporary.write_text(build_id, encoding="ascii")
    temporary.replace(marker)
    return True


def _read_build_id(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="ascii").strip().casefold()
    except (OSError, UnicodeError):
        return None
    return value if re.fullmatch(r"[0-9a-f]{32}", value) else None


def _remove_direct_child(root: Path, name: str) -> None:
    target = root / name
    if target.parent.resolve() != root:
        raise RuntimeError("Authentication cleanup target escaped the data root.")
    if target.is_symlink():
        target.unlink()
    elif target.is_junction():
        target.rmdir()
    elif target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
