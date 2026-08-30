from __future__ import annotations

import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from zenless.diagnostics import ErrorBus
from zenless.managed_browser import ProviderSpec
from zenless.webview2_browser import WebView2BrowserController


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"""<!doctype html><html><body>
        <textarea id="prompt"></textarea><input id="files" type="file">
        <button id="send">Send</button><main></main>
        <script>document.querySelector('#send').onclick=()=>{const x=document.createElement('article');x.className='reply';x.textContent='frozen:'+document.querySelector('#prompt').value;document.querySelector('main').append(x)}</script>
        </body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    executable = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/Zenless.exe").resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    spec = ProviderSpec(
        "chatgpt",
        f"http://127.0.0.1:{server.server_port}/",
        ("#prompt",),
        ("#send",),
        ("#stop",),
        (".reply",),
    )
    try:
        with tempfile.TemporaryDirectory(prefix="zenless-frozen-webview-") as folder:
            root = Path(folder)
            diagnostics = ErrorBus(root / "logs")
            controller = WebView2BrowserController(
                data_root=root,
                diagnostics=diagnostics,
                provider_specs={"chatgpt": spec},
                host_executable=executable,
            )
            try:
                controller.start(timeout=45)
                if not controller.wait_for_provider("chatgpt", 45):
                    raise RuntimeError("Frozen WebView2 helper did not expose the mock composer")
                upload = root / "upload.txt"
                upload.write_text("frozen", encoding="utf-8")
                result = controller.request(
                    "chatgpt",
                    "upload_files",
                    {"files": [str(upload)]},
                    task_id="frozen",
                    timeout=30,
                )
                if result.get("uploaded") != 1:
                    raise RuntimeError(f"Frozen upload failed: {result}")
                response = controller.send_prompt("chatgpt", "ok", task_id="frozen", timeout=30)
                if response != "frozen:ok":
                    raise RuntimeError(f"Frozen response mismatch: {response}")
            finally:
                controller.stop()
                diagnostics.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    print("FROZEN_WEBVIEW2_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
