from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .studio_mcp import MCPError, StudioMCPClient


class ProjectIndexError(RuntimeError):
    pass


class ProjectIndexService:
    def __init__(self, portable_root: Path) -> None:
        self.portable_root = portable_root.resolve()
        self.runtime_root = self.portable_root / "runtime"
        self.source_root = self.runtime_root / "sources" / "code-search"
        self.home_root = self.runtime_root / "home"
        self.index_root = self.runtime_root / "index"
        self._client: StudioMCPClient | None = None
        self._lock = threading.RLock()
        self._project_root = ""

    @property
    def project_root(self) -> str:
        return self._project_root

    @property
    def running(self) -> bool:
        return bool(self._client and self._client.running)

    def configure(self, project_root: str) -> str:
        raw = project_root.strip()
        if not raw:
            self._project_root = ""
            return ""
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            raise ProjectIndexError(f"Project directory does not exist: {path}")
        self._project_root = str(path)
        return self._project_root

    def index(self, project_root: str | None = None, *, incremental: bool = True) -> dict[str, Any]:
        root = self.configure(project_root) if project_root is not None else self._project_root
        if not root:
            raise ProjectIndexError("No project directory is configured.")
        client = self._ensure_client()
        result = client.call_tool(
            "index_directory",
            {"path": root, "incremental": bool(incremental)},
            timeout=900,
        )
        if result.is_error:
            raise ProjectIndexError(result.compact(6000))
        return {"projectRoot": root, "result": result.text, "indexed": True}

    def search(self, query: str, *, limit: int = 12, semantic: bool = True) -> dict[str, Any]:
        root = self._project_root
        if not root:
            return {"projectRoot": "", "query": query, "result": "", "available": False}
        value = query.strip()
        if not value:
            return {"projectRoot": root, "query": "", "result": "", "available": True}
        client = self._ensure_client()
        name = "search_code" if semantic else "search_text"
        arguments = {"query": value, "limit": max(1, min(30, int(limit)))} if semantic else {
            "keyword": value,
            "limit": max(1, min(30, int(limit))),
        }
        result = client.call_tool(name, arguments, timeout=120)
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
            if not path.is_file():
                continue
            try:
                if path.stat().st_size > 128 * 1024:
                    continue
                result[name] = path.read_text(encoding="utf-8", errors="replace")[:16000]
            except OSError:
                continue
        return result

    def status(self) -> dict[str, Any]:
        if not self._project_root:
            return {"configured": False, "projectRoot": "", "running": self.running, "result": ""}
        if not self.running:
            return {"configured": True, "projectRoot": self._project_root, "running": False, "result": ""}
        try:
            result = self._ensure_client().call_tool("get_index_status", {}, timeout=45)
            return {
                "configured": True,
                "projectRoot": self._project_root,
                "running": True,
                "result": result.text,
            }
        except Exception as exc:
            return {
                "configured": True,
                "projectRoot": self._project_root,
                "running": self.running,
                "result": "",
                "error": str(exc),
            }

    def close(self) -> None:
        with self._lock:
            client = self._client
            self._client = None
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
            self._write_config()
            client = StudioMCPClient(
                uv,
                args=("run", "--directory", str(self.source_root), "mcp-code-search"),
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
        return environment

    def _write_config(self) -> None:
        config_root = self.home_root / ".config" / "mcp-code-search"
        config_root.mkdir(parents=True, exist_ok=True)
        config = (
            "[embedding]\n"
            'provider = "sentence-transformers"\n'
            'model = "all-MiniLM-L6-v2"\n\n'
            "[indexing]\n"
            "max_file_size_kb = 750\n"
            "batch_size = 16\n"
            "chunk_overlap_lines = 2\n"
            "max_chunk_lines = 60\n\n"
            "[search]\n"
            "rrf_k = 60\n"
            "snippet_max_lines = 36\n\n"
            "[storage]\n"
            f'base_path = {json.dumps(str(self.index_root))}\n'
        )
        (config_root / "config.toml").write_text(config, encoding="utf-8")
