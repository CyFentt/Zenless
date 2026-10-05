from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


class LocalAIError(RuntimeError):
    pass


class LocalAIService:
    def __init__(self, portable_root: Path) -> None:
        self.portable_root = portable_root.resolve()
        self.runtime_root = self.portable_root / "runtime"
        self.model_path = self.runtime_root / "models" / "Qwen3-4B-Q4_K_M.gguf"
        self._process: subprocess.Popen[bytes] | None = None
        self._port = 0
        self._log_path = self.portable_root / "data" / "logs" / "local-ai.log"
        self._lock = threading.RLock()

    @property
    def available(self) -> bool:
        return any(path.is_file() for path in self._model_paths()) and bool(self._server_candidates())

    def _model_paths(self) -> tuple[Path, Path]:
        return (
            self.runtime_root / "models" / "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
            self.runtime_root / "models" / "Qwen3-4B-Q4_K_M.gguf",
        )

    def model_status(self) -> list[dict[str, object]]:
        return [{"name": path.stem, "installed": path.is_file()} for path in self._model_paths()]

    def _select_model(self, prompt: str) -> None:
        coder, general = self._model_paths()
        if not coder.is_file() and not general.is_file():
            return
        preferred = general if prompt.startswith("Role: Reviewer") else coder
        target = preferred if preferred.is_file() else general if general.is_file() else coder
        if target != self.model_path:
            self._stop_process()
            self.model_path = target

    @property
    def running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None and self._port > 0

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 700,
        temperature: float = 0.15,
        timeout: float = 120.0,
    ) -> str:
        with self._lock:
            return self._complete(prompt, max_tokens=max_tokens, temperature=temperature, timeout=timeout)

    def _complete(
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
        self._select_model(value)
        self._ensure_started()
        payload = {
            "model": "rubra-local",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are Rubra, a Roblox Studio engineering assistant. Build, analyze, or review Luau according "
                        "to the requested role. Follow the supplied JSON protocol exactly when requested. Use only "
                        "advertised tools. Be evidence-aware and never claim a test ran without test evidence. "
                        "Respond in English. /no_think"
                    ),
                },
                {"role": "user", "content": value},
            ],
            "temperature": max(0.0, min(1.0, float(temperature))),
            "max_tokens": max(64, min(2048, int(max_tokens))),
            "stream": False,
        }
        deadline = time.monotonic() + max(10.0, min(900.0, timeout))
        parts: list[str] = []
        for _ in range(3):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LocalAIError("Local completion exceeded its time budget.")
            request = Request(
                f"http://127.0.0.1:{self._port}/v1/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=remaining) as response:
                    body = json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))
                choice = body["choices"][0]
                content = choice["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Empty model content")
            except Exception as exc:
                raise LocalAIError(f"Local model request failed: {exc}") from exc
            parts.append(content)
            if choice.get("finish_reason") != "length":
                return "".join(parts).strip()
            payload["messages"] = [
                *payload["messages"][:2],
                {"role": "assistant", "content": "".join(parts)},
                {
                    "role": "user",
                    "content": "Continue exactly where you stopped. Do not repeat any content or restart the JSON object.",
                },
            ]
        raise LocalAIError(
            "Local output is still truncated after three continuations. Reduce the task scope before applying changes."
        )

    def close(self) -> None:
        self._stop_process()

    def _ensure_started(self) -> None:
        with self._lock:
            self._start()

    def _start(self) -> None:
        with self._lock:
            if self.running:
                return
            if not self.model_path.is_file():
                raise LocalAIError("Portable local model is unavailable.")
            candidates = self._server_candidates()
            if not candidates:
                raise LocalAIError("Portable llama.cpp runtime is unavailable.")

        errors: list[str] = []
        for executable, use_gpu in candidates:
            try:
                self._start_candidate(executable, use_gpu)
                self._wait_until_ready(45.0)
                return
            except Exception as exc:
                errors.append(f"{executable.parent.name}: {exc}")
                self._stop_process()
        raise LocalAIError("No local model backend started successfully. " + " | ".join(errors[-3:]))

    def _start_candidate(self, executable: Path, use_gpu: bool) -> None:
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
            "16384",
            "--threads",
            "4",
            "--parallel",
            "1",
            "--no-webui",
        ]
        command.extend(["--n-gpu-layers", "16" if use_gpu else "0"])
        environment = dict(os.environ)
        environment["LLAMA_CACHE"] = str(self.runtime_root / "model-cache" / "llama")
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("wb") as output:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        with self._lock:
            self._process = process
            self._port = port

    def _stop_process(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._port = 0
            if process is None:
                return
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

    def _server_candidates(self) -> list[tuple[Path, bool]]:
        roots = [
            (self.runtime_root / "local-ai" / "llama-vulkan", True),
            (self.runtime_root / "local-ai" / "llama-cpu", False),
        ]
        result: list[tuple[Path, bool]] = []
        for root, use_gpu in roots:
            if not root.exists():
                continue
            direct = root / "llama-server.exe"
            executable = direct if direct.is_file() else next(root.rglob("llama-server.exe"), None)
            if executable is not None:
                result.append((executable, use_gpu))
        return result

    def _wait_until_ready(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            process = self._process
            if process is None or process.poll() is not None:
                output = ""
                try:
                    with self._log_path.open("rb") as log:
                        log.seek(max(0, self._log_path.stat().st_size - 3000))
                        output = log.read(3000).decode("utf-8", errors="replace")
                except OSError:
                    pass
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
