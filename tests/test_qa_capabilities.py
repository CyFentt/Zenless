from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from zenless.event_bus import EventBus
from zenless.models import TaskOptions
from zenless.qa_breaker import (
    MULTIPLAYER_HARNESS_PROTOCOL,
    PROFILES,
    QABreaker,
)
from zenless.qa_breaker import TestProfile as QAProfile
from zenless.static_quality import StaticCheck
from zenless.store import SQLiteStore
from zenless.studio_mcp import MCPError, MCPTool, MCPToolResult


def _tool(name: str, properties: dict[str, Any], required: list[str]) -> MCPTool:
    return MCPTool(
        name=name,
        description=f"Test schema for {name}",
        input_schema={
            "type": "object",
            "properties": {
                **properties,
                "studio_id": {"type": "string"},
            },
            "required": [*required, "studio_id"],
            "additionalProperties": False,
        },
    )


class _OfflineBridge:
    def wait_for_provider(self, _provider: str, timeout: float = 0.0) -> bool:
        return False

    def send_prompt(self, *_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("Offline provider must not be called")


class _CapabilityStudio:
    def __init__(self, *, marker: bool = False, capture_error: bool = False) -> None:
        self.marker = marker
        self.capture_error = capture_error
        self.calls: list[tuple[str, dict[str, Any], str]] = []
        datamodel = {"type": "string", "enum": ["Edit", "Client", "Server"]}
        self.tools = {
            "execute_luau": _tool(
                "execute_luau",
                {"code": {"type": "string"}, "datamodel_type": datamodel},
                ["code", "datamodel_type"],
            ),
            "screen_capture": _tool(
                "screen_capture",
                {"capture_id": {"type": "string"}},
                ["capture_id"],
            ),
            "script_grep": _tool(
                "script_grep",
                {"query": {"type": "string"}},
                ["query"],
            ),
            "start_stop_play": _tool(
                "start_stop_play",
                {"is_start": {"type": "boolean"}},
                ["is_start"],
            ),
        }

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        studio_id: str = "",
        timeout: float = 0,
    ) -> MCPToolResult:
        del timeout
        self.calls.append((name, dict(arguments), studio_id))
        if name == "start_stop_play":
            return MCPToolResult(name, "", False, ("text",))
        if name == "script_grep":
            if self.marker:
                text = f'ServerScriptService.ZenlessQAHarness:1: protocol = "{MULTIPLAYER_HARNESS_PROTOCOL}"'
            else:
                text = "No matches found"
            return MCPToolResult(name, text, False, ("text",))
        if name == "screen_capture":
            return MCPToolResult(
                name,
                "capture failed" if self.capture_error else "[image]",
                self.capture_error,
                ("text",) if self.capture_error else ("image",),
            )
        if name != "execute_luau":
            raise AssertionError(f"Unexpected tool: {name}")

        code = str(arguments["code"])
        if "CreateVirtualInput" in code:
            payload = {"ok": True, "probe": "Unknown key down/up", "stage": "send"}
        elif "ExecuteMultiplayerTestAsync" in code:
            match = re.search(r"ExecuteMultiplayerTestAsync\((\d+)", code)
            assert match is not None
            players = int(match.group(1))
            payload = {"ok": True, "protocol": MULTIPLAYER_HARNESS_PROTOCOL, "players": players}
        elif "GetResolutionAsync" in code:
            payload = {
                "ok": True,
                "original": {
                    "device": "default",
                    "width": 1920,
                    "height": 1080,
                    "orientation": "LandscapeLeft",
                    "density": 96,
                    "scaling": "Fit",
                },
                "readBack": {"width": 390, "height": 844, "orientation": "Portrait"},
            }
        else:
            payload = {"ok": True, "error": ""}
        return MCPToolResult(name, json.dumps(payload), False, ("text",))


class QACapabilityTests(unittest.TestCase):
    def test_static_checks_all_skipped_are_not_reported_as_passed(self) -> None:
        qa = self._qa(_CapabilityStudio())
        self.store.set_setting("ui.settings", {"projectRoot": self.temp.name})
        with patch.object(qa.static_quality, "run", return_value=[StaticCheck("StyLua", "SKIPPED", "Unavailable")]):
            self.assertEqual(qa._run_static_quality("job")[0], "SKIPPED")

    def test_playtest_requires_explicit_evidence_and_always_requests_cleanup(self) -> None:
        for text, expected in [
            ('{"passed": false, "summary": "Character fell through floor"}', "FAILED"),
            ('{"passed": true, "summary": "Spawn and movement observed", "failures": []}', "PASSED"),
            ("Unable to run this scenario", "SKIPPED"),
            ("", "SKIPPED"),
        ]:
            with self.subTest(text=text):
                studio = _CapabilityStudio()
                studio.tools["subagent"] = _tool("subagent", {
                    "type": {"type": "string", "enum": ["explore", "playtest"]},
                    "prompt": {"type": "string"},
                }, ["type", "prompt"])
                original_call = studio.call_tool

                def call(name: str, arguments: dict[str, Any], **kwargs: Any) -> MCPToolResult:
                    if name == "subagent":
                        return MCPToolResult(name, text, False, ("text",))
                    return original_call(name, arguments, **kwargs)

                qa = self._qa(studio)
                with patch.object(studio, "call_tool", side_effect=call):
                    self.assertEqual(qa._run_official_playtest_subagent("job", "studio-1", ["Move"])[0], expected)
                self.assertEqual(studio.calls[-1], ("start_stop_play", {"is_start": False}, "studio-1"))

    def test_playtest_timeout_still_stops_play(self) -> None:
        studio = _CapabilityStudio()
        studio.tools["subagent"] = _tool("subagent", {
            "type": {"type": "string", "enum": ["playtest"]},
            "prompt": {"type": "string"},
        }, ["type", "prompt"])
        original_call = studio.call_tool

        def call(name: str, arguments: dict[str, Any], **kwargs: Any) -> MCPToolResult:
            if name == "subagent":
                raise MCPError("Timed out")
            return original_call(name, arguments, **kwargs)

        qa = self._qa(studio)
        with patch.object(studio, "call_tool", side_effect=call):
            self.assertEqual(qa._run_official_playtest_subagent("job", "studio-1", ["Move"])[0], "FAILED")
        self.assertEqual(studio.calls[-1][1], {"is_start": False})

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(Path(self.temp.name) / "qa.db")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _qa(self, studio: _CapabilityStudio) -> QABreaker:
        return QABreaker(
            store=self.store,
            studio=studio,
            bridge=_OfflineBridge(),
            events=EventBus(),
            play_test_seconds=1,
        )

    def test_virtual_input_executes_bounded_noop_and_always_stops_play(self) -> None:
        studio = _CapabilityStudio()
        qa = self._qa(studio)

        with patch("zenless.qa_breaker.time.sleep"):
            status, _, actual = qa._run_virtual_input_smoke("studio-1")

        self.assertEqual(status, "PASSED")
        self.assertIn("no gameplay behavior was asserted", actual)
        play_states = [args["is_start"] for name, args, _ in studio.calls if name == "start_stop_play"]
        self.assertEqual(play_states, [True, False])
        execute = next(args for name, args, _ in studio.calls if name == "execute_luau")
        self.assertEqual(execute["datamodel_type"], "Client")
        self.assertIn("Enum.KeyCode.Unknown", execute["code"])

    def test_device_capture_failure_is_failed_and_original_state_is_restored(self) -> None:
        studio = _CapabilityStudio(capture_error=True)
        qa = self._qa(studio)

        status, _, _ = qa._run_device_emulator_smoke("studio-1", 123)

        self.assertEqual(status, "FAILED")
        execute_codes = [args["code"] for name, args, _ in studio.calls if name == "execute_luau"]
        self.assertEqual(len(execute_codes), 2)
        self.assertIn("SetResolutionAsync(390, 844)", execute_codes[0])
        self.assertIn("StopSimulationAsync", execute_codes[1])

    def test_multiplayer_is_skipped_without_exact_project_harness_marker(self) -> None:
        studio = _CapabilityStudio(marker=False)
        qa = self._qa(studio)

        status, _, actual = qa._run_multiplayer_test("studio-1", PROFILES["DEEP"], 99)

        self.assertEqual(status, "SKIPPED")
        self.assertIn("no multiplayer test was launched", actual)
        self.assertFalse(any(name == "execute_luau" for name, _, _ in studio.calls))
        self.assertEqual(qa._check_multiplayer_capability()[0], "SKIPPED")

    def test_multiplayer_runs_signed_harness_and_caps_clients_at_eight(self) -> None:
        studio = _CapabilityStudio(marker=True)
        qa = self._qa(studio)
        oversized = QAProfile("DEEP", 240.0, 18, 99, 5)

        status, _, actual = qa._run_multiplayer_test("studio-1", oversized, 42)

        self.assertEqual(status, "PASSED")
        self.assertIn("8 clients", actual)
        execute = next(args for name, args, _ in studio.calls if name == "execute_luau")
        self.assertIn("ExecuteMultiplayerTestAsync(8", execute["code"])
        self.assertIn("expectedPlayers = 8", execute["code"])
        self.assertEqual(studio.calls[-1][0:2], ("start_stop_play", {"is_start": False}))

    def test_qa_smart_routing_off_skips_local_scout_and_requires_web_text_provider(self) -> None:
        class RoutingBridge(_OfflineBridge):
            def __init__(self) -> None:
                self.web_checks: list[str] = []

            def wait_for_web_provider(self, provider: str, timeout: float = 0.0) -> bool:
                self.web_checks.append(provider)
                return provider == "chatgpt"

            def send_prompt(self, provider: str, prompt: str, *, task_id: str, timeout: float = 360.0) -> str:
                self.assert_provider = provider
                return '{"scenarios":["web-only scenario"]}'

        bridge = RoutingBridge()
        self.store.create_task("routing-off", "test routing", TaskOptions(smart_routing=False))
        local_calls: list[str] = []
        qa = QABreaker(
            store=self.store,
            studio=_CapabilityStudio(),
            bridge=bridge,
            events=EventBus(),
            play_test_seconds=1,
            local_ai_callback=lambda prompt: local_calls.append(prompt) or '{"scenarios":["local"]}',
        )

        scenarios = qa._ai_scenarios("routing-off", "feature", [], [])

        self.assertEqual(local_calls, [])
        self.assertEqual(scenarios, ["web-only scenario"])
        self.assertIn("chatgpt", bridge.web_checks)

    def test_validated_calls_reject_invalid_studio_id_before_dispatch(self) -> None:
        studio = _CapabilityStudio()
        qa = self._qa(studio)

        with self.assertRaises(MCPError):
            qa._call_validated(
                "start_stop_play",
                {"is_start": True},
                studio_id="",
                timeout=30,
            )
        self.assertEqual(studio.calls, [])


if __name__ == "__main__":
    unittest.main()
