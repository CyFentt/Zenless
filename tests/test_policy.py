from __future__ import annotations

import unittest

from zenless.models import ProposalAction
from zenless.policy import classify_action, validate_proposal

AVAILABLE = {"script_read", "multi_edit", "execute_luau", "start_stop_play", "skill"}


class PolicyTests(unittest.TestCase):
    def test_read_only_action_is_low_risk(self) -> None:
        result = classify_action(ProposalAction("script_read", {"target_file": "game.A"}), AVAILABLE)
        self.assertTrue(result.allowed)
        self.assertEqual(result.risk, "low")
        skill = classify_action(ProposalAction("skill", {"skill_name": "rbx-docs-search"}), AVAILABLE)
        self.assertTrue(skill.allowed)
        self.assertEqual(skill.risk, "low")

    def test_valid_multi_edit_is_allowed(self) -> None:
        action = ProposalAction(
            "multi_edit",
            {
                "file_path": "game.ServerScriptService.Main",
                "edits": [{"old_string": "local a = 1", "new_string": "local a = 2"}],
            },
        )
        result = classify_action(action, AVAILABLE)
        self.assertTrue(result.allowed)
        self.assertEqual(result.risk, "medium")

    def test_execute_luau_and_orchestrator_tools_are_blocked(self) -> None:
        self.assertFalse(classify_action(ProposalAction("execute_luau", {"code": "return 1"}), AVAILABLE).allowed)
        self.assertFalse(classify_action(ProposalAction("start_stop_play", {"is_start": True}), AVAILABLE).allowed)

    def test_destructive_source_is_blocked(self) -> None:
        action = ProposalAction(
            "multi_edit",
            {
                "file_path": "game.ServerScriptService.Main",
                "edits": [{"old_string": "return", "new_string": "workspace:ClearAllChildren()"}],
            },
        )
        result = classify_action(action, AVAILABLE)
        self.assertFalse(result.allowed)
        self.assertEqual(result.risk, "critical")

    def test_invalid_path_is_rejected(self) -> None:
        action = ProposalAction(
            "multi_edit",
            {"file_path": "Main", "edits": [{"old_string": "a", "new_string": "b"}]},
        )
        self.assertTrue(validate_proposal([action], AVAILABLE))


if __name__ == "__main__":
    unittest.main()
