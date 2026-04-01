from django.contrib.auth import get_user_model
from django.test import TestCase
from django.conf import settings
from rest_framework.settings import api_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle
from ai_agent.views import QueryView


class AIAgentThrottleLoggingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self._orig_rates = settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {}).copy()
        self.user = get_user_model().objects.create_user(
            username="agent_user",
            password="testpass123",
        )
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = self._orig_rates
        api_settings.reload()

    def _set_rate(self, scope: str, rate: str) -> None:
        rates = self._orig_rates.copy()
        rates[scope] = rate
        settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = rates
        api_settings.reload()

    def test_query_throttled(self):
        view = QueryView()
        view.throttle_scope = "ai_agent_query"
        throttle = ScopedRateThrottle()
        throttle.scope = view.throttle_scope
        self.assertEqual(throttle.get_rate(), "20/min")

    def test_query_logs_minimal(self):
        url = reverse("ai_agent:agent-query")
        payload = {"operation": "get_admin_payment_summary", "params": {}}
        with self.assertLogs("ai_agent.views", level="INFO") as captured:
            self.client.post(url, payload, format="json")
        combined = " ".join(captured.output)
        self.assertIn("ai_agent_query", combined)
        self.assertNotIn("token", combined)
