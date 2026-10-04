from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


class LocalAIError(RuntimeError):
    pass


class LocalAIService:
    def __init__(self, portable_root: Path) -> None:
        self.portable_root = portable_root.resolve()
        self.runtime_root = self.portable_root / "runtime"
        self.model_path = self.runtime_root / "models" / "Qwen3-4B-Q4_K_M.gguf"
        self._process: subprocess.Popen[str] | None = None
        self._port = 0
        self._lock = threading.RLock()

    @property
    def available(self) -> bool:
        return self.model_path.is_file() and self._server_executable() is not None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None and self._port > 0

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 700,
        temperature: float = 0.15,
        timeout: float = 120.0,
    ) -> str:
        value = prompt.strip()
        if not value:
            raise LocalAIError("Local prompt is empty.")
        self._ensure_started()
        payload = {
            "model": "rubra-local",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are Rubra Local Scout. Work only as an analysis and planning assistant for legitimate "
                        "Roblox Studio development. Be concise, technical, evidence-aware, and never claim a test ran "
                        "unless the prompt contains test evidence. Respond in English."
                    ),
                },
                {"role": "user", "content": value},
            ],
            "temperature": max(0.0, min(1.0, float(temperature))),
            "max_tokens": max(64, min(2048, int(max_tokens))),
            "stream": False,
        }
        request = Request(
            f"http://127.0.0.1:{self._port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=max(10.0, min(300.0, timeout))) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise LocalAIError(f"Local model request failed: {exc}") from exc
        try:
            text = str(body["choices"][0]["message"]["content"]).strip()
        except Exception as exc:
            raise LocalAIError("Local model returned an invalid response.") from exc
        return text[:16000]

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._port = 0
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

    def _ensure_started(self) -> None:
        with self._lock:
            if self.running:
                return
            executable = self._server_executable()
            if executable is None or not self.model_path.is_file():
                raise LocalAIError("Portable local model runtime is unavailable.")
            port = self._free_loopback_port()
            command = [
                str(executable),
                "--model",
                str(self.model_path),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--ctx-size",
                "4096",
                "--threads",
                "4",
                "--parallel",
                "1",
                "--no-webui",
            ]
            if "vulkan" in str(executable).casefold():
                command.extend(["--n-gpu-layers", "99"])
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            environment = dict(os.environ)
            environment["LLAMA_CACHE"] = str(self.runtime_root / "model-cache" / "llama")
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                creationflags=creation_flags,
            )
            self._process = process
            self._port = port
        try:
            self._wait_until_ready(45.0)
        except Exception:
            self.close()
            raise

    def _server_executable(self) -> Path | None:
        roots = [
            self.runtime_root / "local-ai" / "llama-vulkan",
            self.runtime_root / "local-ai" / "llama-cpu",
        ]
        for root in roots:
            if not root.exists():
                continue
            direct = root / "llama-server.exe"
            if direct.is_file():
                return direct
            found = next(root.rglob("llama-server.exe"), None)
            if found is not None:
                return found
        return None

    def _wait_until_ready(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            process = self._process
            if process is None or process.poll() is not None:
                output = ""
                if process is not None and process.stdout is not None:
                    try:
                        output = process.stdout.read()[-3000:]
                    except Exception:
                        output = ""
                raise LocalAIError("Local model server exited during startup. " + output)
            try:
                with urlopen(f"http://127.0.0.1:{self._port}/health", timeout=1.0) as response:
                    if 200 <= response.status < 500:
                        return
            except URLError as exc:
                last_error = str(exc)
            time.sleep(0.25)
        raise LocalAIError("Local model server did not become ready. " + last_error)

    @staticmethod
    def _free_loopback_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            return int(server.getsockname()[1])
