from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import winreg
from pathlib import Path


def folder(identifier: int) -> Path:
    buffer = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, identifier, None, 0, buffer) != 0:
        raise RuntimeError("Windows known folder lookup failed")
    return Path(buffer.value).resolve()


def snapshot(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise RuntimeError("Validation refuses redirected application data")
        if path.is_file():
            with path.open("rb") as stream:
                result[str(path.relative_to(root))] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def remove_temporary(root: Path, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while root.exists() and time.monotonic() < deadline:
        try:
            shutil.rmtree(root)
        except OSError:
            time.sleep(0.2)
    if root.exists():
        raise RuntimeError("Installed smoke left its temporary profile locked")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("setup", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/final-validation/installer.json"))
    arguments = parser.parse_args()
    setup = arguments.setup.resolve(strict=True)
    local = folder(28)
    install = local / "Programs" / "Zenless"
    data = local / "Zenless"
    desktop_link = folder(16) / "Zenless.lnk"
    menu = folder(2) / "Zenless"
    registry_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Zenless"
    if install.exists() or desktop_link.exists() or menu.exists():
        raise RuntimeError("An existing installation or shortcut must not be replaced by validation")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path):
            raise RuntimeError("An existing uninstall entry must not be replaced by validation")
    except FileNotFoundError:
        pass
    before = snapshot(data)
    report: dict[str, object] = {"status": "FAILED", "full_remove": "NOT_RUN_EXISTING_USER_DATA"}
    uninstaller = install / "Uninstall Zenless.exe"
    try:
        for iteration in range(2):
            subprocess.run([str(setup), "/S"], timeout=90, check=True)
            installed = install / "Zenless.exe"
            if not installed.is_file() or not uninstaller.is_file():
                raise RuntimeError("Installed binaries are missing")
            if not desktop_link.is_file() or not (menu / "Zenless.lnk").is_file():
                raise RuntimeError("Installed shortcuts are missing")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
                command = winreg.QueryValueEx(key, "UninstallString")[0]
                if command != f'"{uninstaller}"':
                    raise RuntimeError("Uninstall registry command is incorrect")
            temporary = Path(tempfile.mkdtemp(prefix="zenless-installed-validation-"))
            try:
                environment = {**os.environ, "ZENLESS_DATA_ROOT": str(temporary)}
                subprocess.run(
                    [str(installed), "--smoke-test", "--no-provision"],
                    env=environment,
                    timeout=90,
                    check=True,
                )
            finally:
                remove_temporary(temporary)
            subprocess.run([str(uninstaller), "/S", "/KEEPDATA"], cwd=local, timeout=90, check=True)
            deadline = time.monotonic() + 20
            while install.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            if install.exists() or desktop_link.exists() or menu.exists():
                raise RuntimeError("Uninstall left installed files or shortcuts")
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path):
                    raise RuntimeError("Uninstall left its registry entry")
            except FileNotFoundError:
                pass
            if snapshot(data) != before:
                raise RuntimeError("Keep Settings changed existing application data")
            report[f"install_cycle_{iteration + 1}"] = "PASS"
        report.update({"status": "PASSED", "keep_data": "PASS", "reinstall": "PASS", "preserved_files": len(before)})
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if uninstaller.is_file():
            result = subprocess.run([str(uninstaller), "/S", "/KEEPDATA"], cwd=local, timeout=90, check=False)
            report["cleanup_exit"] = result.returncode
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
