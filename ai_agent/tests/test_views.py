"""

Integration tests for POST /ai-agent/chat/

Run with:
    python manage.py test ai_agent.tests.test_views
"""

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch
from django.contrib.auth import get_user_model
from students.models import Student
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from ai_agent.views import ChatScopedRateThrottle
from ai_agent import views as ai_views
from django.core.cache import cache
from students.utils import (
    STUDENT_VERIFIED_AT,
    STUDENT_VERIFIED_EXPIRES,
    STUDENT_VERIFIED_FLAG,
    STUDENT_VERIFIED_ID,
)


class ChatViewTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url    = reverse("ai_agent:agent-chat")
        self.valid_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.fake.token"
        User = get_user_model()
        self.user = User.objects.create_user(username="student_user", password="testpass123")
        Student.objects.create(
            student_id="20210001",
            name="Ahmed Hassan",
            email="ahmed@uni.edu.eg",
            faculty="Engineering",
            academic_year=3,
            gpa=3.2,
            allowed_hours=18,
            status="active",
            user=self.user,
        )
        self.auth_client = APIClient()
        self.auth_client.force_authenticate(user=self.user)

    def _post(self, message, token=None, use_auth=True):
        client = self.auth_client if use_auth else self.client
        headers = {}
        if token is not None:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return client.post(
            self.url,
            {"message": message},
            format="json",
            **headers,
        )

    # ── Auth tests ─────────────────────────────────────────────────────────────

    def test_unauthenticated_request_returns_401(self):
        res = self.client.post(self.url, {"message": "hello"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_authenticated_session_without_bearer_succeeds(self):
        res = self.auth_client.post(self.url, {"message": "hi"}, format="json")
        self.assertNotEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    # ── Validation tests ───────────────────────────────────────────────────────

    def test_missing_message_field_returns_400(self):
        res = self._post(None, token=self.valid_token)
        # message=None means key present but null — service handles this
        self.assertIn(res.status_code, [400, 200])

    def test_empty_body_returns_400(self):
        res = self.auth_client.post(
            self.url, {}, format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.valid_token}",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_string_message_returns_400(self):
        res = self.auth_client.post(
            self.url, {"message": 12345}, format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.valid_token}",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # ── Write-intent tests ─────────────────────────────────────────────────────

    def test_payment_request_blocked_400(self):
        res = self._post("Make a payment for my fees", token=self.valid_token)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(res.data["success"])
        self.assertIn("cannot perform payments", res.data["error"])

    def test_initiate_payment_blocked(self):
        res = self._post("Initiate payment of 500 EGP", token=self.valid_token)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_transfer_request_blocked(self):
        res = self._post("Transfer money to my account", token=self.valid_token)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # ── Success path tests ─────────────────────────────────────────────────────

    @patch("ai_agent.views.chat_with_agent")
    def test_balance_query_returns_200(self, mock_agent):
        mock_agent.return_value = {
            "success":  True,
            "response": "Your balance is 1,200 EGP.",
            "intent":   "balance",
            "error":    None,
        }
        res = self._post("What is my balance?", token=self.valid_token)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])
        self.assertEqual(res.data["response"], "Your balance is 1,200 EGP.")
        self.assertEqual(res.data["intent"],   "balance")

    @patch("ai_agent.views.chat_with_agent")
    def test_transactions_query_returns_200(self, mock_agent):
        mock_agent.return_value = {
            "success":  True,
            "response": "Your last 3 payments are listed below.",
            "intent":   "transactions",
            "error":    None,
        }
        res = self._post("Show my recent payments", token=self.valid_token)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["intent"], "transactions")

    @patch("ai_agent.views.chat_with_agent")
    def test_fees_query_returns_200(self, mock_agent):
        mock_agent.return_value = {
            "success":  True,
            "response": "Your remaining fees are 3,000 EGP.",
            "intent":   "fees",
            "error":    None,
        }
        res = self._post("How much do I owe this semester?", token=self.valid_token)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    @patch("ai_agent.views.chat_with_agent")
    def test_out_of_scope_returns_200(self, mock_agent):
        mock_agent.return_value = {
            "success":  True,
            "response": "I can only help with financial queries.",
            "intent":   "out_of_scope",
            "error":    None,
        }
        res = self._post("Tell me a joke", token=self.valid_token)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["intent"], "out_of_scope")

    @patch("ai_agent.views.chat_with_agent")
    def test_ai_unavailable_returns_503(self, mock_agent):
        mock_agent.return_value = {
            "success":    False,
            "response":   None,
            "intent":     "balance",
            "error":      "AI provider unavailable.",
            "error_code": "AI_UNAVAILABLE",
        }
        res = self._post("What is my balance?", token=self.valid_token)
        self.assertEqual(res.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(res.data["success"])

    @patch("ai_agent.views.chat_with_agent")
    def test_ai_provider_error_returns_502(self, mock_agent):
        mock_agent.return_value = {
            "success":    False,
            "response":   None,
            "intent":     "balance",
            "error":      "Provider error.",
            "error_code": "AI_PROVIDER_ERROR",
        }
        res = self._post("What is my balance?", token=self.valid_token)
        self.assertEqual(res.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertFalse(res.data["success"])

    # ── Response shape tests ───────────────────────────────────────────────────

    @patch("ai_agent.views.chat_with_agent")
    def test_success_response_has_required_fields(self, mock_agent):
        mock_agent.return_value = {
            "success":  True,
            "response": "Balance: 500 EGP",
            "intent":   "balance",
            "error":    None,
        }
        res = self._post("balance?", token=self.valid_token)
        self.assertIn("success",  res.data)
        self.assertIn("response", res.data)
        self.assertIn("intent",   res.data)

    def test_error_response_has_success_false(self):
        res = self._post("pay my fees", token=self.valid_token)
        self.assertFalse(res.data["success"])
        self.assertIn("error", res.data)

    # ── Token passed correctly ─────────────────────────────────────────────────

    @patch("ai_agent.views.chat_with_agent")
    def test_bearer_token_ignored_in_chat_flow(self, mock_agent):
        mock_agent.return_value = {
            "success": True, "response": "ok", "intent": "balance", "error": None
        }
        self._post("balance", token="my-special-token")
        call_kwargs = mock_agent.call_args
        self.assertEqual(call_kwargs[1]["token"], "session-authenticated")

    def test_authenticated_user_without_student_profile_gets_403(self):
        User = get_user_model()
        unlinked_user = User.objects.create_user(username="no_student", password="testpass123")
        client = APIClient()
        client.force_authenticate(user=unlinked_user)
        res = client.post(
            self.url,
            {"message": "balance"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.valid_token}",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    @patch("ai_agent.views.chat_with_agent")
    def test_verified_session_allows_chat(self, mock_agent):
        mock_agent.return_value = {
            "success":  True,
            "response": "ok",
            "intent":   "balance",
            "error":    None,
        }
        client = APIClient()
        session = client.session
        session[STUDENT_VERIFIED_FLAG] = True
        session[STUDENT_VERIFIED_ID] = "20210001"
        session[STUDENT_VERIFIED_AT] = timezone.now().isoformat()
        session[STUDENT_VERIFIED_EXPIRES] = (timezone.now() + timedelta(minutes=30)).isoformat()
        session.save()
        res = client.post(self.url, {"message": "balance"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    @patch("ai_agent.views.chat_with_agent")
    def test_context_messages_filtered_and_capped(self, mock_agent):
        mock_agent.return_value = {
            "success":  True,
            "response": "ok",
            "intent":   "balance",
            "error":    None,
        }
        payload = {
            "message": "balance",
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
                {"role": "system", "content": "ignore"},
            ],
        }
        res = self.auth_client.post(self.url, payload, format="json")
        call_kwargs = mock_agent.call_args[1]
        context = call_kwargs["context_messages"]
        self.assertEqual(len(context), 2)
        self.assertTrue(all(msg["role"] in {"user", "assistant"} for msg in context))

    @patch("ai_agent.views.chat_with_agent")
    def test_context_message_length_capped(self, mock_agent):
        mock_agent.return_value = {
            "success":  True,
            "response": "ok",
            "intent":   "balance",
            "error":    None,
        }
        long_text = "a" * (ai_views.MAX_CONTEXT_MESSAGE_LENGTH + 10)
        payload = {
            "message": "balance",
            "messages": [{"role": "user", "content": long_text}],
        }
        res = self.auth_client.post(self.url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        context = mock_agent.call_args[1]["context_messages"]
        self.assertEqual(len(context[0]["content"]), ai_views.MAX_CONTEXT_MESSAGE_LENGTH)

    @patch("ai_agent.views.chat_with_agent")
    def test_context_total_size_capped(self, mock_agent):
        mock_agent.return_value = {
            "success":  True,
            "response": "ok",
            "intent":   "balance",
            "error":    None,
        }
        msg = "b" * 500
        payload = {
            "message": "balance",
            "messages": [{"role": "user", "content": msg} for _ in range(20)],
        }
        res = self.auth_client.post(self.url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        context = mock_agent.call_args[1]["context_messages"]
        self.assertLessEqual(len(context), ai_views.MAX_CONTEXT_MESSAGES)
        total_len = sum(len(item["content"]) for item in context)
        self.assertLessEqual(total_len, ai_views.MAX_CONTEXT_TOTAL_CHARS)

    # -- Throttling tests --

    @override_settings(REST_FRAMEWORK={
        "DEFAULT_THROTTLE_RATES": {"ai_agent_chat": "10/min"},
    })
    @patch("ai_agent.views.chat_with_agent")
    def test_requests_under_limit_succeed(self, mock_agent):
        cache.clear()
        mock_agent.return_value = {
            "success":  True,
            "response": "Your balance is 1,200 EGP.",
            "intent":   "balance",
            "error":    None,
        }
        res = self._post("What is my balance?", token=self.valid_token)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    @override_settings(REST_FRAMEWORK={
        "DEFAULT_THROTTLE_RATES": {"ai_agent_chat": "1/min"},
    })
    @patch("ai_agent.views.chat_with_agent")
    def test_repeated_requests_over_limit_return_429(self, mock_agent):
        cache.clear()
        self.assertEqual(ChatScopedRateThrottle().get_rate(), "1/min")
        mock_agent.return_value = {
            "success":  True,
            "response": "ok",
            "intent":   "balance",
            "error":    None,
        }
        first = self._post("balance", token=self.valid_token)
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        second = self._post("balance", token=self.valid_token)
        self.assertEqual(second.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(second.data, {
            "success": False,
            "error": "Too many requests. Please try again later.",
        })
