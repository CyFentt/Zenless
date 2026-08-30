from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="zenless-perf-") as folder:
        environment = dict(os.environ)
        environment["ZENLESS_DATA_ROOT"] = folder
        started = time.perf_counter()
        child = subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / "main.py"), "--smoke-test"],
            cwd=PROJECT_ROOT,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        process = psutil.Process(child.pid)
        peak_rss = 0
        peak_tree_rss = 0
        cpu_samples: list[float] = []
        while child.poll() is None:
            if time.perf_counter() - started > 30:
                raise TimeoutError("Zenless smoke test did not close cooperatively within 30 seconds")
            try:
                current_rss = process.memory_info().rss
                peak_rss = max(peak_rss, current_rss)
                descendants = process.children(recursive=True)
                tree_rss = current_rss + sum(item.memory_info().rss for item in descendants if item.is_running())
                peak_tree_rss = max(peak_tree_rss, tree_rss)
                cpu_samples.append(process.cpu_percent(interval=0.15))
            except psutil.NoSuchProcess, psutil.AccessDenied:
                break
        return_code = child.wait(timeout=5)
        elapsed = time.perf_counter() - started
        if return_code != 0:
            raise RuntimeError(f"Zenless smoke process exited with {return_code}")
        result = {
            "startup_and_idle_seconds": round(elapsed, 3),
            "peak_main_rss_mb": round(peak_rss / 1024 / 1024, 2),
            "peak_process_tree_rss_mb": round(peak_tree_rss / 1024 / 1024, 2),
            "average_main_cpu_percent": round(sum(cpu_samples) / max(1, len(cpu_samples)), 2),
            "samples": len(cpu_samples),
        }
        artifact = PROJECT_ROOT / "artifacts" / "performance-smoke.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
