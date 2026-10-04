from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import urllib.request
import urllib.parse
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class ToolchainError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class InstallResult:
    item_id: str
    state: str
    detail: str
    path: str = ""


class ToolchainManager:
    def __init__(self, *, resource_root: Path, portable_root: Path, status_callback: Callable[[str, str], None] | None = None) -> None:
        self.resource_root = resource_root.resolve()
        self.portable_root = portable_root.resolve()
        self.runtime_root = self.portable_root / "runtime"
        self.download_root = self.runtime_root / "downloads"
        self.state_path = self.runtime_root / "toolchain-state.json"
        self.status_callback = status_callback
        self._lock = threading.RLock()
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.manifest = json.loads((self.resource_root / "assets" / "toolchain.json").read_text(encoding="utf-8"))
        self._state = self._load_state()

    def ensure_default(self) -> list[InstallResult]:
        with self._lock:
            results: list[InstallResult] = []
            for item in self.manifest.get("artifacts", []):
                if not self._eligible(item):
                    results.append(InstallResult(str(item["id"]), "skipped", "Hardware threshold not met"))
                    continue
                try:
                    path = self._ensure_artifact(item)
                    results.append(InstallResult(str(item["id"]), "ready", "Verified and ready", str(path)))
                except Exception as exc:
                    results.append(InstallResult(str(item["id"]), "failed", str(exc)))
                    if item.get("critical"):
                        raise
            for item in self.manifest.get("sources", []):
                try:
                    path = self._ensure_source(item)
                    results.append(InstallResult(str(item["id"]), "ready", "Pinned source ready", str(path)))
                except Exception as exc:
                    results.append(InstallResult(str(item["id"]), "failed", str(exc)))
            self._ensure_npm_packages(results)
            self._save_state()
            return results

    def environment(self) -> dict[str, str]:
        env = dict(os.environ)
        roots = [
            self.runtime_root / "node",
            self.runtime_root / "tools" / "rokit",
            self.runtime_root / "tools" / "rojo",
            self.runtime_root / "tools" / "selene",
            self.runtime_root / "tools" / "stylua",
            self.runtime_root / "tools" / "luau-lsp",
            self.runtime_root / "tools" / "lune",
            self.runtime_root / "tools" / "ripgrep",
            self.runtime_root / "tools" / "jq",
            self.runtime_root / "npm" / "node_modules" / ".bin",
        ]
        env["PATH"] = os.pathsep.join([str(path) for path in roots if path.exists()] + [env.get("PATH", "")])
        env["NPM_CONFIG_CACHE"] = str(self.runtime_root / "npm-cache")
        env["NPM_CONFIG_PREFIX"] = str(self.runtime_root / "npm-prefix")
        env["RUBRA_HOME"] = str(self.portable_root)
        return env

    def path(self, item_id: str, executable: str = "") -> Path | None:
        for item in self.manifest.get("artifacts", []):
            if item.get("id") != item_id:
                continue
            target = self.portable_root / str(item["target"])
            if item.get("kind") == "raw":
                return target if target.is_file() else None
            name = executable or str(item.get("marker") or "")
            if name:
                direct = target / name
                if direct.is_file():
                    return direct
                return next(target.rglob(name), None) if target.exists() else None
            return target if target.exists() else None
        return None

    def _ensure_artifact(self, item: dict[str, Any]) -> Path:
        item_id = str(item["id"])
        target = self.portable_root / str(item["target"])
        if self._target_ready(target, str(item.get("marker") or ""), str(item.get("kind") or "")):
            return target
        self._status(item_id, f"Installing {item.get('name', item_id)}")
        url = str(item["url"])
        parsed = urllib.parse.urlparse(url)
        kind = str(item.get("kind") or "raw")
        suffix = ".tar.gz" if kind == "tar.gz" else Path(parsed.path).suffix
        archive = self.download_root / f"{item_id}{suffix or '.bin'}"
        self._download(url, archive)
        expected = str(item.get("sha256") or "").lower()
        if expected and self._sha256(archive) != expected:
            actual = self._sha256(archive)
            archive.unlink(missing_ok=True)
            raise ToolchainError(f"SHA-256 mismatch for {item_id}: {actual}")
        if kind == "raw":
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".partial")
            shutil.copy2(archive, temporary)
            os.replace(temporary, target)
        else:
            self._extract_atomic(archive, target, kind, bool(item.get("flatten")))
        self._state[item_id] = {"url": url, "sha256": expected, "target": str(target)}
        return target

    def _ensure_source(self, item: dict[str, Any]) -> Path:
        item_id = str(item["id"])
        target = self.portable_root / str(item["target"])
        commit = str(item["commit"])
        marker = target / ".rubra-source.json"
        if marker.is_file():
            try:
                payload = json.loads(marker.read_text(encoding="utf-8"))
                if payload.get("commit") == commit and payload.get("repo") == item.get("repo"):
                    return target
            except Exception:
                pass
        repo = str(item["repo"])
        self._status(item_id, f"Syncing {repo}")
        archive = self.download_root / f"source-{item_id}.zip"
        self._download(f"https://github.com/{repo}/archive/{commit}.zip", archive)
        self._extract_atomic(archive, target, "zip", True)
        marker.write_text(json.dumps({"repo": repo, "commit": commit}, indent=2), encoding="utf-8")
        return target

    def _ensure_npm_packages(self, results: list[InstallResult]) -> None:
        node = self.path("node", "node.exe")
        if node is None:
            return
        npm = node.parent / "npm.cmd"
        if not npm.is_file():
            return
        prefix = self.runtime_root / "npm"
        prefix.mkdir(parents=True, exist_ok=True)
        package_json = prefix / "package.json"
        if not package_json.is_file():
            package_json.write_text('{"private":true}', encoding="utf-8")
        for item in self.manifest.get("npm", []):
            item_id = str(item["id"])
            package = str(item["package"])
            marker = prefix / ".rubra-packages" / item_id
            if marker.is_file() and marker.read_text(encoding="utf-8").strip() == package:
                results.append(InstallResult(item_id, "ready", "Portable npm package ready", str(prefix)))
                continue
            marker.parent.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(
                [str(npm), "install", "--prefix", str(prefix), "--no-audit", "--no-fund", "--save-exact", package],
                env=self.environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            if completed.returncode != 0:
                results.append(InstallResult(item_id, "failed", completed.stdout[-3000:]))
                if item.get("critical"):
                    raise ToolchainError(f"npm install failed for {package}")
                continue
            marker.write_text(package, encoding="utf-8")
            results.append(InstallResult(item_id, "ready", "Portable npm package ready", str(prefix)))

    def _eligible(self, item: dict[str, Any]) -> bool:
        rule = item.get("hardware_auto")
        if not isinstance(rule, dict):
            return True
        return self._ram_gb() >= float(rule.get("min_ram_gb") or 0) and shutil.disk_usage(self.portable_root).free / (1024 ** 3) >= float(rule.get("min_free_gb") or 0)

    def _status(self, stage: str, detail: str) -> None:
        if self.status_callback is not None:
            self.status_callback(stage.upper(), detail)

    def _download(self, url: str, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".partial")
        request = urllib.request.Request(url, headers={"User-Agent": "Rubra/1"})
        try:
            with urllib.request.urlopen(request, timeout=90) as response, partial.open("wb") as stream:
                shutil.copyfileobj(response, stream, length=1024 * 1024)
            os.replace(partial, target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

    def _extract_atomic(self, archive: Path, target: Path, kind: str, flatten: bool) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f"{target.name}.", dir=target.parent))
        try:
            if kind == "zip":
                with zipfile.ZipFile(archive) as bundle:
                    self._safe_zip(bundle, temporary)
            elif kind == "tar.gz":
                with tarfile.open(archive, "r:gz") as bundle:
                    self._safe_tar(bundle, temporary)
            else:
                raise ToolchainError(f"Unsupported archive type: {kind}")
            source = temporary
            children = list(temporary.iterdir())
            if flatten and len(children) == 1 and children[0].is_dir():
                source = children[0]
            staged = target.with_name(target.name + ".new")
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)
            shutil.copytree(source, staged)
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            os.replace(staged, target)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    @staticmethod
    def _safe_zip(bundle: zipfile.ZipFile, target: Path) -> None:
        root = target.resolve()
        for info in bundle.infolist():
            destination = (target / info.filename).resolve()
            if destination != root and root not in destination.parents:
                raise ToolchainError("Archive path traversal blocked")
        bundle.extractall(target)

    @staticmethod
    def _safe_tar(bundle: tarfile.TarFile, target: Path) -> None:
        root = target.resolve()
        members = []
        for member in bundle.getmembers():
            destination = (target / member.name).resolve()
            if destination != root and root not in destination.parents:
                raise ToolchainError("Archive path traversal blocked")
            members.append(member)
        bundle.extractall(target, members=members)

    @staticmethod
    def _target_ready(target: Path, marker: str, kind: str) -> bool:
        if kind == "raw":
            return target.is_file()
        if not target.exists():
            return False
        return not marker or (target / marker).is_file() or next(target.rglob(marker), None) is not None

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _ram_gb() -> float:
        if os.name != "nt":
            return 0.0
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        return status.ullTotalPhys / (1024 ** 3) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else 0.0

    def _load_state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.state_path)
