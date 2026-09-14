from __future__ import annotations

import unittest

from zenless.agent_gateway import AgentGateway
from zenless.core import ZenlessCore
from zenless.managed_browser import ManagedBrowserController
from zenless.provider_failures import ProviderAvailability, classify_provider_failure, failure_from_error


class ProviderFailureTests(unittest.TestCase):
    def test_quota_exhaustion_is_actionable(self) -> None:
        failure = classify_provider_failure("You have reached your usage limit for this model")

        self.assertIsNotNone(failure)
        assert failure is not None
        self.assertEqual(failure.state, ProviderAvailability.QUOTA_EXHAUSTED)
        self.assertIn("Select another available model", failure.message)

    def test_rate_limit_is_distinct_from_quota(self) -> None:
        failure = classify_provider_failure("Too many requests. Try again in 42 seconds.")

        self.assertIsNotNone(failure)
        assert failure is not None
        self.assertEqual(failure.state, ProviderAvailability.RATE_LIMITED)

    def test_model_unavailable_is_distinct(self) -> None:
        failure = classify_provider_failure("The selected model is currently unavailable")

        self.assertIsNotNone(failure)
        assert failure is not None
        self.assertEqual(failure.state, ProviderAvailability.MODEL_UNAVAILABLE)

    def test_normal_response_is_not_a_failure(self) -> None:
        self.assertIsNone(classify_provider_failure("The implementation is ready for review."))

    def test_structured_bridge_error_round_trips(self) -> None:
        failure = failure_from_error("QUOTA_EXHAUSTED: Select another model.")

        self.assertIsNotNone(failure)
        assert failure is not None
        self.assertEqual(failure.state, ProviderAvailability.QUOTA_EXHAUSTED)
        self.assertEqual(failure.message, "Select another model.")

    def test_authentication_remains_ready_during_quota_failure(self) -> None:
        self.assertEqual(ZenlessCore._provider_auth_state("Quota Exhausted").value, "READY")
        self.assertEqual(
            ZenlessCore._provider_availability_state("Quota Exhausted"),
            ProviderAvailability.QUOTA_EXHAUSTED,
        )
        self.assertEqual(ZenlessCore._normalize_connection("Quota Exhausted"), "ERR")
        self.assertTrue(AgentGateway._status_availability_failure({"state": "Quota Exhausted"}))
        self.assertTrue(ManagedBrowserController._is_availability_failure("RATE_LIMITED"))


if __name__ == "__main__":
    unittest.main()
