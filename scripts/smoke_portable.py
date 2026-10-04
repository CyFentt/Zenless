from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def smoke(root: Path) -> None:
    if os.name != "nt":
        raise RuntimeError("The portable smoke test requires Windows.")
    environment = dict(os.environ, RUBRA_HOME=str(root))
    subprocess.run(
        [str(root / "runtime/python/python.exe"), "-s", "-c",
         "import main, clr, webview, aiohttp, websockets, playwright.sync_api; "
         "from pathlib import Path; "
         "assert main._portable_root() == Path.cwd(); "
         "assert main._resource_root() == Path.cwd() / 'app'; "
         "print('PORTABLE_IMPORTS_OK')"],
        cwd=root, env=environment, check=True, timeout=60,
    )
    subprocess.run(
        [str(root / "Rubra.exe"), "--no-toolchain", "--no-provision", "--smoke-test"],
        cwd=root, env=environment, check=True, timeout=90,
    )
    print("PORTABLE_WINDOW_OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    smoke(args.folder.resolve())
