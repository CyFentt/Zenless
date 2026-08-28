from __future__ import annotations

import io
import struct
import threading
import unittest

from zenless.native_host import NativeHostError, read_native_message, write_native_message


class NativeHostFramingTests(unittest.TestCase):
    def test_round_trip_frame(self) -> None:
        stream = io.BytesIO()
        payload = b'{"version":1}'
        write_native_message(stream, payload, threading.Lock())
        stream.seek(0)
        self.assertEqual(read_native_message(stream), payload)

    def test_eof_is_clean(self) -> None:
        self.assertIsNone(read_native_message(io.BytesIO()))

    def test_truncated_and_oversized_frames_are_rejected(self) -> None:
        with self.assertRaises(NativeHostError):
            read_native_message(io.BytesIO(struct.pack("<I", 10) + b"short"))
        with self.assertRaises(NativeHostError):
            read_native_message(io.BytesIO(struct.pack("<I", 3 * 1024 * 1024)))


if __name__ == "__main__":
    unittest.main()
