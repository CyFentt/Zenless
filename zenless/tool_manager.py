from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .attachments import ArchiveExtractor


class ToolError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ToolManifest:
    id: str
    name: str
    purpose: str
    version: str
    source: str
    license: str
    download_size: int
    installed_size: int
    checksum: str
    trust_level: str
    update_policy: str = "MANUAL"
    archive: bool = False


class ToolManager:
    def __init__(self, root: Path, manifests: tuple[ToolManifest, ...] = ()) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifests = {manifest.id: manifest for manifest in manifests}
        self.state_path = self.root / "tools.json"
        self._state = self._load_state()

    def catalog(self) -> list[dict[str, object]]:
        result = []
        for tool_id in sorted(self.manifests):
            manifest = self.manifests[tool_id]
            state = self._state.get(tool_id, {})
            target = self.root / tool_id
            installed = target.is_dir() and bool(state.get("installedAt"))
            result.append(
                {
                    **asdict(manifest),
                    "downloadSize": manifest.download_size,
                    "installedSize": self._size(target) if installed else manifest.installed_size,
                    "trustLevel": manifest.trust_level,
                    "updatePolicy": manifest.update_policy,
                    "status": "INSTALLED"
                    if installed
                    else ("AVAILABLE" if self._installable(manifest) else "ON_DEMAND"),
                    "lastUsed": state.get("lastUsed"),
                    "installedAt": state.get("installedAt"),
                }
            )
        return result

    def install(self, tool_id: str) -> dict[str, object]:
        manifest = self._manifest(tool_id)
        if not self._installable(manifest):
            raise ToolError("This tool has no verified pinned package configured for automatic installation.")
        target = (self.root / tool_id).resolve()
        self._require_owned(target)
        if target.exists():
            return self.status(tool_id)
        staging = (self.root / f".{tool_id}-{int(time.time() * 1000)}.part").resolve()
        self._require_owned(staging)
        request = Request(manifest.source, headers={"User-Agent": "Zenless/2.0"})
        try:
            with urlopen(request, timeout=90) as response, staging.open("xb") as output:
                hasher = hashlib.sha256()
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if manifest.download_size and total > manifest.download_size * 2:
                        raise ToolError("The tool download exceeded its manifest size bound.")
                    hasher.update(chunk)
                    output.write(chunk)
            if hasher.hexdigest().casefold() != manifest.checksum.casefold():
                raise ToolError("The tool package checksum does not match its pinned manifest.")
            if manifest.archive:
                ArchiveExtractor().extract(staging, target)
                staging.unlink(missing_ok=True)
            else:
                target.mkdir(parents=True)
                staging.replace(target / Path(urlparse(manifest.source).path).name)
            self._state[tool_id] = {"installedAt": self._now(), "lastUsed": None, "version": manifest.version}
            self._save_state()
            return self.status(tool_id)
        except Exception:
            staging.unlink(missing_ok=True)
            if target.exists() and self._require_owned(target):
                shutil.rmtree(target, ignore_errors=True)
            raise

    def remove(self, tool_id: str) -> dict[str, object]:
        self._manifest(tool_id)
        target = (self.root / tool_id).resolve()
        self._require_owned(target)
        if target.is_dir():
            shutil.rmtree(target)
        self._state.pop(tool_id, None)
        self._save_state()
        return self.status(tool_id)

    def status(self, tool_id: str) -> dict[str, object]:
        return next(item for item in self.catalog() if item["id"] == tool_id)

    def touch(self, tool_id: str) -> None:
        self._manifest(tool_id)
        state = self._state.setdefault(tool_id, {})
        state["lastUsed"] = self._now()
        self._save_state()

    def _manifest(self, tool_id: str) -> ToolManifest:
        try:
            return self.manifests[tool_id]
        except KeyError as exc:
            raise ToolError("Unknown optional tool.") from exc

    def _load_state(self) -> dict[str, dict[str, object]]:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            return {}
        return (
            {str(key): dict(value) for key, value in raw.items() if isinstance(value, dict)}
            if isinstance(raw, dict)
            else {}
        )

    def _save_state(self) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._state, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        temporary.replace(self.state_path)

    def _require_owned(self, path: Path) -> bool:
        if path == self.root or self.root not in path.parents:
            raise ToolError("Optional tool path escaped Zenless storage.")
        return True

    @staticmethod
    def _installable(manifest: ToolManifest) -> bool:
        parsed = urlparse(manifest.source)
        return parsed.scheme == "https" and len(manifest.checksum) == 64 and bool(manifest.version)

    @staticmethod
    def _size(root: Path) -> int:
        if not root.exists():
            return 0
        return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


DEFAULT_TOOL_MANIFESTS = (
    ToolManifest("git", "Git", "Repository workflows", "", "https://git-scm.com/", "GPL-2.0", 0, 0, "", "OFFICIAL"),
    ToolManifest(
        "stylua",
        "StyLua",
        "Luau formatting",
        "",
        "https://github.com/JohnnyMorganz/StyLua",
        "MPL-2.0",
        0,
        0,
        "",
        "OFFICIAL",
    ),
    ToolManifest(
        "selene", "Selene", "Luau linting", "", "https://github.com/Kampfkarren/selene", "MPL-2.0", 0, 0, "", "OFFICIAL"
    ),
    ToolManifest(
        "luau-lsp",
        "Luau LSP",
        "Luau analysis",
        "",
        "https://github.com/JohnnyMorganz/luau-lsp",
        "MIT",
        0,
        0,
        "",
        "OFFICIAL",
    ),
    ToolManifest(
        "luau-analyze",
        "Luau Analyze",
        "Static Luau analysis",
        "",
        "https://github.com/luau-lang/luau",
        "MIT",
        0,
        0,
        "",
        "OFFICIAL",
    ),
    ToolManifest(
        "rokit",
        "Rokit",
        "Project-scoped toolchain management",
        "",
        "https://github.com/rojo-rbx/rokit",
        "MIT",
        0,
        0,
        "",
        "OFFICIAL",
    ),
    ToolManifest(
        "lune",
        "Lune",
        "Standalone Luau automation",
        "",
        "https://github.com/lune-org/lune",
        "MIT",
        0,
        0,
        "",
        "OFFICIAL",
    ),
    ToolManifest(
        "rojo",
        "Rojo",
        "Filesystem project synchronization",
        "",
        "https://github.com/rojo-rbx/rojo",
        "MPL-2.0",
        0,
        0,
        "",
        "OFFICIAL",
    ),
    ToolManifest(
        "wally",
        "Wally",
        "Package management",
        "",
        "https://github.com/UpliftGames/wally",
        "MPL-2.0",
        0,
        0,
        "",
        "OFFICIAL",
    ),
    ToolManifest(
        "jest-roblox",
        "Jest Roblox",
        "Pure module testing",
        "",
        "https://github.com/Roblox/jest-roblox",
        "MIT",
        0,
        0,
        "",
        "OFFICIAL",
    ),
    ToolManifest(
        "advanced-studio-mcp",
        "Advanced Studio MCP",
        "On-demand multiplayer and profiling diagnostics",
        "",
        "https://github.com/Chrrxs/robloxstudio-mcp",
        "MIT",
        0,
        0,
        "",
        "COMMUNITY",
    ),
    ToolManifest(
        "7zip", "7-Zip", "Optional archive extraction", "", "https://www.7-zip.org/", "LGPL-2.1", 0, 0, "", "OFFICIAL"
    ),
    ToolManifest(
        "osv-scanner",
        "OSV-Scanner",
        "Dependency vulnerability scanning",
        "",
        "https://github.com/google/osv-scanner",
        "Apache-2.0",
        0,
        0,
        "",
        "OFFICIAL",
    ),
    ToolManifest(
        "blender", "Blender", "Optional 3D workflows", "", "https://www.blender.org/", "GPL-3.0", 0, 0, "", "OFFICIAL"
    ),
)
