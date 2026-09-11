from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import psutil
from playwright.sync_api import sync_playwright


def seed_fixtures(root: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from PIL import Image
    from test_glb_viewer import make_triangle_glb

    from zenless.models import Stage, TaskOptions
    from zenless.store import SQLiteStore

    store = SQLiteStore(root / "zenless.db")
    job_id = "validation-fixture"
    store.create_task(job_id, "Controlled visual and QA fixtures", TaskOptions())
    store.update_task(job_id, stage=Stage.COMPLETE, status="complete")
    store.append_message(job_id, "user", "user", "Controlled fixture data for release validation")
    visual: dict[str, object] = {"version": 1, "status": "APPROVED"}
    views = []
    for index, name in enumerate(("front", "back", "left", "right", "top", "bottom")):
        path = root / f"{name}.png"
        Image.new("RGB", (64, 64), (40 + index * 30, 80, 100)).save(path)
        store.register_asset(name, job_id=job_id, name=path.name, kind="VIEW", path=path, mime="image/png")
        visual[name] = {"asset_id": name}
        views.append({"name": name.upper(), "state": "APPROVED", "imageUrl": f"/api/assets/{name}/content"})
    store.update_context_section(job_id, "visual", visual)
    store.upsert_artifact("visual-v1", job_id, "IMAGE", "Visual fixture V1", "APPROVED", metadata={"views": views})
    model_path = root / "triangle.glb"
    make_triangle_glb(model_path)
    store.register_asset("triangle", job_id=job_id, name=model_path.name, kind="GLB", path=model_path, mime="model/gltf-binary")
    store.update_context_section(job_id, "model", {"asset_id": "triangle", "status": "APPROVED", "geometry_path": str(model_path), "texture_path": str(model_path)})
    store.upsert_artifact("model-v1", job_id, "MODEL_3D", "Model fixture V1", "APPROVED", model_url="/api/assets/triangle/content", metadata={"assetId": "triangle", "geometryStatus": "READY", "textureStatus": "READY"})
    store.create_test_run("fixture-run", job_id, "SMOKE", 1)
    store.append_test_case("fixture-case", run_id="fixture-run", job_id=job_id, name="Controlled failure", suite="PLAY", status="FAILED", severity="MEDIUM", details={"expected": "Pass", "actual": "Injected failure"}, duration_ms=1, started_at=1, finished_at=2)
    store.append_test_failure("fixture-failure", run_id="fixture-run", job_id=job_id, test_case_id="fixture-case", name="Controlled failure", suite="PLAY", severity="MEDIUM", message="Injected fixture failure", details={}, timestamp=2)
    store.finish_test_run("fixture-run", "FAILED", {"durationMs": 1})


def close_windows(process_ids: set[int]) -> None:
    def close(window: int, _parameter: int) -> bool:
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value in process_ids and ctypes.windll.user32.IsWindowVisible(window):
            ctypes.windll.user32.PostMessageW(window, 0x0010, 0, 0)
        return True

    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(close)
    ctypes.windll.user32.EnumWindows(callback, 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--fixtures", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("artifacts/final-validation/gui"))
    arguments = parser.parse_args()
    executable = arguments.executable.resolve(strict=True)
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    report: dict[str, object] = {"status": "FAILED", "executable": str(executable)}
    owned: dict[int, psutil.Process] = {}
    with tempfile.TemporaryDirectory(prefix="zenless-main-smoke-") as folder:
        if arguments.fixtures:
            seed_fixtures(Path(folder))
            report["fixture_evidence"] = True
        environment = dict(os.environ)
        environment["ZENLESS_DATA_ROOT"] = folder
        environment["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
            f"--remote-debugging-port={port} --remote-debugging-address=127.0.0.1"
        )
        started = time.perf_counter()
        process = subprocess.Popen([str(executable), "--no-provision"], env=environment)
        root = psutil.Process(process.pid)
        owned[root.pid] = root
        try:
            endpoint = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Application exited during startup: {process.returncode}")
                owned.update({child.pid: child for child in root.children(recursive=True)})
                try:
                    with urllib.request.urlopen(f"{endpoint}/json/version", timeout=1) as response:
                        if response.status == 200:
                            break
                except (OSError, TimeoutError):
                    time.sleep(0.25)
            else:
                raise TimeoutError("WebView2 debugging endpoint did not become available")
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(endpoint, timeout=30000)
                context = browser.contexts[0]
                deadline = time.monotonic() + 30
                page = None
                while time.monotonic() < deadline:
                    page = next((item for item in context.pages if item.url.startswith("http://127.0.0.1:")), None)
                    if page is not None:
                        break
                    time.sleep(0.1)
                if page is None:
                    raise RuntimeError("The native shell did not load the local bridge")
                errors: list[str] = []
                sockets: set[object] = set()
                page.on("pageerror", lambda error: errors.append(str(error)))

                def opened(connection: object) -> None:
                    sockets.add(connection)
                    connection.on("close", lambda: sockets.discard(connection))

                page.on("websocket", opened)
                page.add_init_script("window.validationSockets = []; const NativeSocket = window.WebSocket; window.WebSocket = class extends NativeSocket { constructor(...args) { super(...args); window.validationSockets.push(this); } };")
                page.reload()
                page.get_by_placeholder("Message Zenless").wait_for(timeout=60000)
                page.wait_for_function("document.querySelector('[aria-label=CHAT]').getAttribute('aria-current') === 'page'")
                report["startup_seconds"] = round(time.perf_counter() - started, 2)
                report["bridge_origin"] = page.url
                print("FROZEN_CHAT_READY", flush=True)
                snapshots = []
                for width, height in ((1420, 880), (1000, 650)):
                    page.set_viewport_size({"width": width, "height": height})
                    for name in ("CHAT", "HOME", "BUILD", "VISUAL", "EDITOR", "TEST", "SETTINGS"):
                        button = page.get_by_role("button", name=name, exact=True)
                        button.click()
                        page.wait_for_function(
                            "name => document.querySelector(`[aria-label=${name}]`).getAttribute('aria-current') === 'page'",
                            arg=name,
                        )
                        page.wait_for_timeout(250)
                        overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
                        if overflow:
                            raise RuntimeError(f"Horizontal overflow on {name} at {width}x{height}")
                        page.screenshot(path=str(output / f"{name.lower()}-{width}.png"))
                        snapshots.append(f"{name}:{width}x{height}")
                if arguments.fixtures:
                    page.get_by_role("button", name="VISUAL", exact=True).click()
                    page.wait_for_function("Array.from(document.images).filter(image => image.src.includes('/api/assets/')).length >= 6 && Array.from(document.images).filter(image => image.src.includes('/api/assets/')).every(image => image.complete && image.naturalWidth > 0)")
                    page.get_by_role("button", name="3D", exact=True).click()
                    page.locator("canvas").wait_for(timeout=30000)
                    page.wait_for_timeout(1500)
                    page.screenshot(path=str(output / "model-fixture.png"))
                    report["authorized_images_and_glb_canvas"] = "PASS"
                page.get_by_role("button", name="CHAT", exact=True).click()
                for _ in range(2):
                    page.reload()
                    page.get_by_placeholder("Message Zenless").wait_for(timeout=45000)
                    page.wait_for_timeout(500)
                    if len(sockets) != 1:
                        raise RuntimeError(f"Expected one live WebSocket after reload, found {len(sockets)}")
                page.evaluate("window.validationSockets.forEach(connection => connection.close())")
                page.wait_for_function("window.validationSockets.length > 1 && window.validationSockets.filter(connection => connection.readyState === WebSocket.OPEN).length === 1", timeout=30000)
                page.get_by_placeholder("Message Zenless").wait_for()
                if len(sockets) != 1:
                    raise RuntimeError("Reconnect left duplicate live WebSockets")
                report["websocket_reconnect"] = "PASS"
                provider_states = page.evaluate("async () => { const response = await fetch('/api/providers', {headers: {'X-Zenless-Token': localStorage.getItem('zenless_token')}}); if (!response.ok) throw new Error('Provider state query failed'); const providers = await response.json(); return providers.map(provider => ({id: provider.providerId, authState: provider.authState, support: provider.support})); }")
                report["provider_states"] = provider_states
                if arguments.fixtures and any(provider["authState"] == "READY" for provider in provider_states):
                    raise RuntimeError("A fresh profile reported an authenticated provider")
                report["screens"] = snapshots
                report["single_websocket_after_reloads"] = True
                report["javascript_errors"] = errors
                if errors:
                    raise RuntimeError("Uncaught frontend errors: " + " | ".join(errors))
                owned.update({child.pid: child for child in root.children(recursive=True)})
                report["process_count"] = len(owned)
                report["working_set_mib"] = round(sum(item.memory_info().rss for item in owned.values() if item.is_running()) / 1048576, 2)
                close_windows(set(owned))
                process.wait(timeout=45)
                if process.returncode != 0:
                    raise RuntimeError(f"Application exited with {process.returncode}")
                _, alive = psutil.wait_procs(list(owned.values()), timeout=10)
                if alive:
                    raise RuntimeError(f"Owned processes survived native close: {[item.pid for item in alive]}")
                report["clean_close"] = True
                report["status"] = "PASSED"
        except Exception as error:
            report["error"] = f"{type(error).__name__}: {error}"
        finally:
            for item in owned.values():
                try:
                    if item.is_running():
                        item.terminate()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(list(owned.values()), timeout=10)
            for item in alive:
                item.kill()
            psutil.wait_procs(alive, timeout=5)
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2), flush=True)
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
