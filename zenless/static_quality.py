from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StaticCheck:
    name: str
    status: str
    output: str


class StaticQualityRunner:
    def __init__(self, portable_root: Path) -> None:
        self.portable_root = portable_root.resolve()
        self.runtime_root = self.portable_root / "runtime"

    def run(
        self,
        project_root: Path,
        *,
        timeout: float = 180.0,
        cancel_event: threading.Event | None = None,
    ) -> list[StaticCheck]:
        project = project_root.resolve()
        files = self._luau_files(project)
        if not files:
            return [StaticCheck("Luau source discovery", "SKIPPED", "No .luau or .lua files were found.")]
        checks: list[StaticCheck] = []
        if cancel_event is not None and cancel_event.is_set():
            return checks
        stylua = self._tool("stylua", "stylua.exe")
        if stylua is not None:
            checks.append(self._run_command("StyLua check", [str(stylua), "--check", str(project)], project, timeout, cancel_event))
            if cancel_event is not None and cancel_event.is_set():
                return checks
        else:
            checks.append(StaticCheck("StyLua check", "SKIPPED", "StyLua is not installed."))

        selene = self._tool("selene", "selene.exe")
        has_selene_config = any((project / name).is_file() for name in ("selene.toml", "selene.yml", "selene.yaml"))
        if selene is not None and has_selene_config:
            checks.append(self._run_command("Selene lint", [str(selene), str(project)], project, timeout, cancel_event))
            if cancel_event is not None and cancel_event.is_set():
                return checks
        elif selene is None:
            checks.append(StaticCheck("Selene lint", "SKIPPED", "Selene is not installed."))
        else:
            checks.append(StaticCheck("Selene lint", "SKIPPED", "No Selene project configuration exists."))

        rojo = self._tool("rojo", "rojo.exe")
        project_file = project / "default.project.json"
        if rojo is not None and project_file.is_file():
            qa_root = self.portable_root / "data" / "qa-static"
            qa_root.mkdir(parents=True, exist_ok=True)
            target = qa_root / "rubra-build.rbxlx"
            check = self._run_command(
                "Rojo build",
                [str(rojo), "build", str(project_file), "--output", str(target)],
                project,
                timeout,
                cancel_event,
            )
            checks.append(check)
            target.unlink(missing_ok=True)
            if cancel_event is not None and cancel_event.is_set():
                return checks
        elif rojo is None:
            checks.append(StaticCheck("Rojo build", "SKIPPED", "Rojo is not installed."))
        else:
            checks.append(StaticCheck("Rojo build", "SKIPPED", "default.project.json is not present."))

        luau_lsp = self._tool("luau-lsp", "luau-lsp.exe")
        has_luau_config = (project / ".luaurc").is_file() or (project / "sourcemap.json").is_file()
        if luau_lsp is not None and has_luau_config:
            command = [str(luau_lsp), "analyze"]
            if (project / "sourcemap.json").is_file():
                command.extend(["--sourcemap", str(project / "sourcemap.json")])
            command.append(str(project))
            result = self._run_command("Luau LSP analyze", command, project, timeout, cancel_event)
            if result.status == "FAILED":
                result = StaticCheck(result.name, "WARNING", result.output)
            checks.append(result)
            if cancel_event is not None and cancel_event.is_set():
                return checks
        elif luau_lsp is None:
            checks.append(StaticCheck("Luau LSP analyze", "SKIPPED", "Luau Language Server is not installed."))
        else:
            checks.append(StaticCheck("Luau LSP analyze", "SKIPPED", "No .luaurc or sourcemap.json is present."))

        lune = self._tool("lune", "lune.exe")
        test_runner = project / "tests" / "run_tests.luau"
        if lune is not None and test_runner.is_file():
            checks.append(
                self._run_command(
                    "Lune project tests",
                    [str(lune), "run", str(test_runner)],
                    project,
                    max(timeout, 300.0),
                    cancel_event,
                )
            )
        elif lune is None:
            checks.append(StaticCheck("Lune project tests", "SKIPPED", "Lune is not installed."))
        else:
            checks.append(StaticCheck("Lune project tests", "SKIPPED", "tests/run_tests.luau is not present."))

        return checks

    def _tool(self, tool_id: str, executable: str) -> Path | None:
        root = self.runtime_root / "tools" / tool_id
        direct = root / executable
        if direct.is_file():
            return direct
        return next(root.rglob(executable), None) if root.exists() else None

    @staticmethod
    def _luau_files(project: Path) -> list[Path]:
        ignored = {".git", ".venv", "node_modules", "Packages", "DevPackages", "dist", "build"}
        result: list[Path] = []
        for root, dirs, files in os.walk(project):
            dirs[:] = [name for name in dirs if name not in ignored and not name.startswith(".rubra")]
            for name in files:
                if name.casefold().endswith((".luau", ".lua")):
                    result.append(Path(root) / name)
                    if len(result) >= 10000:
                        return result
        return result

    @staticmethod
    def _run_command(
        name: str,
        command: list[str],
        cwd: Path,
        timeout: float,
        cancel_event: threading.Event | None = None,
    ) -> StaticCheck:
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            return StaticCheck(name, "FAILED", str(exc))

        deadline = time.monotonic() + max(10.0, min(600.0, timeout))
        output = ""
        while True:
            if cancel_event is not None and cancel_event.is_set():
                process.terminate()
                try:
                    output, _ = process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        output, _ = process.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        output = ""
                return StaticCheck(name, "FAILED", "Cancelled.\n" + output[-12000:])
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                try:
                    output, _ = process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    output = ""
                return StaticCheck(name, "FAILED", "Timed out.\n" + output[-12000:])
            try:
                output, _ = process.communicate(timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired:
                continue

        output = output[-12000:].strip()
        return StaticCheck(name, "PASSED" if process.returncode == 0 else "FAILED", output or f"Exit code {process.returncode}")
