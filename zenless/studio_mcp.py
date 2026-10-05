from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MCPToolResult:
    tool_name: str
    text: str
    is_error: bool
    content_types: tuple[str, ...]
    images: tuple[dict[str, str], ...] = ()
    structured_content: dict[str, Any] | list[Any] | None = None

    def compact(self, limit: int = 12_000) -> str:
        text = self.text.strip()
        if len(text) <= limit:
            return text
        return text[:limit] + "\n...[result truncated]"


@dataclass(frozen=True, slots=True)
class StudioTarget:
    studio_id: str
    label: str
    raw: dict[str, Any]


def select_studio_target(studios: list[StudioTarget], studio_id: str = "") -> StudioTarget:
    if studio_id:
        for studio in studios:
            if studio.studio_id == studio_id:
                return studio
        raise MCPError("The Studio instance assigned to this task is no longer connected.")
    if not studios:
        raise MCPError("No Studio instance is connected.")
    if len(studios) != 1:
        raise MCPError("Multiple Studio instances are connected. Keep only the intended place open before starting a task.")
    return studios[0]


def find_studio_mcp(explicit_path: str = "") -> Path:
    if explicit_path:
        candidate = Path(explicit_path).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise MCPError(f"StudioMCP was not found at the configured path: {candidate}")

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise MCPError("The LOCALAPPDATA environment variable is unavailable.")

    launcher = Path(local_app_data) / "Roblox" / "mcp.bat"
    if launcher.is_file():
        return launcher

    versions = Path(local_app_data) / "Roblox" / "Versions"
    paired: list[Path] = []
    fallback: list[Path] = []
    for candidate in versions.glob("version-*/StudioMCP.exe"):
        fallback.append(candidate)
        version_dir = candidate.parent
        if (version_dir / "RobloxStudioBeta.exe").is_file() or (version_dir / "RobloxStudio.exe").is_file():
            paired.append(candidate)
    candidates = paired or fallback
    if not candidates:
        raise MCPError("Studio MCP was not found. Update Studio and enable Assistant > MCP Servers.")
    return max(candidates, key=lambda path: path.stat().st_mtime)


class StudioMCPClient:
    def __init__(
        self,
        executable: Path,
        notification_callback: Callable[[dict[str, Any]], None] | None = None,
        *,
        args: tuple[str, ...] = (),
        env: dict[str, str] | None = None,
        client_name: str = "Rubra",
        client_version: str = "1.0.0",
        startup_timeout: float = 25.0,
    ) -> None:
        self.executable = executable
        self.args = tuple(args)
        self.env = dict(env) if env is not None else None
        self.client_name = client_name
        self.client_version = client_version
        self.startup_timeout = max(5.0, min(900.0, float(startup_timeout)))
        self.notification_callback = notification_callback
        self.process: subprocess.Popen[str] | None = None
        self.tools: dict[str, MCPTool] = {}
        self._next_id = 1
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._tool_call_lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self.stderr_tail: deque[str] = deque(maxlen=80)

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        with self._lifecycle_lock:
            if self.running:
                return
            if self.process is not None:
                self.close()
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if self.executable.suffix.casefold() in {".bat", ".cmd"}:
                command = ["cmd.exe", "/d", "/s", "/c", str(self.executable), *self.args]
            else:
                command = [str(self.executable), *self.args]
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation_flags,
                env=self.env,
            )
            safe_name = "".join(ch if ch.isalnum() else "-" for ch in self.client_name)[:32] or "MCP"
            self._reader = threading.Thread(target=self._read_stdout, name=f"Rubra-{safe_name}-stdout", daemon=True)
            self._stderr_reader = threading.Thread(target=self._read_stderr, name=f"Rubra-{safe_name}-stderr", daemon=True)
            self._reader.start()
            self._stderr_reader.start()

            try:
                self.request(
                    "initialize",
                    {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": self.client_name, "version": self.client_version},
                    },
                    timeout=self.startup_timeout,
                )
                self.notify("notifications/initialized", {})
                self.refresh_tools()
            except Exception:
                self.close()
                raise

    def refresh_tools(self) -> list[MCPTool]:
        discovered: dict[str, MCPTool] = {}
        params: dict[str, Any] = {}
        cursors: set[str] = set()
        for _ in range(64):
            response = self.request("tools/list", params, timeout=self.startup_timeout)
            for raw in response.get("tools", []):
                if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
                    continue
                schema = raw.get("inputSchema", {"type": "object"})
                if not isinstance(schema, dict):
                    raise MCPError(f"Invalid input schema for {raw['name']}.")
                tool = MCPTool(name=raw["name"], description=str(raw.get("description", "")), input_schema=schema)
                discovered[tool.name] = tool
            cursor = response.get("nextCursor")
            if cursor is None:
                break
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise MCPError("MCP tool pagination returned an invalid or repeated cursor.")
            cursors.add(cursor)
            params = {"cursor": cursor}
        else:
            raise MCPError("MCP tool pagination exceeded 64 pages.")
        if not discovered:
            raise MCPError(f"{self.client_name} started but did not advertise any tools.")
        self.tools = discovered
        return list(discovered.values())

    def list_studios(self) -> list[StudioTarget]:
        if "list_roblox_studios" not in self.tools:
            raise MCPError("The current StudioMCP version does not provide list_roblox_studios.")
        result = self.call_tool("list_roblox_studios", {}, timeout=5)
        if result.is_error:
            raise MCPError(result.text or "Failed to list Studio instances.")
        payload = result.structured_content
        if payload is None:
            try:
                payload = json.loads(result.text)
            except json.JSONDecodeError as exc:
                raise MCPError("Studio discovery returned invalid JSON.") from exc
        raw_studios = payload.get("studios", []) if isinstance(payload, dict) else payload
        if not isinstance(raw_studios, list):
            raise MCPError("Studio discovery returned an invalid instance list.")
        studios: list[StudioTarget] = []
        for index, raw in enumerate(raw_studios):
            if not isinstance(raw, dict):
                continue
            studio_id = str(raw.get("studio_id") or raw.get("studioId") or raw.get("id") or "")
            if not studio_id:
                continue
            name = str(raw.get("name") or raw.get("place_name") or raw.get("placeName") or f"Studio {index + 1}")
            place_id = raw.get("place_id") or raw.get("placeId")
            label = f"{name} • {place_id}" if place_id else name
            studios.append(StudioTarget(studio_id=studio_id, label=label, raw=raw))
        return studios

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        studio_id: str = "",
        timeout: float = 180,
    ) -> MCPToolResult:
        with self._tool_call_lock:
            return self._call_tool(name, arguments, studio_id=studio_id, timeout=timeout)

    def _call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        studio_id: str = "",
        timeout: float = 180,
    ) -> MCPToolResult:
        tool = self.tools.get(name)
        if tool is None:
            raise MCPError(f"Unknown MCP tool: {name}")

        safe_arguments = dict(arguments)
        properties = tool.input_schema.get("properties", {})
        if name != "list_roblox_studios" and "studio_id" in properties:
            if not studio_id:
                raise MCPError(f"{name} requires a selected Studio instance.")
            safe_arguments["studio_id"] = studio_id

        schema_errors = validate_json_schema(safe_arguments, tool.input_schema)
        if schema_errors:
            raise MCPError("Invalid MCP arguments: " + "; ".join(schema_errors[:6]))

        raw_result = self.request(
            "tools/call",
            {"name": name, "arguments": safe_arguments},
            timeout=timeout,
        )
        content = raw_result.get("content", [])
        text_parts: list[str] = []
        content_types: list[str] = []
        images: list[dict[str, str]] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "unknown"))
            content_types.append(item_type)
            if item_type == "text":
                text_parts.append(str(item.get("text", "")))
            elif item_type == "image":
                mime = str(item.get("mimeType") or item.get("mime_type") or "application/octet-stream")
                data = str(item.get("data") or "")
                if data:
                    images.append({"mimeType": mime, "data": data})
                text_parts.append(f"[MCP image: {mime}]")
            elif item_type == "resource":
                text_parts.append("[MCP resource returned]")
        structured = raw_result.get("structuredContent")
        if not isinstance(structured, (dict, list)):
            structured = None
        if structured is not None and not text_parts:
            text_parts.append(json.dumps(structured, ensure_ascii=False))
        return MCPToolResult(
            tool_name=name,
            text="\n".join(text_parts),
            is_error=bool(raw_result.get("isError", False)),
            content_types=tuple(content_types),
            images=tuple(images),
            structured_content=structured,
        )

    def request(self, method: str, params: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        process = self.process
        if process is None or process.poll() is not None or process.stdin is None:
            raise MCPError(f"{self.client_name} is not running.")
        if self._reader is not None and not self._reader.is_alive():
            raise MCPError(f"{self.client_name} closed the connection.")
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        try:
            try:
                with self._send_lock:
                    process.stdin.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
                    process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise MCPError(f"{self.client_name} could not send {method}: {exc}") from exc
            try:
                response = response_queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise MCPError(f"{self.client_name} exceeded {timeout:.0f}s while running {method}.") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

        if "error" in response:
            error = response["error"]
            if isinstance(error, dict):
                message = error.get("message", error)
            else:
                message = error
            raise MCPError(f"{self.client_name} rejected {method}: {message}")
        result = response.get("result", {})
        return result if isinstance(result, dict) else {"value": result}

    def notify(self, method: str, params: dict[str, Any]) -> None:
        if not self.running or self.process is None or self.process.stdin is None:
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        with self._send_lock:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def close(self) -> None:
        with self._lifecycle_lock:
            process = self.process
            self.process = None
            if process is None:
                return
            if process.poll() is None:
                if process.stdin is not None:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
            for stream, reader in ((process.stdout, self._reader), (process.stderr, self._stderr_reader)):
                if reader is not None and reader is not threading.current_thread():
                    reader.join(timeout=1)
                if stream is not None and (reader is None or not reader.is_alive()):
                    try:
                        stream.close()
                    except OSError:
                        pass
            self._reader = None
            self._stderr_reader = None

    def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                request_id = message.get("id")
                if type(request_id) is int and "method" not in message:
                    with self._pending_lock:
                        target = self._pending.get(request_id)
                    if target is not None:
                        try:
                            target.put_nowait(message)
                        except queue.Full:
                            pass
                elif self.notification_callback is not None:
                    try:
                        self.notification_callback(message)
                    except Exception as exc:
                        self.stderr_tail.append(f"MCP notification handler failed: {exc}")
        except (OSError, ValueError) as exc:
            self.stderr_tail.append(f"MCP output stream failed: {exc}")
        finally:
            if self.process is process or self.process is None:
                failure = {"error": {"message": "StudioMCP closed the connection."}}
                with self._pending_lock:
                    pending = list(self._pending.values())
                for target in pending:
                    try:
                        target.put_nowait(failure)
                    except queue.Full:
                        pass

    def _read_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            self.stderr_tail.append(line.rstrip())


def validate_json_schema(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors

    for keyword in ("anyOf", "oneOf", "allOf"):
        alternatives = schema.get(keyword)
        if isinstance(alternatives, list):
            matches = sum(not validate_json_schema(value, option, path) for option in alternatives)
            valid = matches == len(alternatives) if keyword == "allOf" else matches == 1 if keyword == "oneOf" else matches > 0
            if not valid:
                errors.append(f"{path} does not satisfy {keyword}")

    expected = schema.get("type")
    valid_type = True
    if isinstance(expected, list):
        valid_type = any(not validate_json_schema(value, {"type": item}, path) for item in expected)
    elif expected == "object":
        valid_type = isinstance(value, dict)
    elif expected == "array":
        valid_type = isinstance(value, list)
    elif expected == "string":
        valid_type = isinstance(value, str)
    elif expected == "integer":
        valid_type = isinstance(value, int) and not isinstance(value, bool)
    elif expected == "number":
        valid_type = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif expected == "boolean":
        valid_type = isinstance(value, bool)
    elif expected == "null":
        valid_type = value is None
    if not valid_type:
        return [f"{path} must be {expected}"]

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} must be one of {schema['enum']}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key} is required")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child in value.items():
                if key in properties:
                    errors.extend(validate_json_schema(child, properties[key], f"{path}.{key}"))
                elif schema.get("additionalProperties") is False:
                    errors.append(f"{path}.{key} is not allowed")
    elif isinstance(value, list):
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(validate_json_schema(item, schema["items"], f"{path}[{index}]"))
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            errors.append(f"{path} requires at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            errors.append(f"{path} accepts at most {schema['maxItems']} items")
    elif isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            errors.append(f"{path} is too short")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            errors.append(f"{path} is too long")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path} must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path} must be <= {schema['maximum']}")
    return errors
