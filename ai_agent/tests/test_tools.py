"""

Unit tests for ai_agent/tools.py — all HTTP calls are mocked.

Run with:
    python manage.py test ai_agent.tests.test_tools
"""

from django.test import TestCase
from unittest.mock import patch, MagicMock
import requests

from ai_agent.tools import get_balance, get_transactions, get_fees


def _mock_response(status_code=200, json_data=None):
    """Helper: create a mock requests.Response."""
    mock = MagicMock(spec=requests.Response)
    mock.status_code = status_code
    mock.ok          = status_code < 400
    mock.json.return_value = json_data or {}
    return mock


class GetBalanceTests(TestCase):

    @patch("ai_agent.tools.requests.get")
    def test_success_returns_ok_true(self, mock_get):
        mock_get.return_value = _mock_response(200, {"balance": "1200.00", "currency": "EGP"})
        result = get_balance("valid-token")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["balance"], "1200.00")

    @patch("ai_agent.tools.requests.get")
    def test_401_returns_auth_error(self, mock_get):
        mock_get.return_value = _mock_response(401)
        result = get_balance("bad-token")
        self.assertFalse(result["ok"])
        self.assertIn("expired", result["error"].lower())

    @patch("ai_agent.tools.requests.get")
    def test_500_returns_server_error(self, mock_get):
        mock_get.return_value = _mock_response(500)
        result = get_balance("token")
        self.assertFalse(result["ok"])
        self.assertIn("internal error", result["error"].lower())

    @patch("ai_agent.tools.requests.get")
    def test_connection_error_handled(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError()
        result = get_balance("token")
        self.assertFalse(result["ok"])
        self.assertIn("connect", result["error"].lower())

    @patch("ai_agent.tools.requests.get")
    def test_timeout_handled(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout()
        result = get_balance("token")
        self.assertFalse(result["ok"])
        self.assertIn("too long", result["error"].lower())

    def test_empty_token_returns_error(self):
        result = get_balance("")
        self.assertFalse(result["ok"])
        self.assertIn("token", result["error"].lower())

    def test_none_token_returns_error(self):
        result = get_balance(None)
        self.assertFalse(result["ok"])


class GetTransactionsTests(TestCase):

    @patch("ai_agent.tools.requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "transactions": [{"amount": "500", "status": "paid"}],
            "total": 1,
        })
        result = get_transactions("token")
        self.assertTrue(result["ok"])
        self.assertIn("transactions", result["data"])

    @patch("ai_agent.tools.requests.get")
    def test_limit_clamped_to_50(self, mock_get):
        mock_get.return_value = _mock_response(200, {"transactions": []})
        get_transactions("token", limit=999)
        called_url = mock_get.call_args[0][0]
        self.assertIn("limit=50", called_url)

    @patch("ai_agent.tools.requests.get")
    def test_limit_minimum_1(self, mock_get):
        mock_get.return_value = _mock_response(200, {"transactions": []})
        get_transactions("token", limit=0)
        called_url = mock_get.call_args[0][0]
        self.assertIn("limit=1", called_url)

    @patch("ai_agent.tools.requests.get")
    def test_403_returns_permission_error(self, mock_get):
        mock_get.return_value = _mock_response(403)
        result = get_transactions("token")
        self.assertFalse(result["ok"])
        self.assertIn("permission", result["error"].lower())

    def test_empty_token_blocked(self):
        result = get_transactions("")
        self.assertFalse(result["ok"])


class GetFeesTests(TestCase):

    @patch("ai_agent.tools.requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = _mock_response(200, {
            "total_fees": "5000", "paid": "2000", "remaining": "3000",
            "semester": "2025-Spring",
        })
        result = get_fees("token", student_id="20210001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["total_fees"], "5000")

    @patch("ai_agent.tools.requests.get")
    def test_404_returns_not_found(self, mock_get):
        mock_get.return_value = _mock_response(404)
        result = get_fees("token", student_id="20210001")
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"].lower())

    @patch("ai_agent.tools.requests.get")
    def test_non_json_response_handled(self, mock_get):
        mock = MagicMock(spec=requests.Response)
        mock.status_code = 200
        mock.ok          = True
        mock.json.side_effect = ValueError("No JSON")
        mock_get.return_value  = mock
        result = get_fees("token", student_id="20210001")
        self.assertFalse(result["ok"])
        self.assertIn("unreadable", result["error"].lower())

    def test_none_token_blocked(self):
        result = get_fees(None)
        self.assertFalse(result["ok"])
