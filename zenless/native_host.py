from __future__ import annotations

import json
import struct
import sys
import threading
from pathlib import Path
from typing import BinaryIO

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from .protocol import MAX_ENVELOPE_BYTES, ProtocolError, make_envelope, parse_envelope


class NativeHostError(RuntimeError):
    pass


def read_native_message(stream: BinaryIO) -> bytes | None:
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise NativeHostError("Incomplete Native Messaging header.")
    length = struct.unpack("<I", header)[0]
    if length <= 0 or length > MAX_ENVELOPE_BYTES:
        raise NativeHostError("Native Messaging payload is outside the allowed limit.")
    payload = stream.read(length)
    if len(payload) != length:
        raise NativeHostError("Truncated Native Messaging payload.")
    return payload


def write_native_message(stream: BinaryIO, payload: bytes, lock: threading.Lock) -> None:
    if len(payload) > MAX_ENVELOPE_BYTES:
        raise NativeHostError("Native Messaging response is outside the allowed limit.")
    with lock:
        stream.write(struct.pack("<I", len(payload)))
        stream.write(payload)
        stream.flush()


def run_native_host(runtime_file: Path) -> int:
    source = sys.stdin.buffer
    target = sys.stdout.buffer
    write_lock = threading.Lock()
    first = read_native_message(source)
    if first is None:
        return 0
    try:
        hello = parse_envelope(first)
    except ProtocolError:
        return 2

    try:
        runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
        host = str(runtime["host"])
        port = int(runtime["port"])
        token = str(runtime["token"])
    except OSError, KeyError, TypeError, ValueError, json.JSONDecodeError:
        error = (
            make_envelope(
                "agent.error",
                source="native-host",
                provider=hello.provider,
                reply_to=hello.id,
                payload={"error": "Zenless.exe is not open or the local runtime is unavailable."},
            )
            .to_json()
            .encode("utf-8")
        )
        write_native_message(target, error, write_lock)
        return 3

    uri = f"ws://{host}:{port}/native?token={token}"
    try:
        with connect(uri, open_timeout=8, close_timeout=3, max_size=MAX_ENVELOPE_BYTES) as websocket:
            websocket.send(first.decode("utf-8"))
            stopped = threading.Event()

            def downstream() -> None:
                try:
                    while not stopped.is_set():
                        message = websocket.recv()
                        encoded = message if isinstance(message, bytes) else message.encode("utf-8")
                        write_native_message(target, encoded, write_lock)
                except ConnectionClosed, OSError, NativeHostError:
                    pass
                finally:
                    stopped.set()

            reader = threading.Thread(target=downstream, name="Zenless-NativeHost-Down", daemon=True)
            reader.start()
            while not stopped.is_set():
                message = read_native_message(source)
                if message is None:
                    break
                parse_envelope(message)
                websocket.send(message.decode("utf-8"))
            stopped.set()
            websocket.close(1000, "Native host closed")
            reader.join(timeout=2)
        return 0
    except OSError, ConnectionClosed, TimeoutError, ProtocolError, NativeHostError:
        return 4


def main(runtime_file: Path | None = None) -> int:
    if runtime_file is None:
        base = Path.home() / "AppData" / "Local" / "Zenless"
        runtime_file = base / "runtime.json"
    return run_native_host(runtime_file)
