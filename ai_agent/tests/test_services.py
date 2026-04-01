"""
Unit tests for ai_agent/services.py - all business logic tested without HTTP.

Run with:
    python manage.py test ai_agent.tests.test_services
"""

from django.test import TestCase, override_settings
from unittest.mock import patch, MagicMock

from ai_agent.services import (
    is_write_request,
    classify_intent,
    fetch_tool_data,
    build_context_block,
    AIAgentUnavailable,
    AIAgentProviderError,
    chat_with_agent,
)


# -- is_write_request tests --

class IsWriteRequestTests(TestCase):

    def test_pay_keyword_blocked(self):
        self.assertTrue(is_write_request("I want to pay my fees"))

    def test_transfer_blocked(self):
        self.assertTrue(is_write_request("Transfer 500 EGP"))

    def test_initiate_blocked(self):
        self.assertTrue(is_write_request("Initiate a payment"))

    def test_retry_payment_blocked(self):
        self.assertTrue(is_write_request("Please retry payment"))

    def test_arabic_start_payment_blocked(self):
        self.assertTrue(is_write_request("عايز افتح عملية دفع جديدة"))

    def test_arabic_cancel_payment_blocked(self):
        self.assertTrue(is_write_request("الغي العملية"))

    def test_balance_query_allowed(self):
        self.assertFalse(is_write_request("What is my balance?"))

    def test_transaction_query_allowed(self):
        self.assertFalse(is_write_request("Show me my last transactions"))

    def test_fees_query_allowed(self):
        self.assertFalse(is_write_request("How much do I owe in fees?"))

    def test_case_insensitive(self):
        self.assertTrue(is_write_request("MAKE A PAYMENT please"))


# -- classify_intent tests --

class ClassifyIntentTests(TestCase):

    def test_balance_intent(self):
        self.assertEqual(classify_intent("What is my balance?"),      "balance")
        self.assertEqual(classify_intent("Show my account balance"),   "balance")
        self.assertEqual(classify_intent("كم رصيدي"),                 "balance")

    def test_transactions_intent(self):
        self.assertEqual(classify_intent("Show my last payments"),     "transactions")
        self.assertEqual(classify_intent("Payment history"),           "transactions")
        self.assertEqual(classify_intent("List my recent transactions"),"transactions")
        self.assertEqual(classify_intent("عايز اعرف تاريخ عملياتي"),   "transactions")

    def test_fees_intent(self):
        self.assertEqual(classify_intent("How much do I owe?"),        "fees")
        self.assertEqual(classify_intent("What are my semester fees?"), "fees")
        self.assertEqual(classify_intent("tuition cost"),               "fees")

    def test_failed_payment_intent(self):
        self.assertEqual(classify_intent("Why did my payment fail?"),  "failed_payment")
        self.assertEqual(classify_intent("Payment was rejected"),      "failed_payment")
        self.assertEqual(classify_intent("why was it declined"),       "failed_payment")

    def test_status_intent(self):
        self.assertEqual(classify_intent("What is my payment status?"), "status")
        self.assertEqual(classify_intent("Why can't I start a payment?"), "status")
        self.assertEqual(classify_intent("what is my current payment?"), "status")
        self.assertEqual(classify_intent("tell me about my current payment"), "status")
        self.assertEqual(classify_intent("do I have an open payment?"), "status")
        self.assertEqual(classify_intent("what is my open payment status?"), "status")
        self.assertEqual(classify_intent("حالة الدفع ايه؟"), "status")
        self.assertEqual(classify_intent("ايه العملية الحالية عندي؟"), "status")
        self.assertEqual(classify_intent("هل عندي عملية دفع مفتوحة؟"), "status")
        self.assertEqual(classify_intent("العملية الحالية"), "status")
        self.assertEqual(classify_intent("أعمل ايه دلوقتي؟"), "status")
        self.assertEqual(classify_intent("أعمل إيه دلوقتي؟"), "status")
        self.assertEqual(classify_intent("اعمل ايه دلوقتي؟"), "status")
        self.assertEqual(classify_intent("الخطوة الجاية ايه؟"), "status")
        self.assertEqual(classify_intent("المفروض أعمل ايه الآن؟"), "status")

    def test_out_of_scope(self):
        self.assertEqual(classify_intent("How is the weather today?"), "out_of_scope")
        self.assertEqual(classify_intent("Tell me a joke"),            "out_of_scope")
        self.assertEqual(classify_intent(""),                           "out_of_scope")


# -- fetch_tool_data tests --

class FetchToolDataTests(TestCase):

    @patch("ai_agent.services.get_balance")
    def test_balance_calls_get_balance(self, mock_balance):
        mock_balance.return_value = {"ok": True, "data": {"balance": 1200}}
        result = fetch_tool_data("balance", "fake-token")
        mock_balance.assert_called_once_with("fake-token")
        self.assertIn("balance", result)

    @patch("ai_agent.services.get_transactions")
    def test_transactions_calls_get_transactions(self, mock_txns):
        mock_txns.return_value = {"ok": True, "data": {"transactions": []}}
        result = fetch_tool_data("transactions", "fake-token")
        mock_txns.assert_called_once_with("fake-token", limit=10)
        self.assertIn("transactions", result)

    @patch("ai_agent.services.get_fees")
    def test_fees_calls_get_fees(self, mock_fees):
        mock_fees.return_value = {"ok": True, "data": {"total_fees": 5000}}
        result = fetch_tool_data("fees", "fake-token")
        mock_fees.assert_called_once_with("fake-token")
        self.assertIn("fees", result)

    @patch("ai_agent.services.get_transactions")
    @patch("ai_agent.services.get_balance")
    def test_failed_payment_calls_both(self, mock_balance, mock_txns):
        mock_balance.return_value = {"ok": True, "data": {"balance": 300}}
        mock_txns.return_value    = {"ok": True, "data": {"transactions": []}}
        result = fetch_tool_data("failed_payment", "fake-token")
        self.assertIn("transactions", result)
        self.assertIn("balance",      result)

    def test_out_of_scope_calls_no_tools(self):
        result = fetch_tool_data("out_of_scope", "fake-token")
        self.assertEqual(result, {})


# -- build_context_block tests --

class BuildContextBlockTests(TestCase):

    def test_balance_context(self):
        tool_data = {"balance": {"ok": True, "data": {"balance": "1200.00", "currency": "EGP"}}}
        ctx = build_context_block("balance", tool_data)
        self.assertIn("1200.00", ctx)
        self.assertIn("EGP",     ctx)
        self.assertIn("BALANCE", ctx)

    def test_transactions_context(self):
        tool_data = {
            "transactions": {
                "ok": True,
                "data": {
                    "transactions": [
                        {"amount": "500", "status": "paid", "created_at": "2025-01-01",
                         "payment_method": "fawry", "gateway_reference": "REF123",
                         "transaction_id": "11111111-2222-3333-4444-555555555555"},
                    ]
                }
            }
        }
        ctx = build_context_block("transactions", tool_data)
        self.assertIn("500",   ctx)
        self.assertIn("paid",  ctx)
        self.assertIn("fawry", ctx)
        self.assertNotIn("REF123", ctx)
        self.assertNotIn("11111111-2222-3333-4444-555555555555", ctx)

    def test_fees_context(self):
        tool_data = {
            "fees": {
                "ok": True,
                "data": {"total_fees": "5000", "paid": "2000", "remaining": "3000", "semester": "2025-Spring"}
            }
        }
        ctx = build_context_block("fees", tool_data)
        self.assertIn("5000",        ctx)
        self.assertIn("3000",        ctx)
        self.assertIn("2025-Spring", ctx)

    def test_tool_error_shown_in_context(self):
        tool_data = {"balance": {"ok": False, "error": "Token expired"}}
        ctx = build_context_block("balance", tool_data)
        self.assertIn("Token expired", ctx)
        self.assertIn("unavailable",   ctx)


# -- chat_with_agent tests --

class ChatWithAgentTests(TestCase):

    def test_empty_message_returns_error(self):
        result = chat_with_agent("", "token")
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"])

    def test_none_message_returns_error(self):
        result = chat_with_agent(None, "token")
        self.assertFalse(result["success"])

    def test_missing_token_returns_error(self):
        result = chat_with_agent("What is my balance?", "")
        self.assertFalse(result["success"])

    def test_write_request_blocked(self):
        result = chat_with_agent("Pay my fees now", "valid-token")
        self.assertFalse(result["success"])
        self.assertEqual(result["intent"], "write_blocked")
        self.assertIn("cannot perform payments", result["error"])

    def test_too_long_message_blocked(self):
        result = chat_with_agent("x" * 1001, "valid-token")
        self.assertFalse(result["success"])
        self.assertIn("too long", result["error"])

    def test_out_of_scope_returns_helpful_message(self):
        result = chat_with_agent("Tell me the weather", "valid-token")
        self.assertTrue(result["success"])
        self.assertEqual(result["intent"], "out_of_scope")
        self.assertIn("Financial Assistant", result["response"])

    @patch("ai_agent.services.call_groq_llm")
    @patch("ai_agent.services.fetch_tool_data")
    def test_balance_query_calls_llm(self, mock_fetch, mock_llm):
        mock_fetch.return_value = {
            "balance": {"ok": True, "data": {"balance": "1200.00", "currency": "EGP"}}
        }
        mock_llm.return_value = "Your balance is 1200.00 EGP."

        result = chat_with_agent("What is my balance?", "valid-token")

        self.assertTrue(result["success"])
        self.assertEqual(result["intent"], "balance")
        self.assertEqual(result["response"], "Your balance is 1200.00 EGP.")
        mock_llm.assert_called_once()

    @patch("ai_agent.services.call_groq_llm")
    @patch("ai_agent.services.fetch_tool_data")
    def test_failed_payment_query(self, mock_fetch, mock_llm):
        mock_fetch.return_value = {
            "transactions": {"ok": True, "data": {"transactions": [
                {"amount": "500", "status": "failed", "created_at": "2025-01-10",
                 "payment_method": "fawry", "gateway_reference": "REF999"}
            ]}},
            "balance": {"ok": True, "data": {"balance": "300.00", "currency": "EGP"}},
        }
        mock_llm.return_value = (
            "Your last payment of 500 EGP via Fawry was rejected. "
            "Your current balance is 300 EGP."
        )

        result = chat_with_agent("Why did my last payment fail?", "valid-token")

        self.assertTrue(result["success"])
        self.assertEqual(result["intent"], "failed_payment")
        self.assertIn("500", result["response"])

    @patch("ai_agent.services.call_groq_llm")
    @patch("ai_agent.services.fetch_tool_data")
    def test_llm_unavailable_returns_error(self, mock_fetch, mock_llm):
        mock_fetch.return_value = {
            "balance": {"ok": True, "data": {"balance": "1200.00", "currency": "EGP"}}
        }
        mock_llm.side_effect = AIAgentUnavailable("AI provider unavailable.")

        result = chat_with_agent("What is my balance?", "valid-token")

        self.assertFalse(result["success"])
        self.assertEqual(result.get("error_code"), "AI_UNAVAILABLE")

    @patch("ai_agent.services.call_groq_llm")
    @patch("ai_agent.services.fetch_tool_data")
    def test_llm_provider_error_returns_error(self, mock_fetch, mock_llm):
        mock_fetch.return_value = {
            "balance": {"ok": True, "data": {"balance": "1200.00", "currency": "EGP"}}
        }
        mock_llm.side_effect = AIAgentProviderError("Upstream failure.")

        result = chat_with_agent("What is my balance?", "valid-token")

        self.assertFalse(result["success"])
        self.assertEqual(result.get("error_code"), "AI_PROVIDER_ERROR")


