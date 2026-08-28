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

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description[:1024],
            "parameters": self.input_schema,
            "strict": False,
        }


@dataclass(frozen=True, slots=True)
class MCPToolResult:
    tool_name: str
    text: str
    is_error: bool
    content_types: tuple[str, ...]

    def compact(self, limit: int = 12_000) -> str:
        text = self.text.strip()
        if len(text) <= limit:
            return text
        return text[:limit] + "\n...[resultado truncado pelo Zenless]"


@dataclass(frozen=True, slots=True)
class StudioTarget:
    studio_id: str
    label: str
    raw: dict[str, Any]


def find_studio_mcp(explicit_path: str = "") -> Path:
    if explicit_path:
        candidate = Path(explicit_path).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise MCPError(f"StudioMCP não encontrado no caminho configurado: {candidate}")

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise MCPError("A variável LOCALAPPDATA não está disponível.")

    versions = Path(local_app_data) / "Roblox" / "Versions"
    paired: list[Path] = []
    fallback: list[Path] = []
    for candidate in versions.glob("version-*\\StudioMCP.exe"):
        fallback.append(candidate)
        version_dir = candidate.parent
        if (version_dir / "RobloxStudioBeta.exe").is_file() or (version_dir / "RobloxStudio.exe").is_file():
            paired.append(candidate)
    candidates = paired or fallback
    if not candidates:
        raise MCPError(
            "StudioMCP.exe não foi encontrado. Atualize o Roblox Studio e ative Assistant > MCP Servers."
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


class StudioMCPClient:
    def __init__(
        self,
        executable: Path,
        notification_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.executable = executable
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
            self.process = subprocess.Popen(
                [str(self.executable)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation_flags,
            )
            self._reader = threading.Thread(target=self._read_stdout, name="Zenless-MCP-stdout", daemon=True)
            self._stderr_reader = threading.Thread(target=self._read_stderr, name="Zenless-MCP-stderr", daemon=True)
            self._reader.start()
            self._stderr_reader.start()

            try:
                self.request(
                    "initialize",
                    {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "Zenless", "version": "2.0.0"},
                    },
                    timeout=25,
                )
                self.notify("notifications/initialized", {})
                self.refresh_tools()
            except Exception:
                self.close()
                raise

    def refresh_tools(self) -> list[MCPTool]:
        response = self.request("tools/list", {}, timeout=25)
        discovered: dict[str, MCPTool] = {}
        for raw in response.get("tools", []):
            if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
                continue
            tool = MCPTool(
                name=raw["name"],
                description=str(raw.get("description", "")),
                input_schema=raw.get("inputSchema", {"type": "object"}),
            )
            discovered[tool.name] = tool
        if not discovered:
            raise MCPError("O StudioMCP iniciou, mas não anunciou nenhuma ferramenta.")
        self.tools = discovered
        return list(discovered.values())

    def list_studios(self) -> list[StudioTarget]:
        if "list_roblox_studios" not in self.tools:
            raise MCPError("A versão atual do StudioMCP não oferece list_roblox_studios.")
        result = self.call_tool("list_roblox_studios", {}, timeout=30)
        if result.is_error:
            raise MCPError(result.text or "Falha ao listar instâncias do Roblox Studio.")
        try:
            payload = json.loads(result.text)
        except json.JSONDecodeError:
            payload = {}
        raw_studios = payload.get("studios", []) if isinstance(payload, dict) else []
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
            raise MCPError(f"Ferramenta MCP desconhecida: {name}")

        safe_arguments = dict(arguments)
        properties = tool.input_schema.get("properties", {})
        if name != "list_roblox_studios" and "studio_id" in properties:
            if not studio_id:
                raise MCPError(f"{name} requer um Studio selecionado.")
            safe_arguments["studio_id"] = studio_id

        schema_errors = validate_json_schema(safe_arguments, tool.input_schema)
        if schema_errors:
            raise MCPError("Argumentos MCP inválidos: " + "; ".join(schema_errors[:6]))

        raw_result = self.request(
            "tools/call",
            {"name": name, "arguments": safe_arguments},
            timeout=timeout,
        )
        content = raw_result.get("content", [])
        text_parts: list[str] = []
        content_types: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "unknown"))
            content_types.append(item_type)
            if item_type == "text":
                text_parts.append(str(item.get("text", "")))
            elif item_type == "image":
                text_parts.append(f"[imagem MCP: {item.get('mimeType', 'tipo desconhecido')}]")
            elif item_type == "resource":
                text_parts.append("[recurso MCP retornado]")
        return MCPToolResult(
            tool_name=name,
            text="\n".join(text_parts),
            is_error=bool(raw_result.get("isError", False)),
            content_types=tuple(content_types),
        )

    def request(self, method: str, params: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        if not self.running or self.process is None or self.process.stdin is None:
            raise MCPError("StudioMCP não está em execução.")
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        try:
            with self._send_lock:
                self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
            try:
                response = response_queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise MCPError(f"StudioMCP excedeu {timeout:.0f}s em {method}.") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

        if "error" in response:
            error = response["error"]
            if isinstance(error, dict):
                message = error.get("message", error)
            else:
                message = error
            raise MCPError(f"StudioMCP rejeitou {method}: {message}")
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
                        self.stderr_tail.append("StudioMCP filho não encerrou no prazo; nenhum kill forçado foi usado.")
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            for reader in (self._reader, self._stderr_reader):
                if reader is not None and reader is not threading.current_thread():
                    reader.join(timeout=1)
            self._reader = None
            self._stderr_reader = None

    def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = message.get("id")
            if isinstance(request_id, int):
                with self._pending_lock:
                    target = self._pending.get(request_id)
                if target is not None:
                    try:
                        target.put_nowait(message)
                    except queue.Full:
                        pass
            elif self.notification_callback is not None:
                self.notification_callback(message)
        failure = {"error": {"message": "StudioMCP encerrou a conexão."}}
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

    alternatives = schema.get("anyOf") or schema.get("oneOf")
    if isinstance(alternatives, list):
        if not any(not validate_json_schema(value, option, path) for option in alternatives):
            errors.append(f"{path} não corresponde a nenhuma alternativa aceita")
        return errors

    expected = schema.get("type")
    valid_type = True
    if expected == "object":
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
        return [f"{path} deveria ser {expected}"]

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} deve ser um de {schema['enum']}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key} é obrigatório")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child in value.items():
                if key in properties:
                    errors.extend(validate_json_schema(child, properties[key], f"{path}.{key}"))
                elif schema.get("additionalProperties") is False:
                    errors.append(f"{path}.{key} não é permitido")
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(validate_json_schema(item, schema["items"], f"{path}[{index}]"))
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            errors.append(f"{path} precisa de ao menos {schema['minItems']} itens")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            errors.append(f"{path} aceita no máximo {schema['maxItems']} itens")
    elif isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            errors.append(f"{path} é curto demais")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            errors.append(f"{path} é longo demais")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path} deve ser >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path} deve ser <= {schema['maximum']}")
    return errors
