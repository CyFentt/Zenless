from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    import winreg


HOST_NAME = "app.zenless.bridge"
EXTENSION_ID = "zenless@local.app"


def manifest_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is unavailable.")
    return Path(appdata) / "Mozilla" / "NativeMessagingHosts" / f"{HOST_NAME}.json"


def install_native_host(executable: Path | None = None) -> Path:
    target_executable = (executable or Path(sys.executable)).resolve()
    if not target_executable.is_file():
        raise RuntimeError(f"Native host executable not found: {target_executable}")
    target = manifest_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": HOST_NAME,
        "description": "Zenless local browser bridge",
        "path": str(target_executable),
        "type": "stdio",
        "allowed_extensions": [EXTENSION_ID],
    }
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    if sys.platform == "win32":
        registry_path = rf"Software\Mozilla\NativeMessagingHosts\{HOST_NAME}"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, registry_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(target))
    return target


def uninstall_native_host() -> bool:
    target = manifest_path()
    removed = False
    if target.exists():
        target.unlink()
        removed = True
    if sys.platform == "win32":
        registry_path = rf"Software\Mozilla\NativeMessagingHosts\{HOST_NAME}"
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, registry_path)
            removed = True
        except FileNotFoundError:
            pass
    return removed
