from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
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
    def __init__(self, *, resource_root: Path, portable_root: Path, status_callback: Callable[[str, str], None] | None = None, cancel_event: threading.Event | None = None) -> None:
        self.resource_root = resource_root.resolve()
        self.portable_root = portable_root.resolve()
        self.runtime_root = self.portable_root / "runtime"
        self.download_root = self.runtime_root / "downloads"
        self.state_path = self.runtime_root / "toolchain-state.json"
        self.status_callback = status_callback
        self.cancel_event = cancel_event or threading.Event()
        self._lock = threading.RLock()
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.manifest = json.loads((self.resource_root / "assets" / "toolchain.json").read_text(encoding="utf-8"))
        self._state = self._load_state()

    def ensure_default(self) -> list[InstallResult]:
        with self._lock:
            results: list[InstallResult] = []
            artifacts = self.manifest.get("artifacts", [])
            models = [item for item in artifacts if str(item.get("target", "")).startswith("runtime/models/")]
            small = [item for item in artifacts if item not in models]
            queue = [(item, False) for item in small] + [(item, True) for item in self.manifest.get("sources", [])]
            queue += [(item, False) for item in models]
            for item, source in queue:
                if self.cancel_event.is_set():
                    break
                item_id = str(item["id"])
                if item.get("auto", True) is False:
                    result = InstallResult(item_id, "optional", "Available on demand")
                elif not self._eligible(item):
                    result = InstallResult(item_id, "skipped", "Hardware threshold not met")
                else:
                    try:
                        path = self._ensure_source(item) if source else self._ensure_artifact(item)
                        result = InstallResult(item_id, "ready", "Pinned source available" if source else "Verified and ready", str(path))
                    except Exception as exc:
                        result = InstallResult(item_id, "failed", str(exc))
                results.append(result)
                self._save_results(results)
            if not self.cancel_event.is_set():
                try:
                    self._ensure_npm_packages(results)
                except Exception as exc:
                    results.append(InstallResult("npm", "failed", str(exc)))
            self._save_results(results)
            self._save_state()
            return results

    def _save_results(self, results: list[InstallResult]) -> None:
        target = self.runtime_root / "toolchain-results.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps({item.item_id: asdict(item) for item in results}, indent=2), encoding="utf-8")
        os.replace(temporary, target)

    def install(self, item_id: str) -> InstallResult:
        target_id = item_id.strip()
        if not target_id:
            raise ToolchainError("Tool ID is empty.")
        with self._lock:
            for item in self.manifest.get("artifacts", []):
                if str(item.get("id") or "") != target_id:
                    continue
                if not self._eligible(item):
                    raise ToolchainError(f"Hardware threshold not met for {target_id}.")
                path = self._ensure_artifact(item)
                self._save_state()
                return InstallResult(target_id, "ready", "Verified and ready", str(path))
            for item in self.manifest.get("sources", []):
                if str(item.get("id") or "") != target_id:
                    continue
                path = self._ensure_source(item)
                self._save_state()
                return InstallResult(target_id, "ready", "Pinned source ready", str(path))
        raise ToolchainError(f"Unknown tool or source: {target_id}")

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
            self.runtime_root / "tools" / "uv",
            self.runtime_root / "tools" / "pesde",
            self.runtime_root / "tools" / "darklua",
            self.runtime_root / "npm" / "node_modules" / ".bin",
        ]
        env["PATH"] = os.pathsep.join([str(path) for path in roots if path.exists()] + [env.get("PATH", "")])
        env["NPM_CONFIG_CACHE"] = str(self.runtime_root / "npm-cache")
        env["NPM_CONFIG_PREFIX"] = str(self.runtime_root / "npm-prefix")
        env["RUBRA_HOME"] = str(self.portable_root)
        env["UV_CACHE_DIR"] = str(self.runtime_root / "uv-cache")
        env["UV_PYTHON_INSTALL_DIR"] = str(self.runtime_root / "python")
        env["HF_HOME"] = str(self.runtime_root / "model-cache" / "huggingface")
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
        if self._artifact_ready(item, target):
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
        marker_path = self._marker_path(target, str(item.get("marker") or ""), kind)
        marker_sha = self._sha256(marker_path) if marker_path is not None and marker_path.is_file() else ""
        size = target.stat().st_size if target.is_file() else 0
        self._state[item_id] = {
            "url": url,
            "sha256": expected,
            "target": str(target),
            "markerSha256": marker_sha,
            "size": size,
        }
        self._save_state()
        self._status(item_id, f"Ready: {item.get('name', item_id)}")
        archive.unlink(missing_ok=True)
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
        self._save_state()
        self._status(item_id, f"Ready: {item.get('name', item_id)}")
        archive.unlink(missing_ok=True)
        return target

    def _ensure_npm_packages(self, results: list[InstallResult]) -> None:
        node = self.path("node", "node.exe")
        if node is None:
            return
        npm = node.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if not npm.is_file():
            raise ToolchainError("The portable Node installation is missing npm-cli.js.")
        prefix = self.runtime_root / "npm"
        prefix.mkdir(parents=True, exist_ok=True)
        package_json = prefix / "package.json"
        if not package_json.is_file():
            package_json.write_text('{"private":true}', encoding="utf-8")
        for item in self.manifest.get("npm", []):
            item_id = str(item["id"])
            if item.get("auto", True) is False:
                results.append(InstallResult(item_id, "optional", "Available on demand"))
                continue
            if self.cancel_event.is_set():
                return
            package = str(item["package"])
            marker = prefix / ".rubra-packages" / item_id
            if marker.is_file() and marker.read_text(encoding="utf-8").strip() == package:
                results.append(InstallResult(item_id, "ready", "Portable npm package ready", str(prefix)))
                continue
            marker.parent.mkdir(parents=True, exist_ok=True)
            try:
                process = subprocess.Popen(
                    [str(node), str(npm), "install", "--prefix", str(prefix), "--no-audit", "--no-fund", "--save-exact", package],
                    env=self.environment(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                deadline = time.monotonic() + 900.0
                output = ""
                while True:
                    if self.cancel_event.is_set():
                        process.terminate()
                        try:
                            output, _ = process.communicate(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            output, _ = process.communicate(timeout=2)
                        raise ToolchainError("Tool preparation cancelled.")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        process.kill()
                        output, _ = process.communicate(timeout=2)
                        raise ToolchainError(f"npm install timed out for {package}.")
                    try:
                        output, _ = process.communicate(timeout=min(0.25, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except (OSError, ToolchainError) as exc:
                results.append(InstallResult(item_id, "failed", str(exc)))
                if item.get("critical") or self.cancel_event.is_set():
                    raise ToolchainError(f"npm install failed for {package}: {exc}") from exc
                continue
            if process.returncode != 0:
                results.append(InstallResult(item_id, "failed", output[-3000:]))
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
        last_error: BaseException | None = None
        for attempt in range(5):
            if self.cancel_event.is_set():
                raise ToolchainError("Tool preparation cancelled. The partial download was kept for resume.")
            resume_from = partial.stat().st_size if partial.is_file() else 0
            headers = {"User-Agent": "Rubra/1", "Accept-Encoding": "identity"}
            if resume_from:
                headers["Range"] = f"bytes={resume_from}-"
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    status = int(getattr(response, "status", 200) or 200)
                    resumed = resume_from > 0 and status == 206
                    if resume_from and not resumed:
                        resume_from = 0
                    total_remaining = int(response.headers.get("Content-Length") or 0)
                    total = resume_from + total_remaining if total_remaining else 0
                    copied = resume_from
                    mode = "ab" if resumed else "wb"
                    last_percent = int(copied * 100 / total) if total else -1
                    with partial.open(mode) as stream:
                        while chunk := response.read(1024 * 1024):
                            if self.cancel_event.is_set():
                                raise ToolchainError(
                                    "Tool preparation cancelled. The partial download was kept for resume."
                                )
                            stream.write(chunk)
                            copied += len(chunk)
                            percent = int(copied * 100 / total) if total else -1
                            if percent != last_percent:
                                detail = (
                                    f"Downloading {percent}% ({copied // (1024 * 1024)} MB)"
                                    if total
                                    else f"Downloading {copied // (1024 * 1024)} MB"
                                )
                                self._status(target.stem, detail)
                                last_percent = percent
                os.replace(partial, target)
                return
            except ToolchainError:
                raise
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 416 and partial.exists():
                    partial.unlink(missing_ok=True)
            except (OSError, TimeoutError, urllib.error.URLError) as exc:
                last_error = exc
            if attempt < 4:
                delay = min(16.0, 2.0 ** attempt)
                self._status(
                    target.stem,
                    f"Download interrupted; resuming in {int(delay)}s ({attempt + 1}/5)",
                )
                if self.cancel_event.wait(delay):
                    raise ToolchainError(
                        "Tool preparation cancelled. The partial download was kept for resume."
                    )
        raise ToolchainError(
            f"Download failed after 5 attempts; partial data was kept for resume: {last_error}"
        )

    def _extract_atomic(self, archive: Path, target: Path, kind: str, flatten: bool) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f"{target.name}.", dir=target.parent))
        staged = target.with_name(target.name + ".new")
        backup = target.with_name(target.name + ".old")
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
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            shutil.copytree(source, staged)
            moved_existing = False
            if target.exists():
                os.replace(target, backup)
                moved_existing = True
            try:
                os.replace(staged, target)
            except Exception:
                if moved_existing and backup.exists() and not target.exists():
                    os.replace(backup, target)
                raise
            else:
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)

    @staticmethod
    def _safe_zip(bundle: zipfile.ZipFile, target: Path) -> None:
        root = target.resolve()
        for info in bundle.infolist():
            destination = (target / info.filename).resolve()
            if destination != root and root not in destination.parents:
                raise ToolchainError("Archive path traversal blocked")
            unix_mode = (info.external_attr >> 16) & 0xF000
            if unix_mode == 0xA000:
                raise ToolchainError("Archive symbolic links are not allowed")
        bundle.extractall(target)

    @staticmethod
    def _safe_tar(bundle: tarfile.TarFile, target: Path) -> None:
        root = target.resolve()
        members = []
        for member in bundle.getmembers():
            destination = (target / member.name).resolve()
            if destination != root and root not in destination.parents:
                raise ToolchainError("Archive path traversal blocked")
            if member.issym() or member.islnk() or member.isdev():
                raise ToolchainError("Archive links and device entries are not allowed")
            members.append(member)
        bundle.extractall(target, members=members, filter="data")

    def _artifact_ready(self, item: dict[str, Any], target: Path) -> bool:
        item_id = str(item.get("id") or "")
        kind = str(item.get("kind") or "")
        marker = str(item.get("marker") or "")
        marker_path = self._marker_path(target, marker, kind)
        if marker_path is None or not marker_path.is_file():
            return False
        expected = str(item.get("sha256") or "").lower()
        state = self._state.get(item_id)
        if not expected or not isinstance(state, dict):
            return False
        if str(state.get("sha256") or "").lower() != expected:
            return False
        if str(state.get("target") or "") != str(target):
            return False
        if kind == "raw":
            try:
                size = target.stat().st_size
            except OSError:
                return False
            recorded_size = int(state.get("size") or 0)
            if recorded_size and size != recorded_size:
                return False
            if size <= 128 * 1024 * 1024:
                return self._sha256(target) == expected
            return True
        recorded_marker_sha = str(state.get("markerSha256") or "").lower()
        if not recorded_marker_sha:
            return False
        try:
            if marker_path.stat().st_size > 128 * 1024 * 1024:
                return True
        except OSError:
            return False
        return self._sha256(marker_path) == recorded_marker_sha

    @staticmethod
    def _marker_path(target: Path, marker: str, kind: str) -> Path | None:
        if kind == "raw":
            return target if target.is_file() else None
        if not target.exists():
            return None
        if not marker:
            return target if target.is_file() else None
        direct = target / marker
        if direct.is_file():
            return direct
        return next(target.rglob(marker), None)

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
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _save_state(self) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.state_path)
