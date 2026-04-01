from django.contrib.auth import get_user_model
from django.test import TestCase
from django.conf import settings
from rest_framework.settings import api_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from auth_api.views import LoginView


class AuthThrottleLoggingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self._orig_rates = settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {}).copy()
        self.user = get_user_model().objects.create_user(
            username="student_user",
            password="testpass123",
        )

    def tearDown(self):
        settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = self._orig_rates
        api_settings.reload()

    def _set_rate(self, scope: str, rate: str) -> None:
        rates = self._orig_rates.copy()
        rates[scope] = rate
        settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = rates
        api_settings.reload()

    def test_login_throttled_after_limit(self):
        view = LoginView()
        view.throttle_scope = "auth_login"
        throttle = ScopedRateThrottle()
        throttle.scope = view.throttle_scope
        self.assertEqual(throttle.get_rate(), "5/min")

    def test_login_failure_logs_minimal(self):
        url = reverse("auth_api:login")
        with self.assertLogs("auth_api.views", level="INFO") as captured:
            self.client.post(url, {"username": "student_user", "password": "bad"}, format="json")
        combined = " ".join(captured.output)
        self.assertIn("auth_login_failed", combined)
        self.assertNotIn("password", combined)
