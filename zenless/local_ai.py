from __future__ import annotations

import hashlib
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
    CONTEXT_SIZE = 32768
    MAX_PROMPT_CHARS = 64_000

    def __init__(self, portable_root: Path) -> None:
        self.portable_root = portable_root.resolve()
        self.runtime_root = self.portable_root / "runtime"
        self.model_path = self.runtime_root / "models" / "Qwen3-4B-Q4_K_M.gguf"
        self._process: subprocess.Popen[bytes] | None = None
        self._port = 0
        self._log_path = self.portable_root / "data" / "logs" / "local-ai.log"
        self._lock = threading.RLock()
        self._inference_lock = threading.Lock()
        self._ollama_models_cache: tuple[str, ...] = ()
        self._ollama_cache_until = 0.0

    @property
    def available(self) -> bool:
        return self._portable_available() or bool(
            self._select_ollama_model("Role: Builder") or self._select_ollama_model("Role: Reviewer")
        )

    @property
    def backend_label(self) -> str:
        if self._portable_available():
            return "Rubra local · Qwen"
        ollama = self._select_ollama_model("Role: Builder") or self._select_ollama_model("Role: Reviewer")
        return f"Ollama · {ollama}" if ollama else "Local AI unavailable"

    def _model_paths(self) -> tuple[Path, Path]:
        return (
            self.runtime_root / "models" / "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
            self.runtime_root / "models" / "Qwen3-4B-Q4_K_M.gguf",
        )

    def model_status(self) -> list[dict[str, object]]:
        coder, general = self._model_paths()
        result: list[dict[str, object]] = [
            {"id": "qwen-coder-7b", "name": coder.stem, "installed": coder.is_file()},
            {"id": "qwen3-4b", "name": general.stem, "installed": general.is_file()},
        ]
        builder_model = self._select_ollama_model("Role: Builder")
        reviewer_model = self._select_ollama_model("Role: Reviewer")
        ollama_model = builder_model or reviewer_model
        if ollama_model:
            roles = []
            if builder_model:
                roles.append(f"Builder: {builder_model}")
            if reviewer_model:
                roles.append(f"Reviewer: {reviewer_model}")
            result.append(
                {
                    "id": "ollama",
                    "name": f"Ollama · {ollama_model}",
                    "installed": True,
                    "state": "ready",
                    "detail": "Detected through the local Ollama API; " + " · ".join(roles),
                }
            )
        return result

    def _portable_available(self) -> bool:
        return any(path.is_file() for path in self._model_paths()) and bool(self._server_candidates())

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
        with self._inference_lock:
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
        value = self._compact_prompt(value)
        portable_error: LocalAIError | None = None
        if self._portable_available():
            try:
                return self._complete_portable(
                    value,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=timeout,
                )
            except LocalAIError as exc:
                portable_error = exc

        ollama_model = self._select_ollama_model(value)
        if ollama_model:
            try:
                return self._complete_ollama(
                    value,
                    ollama_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=timeout,
                )
            except LocalAIError as exc:
                if portable_error is not None:
                    raise LocalAIError(
                        f"Portable local AI failed: {portable_error} | Ollama fallback failed: {exc}"
                    ) from exc
                raise

        if portable_error is not None:
            raise portable_error
        raise LocalAIError(
            "No local text model is available. Install the pinned Rubra model/runtime or start Ollama with a supported local model."
        )

    def _complete_portable(
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
        value = self._compact_prompt(value)
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

    def _ollama_models(self) -> tuple[str, ...]:
        now = time.monotonic()
        if now < self._ollama_cache_until:
            return self._ollama_models_cache
        models: tuple[str, ...] = ()
        try:
            request = Request("http://127.0.0.1:11434/api/tags", headers={"Accept": "application/json"})
            with urlopen(request, timeout=0.4) as response:
                payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
            raw_models = payload.get("models", []) if isinstance(payload, dict) else []
            names = []
            for item in raw_models if isinstance(raw_models, list) else []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("model") or "").strip()
                if name:
                    names.append(name)
            models = tuple(dict.fromkeys(names))
        except (OSError, TimeoutError, URLError, ValueError, json.JSONDecodeError):
            models = ()
        self._ollama_models_cache = models
        self._ollama_cache_until = now + 10.0
        return models

    def _select_ollama_model(self, prompt: str) -> str:
        models = self._ollama_models()
        if not models:
            return ""
        override = str(os.environ.get("RUBRA_OLLAMA_MODEL") or "").strip()
        if override:
            exact = next((model for model in models if model.casefold() == override.casefold()), "")
            if exact:
                return exact
        reviewer = prompt.startswith("Role: Reviewer")
        preferences = (
            (
                "qwen3:4b",
                "qwen3-4b",
                "gpt-oss",
                "qwen3",
                "deepseek-r1",
                "deepseek",
                "llama",
                "mistral",
                "gemma",
                "phi",
            )
            if reviewer
            else (
                "qwen3-coder",
                "qwen2.5-coder",
                "qwen-coder",
                "gpt-oss",
                "deepseek-coder",
                "qwen3",
                "codellama",
                "codegemma",
                "llama",
                "mistral",
                "gemma",
                "phi",
            )
        )
        lowered = [
            (model, model.casefold())
            for model in models
            if not any(blocked in model.casefold() for blocked in ("embed", "embedding", "rerank"))
        ]
        for preferred in preferences:
            match = next((model for model, value in lowered if preferred in value), "")
            if match:
                return match
        return ""

    def _complete_ollama(
        self,
        prompt: str,
        model: str,
        *,
        max_tokens: int,
        temperature: float,
        timeout: float,
    ) -> str:
        system = (
            "You are Rubra, a Roblox Studio engineering assistant. Build, analyze, or review Luau according "
            "to the requested role. Follow the supplied JSON protocol exactly when requested. Use only "
            "advertised tools. Be evidence-aware and never claim a test ran without test evidence. "
            "Respond in English. /no_think"
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        deadline = time.monotonic() + max(10.0, min(900.0, timeout))
        parts: list[str] = []
        for _ in range(3):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LocalAIError("Ollama completion exceeded its time budget.")
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "think": False,
                "keep_alive": 0,
                "options": {
                    "temperature": max(0.0, min(1.0, float(temperature))),
                    "num_predict": max(64, min(2048, int(max_tokens))),
                },
            }
            request = Request(
                "http://127.0.0.1:11434/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=remaining) as response:
                    body = json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))
                message = body.get("message") if isinstance(body, dict) else None
                content = str(message.get("content") or "") if isinstance(message, dict) else ""
                if not content.strip():
                    raise ValueError("Empty Ollama model content")
            except (OSError, TimeoutError, URLError, ValueError, json.JSONDecodeError) as exc:
                self._ollama_cache_until = 0.0
                raise LocalAIError(f"Ollama request failed for {model}: {exc}") from exc
            parts.append(content)
            done_reason = str(body.get("done_reason") or "").casefold() if isinstance(body, dict) else ""
            if done_reason not in {"length", "max_tokens"}:
                return "".join(parts).strip()
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": "".join(parts)},
                {
                    "role": "user",
                    "content": "Continue exactly where you stopped. Do not repeat any content or restart the JSON object.",
                },
            ]
        raise LocalAIError(
            "Ollama output is still truncated after three continuations. Reduce the task scope before applying changes."
        )

    @classmethod
    def _compact_prompt(cls, prompt: str) -> str:
        if len(prompt) <= cls.MAX_PROMPT_CHARS:
            return prompt
        digest = hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest()
        marker = (
            "\n\n[RUBRA LOCAL CONTEXT COMPACTED "
            f"original_chars={len(prompt)} sha256={digest}; "
            "middle evidence omitted to preserve the role contract and most recent evidence]\n\n"
        )
        budget = cls.MAX_PROMPT_CHARS - len(marker)
        head = max(1, budget * 3 // 4)
        tail = max(1, budget - head)
        return prompt[:head] + marker + prompt[-tail:]

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
            str(self.CONTEXT_SIZE),
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
                    if 200 <= response.status < 300:
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
