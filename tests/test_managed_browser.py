from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from zenless.agent_gateway import AgentGateway
from zenless.diagnostics import ErrorBus
from zenless.managed_browser import ProviderSpec
from zenless.webview2_browser import WebView2BrowserController


class ProviderHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"""<!doctype html>
<html><body>
  <p>Upload up to 6 images</p>
  <textarea id="prompt-textarea"></textarea>
  <input id="upload" type="file" accept="image/png,image/jpeg" multiple>
  <button data-model="sol">GPT Sol</button>
  <button id="send">Send</button>
  <main id="messages"></main>
  <script>
    document.cookie = 'zenless_mock_session=ready; SameSite=Lax';
    document.querySelector('#send').addEventListener('click', () => {
      const stop = document.createElement('button');
      stop.id = 'stop';
      document.body.appendChild(stop);
      const reply = document.createElement('article');
      reply.dataset.messageAuthorRole = 'assistant';
      reply.textContent = 'web';
      document.querySelector('#messages').appendChild(reply);
      setTimeout(() => { reply.textContent += 'view2:'; }, 500);
      setTimeout(() => { reply.textContent += document.querySelector('#prompt-textarea').value; }, 1000);
      setTimeout(() => stop.remove(), 1300);
    });
  </script>
</body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@unittest.skipUnless(sys.platform == "win32", "WebView2 host requires Windows")
class WebView2BrowserIntegrationTests(unittest.TestCase):
    def test_provider_round_trip_and_clean_restart(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
        server_thread = threading.Thread(target=server.serve_forever, name="WebView2Mock", daemon=True)
        server_thread.start()
        url = f"http://127.0.0.1:{server.server_port}/provider"
        spec = ProviderSpec(
            "chatgpt",
            url,
            ("#prompt-textarea",),
            ("#send",),
            ("#stop",),
            ("[data-message-author-role='assistant']",),
        )
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                diagnostics = ErrorBus(root / "logs")
                controller = WebView2BrowserController(
                    data_root=root,
                    diagnostics=diagnostics,
                    provider_specs={"chatgpt": spec},
                )
                try:
                    controller.start()
                    self.assertTrue(controller.wait_for_provider("chatgpt", 30))
                    upload = root / "upload.txt"
                    upload.write_text("safe mock", encoding="utf-8")
                    upload_result = controller.request(
                        "chatgpt",
                        "upload_files",
                        {"files": [str(upload)]},
                        task_id="mock",
                        timeout=30,
                    )
                    self.assertEqual(upload_result["uploaded"], 1)
                    model_result = controller.request(
                        "chatgpt",
                        "select_model",
                        {"model": "GPT Sol"},
                        task_id="mock",
                        timeout=30,
                    )
                    self.assertEqual(model_result["selected"], "GPT Sol")
                    capabilities = controller.request(
                        "chatgpt",
                        "capabilities",
                        {},
                        task_id="mock",
                        timeout=30,
                    )["capabilities"]
                    self.assertTrue(capabilities["upload_files"])
                    self.assertEqual(capabilities["max_image_inputs"], 6)
                    self.assertEqual(capabilities["file_types"], ["image/png", "image/jpeg"])
                    deltas: list[str] = []
                    response = controller.send_prompt(
                        "chatgpt",
                        "hello",
                        task_id="mock",
                        timeout=30,
                        stream_callback=deltas.append,
                    )
                    self.assertEqual(response, "webview2:hello")
                    self.assertEqual("".join(deltas), response)
                    self.assertGreaterEqual(len(deltas), 2)
                    self.assertEqual(controller.provider_status()["chatgpt"]["state"], "Ready")
                    controller.stop()
                    self.assertFalse(controller.running)

                    controller.start()
                    self.assertTrue(controller.wait_for_provider("chatgpt", 30))
                finally:
                    controller.stop()
                    diagnostics.close()
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)


class _CapabilityTransport:
    def __init__(self, capabilities: dict[str, Any]) -> None:
        self.capabilities = capabilities
        self.calls: list[str] = []
        self.running = True

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def wait_for_provider(self, _provider: str, _timeout: float = 0.0) -> bool:
        return True

    def provider_status(self) -> dict[str, dict[str, str]]:
        return {"hunyuan": {"state": "Ready", "detail": "test", "transport": "test"}}

    def request(
        self,
        _provider: str,
        action: str,
        _payload: dict[str, Any],
        *,
        task_id: str,
        timeout: float,
        stream_callback: Any = None,
    ) -> dict[str, Any]:
        del task_id, timeout, stream_callback
        self.calls.append(action)
        if action == "capabilities":
            return {"status": "ok", "capabilities": dict(self.capabilities)}
        return {"status": "ok", "text": action}

    def send_prompt(
        self,
        provider: str,
        prompt: str,
        *,
        task_id: str,
        timeout: float = 360.0,
        stream_callback: Any = None,
    ) -> str:
        del provider, task_id, timeout
        self.calls.append("send_prompt")
        if stream_callback is not None:
            stream_callback(prompt[:2])
            stream_callback(prompt[2:])
        return prompt


class AgentGatewayCapabilityTests(unittest.TestCase):
    def test_routes_only_missing_capability_to_playwright_and_preserves_streaming(self) -> None:
        embedded = _CapabilityTransport({"send_text": True, "geometry": False, "max_image_inputs": 1})
        managed = _CapabilityTransport({"send_text": True, "geometry": True, "max_image_inputs": 6})
        gateway = AgentGateway(managed=managed, embedded=embedded)

        self.assertTrue(gateway.wait_for_provider("chatgpt", 1))
        deltas: list[str] = []
        self.assertEqual(
            gateway.send_prompt("chatgpt", "stream", task_id="job", stream_callback=deltas.append),
            "stream",
        )
        self.assertEqual("".join(deltas), "stream")
        result = gateway.request(
            "chatgpt",
            "generate_geometry",
            {"prompt": "mesh"},
            task_id="job",
            timeout=5,
        )
        self.assertEqual(result["text"], "generate_geometry")
        self.assertNotIn("generate_geometry", embedded.calls)
        self.assertIn("generate_geometry", managed.calls)

        combined = gateway.request("chatgpt", "capabilities", {}, task_id="job", timeout=5)
        self.assertTrue(combined["capabilities"]["geometry"])
        self.assertEqual(combined["capabilities"]["max_image_inputs"], 6)
        self.assertEqual(set(combined["routes"]), {"webview2", "playwright"})

    def test_hunyuan_pins_upload_geometry_and_texture_to_one_capable_route(self) -> None:
        embedded = _CapabilityTransport({"upload_files": True, "geometry": True, "texture": False})
        managed = _CapabilityTransport({"upload_files": True, "geometry": True, "texture": True, "max_image_inputs": 5})
        gateway = AgentGateway(managed=managed, embedded=embedded)

        capabilities = gateway.request("hunyuan", "capabilities", {}, task_id="job-3d", timeout=5)
        self.assertEqual(capabilities["transport"], "playwright")
        self.assertEqual(set(capabilities["routes"]), {"playwright"})
        for action in ("upload_files", "generate_geometry", "generate_texture"):
            gateway.request("hunyuan", action, {"prompt": "mesh"}, task_id="job-3d", timeout=5)

        self.assertNotIn("upload_files", embedded.calls)
        self.assertNotIn("generate_geometry", embedded.calls)
        self.assertNotIn("generate_texture", embedded.calls)
        self.assertTrue({"upload_files", "generate_geometry", "generate_texture"}.issubset(managed.calls))


if __name__ == "__main__":
    unittest.main()
