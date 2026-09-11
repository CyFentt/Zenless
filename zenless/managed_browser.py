from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .browser_bridge import BridgeError, LoginWindowOpenedCallback, StatusCallback
from .diagnostics import ErrorBus
from .provider_registry import normalize_capabilities


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    code: str
    url: str
    inputs: tuple[str, ...]
    sends: tuple[str, ...]
    stops: tuple[str, ...]
    responses: tuple[str, ...]
    composers: tuple[str, ...] = ()
    accounts: tuple[str, ...] = ()
    unauthenticated: tuple[str, ...] = ()
    challenges: tuple[str, ...] = ()
    login_paths: tuple[str, ...] = ()
    authenticated_paths: tuple[str, ...] = ()
    mode_options: tuple[tuple[str, tuple[str, ...]], ...] = ()


PROVIDERS: dict[str, ProviderSpec] = {
    "chatgpt": ProviderSpec(
        "chatgpt",
        "https://chatgpt.com/",
        ("textarea", "#prompt-textarea", "div[contenteditable='true'][data-lexical-editor='true']"),
        (
            "#composer-submit-button",
            "button[data-testid='send-button']",
            "button[aria-label*='Send']",
            "button[aria-label*='Enviar']",
        ),
        ("button[data-testid='stop-button']", "button[aria-label*='Stop']", "button[aria-label*='Parar']"),
        ("[data-message-author-role='assistant']", "article[data-testid*='conversation-turn'] .markdown"),
        composers=("textarea", "#prompt-textarea", "div[contenteditable='true'][data-lexical-editor='true']"),
        accounts=(
            "[data-testid='profile-button']",
            "[data-testid='accounts-profile-button']",
            "button[data-testid*='profile']",
            "[data-testid*='user-menu']",
            "button[aria-label*='profile' i]",
            "button[aria-label*='account' i]",
            "button[aria-label*='perfil' i]",
            "button[aria-label*='conta' i]",
        ),
        unauthenticated=("a[href*='/auth/login']", "button[data-testid*='login']", "input[name='email']"),
        challenges=("iframe[src*='captcha']", "[id*='challenge']", "[data-testid*='challenge']"),
        login_paths=("/auth/login", "/auth/", "/login"),
        authenticated_paths=("chatgpt.com/c/",),
    ),
    "deepseek": ProviderSpec(
        "deepseek",
        "https://chat.deepseek.com/",
        ("textarea", "div[contenteditable='true']"),
        (
            ".ds-button--primary",
            "button[aria-label*='Send']",
            "button[class*='send']",
        ),
        (".ds-loading", "button[aria-label*='Stop']", "button[class*='stop']"),
        (".ds-markdown", "[class*='markdown']", "[class*='message'][class*='assistant']"),
        composers=("textarea", "div[contenteditable='true']"),
        accounts=("[class*='avatar']", "[class*='user-info']", "button[aria-label*='account']"),
        unauthenticated=("input[type='password']", "input[name='email']", "[class*='login'] input"),
        challenges=("iframe[src*='captcha']", "[class*='captcha']", "[class*='verify']"),
        login_paths=("/sign_in", "/login"),
        authenticated_paths=("chat.deepseek.com/", "chat.deepseek.com/a/chat", "chat.deepseek.com/chat"),
        mode_options=(("instant", ("instant",)), ("expert", ("expert",))),
    ),
    "hunyuan": ProviderSpec(
        "hunyuan",
        "https://3d.hunyuan.tencent.com/",
        ("textarea", "div[contenteditable='true']"),
        ("button[type='submit']", "button[class*='generate']", "button[class*='create']"),
        ("button[class*='cancel']", "button[class*='stop']"),
        ("[class*='result']", "[class*='asset-card']", "[class*='generation']"),
        composers=("textarea", "div[contenteditable='true']"),
        accounts=("[class*='avatar']", "[class*='user-center']", "[class*='account']"),
        unauthenticated=("input[type='password']", "input[type='email']", "[class*='login'] input"),
        challenges=("iframe[src*='captcha']", "[class*='captcha']", "[class*='verify']"),
        login_paths=("/login", "/signin", "/sign-in"),
        authenticated_paths=("3d.hunyuan.tencent.com/",),
    ),
}


class BrowserRuntimeManager:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self._launchability: dict[tuple[str, int, int], bool] = {}

    def environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment["PLAYWRIGHT_BROWSERS_PATH"] = str(self.runtime_root)
        return environment

    def chromium_executable(self) -> Path | None:
        return next((candidate for candidate in self._candidates() if self._is_launchable(candidate)), None)

    @property
    def installed(self) -> bool:
        return self.chromium_executable() is not None

    def install(self, cancel: threading.Event | None = None) -> Path:
        self._remove_invalid_runtimes()
        existing = self.chromium_executable()
        if existing is not None:
            return existing
        from playwright._impl._driver import compute_driver_executable, get_driver_env

        driver_executable, driver_cli = compute_driver_executable()
        environment = get_driver_env()
        environment.update(self.environment())
        process = subprocess.Popen(
            [driver_executable, driver_cli, "install", "--no-shell", "chromium"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output_text = ""
        while True:
            try:
                output_text, _ = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    process.terminate()
                    output_text, _ = process.communicate(timeout=10)
                    raise BridgeError("Managed browser installation cancelled.")
        if process.returncode != 0:
            raise BridgeError("Managed Chromium preparation failed: " + output_text[-3000:])
        installed = self.chromium_executable()
        if installed is None:
            self._remove_invalid_runtimes()
            raise BridgeError("Managed browser setup completed, but its runtime could not start on this Windows installation.")
        return installed

    def _candidates(self) -> list[Path]:
        return sorted(
            (
                path
                for pattern in ("chromium-*/chrome-win64/chrome.exe", "chromium-*/chrome-win/chrome.exe")
                for path in self.runtime_root.glob(pattern)
                if path.is_file()
            ),
            reverse=True,
        )

    def _is_launchable(self, executable: Path) -> bool:
        try:
            stat = executable.stat()
        except OSError:
            return False
        key = (str(executable.resolve()), stat.st_size, stat.st_mtime_ns)
        cached = self._launchability.get(key)
        if cached is not None:
            return cached
        try:
            result = subprocess.run(
                [str(executable), "--version"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            ready = result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ready = False
        self._launchability[key] = ready
        return ready

    def _remove_invalid_runtimes(self) -> None:
        root = self.runtime_root.resolve()
        invalid = {candidate.parent.parent for candidate in self._candidates() if not self._is_launchable(candidate)}
        for target in invalid:
            if target.parent.resolve() != root:
                raise BridgeError("Managed browser cleanup target escaped the runtime root.")
            if target.is_symlink():
                target.unlink()
            elif target.is_junction():
                target.rmdir()
            else:
                shutil.rmtree(target)


@dataclass(slots=True)
class _Command:
    action: str
    provider: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timeout: float = 60.0
    event: threading.Event = field(default_factory=threading.Event)
    cancelled: threading.Event = field(default_factory=threading.Event)
    stream_callback: Callable[[str], None] | None = None
    result: Any = None
    error: BaseException | None = None


class ManagedBrowserController:
    def __init__(
        self,
        *,
        data_root: Path,
        status_callback: StatusCallback | None = None,
        diagnostics: ErrorBus | None = None,
        provider_specs: dict[str, ProviderSpec] | None = None,
    ) -> None:
        self.data_root = data_root
        self.profile_root = data_root / "browser-profile"
        self.runtime = BrowserRuntimeManager(data_root / "browser-runtime")
        self.download_root = data_root / "downloads"
        self.status_callback = status_callback
        self.diagnostics = diagnostics
        self.provider_specs = dict(provider_specs or PROVIDERS)
        self._commands: queue.Queue[_Command] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._start_error: BaseException | None = None
        self._state_lock = threading.RLock()
        self._states: dict[str, dict[str, str]] = {
            code: {"state": "Standby", "detail": "Managed browser is idle", "transport": "playwright"}
            for code in self.provider_specs
        }
        self._context: Any = None
        self._pages: dict[str, Any] = {}
        self._headed = False
        self._login_provider = ""
        self._login_ready_at = 0.0
        self._runtime_blocked = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._start_error is None

    def start(self, timeout: float = 10.0) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._stop.clear()
        self._start_error = None
        self._thread = threading.Thread(target=self._run, name="Zenless-ManagedBrowser", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise BridgeError("Managed browser controller did not start in time.")
        if self._start_error is not None:
            raise BridgeError(f"Managed browser controller failed to start: {self._start_error}")

    def stop(self, timeout: float = 8.0) -> None:
        self._stop.set()
        command = _Command("stop", timeout=timeout)
        self._commands.put(command)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.1, timeout))

    def provider_status(self) -> dict[str, dict[str, str]]:
        with self._state_lock:
            return {key: dict(value) for key, value in self._states.items()}

    def wait_for_provider(self, provider: str, timeout: float = 5.0) -> bool:
        try:
            result = self._call("health", provider, timeout=max(15.0, timeout))
        except BridgeError:
            return False
        return bool(result.get("ready"))

    def login(
        self,
        provider: str,
        *,
        install_if_missing: bool = True,
        timeout: float = 180.0,
        on_window_opened: LoginWindowOpenedCallback | None = None,
    ) -> dict[str, Any]:
        opened = self._call(
            "login",
            provider,
            {"install_if_missing": install_if_missing},
            timeout=timeout,
        )
        if on_window_opened is not None:
            try:
                on_window_opened(provider, "playwright")
            except Exception as exc:
                self._report(exc, "login-window-opened-callback", provider=provider, severity="WARNING")
        deadline = time.monotonic() + max(30.0, min(900.0, timeout))
        while time.monotonic() < deadline and not self._stop.wait(0.25):
            with self._state_lock:
                state = str(self._states.get(provider, {}).get("state", ""))
            if state == "Ready":
                return {**opened, "state": "ready"}
            if state in {"Unavailable", "Error"}:
                raise BridgeError(f"Managed login failed for {provider}.")
        raise BridgeError(f"Login timeout for {provider}.")

    def send_prompt(
        self,
        provider: str,
        prompt: str,
        *,
        task_id: str,
        timeout: float = 360.0,
        stream_callback: Callable[[str], None] | None = None,
    ) -> str:
        result = self.request(
            provider,
            "send_prompt",
            {"prompt": prompt, "timeout_ms": int(timeout * 1000)},
            task_id=task_id,
            timeout=timeout,
            stream_callback=stream_callback,
        )
        text = str(result.get("text") or "").strip()
        if not text:
            raise BridgeError(f"{provider} completed without returning text.")
        return text

    def request(
        self,
        provider: str,
        action: str,
        payload: dict[str, Any],
        *,
        task_id: str,
        timeout: float,
        stream_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        command_payload = dict(payload)
        command_payload.update({"provider_action": action, "task_id": task_id, "request_id": uuid.uuid4().hex})
        return self._call(
            "request",
            provider,
            command_payload,
            timeout=timeout,
            stream_callback=stream_callback,
        )

    def _call(
        self,
        action: str,
        provider: str = "",
        payload: dict[str, Any] | None = None,
        *,
        timeout: float,
        stream_callback: Callable[[str], None] | None = None,
    ) -> Any:
        if provider and provider not in self.provider_specs:
            raise BridgeError(f"Unknown managed provider: {provider}")
        if not self.running:
            self.start()
        command = _Command(
            action,
            provider,
            payload or {},
            timeout=max(1.0, timeout),
            stream_callback=stream_callback,
        )
        self._commands.put(command)
        if not command.event.wait(command.timeout + 2.0):
            command.cancelled.set()
            raise BridgeError(f"Managed browser timed out ({action}/{provider or 'core'}).")
        if command.error is not None:
            if isinstance(command.error, BridgeError):
                raise command.error
            raise BridgeError(str(command.error)) from command.error
        return command.result

    def _run(self) -> None:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(self.runtime.runtime_root)
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                self._playwright = playwright
                self._ready.set()
                self._event_loop()
        except BaseException as exc:
            self._start_error = exc
            self._ready.set()
            self._report(exc, "managed-browser-thread", severity="CRITICAL")
        finally:
            self._close_context()
            self._fail_pending(BridgeError("Managed browser stopped."))

    def _event_loop(self) -> None:
        while not self._stop.is_set():
            try:
                command = self._commands.get(timeout=0.5)
            except queue.Empty:
                self._poll_login()
                continue
            if command.action == "stop":
                command.result = {"stopped": True}
                command.event.set()
                return
            try:
                command.result = self._handle(command)
            except BaseException as exc:
                if command.action in {"health", "login"} and "launch_persistent_context" in str(exc):
                    self._runtime_blocked = True
                    if command.provider:
                        self._set_state(
                            command.provider,
                            "Unavailable",
                            "Playwright runtime failed; Zenless will try embedded WebView2",
                        )
                command.error = exc
                self._report(
                    exc,
                    f"managed-browser:{command.action}",
                    provider=command.provider,
                    request_id=str(command.payload.get("request_id") or ""),
                    job_id=str(command.payload.get("task_id") or ""),
                )
            finally:
                command.event.set()
            self._poll_login()

    def _handle(self, command: _Command) -> Any:
        if command.action == "health":
            if self._runtime_blocked:
                return {"ready": False, "runtime": "unavailable"}
            if not self.runtime.installed:
                self._set_state(command.provider, "Runtime Required", "Click Login to prepare managed Chromium")
                return {"ready": False, "runtime": "missing"}
            self._ensure_context(headed=False)
            page = self._ensure_page(command.provider)
            auth_state = self._auth_state(page, self.provider_specs[command.provider])
            ready = auth_state == "AUTHENTICATED"
            self._set_state(
                command.provider,
                "Ready" if ready else "Login Required",
                "Authenticated managed session" if ready else f"Provider state: {auth_state}",
            )
            return {
                "ready": ready,
                "runtime": "ready",
                "capabilities": self._capabilities(page, self.provider_specs[command.provider]),
            }
        if command.action == "login":
            if self._runtime_blocked:
                raise BridgeError("Playwright runtime unavailable on this Windows installation.")
            if not self.runtime.installed:
                if not command.payload.get("install_if_missing", True):
                    raise BridgeError("Managed Chromium has not been prepared.")
                self._set_state(command.provider, "Installing", "Preparing managed Chromium once")
                try:
                    self.runtime.install(self._stop)
                except BridgeError:
                    self._runtime_blocked = True
                    raise
            self._ensure_context(headed=True)
            page = self._ensure_page(command.provider, navigate=True)
            page.bring_to_front()
            self._login_provider = command.provider
            self._login_ready_at = 0.0
            self._set_state(command.provider, "Login Required", "Complete login in the managed window")
            return {"state": "login_window_open", "url": page.url}
        if command.action == "request":
            self._ensure_context(headed=False)
            provider_action = str(command.payload.get("provider_action") or "send_prompt")
            if provider_action == "upload_files":
                return self._upload_files(command)
            if provider_action == "select_model":
                return self._select_model(command)
            if provider_action == "select_mode":
                return self._select_mode(command)
            if provider_action == "get_models":
                return self._discover_models(command)
            if provider_action == "cancel":
                return self._cancel_generation(command)
            if provider_action == "reload":
                page = self._ensure_page(command.provider)
                page.reload(wait_until="domcontentloaded", timeout=60_000)
                return {"status": "ok", "reloaded": True, "transport": "playwright"}
            if provider_action == "capabilities":
                page = self._ensure_page(command.provider)
                return {
                    "status": "ok",
                    "capabilities": self._capabilities(page, self.provider_specs[command.provider]),
                    "transport": "playwright",
                }
            return self._send(command)
        raise BridgeError(f"Unsupported browser command: {command.action}")

    def _ensure_context(self, *, headed: bool) -> None:
        if self._context is not None and self._headed == headed:
            return
        reopen = tuple(self._pages)
        self._close_context()
        executable = self.runtime.chromium_executable()
        if executable is None:
            raise BridgeError("Managed Chromium is unavailable. Use Login to prepare it.")
        self.profile_root.mkdir(parents=True, exist_ok=True)
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_root),
            executable_path=str(executable),
            headless=not headed,
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
            args=["--disable-background-networking", "--disable-component-update", "--no-first-run"],
        )
        self._headed = headed
        self._pages = {}
        self._context.route("**/*", self._route_request)
        for code in reopen:
            try:
                self._ensure_page(code)
            except Exception as exc:
                self._report(exc, "restore-page", provider=code, severity="WARNING")

    def _ensure_page(self, provider: str, *, navigate: bool = False) -> Any:
        page = self._pages.get(provider)
        if page is not None and not page.is_closed():
            if navigate and urlparse(page.url).hostname != urlparse(self.provider_specs[provider].url).hostname:
                page.goto(self.provider_specs[provider].url, wait_until="domcontentloaded", timeout=60_000)
            return page
        page = self._context.new_page()
        self._pages[provider] = page
        page.on("pageerror", lambda error, code=provider: self._page_error(code, error))
        page.on("console", lambda message, code=provider: self._console_event(code, message))
        page.on("requestfailed", lambda request, code=provider: self._request_failed(code, request))
        page.goto(self.provider_specs[provider].url, wait_until="domcontentloaded", timeout=60_000)
        return page

    def _send(self, command: _Command) -> dict[str, Any]:
        spec = self.provider_specs[command.provider]
        page = self._ensure_page(command.provider)
        provider_action = str(command.payload.get("provider_action") or "send_prompt")
        if command.provider == "hunyuan" and provider_action in {"generate_geometry", "generate_texture"}:
            self._select_generation_mode(page, provider_action)
        composer = self._composer(page, spec)
        if composer is None:
            self._set_state(command.provider, "Login Required", "Composer unavailable in managed session")
            raise BridgeError(f"{command.provider} requires login or an adapter refresh.")
        if self._is_streaming(page, spec):
            raise BridgeError(f"{command.provider} already has an active generation.")
        response_locator = self._response_locator(page, spec)
        before_count = response_locator.count() if response_locator is not None else 0
        before_text = self._last_text(response_locator)
        prompt = str(command.payload.get("prompt") or "").strip()
        if not prompt:
            raise BridgeError("Prompt is empty.")
        composer.fill(prompt)
        sender = self._first_visible(page, spec.sends)
        if sender is None or sender.is_disabled():
            raise BridgeError(f"Submit button is unavailable for {command.provider}.")
        sender.click()
        self._set_state(command.provider, "Working", "Waiting for provider response")
        text = self._wait_response(page, spec, before_count, before_text, command)
        result: dict[str, Any] = {"status": "ok", "text": text}
        if provider_action == "generate_image":
            result.update(self._capture_generated_image(page, spec, command))
        if provider_action in {"generate_3d", "generate_geometry", "generate_texture"}:
            artifact_url = self._artifact_url(page)
            if artifact_url:
                result["artifact_url"] = artifact_url
                result["artifact_name"] = artifact_url.split("/")[-1].split("?")[0]
                artifact_path = self._download_artifact(artifact_url, str(command.payload.get("task_id") or "job"))
                if artifact_path is not None:
                    result["artifact_path"] = str(artifact_path)
        self._set_state(command.provider, "Ready", "Managed session idle")
        return result

    def _upload_files(self, command: _Command) -> dict[str, Any]:
        files = [Path(str(item)).expanduser().resolve() for item in command.payload.get("files", [])]
        page = self._ensure_page(command.provider)
        capabilities = self._capabilities(page, self.provider_specs[command.provider])
        try:
            max_files = max(1, min(6, int(capabilities.get("max_image_inputs") or 1)))
        except (TypeError, ValueError):
            max_files = 1
        if not files or len(files) > max_files:
            raise BridgeError(f"The provider accepts between 1 and {max_files} files in this session.")
        for path in files:
            if not path.is_file() or path.stat().st_size > 128 * 1024 * 1024:
                raise BridgeError(f"File is missing or larger than 128 MB: {path.name}")
        target = page.locator('input[type="file"]').first
        if target.count() == 0:
            raise BridgeError("The provider page exposes no compatible file input.")
        target.set_input_files([str(path) for path in files])
        return {"status": "ok", "uploaded": len(files), "transport": "playwright"}

    def _select_model(self, command: _Command) -> dict[str, Any]:
        model = str(command.payload.get("model") or "").strip()
        if not model:
            raise BridgeError("Model name is empty.")
        page = self._ensure_page(command.provider)
        nodes = page.locator('[role="option"], [role="menuitem"], [data-model], button')
        count = min(nodes.count(), 300)
        for index in range(count):
            node = nodes.nth(index)
            try:
                text = (node.inner_text(timeout=500) or "").strip()
                if model.casefold() in text.casefold() and node.is_visible():
                    node.click(timeout=3_000)
                    return {"status": "ok", "selected": text or model, "transport": "playwright"}
            except Exception:
                continue
        raise BridgeError(f"Model option not found: {model}")

    def _discover_models(self, command: _Command) -> dict[str, Any]:
        page = self._ensure_page(command.provider)
        values = page.locator(
            '[data-model], [role="option"], [role="menuitem"], '
            'button[aria-haspopup="listbox"], button[aria-haspopup="menu"]'
        ).evaluate_all(
            "nodes => nodes.map(node => (node.dataset.model || node.innerText || node.textContent || '').trim())"
            ".filter((value, index, all) => value && value.length <= 120 && all.indexOf(value) === index)"
            ".slice(0, 30)"
        )
        return {"status": "ok", "models": [str(item) for item in values], "transport": "playwright"}

    def _select_mode(self, command: _Command) -> dict[str, Any]:
        mode = str(command.payload.get("mode") or "").strip().casefold()
        options = dict(self.provider_specs[command.provider].mode_options)
        labels = options.get(mode)
        if labels is None:
            raise BridgeError("The provider mode is not supported by this adapter.")
        page = self._ensure_page(command.provider)
        spec = self.provider_specs[command.provider]
        result = page.evaluate(
            r"""
            ({labels}) => {
              const visible = node => !!node && getComputedStyle(node).display !== 'none' &&
                getComputedStyle(node).visibility !== 'hidden';
              const selected = node => node.getAttribute('aria-pressed') === 'true' ||
                node.getAttribute('aria-selected') === 'true' ||
                ['active', 'on', 'checked'].includes((node.getAttribute('data-state') || '').toLocaleLowerCase()) ||
                /(^|\s)(active|selected|checked)(\s|$)/i.test(node.className || '');
              const nodes = [...document.querySelectorAll('button,[role="tab"],[role="option"]')];
              const target = nodes.find(node => {
                const text = (node.innerText || node.textContent || '').trim().toLocaleLowerCase();
                return visible(node) && labels.some(label => text === label ||
                  (text.startsWith(label) && text.length <= label.length + 20));
              });
              if (!target) return {ok: false};
              const before = selected(target);
              if (!before) target.click();
              return {ok: true, changed: !before};
            }
            """,
            {"labels": [item.casefold() for item in labels]},
        )
        if not isinstance(result, dict) or not result.get("ok"):
            raise BridgeError("CAPABILITY_UNAVAILABLE: the provider did not expose a verified mode control.")
        page.wait_for_timeout(350)
        capabilities = self._capabilities(page, spec)
        if str(capabilities.get("mode") or "").casefold() != mode:
            raise BridgeError("CAPABILITY_UNAVAILABLE: the provider mode change could not be verified.")
        return {
            "status": "ok",
            "selected": mode,
            "capabilities": capabilities,
            "transport": "playwright",
        }

    def _cancel_generation(self, command: _Command) -> dict[str, Any]:
        page = self._ensure_page(command.provider)
        button = self._first_visible(page, self.provider_specs[command.provider].stops)
        if button is None:
            return {"status": "idle", "cancelled": False, "transport": "playwright"}
        button.click()
        return {"status": "ok", "cancelled": True, "transport": "playwright"}

    def _wait_response(
        self,
        page: Any,
        spec: ProviderSpec,
        before_count: int,
        before_text: str,
        command: _Command,
    ) -> str:
        timeout_ms = int(command.payload.get("timeout_ms") or command.timeout * 1000)
        deadline = time.monotonic() + max(10.0, min(900.0, timeout_ms / 1000))
        last_text = ""
        stable_since = 0.0
        while time.monotonic() < deadline:
            if self._stop.is_set() or command.cancelled.is_set():
                raise BridgeError("Managed browser operation cancelled.")
            locator = self._response_locator(page, spec)
            count = locator.count() if locator is not None else 0
            text = self._last_text(locator)
            is_new = count > before_count or bool(text and text != before_text)
            if is_new and text:
                if text != last_text:
                    if command.stream_callback is not None:
                        delta = text[len(last_text) :] if text.startswith(last_text) else ""
                        if delta:
                            try:
                                command.stream_callback(delta)
                            except Exception as exc:
                                self._report(
                                    exc,
                                    "managed-browser:stream-callback",
                                    provider=command.provider,
                                    job_id=str(command.payload.get("task_id") or ""),
                                )
                    last_text = text
                    stable_since = time.monotonic()
                elif not self._is_streaming(page, spec) and time.monotonic() - stable_since >= 2.0:
                    return text
            page.wait_for_timeout(350)
        raise BridgeError(f"Timed out waiting for a complete response from {spec.code}.")

    def _capabilities(self, page: Any, spec: ProviderSpec) -> dict[str, Any]:
        raw = page.evaluate(
            r"""
            ({inputs, sends, stops, responses, modeOptions}) => {
              const visible = node => !!node && getComputedStyle(node).display !== 'none' &&
                getComputedStyle(node).visibility !== 'hidden';
              const any = selectors => selectors.some(selector => [...document.querySelectorAll(selector)].some(visible));
              const file = [...document.querySelectorAll('input[type="file"]')].find(visible);
              const accept = (file?.getAttribute('accept') || '').split(',').map(value => value.trim()).filter(Boolean);
              const body = (document.body?.innerText || '').slice(0, 200000);
              const countMatch = body.match(/(?:up to|max(?:imum)?)\s*(\d+)\s*(?:images?|views?|photos?)/i);
              const explicitCount = countMatch ? Math.max(1, Math.min(6, Number(countMatch[1]))) : 0;
              const selected = node => node.getAttribute('aria-pressed') === 'true' ||
                node.getAttribute('aria-selected') === 'true' ||
                ['active', 'on', 'checked'].includes((node.getAttribute('data-state') || '').toLocaleLowerCase()) ||
                /(^|\s)(active|selected|checked)(\s|$)/i.test(node.className || '');
              const controls = [...document.querySelectorAll('button,[role="tab"],[role="option"]')]
                .filter(visible).slice(0, 400);
              const labels = controls
                .map(node => (node.innerText || node.textContent || '').trim()).filter(Boolean).join('\n');
              const matches = (node, options) => {
                const text = (node.innerText || node.textContent || '').trim().toLocaleLowerCase();
                return options.some(label => text === label ||
                  (text.startsWith(label) && text.length <= label.length + 20));
              };
              const modeControl = controls.find(node => Object.values(modeOptions).some(options => matches(node, options)));
              const activeMode = Object.entries(modeOptions)
                .find(([, options]) => controls.some(node => selected(node) && matches(node, options)))?.[0] || '';
              return {
                send_text: any(inputs) && any(sends),
                upload_files: !!file,
                file_types: accept,
                max_image_inputs: file ? (file.multiple ? (explicitCount || 1) : 1) : 0,
                cancel: any(stops),
                select_model: !!document.querySelector('[role="option"], [role="menuitem"], [data-model]'),
                select_mode: !!modeControl,
                responses: any(responses),
                search: /(web search|search the web)/i.test(labels),
                reasoning: /(reasoning|thinking|expert|reasoner|deepthink|deep think)/i.test(labels),
                mode: activeMode,
                image_generation: /(create image|generate image|image generation)/i.test(labels),
                geometry: /(geometry|shape|mesh)/i.test(labels),
                texture: /(texture|pbr|material)/i.test(labels),
                download_artifact: [...document.querySelectorAll('a[href]')]
                  .some(a => /\.(glb|gltf|fbx|obj)(\?|$)/i.test(a.href))
              };
            }
            """,
            {
                "inputs": list(spec.inputs),
                "sends": list(spec.sends),
                "stops": list(spec.stops),
                "responses": list(spec.responses),
                "modeOptions": {mode: [label.casefold() for label in labels] for mode, labels in spec.mode_options},
            },
        )
        return normalize_capabilities(dict(raw) if isinstance(raw, dict) else {}, source="LIVE")

    @staticmethod
    def _select_generation_mode(page: Any, action: str) -> None:
        patterns = (
            ("geometry", "shape", "mesh")
            if action == "generate_geometry"
            else ("texture", "pbr", "material")
        )
        nodes = page.locator('button, [role="tab"], [role="option"]')
        for index in range(min(nodes.count(), 400)):
            node = nodes.nth(index)
            try:
                label = (node.inner_text(timeout=300) or "").strip().casefold()
                if node.is_visible() and any(pattern in label for pattern in patterns):
                    node.click(timeout=3_000)
                    return
            except Exception:
                continue
        phase = "geometry" if action == "generate_geometry" else "texture"
        raise BridgeError(f"CAPABILITY_UNAVAILABLE: Hunyuan did not expose a {phase} generation mode.")

    def _capture_generated_image(
        self,
        page: Any,
        spec: ProviderSpec,
        command: _Command,
    ) -> dict[str, Any]:
        output_text = str(command.payload.get("output_path") or "").strip()
        if not output_text:
            raise BridgeError("generate_image requires an authorized output_path.")
        output = Path(output_text).resolve()
        try:
            output.relative_to(self.data_root.resolve())
        except ValueError as exc:
            raise BridgeError("Image output escaped Zenless storage.") from exc
        if output.suffix.casefold() != ".png":
            raise BridgeError("Generated concept output must be PNG.")
        response = self._response_locator(page, spec)
        container = response.last if response is not None and response.count() else page.locator("body")
        images = container.locator("img")
        for index in range(images.count() - 1, -1, -1):
            image = images.nth(index)
            try:
                dimensions = image.evaluate(
                    "node => ({width: node.naturalWidth || node.clientWidth, height: node.naturalHeight || node.clientHeight})"
                )
                width = int(dimensions.get("width", 0)) if isinstance(dimensions, dict) else 0
                height = int(dimensions.get("height", 0)) if isinstance(dimensions, dict) else 0
                if image.is_visible() and width >= 256 and height >= 256:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    image.screenshot(path=str(output), type="png")
                    if output.is_file() and output.stat().st_size > 1024:
                        return {
                            "artifact_path": str(output),
                            "artifact_name": output.name,
                            "mime": "image/png",
                        }
            except Exception:
                continue
        raise BridgeError("CAPABILITY_UNAVAILABLE: provider response exposed no generated image to capture.")

    def _poll_login(self) -> None:
        provider = self._login_provider
        if not provider or self._context is None or not self._headed:
            return
        page = self._pages.get(provider)
        if page is None or page.is_closed():
            self._login_provider = ""
            self._set_state(provider, "Login Required", "Managed login window was closed")
            return
        auth_state = self._auth_state(page, self.provider_specs[provider])
        if auth_state != "AUTHENTICATED":
            self._login_ready_at = 0.0
            self._set_state(provider, auth_state.replace("_", " ").title(), "Complete provider authentication")
            return
        if not self._login_ready_at:
            self._login_ready_at = time.monotonic()
            self._set_state(provider, "Authenticated", "Login detected; preparing persistence verification")
            return
        if time.monotonic() - self._login_ready_at < 2.0:
            return
        self._set_state(provider, "Verifying Persistence", "Reopening the persistent session headlessly")
        self._ensure_context(headed=False)
        restored = self._ensure_page(provider)
        if self._auth_state(restored, self.provider_specs[provider]) == "AUTHENTICATED":
            self._login_provider = ""
            self._set_state(provider, "Ready", "Authenticated managed session restored headlessly")
            return
        self._ensure_context(headed=True)
        retry = self._ensure_page(provider, navigate=True)
        retry.bring_to_front()
        self._login_ready_at = 0.0
        self._set_state(provider, "Login Required", "Authentication was not persistent; complete login again")

    def _close_context(self) -> None:
        context = self._context
        self._context = None
        self._pages = {}
        if context is not None:
            try:
                context.close()
            except Exception as exc:
                self._report(exc, "close-context", severity="WARNING")

    def _fail_pending(self, error: BaseException) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            command.error = error
            command.event.set()

    @staticmethod
    def _first_visible(page: Any, selectors: tuple[str, ...]) -> Any | None:
        for selector in selectors:
            locator = page.locator(selector)
            count = min(locator.count(), 20)
            for index in range(count):
                candidate = locator.nth(index)
                try:
                    if candidate.is_visible():
                        return candidate
                except Exception:
                    continue
        return None

    def _composer(self, page: Any, spec: ProviderSpec) -> Any | None:
        return self._first_visible(page, spec.composers or spec.inputs)

    def _auth_state(self, page: Any, spec: ProviderSpec) -> str:
        signals = page.evaluate(
            r"""
            ({composers, accounts, sends, unauthenticated, challenges, loginPaths, authenticatedPaths}) => {
              const visible = node => {
                if (!node) return false;
                const style = getComputedStyle(node);
                const box = node.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0;
              };
              const any = selectors => selectors.some(selector => [...document.querySelectorAll(selector)].some(visible));
              const url = location.href.toLocaleLowerCase();
              return {
                composer: any(composers),
                account: any(accounts),
                send: any(sends),
                unauthenticated: any(unauthenticated) || loginPaths.some(path => url.includes(path.toLocaleLowerCase())),
                challenge: any(challenges),
                authenticatedUrl: authenticatedPaths.some(path => url.includes(path.toLocaleLowerCase()))
              };
            }
            """,
            {
                "composers": list(spec.composers or spec.inputs),
                "accounts": list(spec.accounts),
                "sends": list(spec.sends),
                "unauthenticated": list(spec.unauthenticated),
                "challenges": list(spec.challenges),
                "loginPaths": list(spec.login_paths),
                "authenticatedPaths": list(spec.authenticated_paths),
            },
        )
        if not isinstance(signals, dict):
            return "UNKNOWN"
        if signals.get("challenge"):
            return "CHALLENGE"
        if signals.get("unauthenticated"):
            return "LOGIN_REQUIRED"
        if signals.get("account") and signals.get("composer"):
            return "AUTHENTICATED"
        if signals.get("authenticatedUrl") and signals.get("composer") and signals.get("send"):
            return "AUTHENTICATED"
        if spec.code != "chatgpt" and signals.get("composer") and signals.get("send"):
            return "AUTHENTICATED"
        return "UNKNOWN"

    def _response_locator(self, page: Any, spec: ProviderSpec) -> Any | None:
        for selector in spec.responses:
            locator = page.locator(selector)
            if locator.count():
                return locator
        return None

    @staticmethod
    def _last_text(locator: Any | None) -> str:
        if locator is None or locator.count() == 0:
            return ""
        try:
            return locator.last.inner_text().strip()
        except Exception:
            return ""

    def _is_streaming(self, page: Any, spec: ProviderSpec) -> bool:
        return self._first_visible(page, spec.stops) is not None

    @staticmethod
    def _artifact_url(page: Any) -> str:
        links = page.locator("a[href]").evaluate_all(
            "nodes => nodes.map(node => node.href).filter(href => /\\.(glb|gltf|fbx|obj)(\\?|$)/i.test(href))"
        )
        candidates = [str(link) for link in links]
        glb = [link for link in candidates if ".glb" in link.casefold()]
        return (glb or candidates or [""])[-1]

    def _download_artifact(self, url: str, task_id: str) -> Path | None:
        suffix = Path(urlparse(url).path).suffix.casefold()
        if suffix not in {".glb", ".gltf", ".fbx", ".obj"}:
            return None
        response = self._context.request.get(url, timeout=120_000)
        if not response.ok:
            raise BridgeError(f"3D download failed with HTTP {response.status}.")
        length = int(response.headers.get("content-length", "0") or 0)
        if length > 256 * 1024 * 1024:
            raise BridgeError("3D asset exceeds the local 256 MB limit.")
        body = response.body()
        if len(body) > 256 * 1024 * 1024:
            raise BridgeError("3D asset exceeds the local 256 MB limit.")
        target_dir = self.download_root / task_id[:64]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"hunyuan-{uuid.uuid4().hex[:8]}{suffix}"
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(body)
        temporary.replace(target)
        return target

    @staticmethod
    def _route_request(route: Any, request: Any) -> None:
        host = (urlparse(request.url).hostname or "").casefold()
        blocked_hosts = ("doubleclick.net", "google-analytics.com", "googletagmanager.com")
        if request.resource_type == "media" or any(host == item or host.endswith("." + item) for item in blocked_hosts):
            route.abort()
        else:
            route.continue_()

    def _page_error(self, provider: str, error: Any) -> None:
        self._report(RuntimeError(str(error)), "pageerror", provider=provider, severity="ERROR")

    def _console_event(self, provider: str, message: Any) -> None:
        if message.type != "error":
            return
        text = str(message.text)
        if "favicon" in text.casefold() or "third-party cookie" in text.casefold():
            return
        self._report(RuntimeError(text), "console", provider=provider, severity="WARNING")

    def _request_failed(self, provider: str, request: Any) -> None:
        if request.resource_type not in {"document", "xhr", "fetch", "websocket"}:
            return
        failure = str(request.failure or "request failed")
        if "ERR_ABORTED" in failure:
            return
        self._report(RuntimeError(f"{failure}: {request.url}"), "requestfailed", provider=provider, severity="WARNING")

    def _set_state(self, provider: str, state: str, detail: str) -> None:
        with self._state_lock:
            self._states[provider] = {"state": state, "detail": detail, "transport": "playwright"}
        if self.status_callback is not None:
            self.status_callback(provider, state, detail)

    def _report(
        self,
        exc: BaseException,
        component: str,
        *,
        provider: str = "",
        severity: str = "ERROR",
        request_id: str = "",
        job_id: str = "",
    ) -> None:
        if self.diagnostics is not None:
            self.diagnostics.report(
                severity=severity,
                source="browser",
                component=f"{provider}:{component}" if provider else component,
                message=str(exc),
                exc=exc,
                request_id=request_id,
                job_id=job_id,
                probable_cause="Provider page, session, selector or managed runtime changed state.",
                impact="The current provider operation may require retry or manual login.",
                recovery_action="Use the provider Login control or retry the embedded WebView2 route.",
            )
