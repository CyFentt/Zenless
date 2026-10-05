from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Any

from installer import install
from installer.destinations import SchemeDictionaryDestination
from installer.sources import WheelFile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, cwd=ROOT)


def download(url: str, path: Path, digest: str) -> None:
    if not path.is_file() or sha256(path) != digest:
        temporary = path.with_suffix(path.suffix + ".partial")
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as target:
            shutil.copyfileobj(response, target)
        if sha256(temporary) != digest:
            temporary.unlink()
            raise ValueError(f"SHA-256 mismatch: {path.name}")
        temporary.replace(path)


def extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            destination = (target / item.filename).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise ValueError(f"Unsafe archive path: {item.filename}")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"Archive symlinks are unsupported: {item.filename}")
        source.extractall(target)


def install_wheel(archive: Path, site: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive) as source:
        metadata_path = next(name for name in source.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(source.read(metadata_path).decode("utf-8"))
        wheel_path = metadata_path.rsplit("/", 1)[0] + "/WHEEL"
        wheel = Parser().parsestr(source.read(wheel_path).decode("utf-8"))
        tags = wheel.get_all("Tag", [])
        if not any(tag.endswith(("-win_amd64", "-none-any")) for tag in tags):
            raise ValueError(f"Unsupported Windows wheel: {archive.name}")
        for name in source.namelist():
            if not (site / name).resolve().is_relative_to(site.resolve()):
                raise ValueError(f"Unsafe wheel path: {name}")
    python_root = site.parents[1]
    destination = SchemeDictionaryDestination(
        {
            "purelib": str(site), "platlib": str(site), "scripts": str(python_root / "Scripts"),
            "headers": str(python_root / "Include"), "data": str(python_root),
        },
        interpreter="runtime\\python\\python.exe",
        script_kind="win-amd64",
    )
    with WheelFile.open(archive) as source:
        source.validate_record(validate_contents=True)
        install(source, destination, additional_metadata={"INSTALLER": b"Rubra portable packaging"})
    return {
        "name": metadata["Name"],
        "version": metadata["Version"],
        "wheel": archive.name,
        "sha256": sha256(archive),
    }


def build(cache: Path, makensis: str, allow_dirty: bool) -> None:
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if status and not allow_dirty:
        raise RuntimeError("Commit source changes before building a release, or pass --allow-dirty for local QA.")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    version = (ROOT / "zenless" / "__init__.py").read_text().split('"')[1]
    manifest = json.loads((ROOT / "packaging" / "windows-runtime.json").read_text())
    dist = ROOT / "dist"
    package = dist / "Rubra"
    cache.mkdir(parents=True, exist_ok=True)
    if package.exists():
        shutil.rmtree(package)
    python_root = package / "runtime" / "python"
    python_archive = cache / "python.zip"
    download(manifest["python"]["url"], python_archive, manifest["python"]["sha256"])
    extract(python_archive, python_root)
    (python_root / "python314._pth").write_text(
        "python314.zip\n.\nLib\\site-packages\n..\\..\\app\nimport site\n", encoding="utf-8"
    )
    wheels = cache / "wheels"
    wheels.mkdir(exist_ok=True)
    missing = []
    for item in manifest["wheels"]:
        cached = wheels / item["filename"]
        if cached.is_file() and sha256(cached) != item["sha256"]:
            cached.unlink()
        if not cached.is_file():
            missing.append(item)
    if missing:
        lock = cache / "requirements-windows.lock"
        lock.write_text("\n".join(f"{item['name']}=={item['version']} --hash=sha256:{item['sha256']}" for item in missing))
        run([
            sys.executable, "-m", "pip", "download", "--no-deps", "--require-hashes", "--only-binary=:all:",
            "--platform", "win_amd64", "--python-version", "3.14", "--implementation", "cp", "--abi", "cp314",
            "--dest", str(wheels), "-r", str(lock),
        ])
    receipts = []
    for item in manifest["wheels"]:
        archive = wheels / item["filename"]
        if sha256(archive) != item["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {archive.name}")
        receipts.append(install_wheel(archive, python_root / "Lib" / "site-packages"))

    build_tools = cache / "build-tools"
    build_tools.mkdir(exist_ok=True)
    missing_build_tools = []
    for item in manifest["build_tools"]:
        cached = build_tools / item["filename"]
        if cached.is_file() and sha256(cached) != item["sha256"]:
            cached.unlink()
        if not cached.is_file():
            missing_build_tools.append(item)
    if missing_build_tools:
        build_lock = cache / "requirements-build-tools.lock"
        build_lock.write_text(
            "\n".join(
                f"{item['name']}=={item['version']} --hash=sha256:{item['sha256']}"
                for item in missing_build_tools
            ),
            encoding="utf-8",
        )
        run([
            sys.executable,
            "-m",
            "pip",
            "download",
            "--no-deps",
            "--require-hashes",
            "--only-binary=:all:",
            "--dest",
            str(build_tools),
            "-r",
            str(build_lock),
        ])
    for item in manifest["build_tools"]:
        archive = build_tools / item["filename"]
        if not archive.is_file() or sha256(archive) != item["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {archive.name}")

    build_env = cache / "source-build-env"
    if build_env.exists():
        shutil.rmtree(build_env)
    run([sys.executable, "-m", "venv", str(build_env)])
    build_python = build_env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    build_requirements = [f"{item['name']}=={item['version']}" for item in manifest["build_tools"]]
    run([
        str(build_python),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--no-deps",
        "--find-links",
        str(build_tools),
        *build_requirements,
    ])

    for item in manifest["source_wheels"]:
        archive = cache / item["filename"]
        download(item["url"], archive, item["sha256"])
        output = cache / "built-wheels" / item["name"]
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)
        run([
            str(build_python),
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--no-index",
            "--no-cache-dir",
            "--wheel-dir",
            str(output),
            str(archive),
        ])
        built = list(output.glob("*.whl"))
        if len(built) != 1:
            raise ValueError(f"Expected one source wheel: {item['name']}")
        receipt = install_wheel(built[0], python_root / "Lib" / "site-packages")
        if str(receipt["name"]).casefold().replace("_", "-") != str(item["name"]).casefold().replace("_", "-"):
            raise ValueError(f"Built source wheel name mismatch: {receipt['name']} != {item['name']}")
        if str(receipt["version"]) != str(item["version"]):
            raise ValueError(f"Built source wheel version mismatch: {receipt['version']} != {item['version']}")
        receipt["source_sha256"] = item["sha256"]
        receipts.append(receipt)
    app = package / "app"
    app.mkdir()
    shutil.copy2(ROOT / "main.py", app / "main.py")
    shutil.copytree(ROOT / "zenless", app / "zenless", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "assets", app / "assets", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    frontend = ROOT / "frontend" / "dist"
    if not (frontend / "index.html").is_file():
        raise FileNotFoundError("Build the production frontend before packaging.")
    shutil.copytree(frontend, app / "frontend" / "dist")
    for name in ("LICENSE", "NOTICE.md", "README.md", "RUBRA.md", "RELEASE_NOTES.md"):
        shutil.copy2(ROOT / name, package / name)
    shutil.copy2(ROOT / "packaging" / "NSIS-LICENSE.txt", package / "NSIS-LICENSE.txt")
    (package / "data").mkdir()
    (package / "START_HERE.txt").write_text(
        f"Rubra {version}\n\n"
        "Open Rubra.exe from this writable folder on 64-bit Windows 10 or later.\n"
        "Python is included. The first launch downloads the pinned toolchain and requires Internet access.\n"
        "Install Roblox Studio and open the place you want to develop.\n"
        "Enable Assistant > MCP Servers in Studio. Rubra selects the open place automatically.\n"
        "Complete provider logins inside Rubra; the Settings folder is optional for local files.\n"
        "Close hides Rubra in the tray while work continues. Use the tray menu to reopen or quit.\n"
        "Microsoft WebView2 may be installed during startup.\n"
        "Keep the complete folder together. Remove it to remove Rubra data and portable tools.\n"
        "Windows execution and live Studio/provider integration were not verified in the Linux packaging environment.\n"
        "See RELEASE_NOTES.md for validation status.\n", encoding="utf-8"
    )
    receipt = {
        "product": "Rubra", "version": version, "source_commit": revision, "source_dirty": bool(status),
        "target": "windows-x64", "python": manifest["python"], "dependencies": receipts,
        "source_build_tools": manifest["build_tools"],
        "windows_execution_verified": False,
    }
    (package / "release.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    prefix = "/" if os.name == "nt" else "-"
    run([makensis, f"{prefix}V2", f"{prefix}DVERSION={version}", f"{prefix}DOUTPUT={package / 'Rubra.exe'}", f"{prefix}DICON={ROOT / 'assets' / 'rubra.ico'}",
         str(ROOT / "packaging" / "launcher.nsi")])
    archive = dist / "Rubra-Windows.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                output.write(path, path.relative_to(dist).as_posix())
    run([makensis, f"{prefix}V2", f"{prefix}DVERSION={version}", f"{prefix}DPACKAGE={package}", f"{prefix}DICON={ROOT / 'assets' / 'rubra.ico'}",
         f"{prefix}DOUTPUT={dist / 'Rubra-Setup.exe'}", str(ROOT / "packaging" / "setup.nsi")])
    assets = [archive, dist / "Rubra-Setup.exe"]
    checksums = dist / "SHA256SUMS.txt"
    checksums.write_text("".join(f"{sha256(path)}  {path.name}\n" for path in assets), encoding="utf-8")
    for path in [*assets, checksums]:
        print(f"{path}: {path.stat().st_size:,} bytes")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=ROOT / "build" / "portable-cache")
    parser.add_argument("--makensis", default=shutil.which("makensis") or "makensis")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    build(args.cache.resolve(), args.makensis, args.allow_dirty)


if __name__ == "__main__":
    main()
