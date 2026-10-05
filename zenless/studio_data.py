from __future__ import annotations

import ctypes
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .studio_mcp import MCPError, MCPToolResult, json_values


@dataclass(frozen=True)
class TreeSnapshot:
    instances: list[dict[str, Any]]
    complete: bool
    total: int
    source: str


@dataclass(frozen=True)
class SourceSnapshot:
    scripts: list[dict[str, Any]]
    complete: bool
    total: int


def read_sources(studio: Any, studio_id: str, inventory: TreeSnapshot | None = None) -> SourceSnapshot:
    tools = getattr(studio, "tools", {})
    if isinstance(tools, dict) and "execute_luau" in tools:
        scripts: list[dict[str, Any]] = []
        total = -1
        for offset in range(0, 2000, 40):
            code = f"""local items = {{}}
for _, item in game:GetDescendants() do
    if item:IsA("LuaSourceContainer") then items[#items + 1] = item end
end
local sources = {{}}
for index = {offset + 1}, math.min({offset + 40}, #items) do
    local item = items[index]
    local ok, source = pcall(function() return item.Source end)
    sources[#sources + 1] = {{id = tostring(index), path = "game." .. item:GetFullName(), name = item.Name, className = item.ClassName, source = ok and source or "", readError = ok and "" or tostring(source)}}
end
return game:GetService("HttpService"):JSONEncode({{sources = sources, total = #items, offset = {offset}}})"""
            result = studio.call_tool(
                "execute_luau",
                supported_arguments(studio, "execute_luau", {"code": code, "datamodel_type": "Edit"}),
                studio_id=studio_id,
                timeout=20,
            )
            page = next(
                (
                    item
                    for item in result.json_payloads()
                    if isinstance(item, dict)
                    and isinstance(item.get("sources"), list)
                    and isinstance(item.get("total"), int)
                ),
                None,
            )
            if result.is_error or page is None or page.get("offset") != offset:
                raise MCPError("Live Studio source snapshot returned no valid source page.")
            if total >= 0 and total != page["total"]:
                raise MCPError("The script inventory changed during source collection. Retry the snapshot.")
            total = page["total"]
            chunk = page["sources"]
            if len(chunk) != min(40, max(0, total - offset)) or not all(
                isinstance(item, dict) and isinstance(item.get("source"), str) and isinstance(item.get("path"), str)
                for item in chunk
            ):
                raise MCPError("Live Studio source snapshot returned an incomplete source page.")
            scripts.extend(chunk)
            if len(scripts) >= total:
                return SourceSnapshot(scripts, True, total)
        return SourceSnapshot(scripts, False, total)
    inventory = inventory or read_tree(studio, studio_id)
    scripts = []
    candidates = [
        item
        for item in inventory.instances
        if (item.get("className") or item.get("ClassName") or item.get("class_name"))
        in {"Script", "LocalScript", "ModuleScript"}
    ]
    for item in candidates[:2000]:
        path = str(item.get("path") or item.get("fullPath") or item.get("full_path") or "")
        try:
            result = studio.call_tool(
                "script_read", {"target_file": path, "should_read_entire_file": True}, studio_id=studio_id, timeout=15
            )
            scripts.append({**item, "path": path, "source": script_source(result), "readError": ""})
        except MCPError as exc:
            scripts.append({**item, "path": path, "source": "", "readError": str(exc)})
    return SourceSnapshot(scripts, inventory.complete and len(candidates) <= 2000, len(candidates))


def export_sources(root: Path, studio_id: str, snapshot: SourceSnapshot) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "rubra-studio.json"
    try:
        previous = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        previous = {}
    files: list[str] = []
    mapping: dict[str, str] = {}
    for item in snapshot.scripts:
        if item.get("readError"):
            continue
        key = str(item.get("path")) + ":" + str(item.get("id", ""))
        name = "script_" + hashlib.sha256(key.encode()).hexdigest()[:24] + ".luau"
        temporary = (root / name).with_suffix(".tmp")
        temporary.write_text(item["source"], encoding="utf-8")
        temporary.replace(root / name)
        files.append(name)
        mapping[name] = str(item["path"])
    manifest = {
        "studio_id": studio_id,
        "files": files,
        "paths": mapping,
        "complete": snapshot.complete,
        "total": snapshot.total,
        "readable": len(files),
        "errors": [
            {"path": item["path"], "error": item.get("readError")} for item in snapshot.scripts if item.get("readError")
        ],
    }
    (root / 'selene.toml').write_text('std = "roblox"\n', encoding='utf-8')
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(marker)
    for name in previous.get("files", []):
        if (
            isinstance(name, str)
            and name not in files
            and Path(name).name == name
            and name.startswith("script_")
            and name.endswith(".luau")
        ):
            (root / name).unlink(missing_ok=True)
    return manifest


def active_studio_title() -> str:
    if os.name != "nt":
        return ""
    try:
        from ctypes import wintypes

        user = ctypes.WinDLL("user32", use_last_error=True)
        user.GetForegroundWindow.restype = wintypes.HWND
        user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        title = ctypes.create_unicode_buffer(2048)
        user.GetWindowTextW(user.GetForegroundWindow(), title, len(title))
        return title.value if "roblox studio" in title.value.casefold() else ""
    except OSError, AttributeError:
        return ""


def tree_instances(payload: Any) -> list[dict[str, Any]]:
    for _ in range(12):
        if isinstance(payload, str):
            payload = next(json_values(payload), None)
        if isinstance(payload, list):
            if all(
                isinstance(item, dict)
                and any(item.get(key) for key in ("name", "Name", "path", "Path", "fullPath", "full_path"))
                for item in payload
            ):
                return payload
            break
        if isinstance(payload, dict):
            if any(payload.get(key) for key in ("name", "Name", "path", "Path", "fullPath", "full_path")) and any(
                key in payload for key in ("className", "class_name", "ClassName", "children", "Children")
            ):
                return [payload]
            payload = next(
                (
                    payload[key]
                    for key in ("instances", "results", "tree", "nodes", "data", "result", "output")
                    if key in payload
                ),
                None,
            )
            continue
        break
    raise MCPError("Studio tree returned no readable instance list.")


def result_tree(result: MCPToolResult) -> list[dict[str, Any]]:
    if result.is_error:
        raise MCPError(result.compact(2000))
    for payload in result.json_payloads():
        try:
            return tree_instances(payload)
        except MCPError:
            continue
    raise MCPError("Studio tree response contained a summary or non-JSON text instead of instances.")


def supported_arguments(studio: Any, name: str, values: dict[str, Any]) -> dict[str, Any]:
    tools = getattr(studio, "tools", {})
    tool = tools.get(name) if isinstance(tools, dict) else None
    if tool is None:
        return values
    properties = tool.input_schema.get("properties", {})
    supported = {key: value for key, value in values.items() if key in properties}
    for key, value in supported.items():
        schema = properties[key]
        if isinstance(value, (int, float)) and isinstance(schema, dict):
            if isinstance(schema.get("maximum"), (int, float)):
                supported[key] = min(value, schema["maximum"])
    return supported


def read_tree(studio: Any, studio_id: str, *, max_nodes: int = 50_000) -> TreeSnapshot:
    tools = getattr(studio, "tools", {})
    empty_tree = False
    try:
        result = studio.call_tool(
            "search_game_tree",
            supported_arguments(
                studio, "search_game_tree", {"datamodel_type": "Edit", "max_depth": 20, "head_limit": 500}
            ),
            studio_id=studio_id,
            timeout=10,
        )
        instances = result_tree(result)
        empty_tree = not instances
    except MCPError:
        instances = []
    if not isinstance(tools, dict) or "execute_luau" not in tools:
        if instances or empty_tree:
            return TreeSnapshot(instances, False, len(instances), "search_game_tree")
        raise MCPError(
            "Studio tree is unavailable; the server returned no instance list and has no direct read capability."
        )
    all_instances: list[dict[str, Any]] = []
    total = -1
    for offset in range(0, max_nodes, 500):
        code = f"""local descendants = game:GetDescendants()
local identifiers = {{}}
for index, item in descendants do identifiers[item] = tostring(index) end
local instances = {{}}
for index = {offset + 1}, math.min({offset + 500}, #descendants) do
    local item = descendants[index]
    instances[#instances + 1] = {{id = tostring(index), parentId = identifiers[item.Parent] or "", name = item.Name, className = item.ClassName, path = "game." .. item:GetFullName()}}
end
return game:GetService("HttpService"):JSONEncode({{instances = instances, total = #descendants, offset = {offset}}})"""
        result = studio.call_tool(
            "execute_luau",
            supported_arguments(studio, "execute_luau", {"code": code, "datamodel_type": "Edit"}),
            studio_id=studio_id,
            timeout=15,
        )
        if result.is_error:
            raise MCPError(result.compact(2000))
        page = next(
            (
                payload
                for payload in result.json_payloads()
                if isinstance(payload, dict)
                and isinstance(payload.get("instances"), list)
                and isinstance(payload.get("total"), int)
            ),
            None,
        )
        if page is None or page.get("offset") != offset:
            raise MCPError("Direct Studio inventory returned an invalid page.")
        if total >= 0 and total != page["total"]:
            raise MCPError(
                "The Studio hierarchy changed during indexing. Rubra will retry without losing the connection."
            )
        total = page["total"]
        nodes = tree_instances(page)
        if len(nodes) != min(500, max(0, total - offset)):
            raise MCPError("Direct Studio inventory returned an incomplete page.")
        all_instances.extend(nodes)
        if offset + len(nodes) >= total:
            return TreeSnapshot(all_instances, True, total, "execute_luau")
    return TreeSnapshot(all_instances, False, total, "execute_luau")


def script_source(result: MCPToolResult) -> str:
    if result.is_error:
        raise MCPError(result.compact(2000))
    for payload in result.json_payloads():
        if isinstance(payload, dict):
            for key in ("source", "content", "code"):
                if isinstance(payload.get(key), str):
                    return payload[key]
    return result.text


def studio_edit_mode(result: MCPToolResult) -> bool | None:
    for payload in result.json_payloads():
        if not isinstance(payload, dict):
            continue
        for key in ("isPlaying", "is_playing", "playing"):
            if isinstance(payload.get(key), bool):
                return not payload[key]
        for key in ("mode", "state", "play_state", "playState", "studio_mode", "studioMode", "current_mode"):
            mode = payload.get(key)
            if isinstance(mode, str) and mode.casefold() in {
                "edit",
                "stop",
                "stopped",
                "play",
                "playing",
                "run",
                "running",
                "paused",
                "start_play",
                "run_server",
            }:
                return mode.casefold() in {"edit", "stop", "stopped"}
    if "current studio mode: edit" in result.text.casefold():
        return True
    if "current studio mode: play" in result.text.casefold():
        return False
    return None


def read_scene(studio: Any, studio_id: str, expected: dict[str, Any], *, verify: bool = False) -> dict[str, Any]:
    encoded = json.dumps(json.dumps(expected, ensure_ascii=False), ensure_ascii=False)
    code = f"""local HttpService = game:GetService("HttpService")
local targets = HttpService:JSONDecode({encoded})
local observed, missing, failures = {{}}, {{}}, {{}}
local function normalize(value)
    local kind = typeof(value)
    if kind == "Vector3" then return {{value.X, value.Y, value.Z}} end
    if kind == "Color3" then return {{value.R, value.G, value.B}} end
    if kind == "Vector2" then return {{value.X, value.Y}} end
    if kind == "CFrame" then return {{value:GetComponents()}} end
    if kind == "EnumItem" then return value.Name end
    if kind == "Instance" then return "game." .. value:GetFullName() end
    if kind == "string" or kind == "number" or kind == "boolean" then return value end
    return tostring(value)
end
local function equal(actual, wanted)
    if type(actual) == "number" and type(wanted) == "number" then return math.abs(actual - wanted) < 0.00001 end
    if type(actual) == "table" and type(wanted) == "table" then
        if #actual ~= #wanted then return false end
        for key, value in wanted do if not equal(actual[key], value) then return false end end
        return true
    end
    return actual == wanted
end
for path, properties in targets do
    local node = game
    local first = true
    for segment in string.gmatch(path, "[^%.]+") do
        if first then first = false else
            local matches = {{}}
            if node then for _, child in node:GetChildren() do if child.Name == segment then matches[#matches + 1] = child end end end
            node = #matches == 1 and matches[1] or nil
        end
    end
    if not node then missing[#missing + 1] = path else
        observed[path] = {{}}
        for property, wanted in properties do
            local ok, actual = pcall(function() return normalize(node[property]) end)
            if ok then observed[path][property] = actual end
            if not ok or not equal(actual, wanted) then failures[#failures + 1] = path .. ":" .. property end
        end
    end
end
return HttpService:JSONEncode({{observed = observed, missing = missing, failures = failures}})"""
    result = studio.call_tool(
        "execute_luau",
        supported_arguments(studio, "execute_luau", {"code": code, "datamodel_type": "Edit"}),
        studio_id=studio_id,
        timeout=20,
    )
    if result.is_error:
        raise MCPError(result.compact(3000))
    payload = next(
        (
            item
            for item in result.json_payloads()
            if isinstance(item, dict)
            and (isinstance(item.get("observed"), dict) or item.get("observed") == [])
            and (isinstance(item.get("missing"), list) or item.get("missing") == {})
            and (isinstance(item.get("failures"), list) or item.get("failures") == {})
        ),
        None,
    )
    if payload is None:
        raise MCPError("Studio scene read-back returned no verifiable properties.")
    payload = {"observed": payload["observed"] or {}, "missing": payload["missing"] or [], "failures": payload["failures"] or []}
    if verify and (payload["missing"] or payload["failures"]):
        raise MCPError(
            "Scene read-back did not match the expected instance properties: "
            + json.dumps(payload, ensure_ascii=False)[:3000]
        )
    return payload
