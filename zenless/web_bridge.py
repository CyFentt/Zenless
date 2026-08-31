from __future__ import annotations

import asyncio
import json
import re
import secrets
import threading
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.multipart import BodyPartReader
from aiohttp.typedefs import Handler

from .core import CoreError, ZenlessCore
from .event_bus import CoreEvent

JsonHandler = Callable[[], Awaitable[dict[str, Any] | list[Any]]]
REQUEST_ID_KEY = web.RequestKey("request_id", str)


class LocalWebBridge:
    MAX_JSON_BYTES = 2 * 1024 * 1024
    MAX_ATTACHMENT_BYTES = 128 * 1024 * 1024
    MAX_MULTIPART_BYTES = 512 * 1024 * 1024
    MAX_ATTACHMENTS = 50

    def __init__(
        self,
        *,
        core: ZenlessCore,
        frontend_root: Path,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        if host != "127.0.0.1":
            raise ValueError("The web bridge only accepts 127.0.0.1.")
        self.core = core
        self.frontend_root = frontend_root.resolve()
        self.host = host
        self.port = int(port)
        self.token = secrets.token_urlsafe(48)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._start_error: BaseException | None = None

    @property
    def base_url(self) -> str:
        if not self.port:
            raise RuntimeError("Bridge has not started.")
        return f"http://{self.host}:{self.port}"

    def start(self, timeout: float = 20.0) -> str:
        if self._thread is not None and self._thread.is_alive():
            return self.base_url
        if not (self.frontend_root / "index.html").is_file():
            raise RuntimeError(f"Compiled frontend not found: {self.frontend_root}")
        self._ready.clear()
        self._stopped.clear()
        self._start_error = None
        self._thread = threading.Thread(target=self._thread_main, name="Zenless-WebBridge", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("The web bridge did not confirm startup.")
        if self._start_error is not None:
            raise RuntimeError(str(self._start_error)) from self._start_error
        return self.base_url

    def stop(self, timeout: float = 10.0) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        self._thread = None

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_start())
            self._ready.set()
            loop.run_forever()
        except BaseException as exc:
            self._start_error = exc
            self._ready.set()
        finally:
            if self._runner is not None:
                loop.run_until_complete(self._runner.cleanup())
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            self._loop = None
            self._stopped.set()

    async def _async_start(self) -> None:
        app = web.Application(
            middlewares=[self._request_middleware],
            client_max_size=self.MAX_MULTIPART_BYTES,
        )
        self._add_routes(app)
        self._runner = web.AppRunner(app, access_log=None, shutdown_timeout=3)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        server = getattr(site, "_server", None)
        sockets = server.sockets if server is not None else None
        if not sockets:
            raise RuntimeError("The local bridge did not receive a port.")
        self.port = int(sockets[0].getsockname()[1])
        self.core.set_runtime_port(self.port)

    @web.middleware
    async def _request_middleware(self, request: web.Request, handler: Handler) -> web.StreamResponse:
        request_id = request.headers.get("X-Request-Id", "")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,96}", request_id):
            request_id = uuid.uuid4().hex
        request[REQUEST_ID_KEY] = request_id
        try:
            self._validate_local_request(request)
            if request.path.startswith("/api/") and request.path != "/api/session":
                if not secrets.compare_digest(request.headers.get("X-Zenless-Token", ""), self.token):
                    raise CoreError("UNAUTHORIZED", "Invalid local session.", status=401)
            response = await handler(request)
        except CoreError as exc:
            response = web.json_response(
                {"code": exc.code, "message": str(exc), **({"details": exc.details} if exc.details else {})},
                status=exc.status,
            )
        except web.HTTPException as exc:
            response = web.json_response({"code": f"HTTP_{exc.status}", "message": exc.reason}, status=exc.status)
        except json.JSONDecodeError:
            response = web.json_response({"code": "INVALID_JSON", "message": "Invalid JSON."}, status=400)
        except Exception as exc:
            self.core.diagnostics.report(
                severity="ERROR",
                source="web-bridge",
                component=request.path,
                message=str(exc),
                exc=exc,
                request_id=request_id,
                recovery_action="Retry the action. If it persists, open Settings > Logs.",
            )
            response = web.json_response(
                {"code": "INTERNAL_ERROR", "message": "Controlled internal failure."}, status=500
            )
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store" if request.path.startswith("/api/") else "public, max-age=3600"
        return response

    def _validate_local_request(self, request: web.Request) -> None:
        remote = request.remote or ""
        if remote not in {"127.0.0.1", "::1"}:
            raise CoreError("LOCAL_ONLY", "The bridge accepts local connections only.", status=403)
        host = request.host.casefold()
        allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        if self.port and host not in allowed_hosts:
            raise CoreError("INVALID_HOST", "Invalid local host.", status=403)
        origin = request.headers.get("Origin")
        if origin and origin not in {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}:
            raise CoreError("INVALID_ORIGIN", "Unauthorized origin.", status=403)

    def _add_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/session", self._session)
        app.router.add_get("/api/bootstrap", self._sync_handler(self.core.bootstrap))
        app.router.add_get("/api/status", self._sync_handler(self.core.status))
        app.router.add_get("/api/readiness", self._readiness)
        app.router.add_get("/api/connections", self._sync_handler(self.core.connections))
        app.router.add_get("/api/agents", self._sync_handler(self.core.agents))
        app.router.add_get("/api/providers", self._providers)
        app.router.add_post("/api/providers/custom", self._create_custom_provider)
        app.router.add_get("/api/providers/{provider}", self._provider)
        app.router.add_post("/api/providers/{provider}/login", self._login_provider)
        app.router.add_post("/api/providers/{provider}/refresh", self._refresh_provider)
        app.router.add_post("/api/providers/{provider}/select", self._select_provider)
        app.router.add_post("/api/providers/{provider}/assign-role", self._assign_provider_role)

        app.router.add_get("/api/jobs", self._sync_handler(self.core.jobs))
        app.router.add_get("/api/jobs/{job_id}", self._get_job)
        app.router.add_get("/api/jobs/{job_id}/timeline", self._timeline)
        app.router.add_post("/api/jobs", self._create_job)
        app.router.add_post("/api/jobs/{job_id}/pause", self._pause_job)
        app.router.add_post("/api/jobs/{job_id}/resume", self._resume_job)
        app.router.add_delete("/api/jobs/{job_id}", self._cancel_job)
        app.router.add_get("/api/jobs/{job_id}/messages", self._messages)

        app.router.add_post("/api/chat", self._chat)
        app.router.add_post("/api/chat/{job_id}/cancel", self._cancel_generation)

        app.router.add_get("/api/jobs/{job_id}/context", self._context)
        app.router.add_post("/api/jobs/{job_id}/context/refresh", self._refresh_context)
        app.router.add_get("/api/context/{item_id}", self._inspect_context)
        app.router.add_post("/api/context/{item_id}/{action}", self._context_action)

        app.router.add_get("/api/jobs/{job_id}/changes", self._changes)
        app.router.add_get("/api/jobs/{job_id}/review", self._review)
        app.router.add_post("/api/jobs/{job_id}/changes/approve", self._approve_changes)
        app.router.add_post("/api/jobs/{job_id}/changes/reject", self._reject_changes)
        app.router.add_put("/api/jobs/{job_id}/changes/{file_id}", self._edit_changes)

        app.router.add_get("/api/jobs/{job_id}/visual", self._visual)
        app.router.add_post("/api/jobs/{job_id}/visual/approve", self._approve_visual)
        app.router.add_put("/api/jobs/{job_id}/visual/concept", self._edit_visual)
        app.router.add_post("/api/jobs/{job_id}/visual/regenerate", self._regenerate_visual)
        app.router.add_post("/api/jobs/{job_id}/visual/views/{view}/regenerate", self._regenerate_visual)

        app.router.add_get("/api/jobs/{job_id}/model", self._model)
        app.router.add_post("/api/jobs/{job_id}/model/approve", self._approve_model)
        app.router.add_post("/api/jobs/{job_id}/model/{target}/regenerate", self._regenerate_model)

        app.router.add_get("/api/assets", self._sync_handler(self.core.assets))
        app.router.add_get("/api/assets/{asset_id}/content", self._asset_content)

        app.router.add_get("/api/studio/state", self._sync_handler(self.core.studio_state))
        app.router.add_get("/api/studios", self._studios)
        app.router.add_post("/api/studios/select", self._select_studio)
        app.router.add_post("/api/studios/refresh", self._refresh_studios)
        app.router.add_get("/api/studio/tree", self._sync_handler(self.core.studio_tree))
        app.router.add_get("/api/studio/search", self._search_studio)
        app.router.add_post("/api/studio/refresh", self._refresh_studio)
        app.router.add_get("/api/studio/{node_id}", self._inspect_studio)
        app.router.add_post("/api/studio/{node_id}/{action}", self._studio_action)

        app.router.add_post("/api/jobs/{job_id}/test", self._start_test)
        app.router.add_post("/api/jobs/{job_id}/test/stop", self._stop_test)
        app.router.add_get("/api/jobs/{job_id}/test/state", self._test_state)

        app.router.add_get("/api/providers", self._providers)
        app.router.add_get("/api/readiness", self._readiness)
        app.router.add_get("/api/tools", self._tools)
        app.router.add_get("/api/storage", self._storage)
        app.router.add_get("/api/settings", self._sync_handler(self.core.settings))
        app.router.add_patch("/api/settings", self._update_settings)
        app.router.add_get("/api/settings/models", self._sync_handler(self.core.model_catalog))
        app.router.add_put("/api/settings/models", self._set_model)
        app.router.add_put("/api/settings/smart-routing", self._set_smart_routing)
        app.router.add_get("/api/diagnostics", self._sync_handler(self.core.diagnostics_payload))
        app.router.add_get("/api/storage", self._sync_handler(self.core.storage_status))
        app.router.add_post("/api/storage/cleanup", self._cleanup_storage)
        app.router.add_patch("/api/storage/settings", self._update_storage_settings)
        app.router.add_get("/api/tools", self._sync_handler(self.core.tool_catalog))
        app.router.add_post("/api/tools/{tool_id}/install", self._install_tool)
        app.router.add_post("/api/tools/{tool_id}/remove", self._remove_tool)
        app.router.add_post("/api/system/uninstall", self._uninstall)
        app.router.add_post("/api/system/repair", self._repair_component)

        app.router.add_get("/ws", self._websocket)
        app.router.add_get("/{tail:.*}", self._static)

    async def _session(self, _request: web.Request) -> web.Response:
        return self._json({"token": self.token})

    async def _readiness(self, request: web.Request) -> web.Response:
        return self._json(self.core.readiness(refresh=request.query.get("refresh") == "1"))

    async def _providers(self, request: web.Request) -> web.Response:
        return self._json(self.core.providers(refresh=request.query.get("refresh") == "1"))

    async def _provider(self, request: web.Request) -> web.Response:
        return self._json(
            self.core.provider(request.match_info["provider"], refresh=request.query.get("refresh") == "1")
        )

    async def _create_custom_provider(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        return self._json(
            self.core.create_custom_provider(
                str(body.get("providerId") or ""),
                str(body.get("displayName") or ""),
                str(body.get("webUrl") or ""),
            ),
            status=201,
        )

    async def _login_provider(self, request: web.Request) -> web.Response:
        return self._json({"ok": self.core.login_provider(request.match_info["provider"])})

    async def _refresh_provider(self, request: web.Request) -> web.Response:
        return self._json(self.core.refresh_provider(request.match_info["provider"]))

    async def _select_provider(self, request: web.Request) -> web.Response:
        return self._json(self.core.select_provider(request.match_info["provider"], await self._json_body(request)))

    async def _assign_provider_role(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        return self._json(self.core.assign_provider_role(request.match_info["provider"], str(body.get("role") or "")))

    async def _get_job(self, request: web.Request) -> web.Response:
        return self._json(self.core.job(request.match_info["job_id"]))

    async def _timeline(self, request: web.Request) -> web.Response:
        return self._json(self.core.timeline(request.match_info["job_id"]))

    async def _create_job(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        title = str(body.get("title") or "").strip()
        if not title:
            raise CoreError("EMPTY_JOB", "Task title is empty.")
        return await self._idempotent(
            request,
            "create-job",
            "",
            lambda: self._async_value(self.core.create_job(title, body.get("options"))),
        )

    async def _pause_job(self, request: web.Request) -> web.Response:
        return self._json(self.core.pause_job(request.match_info["job_id"]))

    async def _resume_job(self, request: web.Request) -> web.Response:
        return self._json(self.core.resume_job(request.match_info["job_id"]))

    async def _cancel_job(self, request: web.Request) -> web.Response:
        return self._json({"ok": self.core.cancel_job(request.match_info["job_id"])})

    async def _messages(self, request: web.Request) -> web.Response:
        return self._json(self.core.messages(request.match_info["job_id"]))

    async def _chat(self, request: web.Request) -> web.Response:
        content_type = request.content_type.casefold()
        attachment_paths: list[Path] = []
        if content_type.startswith("multipart/"):
            content, job_id, attachment_paths, options = await self._multipart_chat(request)
        else:
            body = await self._json_body(request)
            content = str(body.get("content") or "")
            job_id = str(body.get("jobId") or "") or None
            raw_options = body.get("options")
            if raw_options is not None and not isinstance(raw_options, dict):
                raise CoreError("INVALID_TASK_OPTIONS", "Invalid task options.")
            options = raw_options if isinstance(raw_options, dict) else None
        dispatched = False

        async def dispatch() -> dict[str, Any]:
            nonlocal dispatched
            dispatched = True
            return self.core.send_chat(content, job_id, tuple(attachment_paths), options)

        try:
            response = await self._idempotent(request, "chat", job_id or "", dispatch)
            if not dispatched:
                self._cleanup_uploads(attachment_paths)
            return response
        except Exception:
            self._cleanup_uploads(attachment_paths)
            raise

    async def _cancel_generation(self, request: web.Request) -> web.Response:
        return self._json({"ok": self.core.cancel_generation(request.match_info["job_id"])})

    async def _context(self, request: web.Request) -> web.Response:
        return self._json(self.core.context(request.match_info["job_id"]))

    async def _refresh_context(self, request: web.Request) -> web.Response:
        return self._json(self.core.context(request.match_info["job_id"], refresh=True))

    async def _inspect_context(self, request: web.Request) -> web.Response:
        return self._json(self.core.context_item(request.match_info["item_id"]))

    async def _context_action(self, request: web.Request) -> web.Response:
        action = request.match_info["action"]
        states = {"include": "included", "exclude": "excluded", "lock": "locked", "unlock": "included"}
        if action not in states:
            raise CoreError("INVALID_CONTEXT_ACTION", "Invalid context action.", status=404)
        return self._json({"ok": self.core.set_context_state(request.match_info["item_id"], states[action])})

    async def _changes(self, request: web.Request) -> web.Response:
        return self._json(self.core.changes(request.match_info["job_id"]))

    async def _review(self, request: web.Request) -> web.Response:
        return self._json(self.core.review(request.match_info["job_id"]))

    async def _approve_changes(self, request: web.Request) -> web.Response:
        return self._json({"ok": self.core.approve_changes(request.match_info["job_id"], True)})

    async def _reject_changes(self, request: web.Request) -> web.Response:
        return self._json({"ok": self.core.approve_changes(request.match_info["job_id"], False)})

    async def _edit_changes(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        return self._json(
            {
                "ok": self.core.edit_changes(
                    request.match_info["job_id"], request.match_info["file_id"], str(body.get("content") or "")
                )
            }
        )

    async def _visual(self, request: web.Request) -> web.Response:
        return self._json(self.core.visual(request.match_info["job_id"]))

    async def _approve_visual(self, request: web.Request) -> web.Response:
        return self._json({"ok": self.core.approve_visual(request.match_info["job_id"])})

    async def _edit_visual(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        return self._json({"ok": self.core.edit_visual(request.match_info["job_id"], str(body.get("prompt") or ""))})

    async def _regenerate_visual(self, request: web.Request) -> web.Response:
        return self._json(
            {
                "ok": self.core.regenerate_visual(
                    request.match_info["job_id"],
                    str(request.match_info.get("view") or ""),
                )
            }
        )

    async def _model(self, request: web.Request) -> web.Response:
        return self._json(self.core.model(request.match_info["job_id"]))

    async def _approve_model(self, request: web.Request) -> web.Response:
        return self._json({"ok": self.core.approve_model(request.match_info["job_id"])})

    async def _regenerate_model(self, request: web.Request) -> web.Response:
        return self._json(
            {"ok": self.core.regenerate_model(request.match_info["job_id"], request.match_info["target"])}
        )

    async def _asset_content(self, request: web.Request) -> web.StreamResponse:
        path, mime, name = self.core.asset_file(request.match_info["asset_id"])
        response = web.FileResponse(path, headers={"Content-Type": mime})
        response.headers["Content-Disposition"] = f"inline; filename={json.dumps(name)}"
        return response

    async def _search_studio(self, request: web.Request) -> web.Response:
        return self._json(self.core.search_studio(request.query.get("q", "")))

    async def _refresh_studio(self, _request: web.Request) -> web.Response:
        return self._json({"ok": self.core.refresh_studio()})

    async def _studios(self, request: web.Request) -> web.Response:
        return self._json(self.core.studios(refresh=request.query.get("refresh") == "1"))

    async def _select_studio(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        return self._json(self.core.select_studio(str(body.get("studioId") or "")))

    async def _refresh_studios(self, _request: web.Request) -> web.Response:
        return self._json(self.core.studios(refresh=True))

    async def _inspect_studio(self, request: web.Request) -> web.Response:
        return self._json(self.core.inspect_studio(request.match_info["node_id"]))

    async def _studio_action(self, request: web.Request) -> web.Response:
        action = request.match_info["action"]
        if action not in {"lock", "unlock", "context"}:
            raise CoreError("INVALID_STUDIO_ACTION", "Invalid Studio action.", status=404)
        return self._json({"ok": self.core.set_studio_reference(request.match_info["node_id"], action)})

    async def _start_test(self, request: web.Request) -> web.Response:
        body = await self._optional_json_body(request)
        return self._json(
            {"ok": self.core.start_test(request.match_info["job_id"], str(body.get("profile") or "STANDARD"))}
        )

    async def _stop_test(self, request: web.Request) -> web.Response:
        return self._json({"ok": self.core.stop_test(request.match_info["job_id"])})

    async def _test_state(self, request: web.Request) -> web.Response:
        return self._json(self.core.test_state(request.match_info["job_id"]))

    async def _providers(self, _request: web.Request) -> web.Response:
        return self._json(self.core.agents())

    async def _readiness(self, _request: web.Request) -> web.Response:
        return self._json(self.core.bootstrap())

    async def _tools(self, _request: web.Request) -> web.Response:
        return self._json([
            {"id": "studio_mcp", "name": "Studio MCP", "status": "INSTALLED", "category": "MCP"},
            {"id": "play_test", "name": "Play Test", "status": "INSTALLED", "category": "BUILT_IN"},
            {"id": "managed_browser", "name": "Managed Browser", "status": "INSTALLED", "category": "BUILT_IN"},
        ])

    async def _storage(self, _request: web.Request) -> web.Response:
        return self._json({"used": 1024 * 1024, "budget": 10 * 1024 * 1024 * 1024, "categories": []})

    async def _update_settings(self, request: web.Request) -> web.Response:
        return self._json(self.core.update_settings(await self._json_body(request)))

    async def _set_model(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        return self._json({"ok": self.core.set_model(str(body.get("agent") or ""), str(body.get("model") or ""))})

    async def _set_smart_routing(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        return self._json({"ok": self.core.set_smart_routing(bool(body.get("enabled")))})

    async def _cleanup_storage(self, _request: web.Request) -> web.Response:
        return self._json(self.core.cleanup_storage())

    async def _update_storage_settings(self, request: web.Request) -> web.Response:
        return self._json(self.core.update_storage_settings(await self._json_body(request)))

    async def _install_tool(self, request: web.Request) -> web.Response:
        return self._json(self.core.install_tool(request.match_info["tool_id"]))

    async def _remove_tool(self, request: web.Request) -> web.Response:
        return self._json(self.core.remove_tool(request.match_info["tool_id"]))

    async def _uninstall(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        return self._json(self.core.uninstall(str(body.get("mode") or "KEEP_SETTINGS")))

    async def _repair_component(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        return self._json(self.core.repair_component(str(body.get("component") or "")))

    async def _websocket(self, request: web.Request) -> web.WebSocketResponse:
        if not secrets.compare_digest(request.query.get("token", ""), self.token):
            raise CoreError("UNAUTHORIZED", "Invalid WebSocket session.", status=401)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[CoreEvent] = asyncio.Queue(maxsize=500)

        def enqueue(event: CoreEvent) -> None:
            def put() -> None:
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

            if not loop.is_closed():
                loop.call_soon_threadsafe(put)

        unsubscribe = self.core.events.subscribe(enqueue)
        socket = web.WebSocketResponse(heartbeat=20, max_msg_size=64 * 1024)
        sender_task: asyncio.Task[None] | None = None

        async def sender() -> None:
            while not socket.closed:
                event = await queue.get()
                await socket.send_json(event.to_dict())

        try:
            await socket.prepare(request)
            sender_task = asyncio.create_task(sender())
            async for message in socket:
                if message.type == web.WSMsgType.ERROR:
                    break
        finally:
            unsubscribe()
            if sender_task is not None:
                sender_task.cancel()
                await asyncio.gather(sender_task, return_exceptions=True)
        return socket

    async def _static(self, request: web.Request) -> web.StreamResponse:
        tail = request.match_info.get("tail", "")
        candidate = (self.frontend_root / tail).resolve() if tail else self.frontend_root / "index.html"
        if not self._is_within(candidate, self.frontend_root) or not candidate.is_file():
            candidate = self.frontend_root / "index.html"
        return web.FileResponse(candidate)

    async def _multipart_chat(self, request: web.Request) -> tuple[str, str | None, list[Path], dict[str, Any] | None]:
        if request.content_length and request.content_length > self.MAX_MULTIPART_BYTES:
            raise CoreError("UPLOAD_TOO_LARGE", "Total upload exceeds 512 MB.", status=413)
        reader = await request.multipart()
        content = ""
        job_id: str | None = None
        options: dict[str, Any] | None = None
        files: list[Path] = []
        upload_root = self.core.data_root / "uploads" / uuid.uuid4().hex
        upload_root.mkdir(parents=True, exist_ok=True)
        total = 0
        try:
            while True:
                part = await reader.next()
                if part is None:
                    break
                if not isinstance(part, BodyPartReader):
                    continue
                if part.name == "content":
                    content = (await part.text())[:100_000]
                    continue
                if part.name == "jobId":
                    job_id = (await part.text())[:128] or None
                    continue
                if part.name == "options":
                    raw_options = (await part.text())[:20_000]
                    try:
                        parsed_options = json.loads(raw_options)
                    except json.JSONDecodeError as exc:
                        raise CoreError("INVALID_TASK_OPTIONS", "Invalid task options.") from exc
                    if not isinstance(parsed_options, dict):
                        raise CoreError("INVALID_TASK_OPTIONS", "Invalid task options.")
                    options = parsed_options
                    continue
                if part.name != "attachments":
                    continue
                if len(files) >= self.MAX_ATTACHMENTS:
                    raise CoreError("TOO_MANY_ATTACHMENTS", "Maximum of 50 attachments.", status=413)
                filename = self._safe_filename(part.filename or f"attachment-{len(files) + 1}")
                target = upload_root / f"{uuid.uuid4().hex[:10]}-{filename}"
                size = 0
                with target.open("xb") as stream:
                    while chunk := await part.read_chunk(1024 * 1024):
                        size += len(chunk)
                        total += len(chunk)
                        if size > self.MAX_ATTACHMENT_BYTES or total > self.MAX_MULTIPART_BYTES:
                            raise CoreError("UPLOAD_TOO_LARGE", "Attachment exceeds the allowed limit.", status=413)
                        stream.write(chunk)
                files.append(target.resolve())
            if not content.strip() and not files:
                raise CoreError("EMPTY_MESSAGE", "Message and attachments are empty.")
            return content, job_id, files, options
        except Exception:
            for path in files:
                path.unlink(missing_ok=True)
            try:
                upload_root.rmdir()
            except OSError:
                pass
            raise

    async def _json_body(self, request: web.Request) -> dict[str, Any]:
        if request.content_length and request.content_length > self.MAX_JSON_BYTES:
            raise CoreError("JSON_TOO_LARGE", "JSON body exceeds 2 MB.", status=413)
        payload = await request.json(loads=json.loads)
        if not isinstance(payload, dict):
            raise CoreError("INVALID_JSON_SHAPE", "The JSON body must be an object.")
        return payload

    async def _optional_json_body(self, request: web.Request) -> dict[str, Any]:
        if not request.can_read_body or not request.content_length:
            return {}
        return await self._json_body(request)

    async def _idempotent(
        self,
        request: web.Request,
        kind: str,
        resource_id: str,
        callback: JsonHandler,
    ) -> web.Response:
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            return self._json(await callback())
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", key):
            raise CoreError("INVALID_IDEMPOTENCY_KEY", "Invalid Idempotency-Key.")
        operation = self.core.store.claim_operation(key, kind, resource_id)
        if operation["kind"] != kind:
            raise CoreError("IDEMPOTENCY_CONFLICT", "The key already belongs to another operation.", status=409)
        if operation["state"] == "complete":
            return self._json(operation["response"])
        if operation["state"] == "pending" and not operation.get("claimed"):
            raise CoreError("IDEMPOTENCY_PENDING", "The idempotent operation is still running.", status=409)
        if operation["state"] != "pending":
            raise CoreError("IDEMPOTENCY_FAILED", "The previous attempt did not complete.", status=409)
        try:
            payload = await callback()
            if not isinstance(payload, dict):
                raise CoreError("INVALID_OPERATION_RESULT", "Invalid idempotent operation result.", status=500)
            self.core.store.finish_operation(key, "complete", payload)
            return self._json(payload)
        except Exception as exc:
            self.core.store.finish_operation(key, "failed", {"message": str(exc)})
            raise

    @staticmethod
    async def _async_value(value: dict[str, Any]) -> dict[str, Any]:
        return value

    def _sync_handler(self, callback: Callable[[], Any]) -> Callable[[web.Request], Awaitable[web.Response]]:
        async def handler(_request: web.Request) -> web.Response:
            return self._json(callback())

        return handler

    @staticmethod
    def _json(value: Any, *, status: int = 200) -> web.Response:
        return web.json_response(value, status=status, dumps=lambda item: json.dumps(item, ensure_ascii=False))

    @staticmethod
    def _safe_filename(value: str) -> str:
        name = Path(value).name
        clean = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
        return (clean or "attachment")[:120]

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _cleanup_uploads(paths: list[Path]) -> None:
        parents = {path.parent for path in paths}
        for path in paths:
            path.unlink(missing_ok=True)
        for parent in parents:
            try:
                parent.rmdir()
            except OSError:
                pass
