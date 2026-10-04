from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Any

from .studio_mcp import MCPError, StudioMCPClient


class ProjectIndexError(RuntimeError):
    pass


class ProjectIndexService:
    def __init__(self, portable_root: Path, resource_root: Path | None = None) -> None:
        self.portable_root = portable_root.resolve()
        self.resource_root = (resource_root or Path(__file__).resolve().parents[1]).resolve()
        self.runtime_root = self.portable_root / "runtime"
        self.source_root = self.runtime_root / "sources" / "code-search"
        self.home_root = self.runtime_root / "home"
        self.index_root = self.runtime_root / "index" / "scoped"
        self._client: StudioMCPClient | None = None
        self._lock = threading.RLock()
        self._project_root = ""
        self._indexed = False

    @property
    def project_root(self) -> str:
        return self._project_root

    @property
    def running(self) -> bool:
        return bool(self._client and self._client.running)

    def configure(self, project_root: str) -> str:
        with self._lock:
            raw = project_root.strip()
            path = Path(raw).expanduser().resolve() if raw else None
            if path is not None and not path.is_dir():
                raise ProjectIndexError(f"Project directory does not exist: {path}")
            root = str(path) if path is not None else ""
            if root != self._project_root:
                self.close()
                self._project_root = root
            return self._project_root

    def index(self, project_root: str | None = None, *, incremental: bool = True) -> dict[str, Any]:
        with self._lock:
            root = self.configure(project_root) if project_root is not None else self._project_root
            if not root:
                raise ProjectIndexError("No project directory is configured.")
            self._indexed = False
            client = self._ensure_client()
            try:
                result = client.call_tool(
                    "index_directory",
                    {"path": root, "incremental": bool(incremental)},
                    timeout=900,
                )
            except MCPError as exc:
                raise ProjectIndexError(str(exc)) from exc
            if result.is_error or result.text.lstrip().startswith("Error:"):
                raise ProjectIndexError(result.compact(6000))
            if "Indexing complete:" not in result.text:
                raise ProjectIndexError("The indexer did not confirm indexing completion.")
            self._indexed = True
            return {"projectRoot": root, "result": result.text, "indexed": True}

    def search(
        self, query: str, *, limit: int = 12, semantic: bool = True, project_root: str | None = None
    ) -> dict[str, Any]:
        with self._lock:
            root = self.configure(project_root) if project_root is not None else self._project_root
            if not root:
                return {"projectRoot": "", "query": query, "result": "", "available": False}
            value = query.strip()
            if not value:
                return {"projectRoot": root, "query": "", "result": "", "available": True}
            self.index(incremental=True)
            client = self._ensure_client()
            name = "search_code" if semantic else "search_text"
            arguments = {"query": value, "limit": max(1, min(30, int(limit)))} if semantic else {
                "keyword": value,
                "limit": max(1, min(30, int(limit))),
            }
            try:
                result = client.call_tool(name, arguments, timeout=120)
            except MCPError as exc:
                raise ProjectIndexError(str(exc)) from exc
            if result.is_error:
                raise ProjectIndexError(result.compact(6000))
            return {
                "projectRoot": root,
                "query": value,
                "result": result.text,
                "available": True,
                "metadata": self.project_metadata(),
            }

    def project_metadata(self) -> dict[str, str]:
        if not self._project_root:
            return {}
        root = Path(self._project_root)
        names = (
            "default.project.json",
            "rokit.toml",
            "aftman.toml",
            "wally.toml",
            "pesde.toml",
            ".luaurc",
            "selene.toml",
            ".darklua.json",
            ".darklua.json5",
        )
        result: dict[str, str] = {}
        for name in names:
            path = root / name
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
                continue
            try:
                if path.stat().st_size > 128 * 1024:
                    continue
                result[name] = path.read_text(encoding="utf-8", errors="replace")[:16000]
            except OSError:
                continue
        return result

    def status(self, project_root: str | None = None) -> dict[str, Any]:
        with self._lock:
            if project_root is not None:
                self.configure(project_root)
            state = {
                "configured": bool(self._project_root),
                "projectRoot": self._project_root,
                "running": self.running,
                "indexed": self._indexed,
                "result": "",
            }
            if not self.running:
                return state
            try:
                result = self._ensure_client().call_tool("get_index_status", {}, timeout=45)
                if result.is_error:
                    raise ProjectIndexError(result.compact(6000))
                state["result"] = result.text
            except Exception as exc:
                state["error"] = str(exc)
            return state

    def close(self) -> None:
        with self._lock:
            client = self._client
            self._client = None
            self._indexed = False
            if client is not None:
                client.close()

    def _ensure_client(self) -> StudioMCPClient:
        with self._lock:
            if self._client is not None and self._client.running:
                return self._client
            uv = self.runtime_root / "tools" / "uv" / "uv.exe"
            if not uv.is_file():
                matches = list((self.runtime_root / "tools" / "uv").rglob("uv.exe"))
                uv = matches[0] if matches else uv
            if not uv.is_file():
                raise ProjectIndexError("Portable uv is not installed.")
            if not (self.source_root / "pyproject.toml").is_file():
                raise ProjectIndexError("Pinned mcp-code-search source is not installed.")
            adapter = self.resource_root / "assets" / "code_search_adapter.py"
            if not adapter.is_file():
                raise ProjectIndexError("The Rubra code-search adapter is unavailable.")
            client = StudioMCPClient(
                uv,
                args=("run", "--locked", "--directory", str(self.source_root), "python", str(adapter)),
                env=self._environment(),
                client_name="Rubra Code Search",
                client_version="1.0.0",
                startup_timeout=900,
            )
            try:
                client.start()
            except MCPError as exc:
                client.close()
                raise ProjectIndexError(str(exc)) from exc
            self._client = client
            return client

    def _environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        self.home_root.mkdir(parents=True, exist_ok=True)
        self.index_root.mkdir(parents=True, exist_ok=True)
        environment["HOME"] = str(self.home_root)
        environment["USERPROFILE"] = str(self.home_root)
        environment["UV_CACHE_DIR"] = str(self.runtime_root / "uv-cache")
        environment["UV_PYTHON_INSTALL_DIR"] = str(self.runtime_root / "python")
        environment["HF_HOME"] = str(self.runtime_root / "model-cache" / "huggingface")
        environment["SENTENCE_TRANSFORMERS_HOME"] = str(self.runtime_root / "model-cache" / "sentence-transformers")
        environment["PYTHONUTF8"] = "1"
        key = hashlib.sha256(os.path.normcase(self._project_root).encode("utf-8")).hexdigest()
        environment["RUBRA_PROJECT_ROOT"] = self._project_root
        environment["RUBRA_PORTABLE_ROOT"] = str(self.portable_root)
        environment["RUBRA_INDEX_ROOT"] = str(self.index_root / key)
        environment["HF_HUB_DISABLE_TELEMETRY"] = "1"
        environment["DO_NOT_TRACK"] = "1"
        environment["TOKENIZERS_PARALLELISM"] = "false"
        return environment
