from __future__ import annotations

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from zenless.local_ai import LocalAIError, LocalAIService


def test_parallel_requests_share_one_serial_worker(tmp_path: Path):
    service = LocalAIService(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    second_entered = threading.Event()

    def complete(prompt, **kwargs):
        if prompt == "first":
            entered.set()
            assert release.wait(3)
        else:
            second_entered.set()
        return prompt

    with patch.object(service, "_complete", side_effect=complete), ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(service.complete, "first")
        assert entered.wait(3)
        second = workers.submit(service.complete, "second")
        try:
            assert not second_entered.wait(0.05)
        finally:
            release.set()
        assert first.result(3) == "first"
        assert second.result(3) == "second"


def test_cpu_fallback_explicitly_disables_gpu_and_uses_file_output(tmp_path: Path):
    service = LocalAIService(tmp_path)
    with patch("zenless.local_ai.subprocess.Popen") as start:
        service._start_candidate(tmp_path / "llama-server.exe", False)
    command = start.call_args.args[0]
    assert command[command.index("--n-gpu-layers") + 1] == "0"
    assert command[command.index("--host") + 1] == "127.0.0.1"
    output = start.call_args.kwargs["stdout"]
    assert output.name == str(tmp_path / "data" / "logs" / "local-ai.log")
    assert output.closed


def test_local_context_is_32k_and_large_prompt_compaction_preserves_contract_and_tail(tmp_path: Path):
    service = LocalAIService(tmp_path)
    with patch("zenless.local_ai.subprocess.Popen") as start:
        service._start_candidate(tmp_path / "llama-server.exe", False)
    command = start.call_args.args[0]
    assert command[command.index("--ctx-size") + 1] == "32768"

    prompt = "ROLE-CONTRACT\n" + ("middle-evidence\n" * 7000) + "LATEST-EVIDENCE"
    compacted = service._compact_prompt(prompt)
    assert len(compacted) <= service.MAX_PROMPT_CHARS
    assert compacted.startswith("ROLE-CONTRACT")
    assert compacted.endswith("LATEST-EVIDENCE")
    assert "RUBRA LOCAL CONTEXT COMPACTED" in compacted
    assert "sha256=" in compacted


def test_local_prompt_under_budget_is_not_modified(tmp_path: Path):
    service = LocalAIService(tmp_path)
    prompt = "Role: Reviewer.\nsmall evidence"
    assert service._compact_prompt(prompt) == prompt


def test_vulkan_failure_is_stopped_before_cpu_retry(tmp_path: Path):
    service = LocalAIService(tmp_path)
    service.model_path.parent.mkdir(parents=True)
    service.model_path.touch()
    gpu, cpu = tmp_path / "vulkan.exe", tmp_path / "cpu.exe"
    events = []
    with (
        patch.object(service, "_server_candidates", return_value=[(gpu, True), (cpu, False)]),
        patch.object(service, "_start_candidate", side_effect=lambda path, gpu: events.append((path, gpu))),
        patch.object(service, "_wait_until_ready", side_effect=[LocalAIError("VRAM unavailable"), None]),
        patch.object(service, "_stop_process", side_effect=lambda: events.append("stop")),
    ):
        service._ensure_started()
    assert events == [(gpu, True), "stop", (cpu, False)]


def test_startup_error_keeps_only_bounded_log_tail(tmp_path: Path):
    service = LocalAIService(tmp_path)
    service._log_path.parent.mkdir(parents=True)
    service._log_path.write_bytes(b"x" * 100_000 + b"GPU allocation failed")
    service._process = Mock()
    service._process.poll.return_value = 1
    with pytest.raises(LocalAIError, match="GPU allocation failed") as failure:
        service._wait_until_ready(1)
    assert len(str(failure.value)) < 3200


@pytest.mark.skipif(os.name == "nt", reason="POSIX fixture launcher; Windows binaries require platform smoke testing")
def test_large_server_logs_do_not_block_health_or_completion(tmp_path: Path):
    service = LocalAIService(tmp_path)
    executable = tmp_path / "llama-server.exe"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import argparse, json, sys\n"
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--port', type=int)\n"
        "options, _ = parser.parse_known_args()\n"
        "sys.stdout.write('x' * 1048576)\n"
        "sys.stdout.flush()\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200)\n"
        "        self.end_headers()\n"
        "        self.wfile.write(b'{}')\n"
        "    def do_POST(self):\n"
        "        self.rfile.read(int(self.headers['Content-Length']))\n"
        "        self.send_response(200)\n"
        "        self.end_headers()\n"
        "        self.wfile.write(json.dumps({'choices':[{'message':{'content':'Scout ready'}}]}).encode())\n"
        "HTTPServer(('127.0.0.1', options.port), Handler).serve_forever()\n"
    )
    executable.chmod(0o700)
    try:
        service._start_candidate(executable, False)
        service._wait_until_ready(3)
        assert service.complete("Inspect inventory") == "Scout ready"
        assert service._log_path.stat().st_size >= 1048576
    finally:
        process = service._process
        service.close()
    assert process is not None and process.poll() is not None
