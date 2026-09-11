import os
import re
import uuid
from pathlib import Path

build_id = os.environ.get("ZENLESS_BUILD_ID", "").strip().casefold() or uuid.uuid4().hex
if not re.fullmatch(r"[0-9a-f]{32}", build_id):
    raise ValueError("ZENLESS_BUILD_ID must contain 32 hexadecimal characters.")
build_id_path = Path("build/generated/zenless-build-id")
build_id_path.parent.mkdir(parents=True, exist_ok=True)
build_id_path.write_text(build_id, encoding="ascii")

datas = [
    ("frontend/dist", "frontend/dist"),
    (str(build_id_path), "."),
]
documents = (
    "README.md",
    "ARCHITECTURE.md",
    "BACKEND_REQUIREMENTS.md",
    "INSTALLATION_ARCHITECTURE.md",
    "PROVIDER_ARCHITECTURE.md",
    "QA_ARCHITECTURE.md",
    "RELEASE_NOTES.md",
    "TOOLS_ARCHITECTURE.md",
    "NOTICE.md",
    "LICENSE",
)
datas.extend((document, ".") for document in documents if os.path.exists(document))
if os.path.exists("assets"):
    datas.append(("assets", "assets"))
if os.path.exists("vendor"):
    datas.append(("vendor", "vendor"))

exe_options = {
    "uac_admin": False,
    "uac_uiaccess": False,
}
if os.path.exists("assets/zenless.ico"):
    exe_options["icon"] = ["assets/zenless.ico"]
if os.path.exists("assets/version_info.txt"):
    exe_options["version"] = "assets/version_info.txt"

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "clr",
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "websockets.sync.client",
        "websockets.sync.server",
        "aiohttp",
        "aiohttp.web",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "cefpython3",
        "gi",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "tkinter",
        "_tkinter",
        "tcl",
        "tk",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Zenless",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    **exe_options,
)
