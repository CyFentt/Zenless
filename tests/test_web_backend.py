from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from aiohttp import ClientSession, WSMsgType

from zenless.event_bus import EventBus
from zenless.models import TaskOptions
from zenless.qa_breaker import QABreaker
from zenless.store import SQLiteStore
from zenless.studio_mcp import MCPToolResult
from zenless.web_bridge import LocalWebBridge


class _Diagnostics:
    def report(self, **_kwargs: Any) -> None:
        pass


class _FakeCore:
    def __init__(self, root: Path) -> None:
        self.data_root = root
        self.store = SQLiteStore(root / "zenless.db")
        self.events = EventBus()
        self.diagnostics = _Diagnostics()
        self.runtime_port = 0
        self.created = 0
        self.chats = 0
        self.last_chat_options: dict[str, Any] | None = None
        self.asset_path = root / "asset.png"
        self.asset_path.write_bytes(b"image")

    def set_runtime_port(self, port: int) -> None:
        self.runtime_port = port

    def bootstrap(self) -> dict[str, Any]:
        return {"jobs": [], "status": self.status()}

    def status(self) -> dict[str, Any]:
        return {"ready": True, "port": self.runtime_port}

    def create_job(self, title: str, _options: Any = None) -> dict[str, Any]:
        self.created += 1
        return {"id": f"job-{self.created}", "title": title}

    def send_chat(
        self,
        content: str,
        job_id: str | None,
        _paths: tuple[Path, ...],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.chats += 1
        self.last_chat_options = options
        return {"jobId": job_id or f"chat-{self.chats}", "content": content}

    def asset_file(self, asset_id: str) -> tuple[Path, str, str]:
        if asset_id != "test-asset":
            raise AssertionError("Unexpected asset identifier")
        return self.asset_path, "image/png", self.asset_path.name

    def __getattr__(self, _name: str) -> Any:
        return lambda *_args, **_kwargs: []


class _OfflineBridge:
    def wait_for_provider(self, _provider: str, timeout: float = 0.0) -> bool:
        return False

    def send_prompt(self, *_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("Provider offline must not receive prompts")


class _QAStudio:
    def __init__(self) -> None:
        self.running = True
        self.tools = {
            "get_studio_state": object(),
            "start_stop_play": object(),
            "get_console_output": object(),
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        studio_id: str = "",
        timeout: float = 0,
    ) -> MCPToolResult:
        self.calls.append((name, dict(arguments)))
        text = "Current Studio mode: Edit" if name == "get_studio_state" else ""
        return MCPToolResult(name, text, False, ("text",))


class WebBackendTests(unittest.TestCase):
    def test_store_operation_claim_is_atomic_and_replayable(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            first = store.claim_operation("operation-123", "chat", "job-1")
            self.assertTrue(first["claimed"])
            store.finish_operation("operation-123", "complete", {"ok": True})
            replay = store.claim_operation("operation-123", "chat", "job-1")
            self.assertFalse(replay["claimed"])
            self.assertEqual(replay["response"], {"ok": True})

    def test_local_bridge_auth_origin_idempotency_and_websocket(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frontend = root / "frontend"
            frontend.mkdir()
            (frontend / "index.html").write_text("<html>Zenless</html>", encoding="utf-8")
            core = _FakeCore(root)
            bridge = LocalWebBridge(core=core, frontend_root=frontend)
            base = bridge.start()
            try:
                with urlopen(Request(base + "/api/session"), timeout=5) as response:
                    session = json.loads(response.read())
                    cookie = str(response.headers.get("Set-Cookie")).split(";", 1)[0]
                token = str(session["token"])
                headers = {"X-Zenless-Token": token, "Origin": base}
                self.assertTrue(self._request(base + "/api/status", headers=headers)["ready"])

                asset_request = Request(
                    base + "/api/assets/test-asset/content",
                    headers={"Cookie": cookie, "Origin": base},
                )
                with urlopen(asset_request, timeout=5) as response:
                    self.assertEqual(response.read(), b"image")
                    self.assertEqual(response.headers.get_content_type(), "image/png")

                with self.assertRaises(HTTPError) as asset_unauthorized:
                    urlopen(Request(base + "/api/assets/test-asset/content"), timeout=5)
                self.assertEqual(asset_unauthorized.exception.code, 401)

                with self.assertRaises(HTTPError) as unauthorized:
                    self._request(base + "/api/status", headers={"X-Zenless-Token": "wrong"})
                self.assertEqual(unauthorized.exception.code, 401)

                with self.assertRaises(HTTPError) as forbidden:
                    self._request(
                        base + "/api/status",
                        headers={"X-Zenless-Token": token, "Origin": "https://example.com"},
                    )
                self.assertEqual(forbidden.exception.code, 403)

                idempotent = {**headers, "Idempotency-Key": "create-job-0001"}
                first = self._request(base + "/api/jobs", method="POST", payload={"title": "Build"}, headers=idempotent)
                replay = self._request(
                    base + "/api/jobs", method="POST", payload={"title": "Build"}, headers=idempotent
                )
                self.assertEqual(first, replay)
                self.assertEqual(core.created, 1)

                chat_headers = {**headers, "Idempotency-Key": "send-chat-0001"}
                chat_payload = {"content": "Hello", "options": {"risk": "high", "autoTest": True}}
                self._request(base + "/api/chat", method="POST", payload=chat_payload, headers=chat_headers)
                self._request(base + "/api/chat", method="POST", payload=chat_payload, headers=chat_headers)
                self.assertEqual(core.chats, 1)
                self.assertEqual(core.last_chat_options, {"risk": "high", "autoTest": True})

                asyncio.run(self._assert_websocket(base, token, core.events))
            finally:
                bridge.stop()

    def test_qa_breaker_runs_bounded_studio_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            store.create_task("job-qa", "Simple text adjustment", TaskOptions())
            events = EventBus()
            studio = _QAStudio()
            qa = QABreaker(
                store=store,
                studio=studio,
                bridge=_OfflineBridge(),
                events=events,
                play_test_seconds=1,
            )
            output = qa.run(
                "job-qa",
                studio_id="studio-1",
                profile_name="SMOKE",
                evidence=[{"tool": "multi_edit", "is_error": False}],
                cancel_event=threading.Event(),
            )
            self.assertNotIn("ERROR:", output)
            self.assertEqual(store.latest_test_run("job-qa")["status"], "PASSED")
            play_calls = [args["is_start"] for name, args in studio.calls if name == "start_stop_play"]
            self.assertEqual(play_calls, [True, False])
            event_names = [event.type for event in events.recent(100)]
            self.assertIn("TEST_CASE_STARTED", event_names)
            self.assertIn("TEST_FINISHED", event_names)

    def test_task_risk_controls_automatic_qa_profile(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            store.create_task(
                "job-high-risk",
                "Change a simple text value",
                TaskOptions.from_api({"risk": "high"}),
            )
            qa = QABreaker(
                store=store,
                studio=_QAStudio(),
                bridge=_OfflineBridge(),
                events=EventBus(),
                play_test_seconds=1,
            )
            self.assertEqual(qa.select_profile("job-high-risk", []).name, "DEEP")

    @staticmethod
    def _request(
        url: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode() if payload is not None else None
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        request = Request(url, data=data, method=method, headers=request_headers)
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read())

    @staticmethod
    async def _assert_websocket(base: str, token: str, events: EventBus) -> None:
        websocket_url = base.replace("http://", "ws://", 1) + f"/ws?token={token}"
        async with ClientSession() as session:
            async with session.ws_connect(websocket_url, origin=base) as socket:
                events.publish("TEST_EVENT", {"value": 7})
                message = await asyncio.wait_for(socket.receive(), timeout=5)
                assert message.type == WSMsgType.TEXT
                assert json.loads(message.data) == {"type": "TEST_EVENT", "data": {"value": 7}}


if __name__ == "__main__":
    unittest.main()
