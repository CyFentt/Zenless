from __future__ import annotations

import argparse
import base64
import importlib
import json
import queue
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO, cast

from .managed_browser import PROVIDERS, ProviderSpec
from .native_host import read_native_message, write_native_message
from .provider_registry import normalize_capabilities


def _mode_options(raw: Any) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(raw, list):
        return ()
    result = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 2 or not isinstance(item[1], list):
            continue
        result.append((str(item[0]), tuple(str(value) for value in item[1])))
    return tuple(result)


def _specs_from_file(path: Path | None) -> dict[str, ProviderSpec]:
    if path is None:
        return dict(PROVIDERS)
    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, ProviderSpec] = {}
    for code, item in raw.items():
        if not isinstance(item, dict):
            continue
        result[str(code)] = ProviderSpec(
            code=str(item.get("code") or code),
            url=str(item["url"]),
            inputs=tuple(str(value) for value in item.get("inputs", [])),
            sends=tuple(str(value) for value in item.get("sends", [])),
            stops=tuple(str(value) for value in item.get("stops", [])),
            responses=tuple(str(value) for value in item.get("responses", [])),
            composers=tuple(str(value) for value in item.get("composers", [])),
            accounts=tuple(str(value) for value in item.get("accounts", [])),
            unauthenticated=tuple(str(value) for value in item.get("unauthenticated", [])),
            challenges=tuple(str(value) for value in item.get("challenges", [])),
            login_paths=tuple(str(value) for value in item.get("login_paths", [])),
            authenticated_paths=tuple(str(value) for value in item.get("authenticated_paths", [])),
            mode_options=_mode_options(item.get("mode_options")),
        )
    return result


class WebViewHost:
    def __init__(
        self,
        *,
        profile_root: Path,
        provider_specs: dict[str, ProviderSpec],
        source: BinaryIO,
        target: BinaryIO,
    ) -> None:
        self.profile_root = profile_root
        self.provider_specs = provider_specs
        self.source = source
        self.target = target
        self._windows: dict[str, Any] = {}
        self._control: Any = None
        self._stop = threading.Event()
        self._requests: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._write_lock = threading.Lock()

    def run(self) -> int:
        import webview

        self.profile_root.mkdir(parents=True, exist_ok=True)
        self._control = webview.create_window(
            "Zenless Managed WebView",
            url="about:blank",
            width=1000,
            height=760,
            hidden=True,
            background_color="#090909",
        )
        if self._control is None:
            return 2
        webview.start(
            self._worker,
            gui="edgechromium",
            debug=False,
            private_mode=False,
            storage_path=str(self.profile_root),
        )
        return 0

    def _worker(self) -> None:
        reader = threading.Thread(target=self._reader, name="Zenless-WebViewHost-Reader", daemon=False)
        reader.start()
        try:
            while not self._stop.is_set():
                try:
                    request = self._requests.get(timeout=0.25)
                except queue.Empty:
                    continue
                if request is None:
                    break
                response = self._handle_guarded(request)
                self._write(response)
                if request.get("action") == "shutdown":
                    break
        finally:
            self._stop.set()
            self._destroy_windows()
            if reader is not threading.current_thread():
                reader.join(timeout=2)

    def _reader(self) -> None:
        try:
            while not self._stop.is_set():
                payload = read_native_message(self.source)
                if payload is None:
                    break
                message = json.loads(payload.decode("utf-8"))
                if isinstance(message, dict):
                    self._requests.put(message)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._requests.put({"id": "", "action": "invalid", "reader_error": str(exc)})
        finally:
            self._stop.set()
            self._requests.put(None)

    def _handle_guarded(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = str(request.get("id") or "")

        def emit_stream(delta: str) -> None:
            if delta:
                self._write({"id": request_id, "event": "stream", "delta": delta})

        def emit_event(event: str, payload: dict[str, Any]) -> None:
            self._write({"id": request_id, "event": event, **payload})

        try:
            result = self._handle(request, stream_callback=emit_stream, event_callback=emit_event)
            return {"id": request_id, "ok": True, "result": result}
        except Exception as exc:
            return {"id": request_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _handle(
        self,
        request: dict[str, Any],
        *,
        stream_callback: Callable[[str], None] | None = None,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        action = str(request.get("action") or "")
        provider = str(request.get("provider") or "")
        raw_payload = request.get("payload")
        payload = cast(dict[str, Any], raw_payload) if isinstance(raw_payload, dict) else {}
        if action == "ping":
            return {"state": "ready", "engine": "webview2"}
        if action == "shutdown":
            self._stop.set()
            return {"state": "stopping"}
        if provider not in self.provider_specs:
            raise ValueError(f"Unknown provider: {provider}")
        window = self._ensure_window(provider)
        spec = self.provider_specs[provider]
        if action == "health":
            state = self._composer_state(window, spec)
            ready = bool(state.get("ready"))
            return {
                "ready": ready,
                "state": str(state.get("state") or "UNKNOWN"),
                "signals": dict(state.get("signals") or {}),
                "url": str(window.get_current_url() or spec.url),
                "capabilities": self._capabilities(window, spec) if ready else {},
            }
        if action == "login":
            window.show()
            window.restore()
            if event_callback is not None:
                event_callback(
                    "login_window_opened",
                    {
                        "provider": provider,
                        "transport": "webview2",
                        "url": str(window.get_current_url() or spec.url),
                    },
                )
            return {"state": "login_window_open", "url": str(window.get_current_url() or spec.url)}
        if action == "hide":
            window.hide()
            return {"state": "hidden"}
        if action == "request":
            provider_action = str(payload.get("provider_action") or "send_prompt")
            if provider_action == "upload_files":
                return self._upload_files(window, payload)
            if provider_action == "select_model":
                return self._select_model(window, str(payload.get("model") or ""))
            if provider_action == "select_mode":
                return self._select_mode(window, spec, str(payload.get("mode") or ""))
            if provider_action == "get_models":
                return self._discover_models(window)
            if provider_action == "cancel":
                return self._cancel(window, spec)
            if provider_action == "reload":
                window.load_url(str(window.get_current_url() or spec.url))
                return {"status": "ok", "reloaded": True, "transport": "webview2"}
            if provider_action == "capabilities":
                return {
                    "status": "ok",
                    "capabilities": self._capabilities(window, spec),
                    "transport": "webview2",
                }
            if payload.get("files"):
                self._upload_files(window, payload)
            if provider == "hunyuan" and provider_action in {"generate_geometry", "generate_texture"}:
                self._select_generation_mode(window, provider_action)
            return self._send(window, spec, payload, stream_callback=stream_callback)
        raise ValueError(f"Unsupported WebView command: {action}")

    def _ensure_window(self, provider: str) -> Any:
        import webview

        existing = self._windows.get(provider)
        if existing is not None:
            try:
                existing.evaluate_js("document.readyState")
                return existing
            except Exception:
                self._windows.pop(provider, None)
        spec = self.provider_specs[provider]
        window = webview.create_window(
            f"Zenless • {provider}",
            url=spec.url,
            width=1050,
            height=780,
            hidden=True,
            background_color="#090909",
        )
        if window is None:
            raise RuntimeError(f"Could not create WebView2 window for {provider}")
        self._windows[provider] = window
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline and not self._stop.wait(0.25):
            try:
                state = window.evaluate_js("document.readyState")
                if state in {"interactive", "complete"}:
                    return window
            except Exception:
                continue
        raise TimeoutError(f"Page load timeout for {provider}")

    def _composer_state(self, window: Any, spec: ProviderSpec) -> dict[str, Any]:
        script = f"""
        (() => {{
          const composers = {json.dumps(spec.composers or spec.inputs)};
          const accounts = {json.dumps(spec.accounts)};
          const sends = {json.dumps(spec.sends)};
          const unauthenticated = {json.dumps(spec.unauthenticated)};
          const challenges = {json.dumps(spec.challenges)};
          const loginPaths = {json.dumps(spec.login_paths)};
          const authenticatedPaths = {json.dumps(spec.authenticated_paths)};
          const relaxedAuth = {json.dumps(spec.code != "chatgpt")};
          const visible = (node) => {{
            if (!node) return false;
            const style = getComputedStyle(node);
            const box = node.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
          }};
          const any = selectors => selectors.some(selector => [...document.querySelectorAll(selector)].some(visible));
          const url = location.href.toLocaleLowerCase();
          const signals = {{
            composer: any(composers),
            account: any(accounts),
            send: any(sends),
            unauthenticated: any(unauthenticated) || loginPaths.some(path => url.includes(path.toLocaleLowerCase())),
            challenge: any(challenges),
            authenticatedUrl: authenticatedPaths.some(path => url.includes(path.toLocaleLowerCase()))
          }};
          let state = 'UNKNOWN';
          if (signals.challenge) state = 'CHALLENGE';
          else if (signals.unauthenticated) state = 'LOGIN_REQUIRED';
          else if ((signals.account && signals.composer) ||
            (signals.authenticatedUrl && signals.composer && signals.send) ||
            (relaxedAuth && signals.composer && signals.send)) state = 'AUTHENTICATED';
          return {{state, ready: state === 'AUTHENTICATED', signals}};
        }})()
        """
        result = window.evaluate_js(script)
        return result if isinstance(result, dict) else {"ready": False}

    def _capabilities(self, window: Any, spec: ProviderSpec) -> dict[str, Any]:
        script = f"""
        (() => {{
          const visible = (node) => !!node && getComputedStyle(node).display !== 'none' &&
            getComputedStyle(node).visibility !== 'hidden';
          const any = (selectors) => selectors.some(selector => [...document.querySelectorAll(selector)].some(visible));
          const file = [...document.querySelectorAll('input[type="file"]')].find(visible);
          const accept = (file?.getAttribute('accept') || '').split(',').map(value => value.trim()).filter(Boolean);
          const body = (document.body?.innerText || '').slice(0, 200000);
          const countMatch = body.match(/(?:up to|max(?:imum)?)\\s*(\\d+)\\s*(?:images?|views?|photos?)/i);
          const explicitCount = countMatch ? Math.max(1, Math.min(6, Number(countMatch[1]))) : 0;
          const selected = node => node.getAttribute('aria-pressed') === 'true' ||
            node.getAttribute('aria-selected') === 'true' ||
            ['active', 'on', 'checked'].includes((node.getAttribute('data-state') || '').toLocaleLowerCase()) ||
            /(^|\\s)(active|selected|checked)(\\s|$)/i.test(node.className || '');
          const controls = [...document.querySelectorAll('button,[role="tab"],[role="option"]')]
            .filter(visible).slice(0, 400);
          const labels = controls
            .map(node => (node.innerText || node.textContent || '').trim()).filter(Boolean).join('\\n');
          const modeOptions = {json.dumps({mode: [label.casefold() for label in labels] for mode, labels in spec.mode_options})};
          const matches = (node, options) => {{
            const text = (node.innerText || node.textContent || '').trim().toLocaleLowerCase();
            return options.some(label => text === label ||
              (text.startsWith(label) && text.length <= label.length + 20));
          }};
          const modeControl = controls.find(node => Object.values(modeOptions).some(options => matches(node, options)));
          const activeMode = Object.entries(modeOptions)
            .find(([, options]) => controls.some(node => selected(node) && matches(node, options)))?.[0] || '';
          return {{
            send_text: any({json.dumps(spec.inputs)}) && any({json.dumps(spec.sends)}),
            upload_files: !!file,
            file_types: accept,
            max_image_inputs: file ? (file.multiple ? (explicitCount || 1) : 1) : 0,
            cancel: any({json.dumps(spec.stops)}),
            select_model: !!document.querySelector('[role="option"], [role="menuitem"], [data-model]'),
            select_mode: !!modeControl,
            responses: any({json.dumps(spec.responses)}),
            search: /(web search|search the web)/i.test(labels),
            reasoning: /(reasoning|thinking|expert|reasoner|deepthink|deep think)/i.test(labels),
            mode: activeMode,
            image_generation: /(create image|generate image|image generation)/i.test(labels),
            geometry: /(geometry|shape|mesh)/i.test(labels),
            texture: /(texture|pbr|material)/i.test(labels),
            download_artifact: [...document.querySelectorAll('a[href]')].some(a => /\\.(glb|gltf|fbx|obj)(\\?|$)/i.test(a.href))
          }};
        }})()
        """
        result = window.evaluate_js(script)
        return normalize_capabilities(dict(result) if isinstance(result, dict) else {}, source="LIVE")

    @staticmethod
    def _devtools(window: Any, method: str, parameters: dict[str, Any]) -> dict[str, Any]:
        Action = getattr(importlib.import_module("System"), "Action")
        native = window.native
        holder: dict[str, Any] = {}

        def invoke() -> None:
            holder["task"] = native.browser.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(
                method,
                json.dumps(parameters, ensure_ascii=False, separators=(",", ":")),
            )

        native.Invoke(Action(invoke))
        task = holder.get("task")
        if task is None or not task.Wait(30_000):
            raise TimeoutError(f"WebView2 DevTools timeout: {method}")
        raw = str(task.Result or "{}")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise RuntimeError(f"Invalid WebView2 DevTools response: {method}")
        return result

    def _upload_files(self, window: Any, payload: dict[str, Any]) -> dict[str, Any]:
        raw_files = payload.get("files")
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("No files were provided for upload")
        files = [str(Path(str(item)).resolve()) for item in raw_files]
        missing = [path for path in files if not Path(path).is_file()]
        if missing:
            raise FileNotFoundError(f"Upload file not found: {missing[0]}")
        selector = str(payload.get("file_selector") or 'input[type="file"]')
        document = self._devtools(window, "DOM.getDocument", {"depth": 1, "pierce": True})
        raw_root = document.get("root")
        root = cast(dict[str, Any], raw_root) if isinstance(raw_root, dict) else {}
        node_id = int(root.get("nodeId") or 0)
        query = self._devtools(window, "DOM.querySelector", {"nodeId": node_id, "selector": selector})
        input_node_id = int(query.get("nodeId") or 0)
        if not input_node_id:
            raise RuntimeError("The provider page does not expose a compatible file input")
        self._devtools(window, "DOM.setFileInputFiles", {"nodeId": input_node_id, "files": files})
        count = window.evaluate_js(f"document.querySelector({json.dumps(selector)})?.files?.length || 0")
        return {"status": "ok", "uploaded": int(count or 0), "transport": "webview2"}

    @staticmethod
    def _select_model(window: Any, model: str) -> dict[str, Any]:
        if not model.strip():
            raise ValueError("Model name is empty")
        result = window.evaluate_js(
            f"""
            (() => {{
              const wanted = {json.dumps(model.casefold())};
              const nodes = [...document.querySelectorAll('[role="option"], [role="menuitem"], [data-model], button')];
              const target = nodes.find(node => (node.innerText || node.textContent || '').trim().toLocaleLowerCase().includes(wanted));
              if (!target) return {{ok: false}};
              target.click();
              return {{ok: true, selected: (target.innerText || target.textContent || '').trim()}};
            }})()
            """
        )
        if not isinstance(result, dict) or not result.get("ok"):
            raise RuntimeError(f"Model option not found: {model}")
        return {"status": "ok", "selected": str(result.get("selected") or model), "transport": "webview2"}

    @staticmethod
    def _discover_models(window: Any) -> dict[str, Any]:
        result = window.evaluate_js(
            """
            (() => {
              const selectors = [
                '[data-model]', '[role="option"]', '[role="menuitem"]',
                'button[aria-haspopup="listbox"]', 'button[aria-haspopup="menu"]'
              ];
              const values = [];
              for (const selector of selectors) {
                for (const node of document.querySelectorAll(selector)) {
                  const value = (node.getAttribute('data-model') || node.innerText || node.textContent || '').trim();
                  if (value && value.length <= 120 && !values.includes(value)) values.push(value);
                  if (values.length >= 30) return values;
                }
              }
              return values;
            })()
            """
        )
        models = [str(item).strip() for item in result] if isinstance(result, list) else []
        return {"status": "ok", "models": [item for item in models if item], "transport": "webview2"}

    def _select_mode(self, window: Any, spec: ProviderSpec, mode: str) -> dict[str, Any]:
        normalized = mode.strip().casefold()
        labels = dict(spec.mode_options).get(normalized)
        if labels is None:
            raise RuntimeError("The provider mode is not supported by this adapter.")
        result = window.evaluate_js(
            f"""
            (() => {{
              const labels = {json.dumps([item.casefold() for item in labels])};
              const visible = node => !!node && getComputedStyle(node).display !== 'none' &&
                getComputedStyle(node).visibility !== 'hidden';
              const selected = node => node.getAttribute('aria-pressed') === 'true' ||
                node.getAttribute('aria-selected') === 'true' ||
                ['active', 'on', 'checked'].includes((node.getAttribute('data-state') || '').toLocaleLowerCase()) ||
                /(^|\\s)(active|selected|checked)(\\s|$)/i.test(node.className || '');
              const nodes = [...document.querySelectorAll('button,[role="tab"],[role="option"]')];
              const target = nodes.find(node => {{
                const text = (node.innerText || node.textContent || '').trim().toLocaleLowerCase();
                return visible(node) && labels.some(label => text === label ||
                  (text.startsWith(label) && text.length <= label.length + 20));
              }});
              if (!target) return {{ok: false}};
              const before = selected(target);
              if (!before) target.click();
              return {{ok: true, changed: !before}};
            }})()
            """
        )
        if not isinstance(result, dict) or not result.get("ok"):
            raise RuntimeError("CAPABILITY_UNAVAILABLE: the provider did not expose a verified mode control.")
        time.sleep(0.35)
        capabilities = self._capabilities(window, spec)
        if str(capabilities.get("mode") or "").casefold() != normalized:
            raise RuntimeError("CAPABILITY_UNAVAILABLE: the provider mode change could not be verified.")
        return {
            "status": "ok",
            "selected": normalized,
            "capabilities": capabilities,
            "transport": "webview2",
        }

    @staticmethod
    def _cancel(window: Any, spec: ProviderSpec) -> dict[str, Any]:
        result = window.evaluate_js(
            f"""
            (() => {{
              for (const selector of {json.dumps(spec.stops)}) {{
                const node = document.querySelector(selector);
                if (node) {{ node.click(); return true; }}
              }}
              return false;
            }})()
            """
        )
        return {"status": "ok" if result else "idle", "cancelled": bool(result), "transport": "webview2"}

    @staticmethod
    def _select_generation_mode(window: Any, action: str) -> None:
        patterns = (
            ("geometry", "shape", "mesh")
            if action == "generate_geometry"
            else ("texture", "pbr", "material")
        )
        result = window.evaluate_js(
            f"""
            (() => {{
              const patterns = {json.dumps(patterns)};
              const nodes = [...document.querySelectorAll('button, [role="tab"], [role="option"]')];
              const target = nodes.find(node => {{
                const style = getComputedStyle(node);
                const label = (node.innerText || node.textContent || '').trim().toLocaleLowerCase();
                return style.display !== 'none' && style.visibility !== 'hidden' &&
                  patterns.some(pattern => label.includes(pattern));
              }});
              if (!target) return false;
              target.click();
              return true;
            }})()
            """
        )
        if not result:
            phase = "geometry" if action == "generate_geometry" else "texture"
            raise RuntimeError(f"CAPABILITY_UNAVAILABLE: Hunyuan did not expose a {phase} generation mode.")

    def _send(
        self,
        window: Any,
        spec: ProviderSpec,
        payload: dict[str, Any],
        *,
        stream_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("Empty prompt")
        setup = window.evaluate_js(self._send_script(spec, prompt))
        if not isinstance(setup, dict) or not setup.get("ok"):
            reason = setup.get("error") if isinstance(setup, dict) else "provider DOM unavailable"
            raise RuntimeError(str(reason))
        before_count = int(setup.get("beforeCount") or 0)
        before_text = str(setup.get("beforeText") or "")
        timeout_ms = int(payload.get("timeout_ms") or 360_000)
        deadline = time.monotonic() + max(10.0, min(900.0, timeout_ms / 1000))
        last_text = ""
        stable_since = 0.0
        while time.monotonic() < deadline and not self._stop.wait(0.4):
            state = window.evaluate_js(self._response_script(spec))
            if not isinstance(state, dict):
                continue
            text = str(state.get("text") or "").strip()
            count = int(state.get("count") or 0)
            is_new = count > before_count or bool(text and text != before_text)
            if is_new and text:
                if text != last_text:
                    if stream_callback is not None:
                        delta = text[len(last_text) :] if text.startswith(last_text) else ""
                        if delta:
                            stream_callback(delta)
                    last_text = text
                    stable_since = time.monotonic()
                elif not state.get("streaming") and time.monotonic() - stable_since >= 2.0:
                    result: dict[str, Any] = {"status": "ok", "text": text, "transport": "webview2"}
                    provider_action = str(payload.get("provider_action") or "send_prompt")
                    if provider_action == "generate_image":
                        result.update(self._capture_generated_image(window, spec, payload))
                    if provider_action in {"generate_3d", "generate_geometry", "generate_texture"}:
                        artifact = window.evaluate_js(
                            "[...document.querySelectorAll('a[href]')].map(a => a.href).filter(h => /\\.(glb|gltf|fbx|obj)(\\?|$)/i.test(h)).pop() || ''"
                        )
                        if artifact:
                            result["artifact_url"] = str(artifact)
                            result["artifact_name"] = str(artifact).split("/")[-1].split("?")[0]
                    return result
        raise TimeoutError(f"Response timeout for {spec.code}")

    def _capture_generated_image(
        self,
        window: Any,
        spec: ProviderSpec,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        output_text = str(payload.get("output_path") or "").strip()
        if not output_text:
            raise ValueError("generate_image requires an authorized output_path")
        output = Path(output_text).resolve()
        try:
            output.relative_to(self.profile_root.parent.resolve())
        except ValueError as exc:
            raise ValueError("Image output escaped Zenless storage") from exc
        if output.suffix.casefold() != ".png":
            raise ValueError("Generated concept output must be PNG")
        bounds = window.evaluate_js(
            f"""
            (() => {{
              const selectors = {json.dumps(spec.responses)};
              const containers = [];
              const seen = new Set();
              for (const selector of selectors) {{
                for (const node of document.querySelectorAll(selector)) {{
                  if (!seen.has(node)) {{ seen.add(node); containers.push(node); }}
                }}
              }}
              const root = containers.at(-1) || document.body;
              const images = [...root.querySelectorAll('img')].reverse();
              const image = images.find(node => {{
                const style = getComputedStyle(node);
                return style.display !== 'none' && style.visibility !== 'hidden' &&
                  (node.naturalWidth || node.clientWidth) >= 256 && (node.naturalHeight || node.clientHeight) >= 256;
              }});
              if (!image) return null;
              image.scrollIntoView({{block: 'center', inline: 'center'}});
              const rect = image.getBoundingClientRect();
              return {{
                x: Math.max(0, rect.left + window.scrollX),
                y: Math.max(0, rect.top + window.scrollY),
                width: Math.max(1, rect.width),
                height: Math.max(1, rect.height)
              }};
            }})()
            """
        )
        if not isinstance(bounds, dict):
            raise RuntimeError("CAPABILITY_UNAVAILABLE: provider response exposed no generated image to capture")
        screenshot = self._devtools(
            window,
            "Page.captureScreenshot",
            {
                "format": "png",
                "captureBeyondViewport": True,
                "clip": {
                    "x": float(bounds.get("x") or 0),
                    "y": float(bounds.get("y") or 0),
                    "width": float(bounds.get("width") or 1),
                    "height": float(bounds.get("height") or 1),
                    "scale": 1,
                },
            },
        )
        raw_data = screenshot.get("data")
        if not isinstance(raw_data, str):
            raise RuntimeError("WebView2 did not return PNG screenshot data")
        try:
            image_bytes = base64.b64decode(raw_data, validate=True)
        except ValueError as exc:
            raise RuntimeError("WebView2 returned invalid PNG screenshot data") from exc
        if len(image_bytes) <= 1024 or not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("WebView2 generated image capture was invalid")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(image_bytes)
        return {
            "artifact_path": str(output),
            "artifact_name": output.name,
            "mime": "image/png",
        }

    @staticmethod
    def _send_script(spec: ProviderSpec, prompt: str) -> str:
        return f"""
        (() => {{
          const inputSelectors = {json.dumps(spec.inputs)};
          const sendSelectors = {json.dumps(spec.sends)};
          const responseSelectors = {json.dumps(spec.responses)};
          const visible = (node) => {{
            if (!node) return false;
            const style = getComputedStyle(node);
            const box = node.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
          }};
          const first = (selectors) => {{
            for (const selector of selectors) {{
              const node = [...document.querySelectorAll(selector)].find(visible);
              if (node) return node;
            }}
            return null;
          }};
          const responses = () => {{
            const nodes = [];
            const seen = new Set();
            for (const selector of responseSelectors) {{
              for (const node of document.querySelectorAll(selector)) {{
                if (!seen.has(node)) {{ seen.add(node); nodes.push(node); }}
              }}
            }}
            return nodes;
          }};
          const input = first(inputSelectors);
          if (!input) return {{ok: false, error: 'Login required or composer selector changed'}};
          const before = responses();
          const beforeText = (before.at(-1)?.innerText || before.at(-1)?.textContent || '').trim();
          input.focus();
          const prompt = {json.dumps(prompt)};
          if (input instanceof HTMLTextAreaElement || input instanceof HTMLInputElement) {{
            const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            if (setter) setter.call(input, prompt); else input.value = prompt;
          }} else {{
            input.textContent = prompt;
          }}
          input.dispatchEvent(new InputEvent('input', {{bubbles: true, inputType: 'insertText', data: prompt}}));
          input.dispatchEvent(new Event('change', {{bubbles: true}}));
          const sender = first(sendSelectors);
          if (!sender || sender.disabled) return {{ok: false, error: 'Send button unavailable'}};
          sender.click();
          return {{ok: true, beforeCount: before.length, beforeText}};
        }})()
        """

    @staticmethod
    def _response_script(spec: ProviderSpec) -> str:
        return f"""
        (() => {{
          const responseSelectors = {json.dumps(spec.responses)};
          const stopSelectors = {json.dumps(spec.stops)};
          const visible = (node) => {{
            if (!node) return false;
            const style = getComputedStyle(node);
            const box = node.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
          }};
          const nodes = [];
          const seen = new Set();
          for (const selector of responseSelectors) {{
            for (const node of document.querySelectorAll(selector)) {{
              if (!seen.has(node)) {{ seen.add(node); nodes.push(node); }}
            }}
          }}
          const last = nodes.at(-1);
          return {{
            count: nodes.length,
            text: (last?.innerText || last?.textContent || '').trim(),
            streaming: stopSelectors.some(selector => [...document.querySelectorAll(selector)].some(visible))
          }};
        }})()
        """

    def _write(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        write_native_message(self.target, payload, self._write_lock)

    def _destroy_windows(self) -> None:
        windows = [*self._windows.values(), self._control]
        self._windows = {}
        self._control = None
        for window in windows:
            if window is None:
                continue
            try:
                window.destroy()
            except Exception:
                continue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--profile-root", required=True)
    parser.add_argument("--provider-config", default="")
    args, _unknown = parser.parse_known_args(argv)
    config_path = Path(args.provider_config) if args.provider_config else None
    host = WebViewHost(
        profile_root=Path(args.profile_root),
        provider_specs=_specs_from_file(config_path),
        source=sys.stdin.buffer,
        target=sys.stdout.buffer,
    )
    return host.run()


if __name__ == "__main__":
    raise SystemExit(main())
