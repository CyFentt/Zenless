from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen

WEBVIEW2_BOOTSTRAPPER_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"


class ProvisioningError(RuntimeError):
    pass


def find_webview2_runtime() -> Path | None:
    roots = {
        Path(value)
        for value in (
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("PROGRAMFILES"),
            os.environ.get("LOCALAPPDATA"),
        )
        if value
    }
    candidates: list[Path] = []
    for root in roots:
        base = root / "Microsoft" / "EdgeWebView" / "Application"
        if not base.is_dir():
            continue
        candidates.extend(path for path in base.glob("*/msedgewebview2.exe") if path.is_file())
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def ensure_webview2(resource_root: Path, data_root: Path) -> Path:
    existing = find_webview2_runtime()
    if existing is not None:
        return existing

    bundled = resource_root / "vendor" / "MicrosoftEdgeWebview2Setup.exe"
    temporary = data_root / "provisioning" / "MicrosoftEdgeWebview2Setup.exe"
    installer = bundled if bundled.is_file() else temporary
    if not installer.is_file():
        temporary.parent.mkdir(parents=True, exist_ok=True)
        partial = temporary.with_suffix(".download")
        request = Request(WEBVIEW2_BOOTSTRAPPER_URL, headers={"User-Agent": "Zenless/2.0"})
        try:
            with urlopen(request, timeout=60) as response, partial.open("wb") as stream:
                shutil.copyfileobj(response, stream, length=1024 * 1024)
            partial.replace(temporary)
        except Exception as exc:
            partial.unlink(missing_ok=True)
            raise ProvisioningError(f"Não foi possível baixar o runtime WebView2 oficial: {exc}") from exc

    _verify_microsoft_signature(installer)
    completed = subprocess.run(
        [str(installer), "/silent", "/install"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if completed.returncode not in {0, 3010}:
        raise ProvisioningError(
            f"Instalação automática do WebView2 falhou ({completed.returncode}): {completed.stdout[-2000:]}"
        )
    installed = find_webview2_runtime()
    if installed is None:
        raise ProvisioningError("O instalador terminou, mas o WebView2 Runtime não foi detectado.")
    return installed


def _verify_microsoft_signature(path: Path) -> None:
    environment = dict(os.environ)
    environment["ZENLESS_VERIFY_FILE"] = str(path.resolve())
    command = (
        "$s=Get-AuthenticodeSignature -LiteralPath $env:ZENLESS_VERIFY_FILE; "
        "if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Microsoft'){exit 7}"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if result.returncode != 0:
        raise ProvisioningError("O instalador WebView2 não possui assinatura Microsoft válida.")
