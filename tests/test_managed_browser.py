from __future__ import annotations

import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from zenless.diagnostics import ErrorBus
from zenless.managed_browser import ProviderSpec
from zenless.webview2_browser import WebView2BrowserController


class ProviderHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        body = b"""<!doctype html>
<html><body>
  <textarea id="prompt-textarea"></textarea>
  <input id="upload" type="file">
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
      reply.textContent = 'webview2:' + document.querySelector('#prompt-textarea').value;
      document.querySelector('#messages').appendChild(reply);
      setTimeout(() => stop.remove(), 250);
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
                    response = controller.send_prompt("chatgpt", "hello", task_id="mock", timeout=30)
                    self.assertEqual(response, "webview2:hello")
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


if __name__ == "__main__":
    unittest.main()
