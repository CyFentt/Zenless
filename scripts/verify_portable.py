from __future__ import annotations

import argparse
import json
import struct
from email.parser import Parser
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def verify(root: Path) -> dict[str, object]:
    receipt = json.loads((root / "release.json").read_text())
    for name in (
        "Rubra.exe", "app/main.py", "app/assets/toolchain.json", "app/frontend/dist/index.html",
        "runtime/python/python.exe", "runtime/python/pythonw.exe", "runtime/python/python314.dll",
        "runtime/python/python314.zip", "runtime/python/LICENSE.txt", "LICENSE", "NSIS-LICENSE.txt",
    ):
        if not (root / name).is_file():
            raise FileNotFoundError(name)
    paths = (root / "runtime/python/python314._pth").read_text().splitlines()
    if paths != ["python314.zip", ".", "Lib\\site-packages", "..\\..\\app", "import site"]:
        raise ValueError("The embedded interpreter search paths do not match the portable layout.")
    environment = default_environment()
    environment.update({
        "sys_platform": "win32", "os_name": "nt", "platform_system": "Windows", "platform_machine": "AMD64",
        "python_version": "3.14", "python_full_version": receipt["python"]["version"], "extra": "",
        "implementation_name": "cpython", "platform_python_implementation": "CPython",
    })
    site = root / "runtime/python/Lib/site-packages"
    metadata = [Parser().parsestr(path.read_text(encoding="utf-8")) for path in site.glob("*.dist-info/METADATA")]
    installed = {canonicalize_name(item["Name"]): item["Version"] for item in metadata}
    expected = {canonicalize_name(item["name"]): item["version"] for item in receipt["dependencies"]}
    if installed != expected:
        raise ValueError("Installed wheels do not match the release receipt.")
    for item in metadata:
        for value in item.get_all("Requires-Dist", []):
            dependency = Requirement(value)
            if dependency.marker and not dependency.marker.evaluate(environment):
                continue
            version = installed.get(canonicalize_name(dependency.name))
            if version is None or version not in dependency.specifier:
                raise ValueError(f"Unsatisfied Windows dependency: {item['Name']} requires {value}")
    machines: dict[str, int] = {}
    for path in root.rglob("*"):
        if path.suffix.lower() not in {".exe", ".dll", ".pyd"}:
            continue
        with path.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError(f"Invalid Windows binary: {path}")
            stream.seek(60)
            pe_offset = struct.unpack("<I", stream.read(4))[0]
            stream.seek(pe_offset)
            if stream.read(4) != b"PE\0\0":
                raise ValueError(f"Invalid PE header: {path}")
            machine = struct.unpack("<H", stream.read(2))[0]
        name = path.relative_to(root).as_posix()
        machines[name] = machine
        if path.suffix.lower() == ".pyd" and machine != 0x8664:
            raise ValueError(f"Non-x64 Python extension: {name}")
    for name in ("runtime/python/python.exe", "runtime/python/pythonw.exe", "runtime/python/python314.dll"):
        if machines[name] != 0x8664:
            raise ValueError(f"Non-x64 Python runtime: {name}")
    if any(path.is_file() for path in (root / "data").rglob("*")):
        raise ValueError("The release contains mutable user data.")
    return {
        "version": receipt["version"], "source_commit": receipt["source_commit"],
        "source_dirty": receipt["source_dirty"], "dependencies_checked": len(installed),
        "windows_binaries_checked": len(machines), "windows_execution_verified": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.folder.resolve()), indent=2))
