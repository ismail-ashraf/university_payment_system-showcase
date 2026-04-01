"""
=== FILE: payments/tests/test_gateways.py ===
Unit tests for all gateway adapters — PRD interface (create_payment/verify_payment).
No DB access — Payment instances are mocked.
"""

import uuid
from decimal import Decimal
from unittest.mock import MagicMock
from django.test import TestCase, override_settings

from payments.gateways import get_gateway, is_valid_provider, SUPPORTED_PROVIDERS
from payments.gateways.fawry    import FawryGateway
from payments.gateways.vodafone import VodafoneGateway
from payments.gateways.bank     import MockBankGateway


def make_mock_payment(
    student_id="20210001",
    student_name="Ahmed Hassan",
    amount="5000.00",
    semester="2025-Spring",
):
    """Create a mock Payment instance — no DB needed."""
    payment             = MagicMock()
    payment.transaction_id  = uuid.uuid4()
    payment.amount          = Decimal(amount)
    payment.semester        = semester
    payment.student.student_id = student_id
    payment.student.name       = student_name
    return payment


# ── Registry ───────────────────────────────────────────────────────────────────

class RegistryTests(TestCase):

    def test_all_providers_registered(self):
        for p in ("fawry", "vodafone", "bank"):
            self.assertIn(p, SUPPORTED_PROVIDERS)

    def test_get_gateway_returns_correct_class(self):
        self.assertIsInstance(get_gateway("fawry"),    FawryGateway)
        self.assertIsInstance(get_gateway("vodafone"), VodafoneGateway)
        self.assertIsInstance(get_gateway("bank"),     MockBankGateway)

    def test_get_gateway_unknown_returns_none(self):
        self.assertIsNone(get_gateway("paypal"))
        self.assertIsNone(get_gateway(""))
        self.assertIsNone(get_gateway(None))

    def test_is_valid_provider_case_insensitive(self):
        self.assertTrue(is_valid_provider("FAWRY"))
        self.assertTrue(is_valid_provider("Vodafone"))

    def test_is_valid_provider_false_for_unknown(self):
        self.assertFalse(is_valid_provider("stripe"))
        self.assertFalse(is_valid_provider(""))
        self.assertFalse(is_valid_provider(None))

    def test_each_get_gateway_returns_fresh_instance(self):
        gw1 = get_gateway("fawry")
        gw2 = get_gateway("fawry")
        self.assertIsNot(gw1, gw2)  # New instance each time — no shared state


# ── Fawry: create_payment ──────────────────────────────────────────────────────

class FawryCreatePaymentTests(TestCase):

    def setUp(self):
        self.gw      = FawryGateway()
        self.payment = make_mock_payment()

    def test_create_payment_succeeds(self):
        resp = self.gw.create_payment(self.payment)
        self.assertTrue(resp.success)

    def test_transaction_reference_format(self):
        resp = self.gw.create_payment(self.payment)
        self.assertTrue(resp.transaction_reference.startswith("FWR-"))

    def test_status_is_pending(self):
        resp = self.gw.create_payment(self.payment)
        self.assertEqual(resp.status, "pending")

    def test_provider_name(self):
        resp = self.gw.create_payment(self.payment)
        self.assertEqual(resp.provider, "fawry")

    def test_instructions_have_steps(self):
        resp = self.gw.create_payment(self.payment)
        self.assertIn("steps", resp.instructions)
        self.assertIsInstance(resp.instructions["steps"], list)
        self.assertGreater(len(resp.instructions["steps"]), 0)

    def test_instructions_have_reference_code(self):
        resp = self.gw.create_payment(self.payment)
        self.assertIn("reference_code", resp.instructions)

    def test_instructions_receipt_line_is_ascii(self):
        resp = self.gw.create_payment(self.payment)
        self.assertIn(
            "Keep your receipt - it contains your confirmation number.",
            resp.instructions.get("steps", []),
        )

    def test_raw_payload_contains_transaction_id(self):
        resp = self.gw.create_payment(self.payment)
        self.assertIn(str(self.payment.transaction_id), resp.raw_payload["transaction_id"])

    def test_raw_payload_contains_amount(self):
        resp = self.gw.create_payment(self.payment)
        self.assertEqual(resp.raw_payload["amount"], str(self.payment.amount))

    def test_external_reference_alias(self):
        """Backward compat: external_reference is alias for transaction_reference."""
        resp = self.gw.create_payment(self.payment)
        self.assertEqual(resp.external_reference, resp.transaction_reference)

    def test_different_payments_get_different_references(self):
        p1 = make_mock_payment()
        p2 = make_mock_payment()
        r1 = self.gw.create_payment(p1)
        r2 = self.gw.create_payment(p2)
        self.assertNotEqual(r1.transaction_reference, r2.transaction_reference)


# ── Fawry: verify_payment ──────────────────────────────────────────────────────

@override_settings(FAWRY_WEBHOOK_SECRET="test-secret", DEBUG=False)
class FawryVerifyPaymentTests(TestCase):

    def setUp(self):
        self.gw = FawryGateway()

    def _signed_body(self, txn_id=None, status="success", amount="5000.00"):
        txn_id = txn_id or str(uuid.uuid4())
        ref    = f"FWR-{txn_id.replace('-','').upper()[:12]}"
        body   = {
            "transaction_id":  txn_id,
            "fawry_reference": ref,
            "status":          status,
            "amount":          amount,
        }
        canonical = self.gw.build_canonical_string({
            "transaction_id":  txn_id,
            "fawry_reference": ref,
            "status":          status,
            "amount":          amount,
        })
        body["signature"] = self.gw.compute_hmac_signature(canonical)
        return body

    def test_valid_webhook_passes(self):
        body   = self._signed_body()
        result = self.gw.verify_payment(body)
        self.assertTrue(result.is_valid)

    def test_invalid_signature_rejected(self):
        body             = self._signed_body()
        body["signature"] = "tampered"
        result           = self.gw.verify_payment(body)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "WEBHOOK_INVALID_SIGNATURE")

    def test_missing_fields_rejected(self):
        result = self.gw.verify_payment({"transaction_id": "x"})
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "WEBHOOK_MISSING_FIELDS")

    def test_unknown_status_rejected(self):
        body           = self._signed_body(status="approved")
        # Re-sign with the bad status so signature check passes
        canonical      = self.gw.build_canonical_string({
            "transaction_id":  body["transaction_id"],
            "fawry_reference": body["fawry_reference"],
            "status":          "approved",
            "amount":          body["amount"],
        })
        body["signature"] = self.gw.compute_hmac_signature(canonical)
        result = self.gw.verify_payment(body)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "WEBHOOK_INVALID_STATUS")

    def test_failed_status_passes_validation(self):
        body   = self._signed_body(status="failed")
        result = self.gw.verify_payment(body)
        self.assertTrue(result.is_valid)

    def test_parse_webhook(self):
        body    = self._signed_body()
        payload = self.gw.parse_webhook(body)
        self.assertEqual(str(payload.transaction_id), body["transaction_id"])
        self.assertEqual(payload.amount,   Decimal(body["amount"]))
        self.assertEqual(payload.status,   body["status"])
        self.assertEqual(payload.provider, "fawry")


# ── Vodafone ───────────────────────────────────────────────────────────────────

@override_settings(VODAFONE_WEBHOOK_SECRET="test-secret", DEBUG=False)
class VodafoneGatewayTests(TestCase):

    def setUp(self):
        self.gw      = VodafoneGateway()
        self.payment = make_mock_payment()

    def test_create_payment_succeeds(self):
        self.assertTrue(self.gw.create_payment(self.payment).success)

    def test_reference_starts_with_vf(self):
        self.assertTrue(self.gw.create_payment(self.payment).transaction_reference.startswith("VF-"))

    def test_status_is_pending(self):
        self.assertEqual(self.gw.create_payment(self.payment).status, "pending")

    def test_instructions_have_request_id(self):
        resp = self.gw.create_payment(self.payment)
        self.assertIn("request_id", resp.instructions)

    def _signed_body(self, txn_id=None, status="success"):
        txn_id = txn_id or str(uuid.uuid4())
        ref    = f"VF-{txn_id.replace('-','').upper()[:10]}"
        body   = {"transaction_id": txn_id, "vf_request_id": ref, "status": status, "amount": "5000.00"}
        canonical = self.gw.build_canonical_string({
            "transaction_id": txn_id, "vf_request_id": ref, "status": status, "amount": "5000.00",
        })
        body["signature"] = self.gw.compute_hmac_signature(canonical)
        return body

    def test_verify_payment_valid(self):
        self.assertTrue(self.gw.verify_payment(self._signed_body()).is_valid)

    def test_verify_payment_bad_signature(self):
        body             = self._signed_body()
        body["signature"] = "bad"
        self.assertFalse(self.gw.verify_payment(body).is_valid)

    def test_parse_webhook(self):
        body    = self._signed_body()
        payload = self.gw.parse_webhook(body)
        self.assertEqual(str(payload.transaction_id), body["transaction_id"])
        self.assertEqual(payload.provider, "vodafone")


# ── MockBank ───────────────────────────────────────────────────────────────────

@override_settings(BANK_WEBHOOK_SECRET="test-secret", DEBUG=False)
class MockBankGatewayTests(TestCase):

    def setUp(self):
        self.gw      = MockBankGateway()
        self.payment = make_mock_payment()

    def test_create_payment_succeeds(self):
        self.assertTrue(self.gw.create_payment(self.payment).success)

    def test_reference_starts_with_bnk(self):
        self.assertTrue(self.gw.create_payment(self.payment).transaction_reference.startswith("BNK-"))

    def test_instructions_have_virtual_iban(self):
        resp = self.gw.create_payment(self.payment)
        self.assertIn("virtual_iban", resp.instructions)

    def _signed_body(self, txn_id=None, status="success"):
        txn_id = txn_id or str(uuid.uuid4())
        ref    = f"BNK-{txn_id[:8].upper()}"
        body   = {"transaction_id": txn_id, "bank_reference": ref, "status": status, "amount": "5000.00"}
        canonical = self.gw.build_canonical_string({
            "transaction_id": txn_id, "bank_reference": ref, "status": status, "amount": "5000.00",
        })
        body["signature"] = self.gw.compute_hmac_signature(canonical)
        return body

    def test_verify_payment_valid(self):
        self.assertTrue(self.gw.verify_payment(self._signed_body()).is_valid)

    def test_verify_missing_fields(self):
        result = self.gw.verify_payment({"transaction_id": "x"})
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "WEBHOOK_MISSING_FIELDS")

    def test_verify_payment_bad_signature(self):
        body             = self._signed_body()
        body["signature"] = "bad"
        result = self.gw.verify_payment(body)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "WEBHOOK_INVALID_SIGNATURE")

    def test_parse_webhook(self):
        body    = self._signed_body()
        payload = self.gw.parse_webhook(body)
        self.assertEqual(payload.provider, "bank")
        self.assertEqual(payload.amount, Decimal("5000.00"))


# ── Signature utilities ────────────────────────────────────────────────────────

class SignatureUtilityTests(TestCase):

    def setUp(self):
        self.gw = FawryGateway()

    def test_hmac_is_deterministic(self):
        s1 = self.gw.compute_hmac_signature("test")
        s2 = self.gw.compute_hmac_signature("test")
        self.assertEqual(s1, s2)

    def test_different_payloads_differ(self):
        self.assertNotEqual(
            self.gw.compute_hmac_signature("a"),
            self.gw.compute_hmac_signature("b"),
        )

    def test_verify_passes(self):
        sig = self.gw.compute_hmac_signature("canonical-string")
        self.assertTrue(self.gw.verify_signature("canonical-string", sig))

    def test_verify_fails_on_tamper(self):
        sig = self.gw.compute_hmac_signature("original")
        self.assertFalse(self.gw.verify_signature("tampered", sig))

    def test_canonical_string_sorted(self):
        s = self.gw.build_canonical_string({"z": "1", "a": "2", "m": "3"})
        self.assertEqual(s, "a=2&m=3&z=1")


@override_settings(FAWRY_WEBHOOK_SECRET="test-secret", DEBUG=False)
class WebhookSecretSettingsTests(TestCase):
    def test_secret_loaded_from_settings(self):
        gw = FawryGateway()
        self.assertEqual(gw.WEBHOOK_SECRET, "test-secret")


class WebhookFallbackSecretPolicyTests(TestCase):
    @override_settings(
        FAWRY_WEBHOOK_SECRET=None,
        DEBUG=True,
        TESTING=False,
        ALLOW_WEBHOOK_SECRET_FALLBACK=True,
        WEBHOOK_ALLOWED_IPS=["127.0.0.1"],
    )
    def test_fallback_allowed_only_with_explicit_flag_and_loopback(self):
        gw = FawryGateway()
        self.assertEqual(gw.WEBHOOK_SECRET, "fawry-webhook-secret-dev")

    @override_settings(
        FAWRY_WEBHOOK_SECRET=None,
        DEBUG=True,
        TESTING=False,
        ALLOW_WEBHOOK_SECRET_FALLBACK=False,
        WEBHOOK_ALLOWED_IPS=["127.0.0.1"],
    )
    def test_fallback_denied_without_explicit_flag(self):
        gw = FawryGateway()
        self.assertIsNone(gw.WEBHOOK_SECRET)

    @override_settings(
        FAWRY_WEBHOOK_SECRET=None,
        DEBUG=False,
        TESTING=False,
        ALLOW_WEBHOOK_SECRET_FALLBACK=True,
        WEBHOOK_ALLOWED_IPS=["127.0.0.1"],
    )
    def test_fallback_denied_without_debug_or_testing(self):
        gw = FawryGateway()
        self.assertIsNone(gw.WEBHOOK_SECRET)

    @override_settings(
        FAWRY_WEBHOOK_SECRET=None,
        DEBUG=True,
        TESTING=False,
        ALLOW_WEBHOOK_SECRET_FALLBACK=True,
        WEBHOOK_ALLOWED_IPS=["127.0.0.1", "10.0.0.5"],
    )
    def test_fallback_denied_with_non_loopback_ips(self):
        gw = FawryGateway()
        self.assertIsNone(gw.WEBHOOK_SECRET)
