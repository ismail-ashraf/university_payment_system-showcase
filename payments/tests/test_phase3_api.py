# """
# === FILE: payments/tests/test_phase3_api.py ===
# Phase 3 API integration tests — submit and webhook endpoints.

# Run with:
#     python manage.py test payments.tests.test_phase3_api
# """

# import uuid
# from decimal import Decimal
# from django.test import TestCase
# from django.urls import reverse
# from rest_framework.test import APIClient
# from rest_framework import status

# from students.models import Student
# from payments.models import Payment, PaymentAuditLog, current_semester
# from payments.gateways.fawry    import FawryGateway
# from payments.gateways.vodafone import VodafoneGateway
# from payments.gateways.bank     import MockBankGateway


# def make_student(**kwargs) -> Student:
#     defaults = {
#         "student_id":    "20210001",
#         "name":          "Ahmed Hassan",
#         "email":         "ahmed@uni.edu.eg",
#         "faculty":       "Engineering",
#         "academic_year": 3,
#         "gpa":           3.20,
#         "allowed_hours": 18,
#         "status":        "active",
#     }
#     defaults.update(kwargs)
#     return Student.objects.create(**defaults)


# def make_payment(student, **kwargs) -> Payment:
#     defaults = {
#         "amount":   Decimal("5000.00"),
#         "semester": current_semester(),
#         "status":   "pending",
#         "used":     False,
#     }
#     defaults.update(kwargs)
#     return Payment.objects.create(student=student, **defaults)


# def signed_fawry_webhook(gw: FawryGateway, transaction_id: str, status_val: str = "success") -> tuple:
#     ref = f"FWR-{transaction_id.replace('-', '').upper()[:12]}"
#     body = {
#         "transaction_id":  transaction_id,
#         "fawry_reference": ref,
#         "status":          status_val,
#         "amount":          "5000.00",
#     }
#     canonical = gw.build_canonical_string({
#         "transaction_id":  transaction_id,
#         "fawry_reference": ref,
#         "status":          status_val,
#         "amount":          "5000.00",
#     })
#     sig = gw.compute_hmac_signature(canonical)
#     return body, sig


# # ── Submit payment endpoint tests ──────────────────────────────────────────────

# class SubmitPaymentViewTests(TestCase):
#     """POST /api/payments/<uuid>/submit/"""

#     def setUp(self):
#         self.client  = APIClient()
#         self.student = make_student()
#         self.payment = make_payment(self.student)
#         self.url     = reverse("payments:payment-submit",
#                                kwargs={"transaction_id": self.payment.transaction_id})

#     def test_submit_fawry_succeeds(self):
#         res = self.client.post(self.url, {"provider": "fawry"}, format="json")
#         self.assertEqual(res.status_code, status.HTTP_200_OK)
#         self.assertTrue(res.data["success"])
#         data = res.data["data"]
#         self.assertEqual(data["provider"], "fawry")
#         self.assertIn("external_reference", data)
#         self.assertIn("instructions", data)

#     def test_submit_vodafone_succeeds(self):
#         res = self.client.post(self.url, {"provider": "vodafone"}, format="json")
#         self.assertEqual(res.status_code, status.HTTP_200_OK)
#         data = res.data["data"]
#         self.assertEqual(data["provider"], "vodafone")
#         self.assertTrue(data["external_reference"].startswith("VF-"))

#     def test_submit_bank_succeeds(self):
#         res = self.client.post(self.url, {"provider": "bank"}, format="json")
#         self.assertEqual(res.status_code, status.HTTP_200_OK)
#         data = res.data["data"]
#         self.assertEqual(data["provider"], "bank")
#         self.assertTrue(data["external_reference"].startswith("BNK-"))

#     def test_payment_status_becomes_processing(self):
#         self.client.post(self.url, {"provider": "fawry"}, format="json")
#         self.payment.refresh_from_db()
#         self.assertEqual(self.payment.status, "processing")

#     def test_payment_used_flag_set(self):
#         self.client.post(self.url, {"provider": "fawry"}, format="json")
#         self.payment.refresh_from_db()
#         self.assertTrue(self.payment.used)

#     def test_gateway_reference_saved(self):
#         self.client.post(self.url, {"provider": "fawry"}, format="json")
#         self.payment.refresh_from_db()
#         self.assertTrue(self.payment.gateway_reference.startswith("FWR-"))

#     def test_audit_log_created_on_submit(self):
#         self.client.post(self.url, {"provider": "fawry"}, format="json")
#         log = PaymentAuditLog.objects.filter(
#             payment=self.payment,
#             event_type="processing",
#         ).first()
#         self.assertIsNotNone(log)

#     def test_400_invalid_provider(self):
#         res = self.client.post(self.url, {"provider": "paypal"}, format="json")
#         self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

#     def test_400_missing_provider(self):
#         res = self.client.post(self.url, {}, format="json")
#         self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

#     def test_404_unknown_transaction(self):
#         url = reverse("payments:payment-submit", kwargs={"transaction_id": uuid.uuid4()})
#         res = self.client.post(url, {"provider": "fawry"}, format="json")
#         self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

#     def test_400_cannot_submit_already_processing(self):
#         # Submit once
#         self.client.post(self.url, {"provider": "fawry"}, format="json")
#         # Try to submit again
#         res = self.client.post(self.url, {"provider": "fawry"}, format="json")
#         self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
#         self.assertEqual(res.data["error"]["code"], "PAYMENT_NOT_OPEN")

#     def test_response_includes_instructions_steps(self):
#         res = self.client.post(self.url, {"provider": "fawry"}, format="json")
#         instructions = res.data["data"]["instructions"]
#         self.assertIn("steps", instructions)
#         self.assertIsInstance(instructions["steps"], list)
#         self.assertGreater(len(instructions["steps"]), 0)


# # ── Webhook endpoint tests ─────────────────────────────────────────────────────

# class WebhookViewTests(TestCase):
#     """POST /api/payments/webhook/<provider>/"""

#     def setUp(self):
#         self.client  = APIClient()
#         self.student = make_student()
#         self.gw      = FawryGateway()
#         # Create payment already in PROCESSING state (submitted to gateway)
#         self.payment = make_payment(
#             self.student,
#             status="processing",
#             used=True,
#             payment_method="fawry",
#             gateway_reference="FWR-TEST123",
#         )
#         self.webhook_url = reverse("payments:payment-webhook", kwargs={"provider": "fawry"})

#     def _post_webhook(self, body, sig):
#         return self.client.post(
#             self.webhook_url,
#             data=body,
#             format="json",
#             HTTP_X_WEBHOOK_SIGNATURE=sig,
#         )

#     def test_success_webhook_marks_paid(self):
#         body, sig = signed_fawry_webhook(self.gw, str(self.payment.transaction_id), "success")
#         res = self._post_webhook(body, sig)
#         self.assertEqual(res.status_code, status.HTTP_200_OK)
#         self.payment.refresh_from_db()
#         self.assertEqual(self.payment.status, "paid")

#     def test_failed_webhook_marks_failed(self):
#         body, sig = signed_fawry_webhook(self.gw, str(self.payment.transaction_id), "failed")
#         res = self._post_webhook(body, sig)
#         self.assertEqual(res.status_code, status.HTTP_200_OK)
#         self.payment.refresh_from_db()
#         self.assertEqual(self.payment.status, "failed")

#     def test_audit_log_written_on_success(self):
#         body, sig = signed_fawry_webhook(self.gw, str(self.payment.transaction_id), "success")
#         self._post_webhook(body, sig)
#         self.assertTrue(
#             PaymentAuditLog.objects.filter(
#                 payment=self.payment,
#                 event_type="success",
#             ).exists()
#         )

#     def test_audit_log_webhook_event_written(self):
#         body, sig = signed_fawry_webhook(self.gw, str(self.payment.transaction_id), "success")
#         self._post_webhook(body, sig)
#         self.assertTrue(
#             PaymentAuditLog.objects.filter(
#                 payment=self.payment,
#                 event_type="webhook",
#             ).exists()
#         )

#     def test_400_invalid_signature(self):
#         body, _ = signed_fawry_webhook(self.gw, str(self.payment.transaction_id))
#         res = self._post_webhook(body, "bad-signature")
#         self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
#         self.assertEqual(res.data["error"]["code"], "WEBHOOK_INVALID_SIGNATURE")

#     def test_400_invalid_provider(self):
#         url = reverse("payments:payment-webhook", kwargs={"provider": "paypal"})
#         res = self.client.post(url, {"transaction_id": str(uuid.uuid4()), "status": "success", "amount": "5000.00"}, format="json")
#         self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
#         self.assertEqual(res.data["error"]["code"], "INVALID_PROVIDER")

#     def test_idempotency_paid_payment_not_double_processed(self):
#         """Second success webhook on an already-paid payment is acknowledged but ignored."""
#         # First webhook — marks as paid
#         body, sig = signed_fawry_webhook(self.gw, str(self.payment.transaction_id), "success")
#         self._post_webhook(body, sig)

#         # Second webhook — must not change state
#         res = self._post_webhook(body, sig)
#         self.assertEqual(res.status_code, status.HTTP_200_OK)
#         self.assertTrue(res.data["data"]["acknowledged"])
#         # Payment still paid (not changed to something else)
#         self.payment.refresh_from_db()
#         self.assertEqual(self.payment.status, "paid")

#     def test_idempotency_replay_blocked_audit_log(self):
#         """Duplicate webhook creates a REPLAY_BLOCKED audit log entry."""
#         body, sig = signed_fawry_webhook(self.gw, str(self.payment.transaction_id), "success")
#         self._post_webhook(body, sig)
#         self._post_webhook(body, sig)  # duplicate
#         self.assertTrue(
#             PaymentAuditLog.objects.filter(
#                 payment=self.payment,
#                 event_type="replay_blocked",
#             ).exists()
#         )

#     def test_unknown_transaction_acknowledged_not_error(self):
#         """Webhook for an unknown transaction_id returns 200 (not 404) to prevent retries."""
#         body, sig = signed_fawry_webhook(self.gw, str(uuid.uuid4()), "success")
#         res = self._post_webhook(body, sig)
#         self.assertEqual(res.status_code, status.HTTP_200_OK)
#         self.assertTrue(res.data["data"]["acknowledged"])

#     def test_pending_webhook_no_state_change(self):
#         body, sig = signed_fawry_webhook(self.gw, str(self.payment.transaction_id), "pending")
#         res = self._post_webhook(body, sig)
#         self.assertEqual(res.status_code, status.HTTP_200_OK)
#         self.payment.refresh_from_db()
#         self.assertEqual(self.payment.status, "processing")  # Unchanged

#     def test_vodafone_webhook_success(self):
#         vf_gw      = VodafoneGateway()
#         vf_payment = make_payment(
#             make_student(student_id="20210002", email="b@uni.edu.eg"),
#             status="processing", used=True, payment_method="vodafone",
#         )
#         txn_id = str(vf_payment.transaction_id)
#         ref    = f"VF-{txn_id.replace('-','').upper()[:10]}"
#         body   = {"transaction_id": txn_id, "vf_request_id": ref, "status": "success", "amount": "5000.00"}
#         canonical = vf_gw.build_canonical_string({
#             "transaction_id": txn_id, "vf_request_id": ref, "status": "success", "amount": "5000.00",
#         })
#         sig = vf_gw.compute_hmac_signature(canonical)
#         url = reverse("payments:payment-webhook", kwargs={"provider": "vodafone"})
#         res = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
#         self.assertEqual(res.status_code, status.HTTP_200_OK)
#         vf_payment.refresh_from_db()
#         self.assertEqual(vf_payment.status, "paid")


# # ── Full flow integration test ─────────────────────────────────────────────────

# class FullPaymentFlowTests(TestCase):
#     """
#     End-to-end: create → submit → webhook success → verify paid.
#     """

#     def setUp(self):
#         self.client  = APIClient()
#         self.student = make_student()
#         self.gw      = FawryGateway()

#     def test_complete_happy_path(self):
#         # Step 1: Create payment
#         res = self.client.post(
#             reverse("payments:payment-start"),
#             {"student_id": "20210001"},
#             format="json",
#         )
#         self.assertEqual(res.status_code, status.HTTP_201_CREATED)
#         txn_id = res.data["data"]["transaction_id"]

#         # Step 2: Submit to Fawry
#         res = self.client.post(
#             reverse("payments:payment-submit", kwargs={"transaction_id": txn_id}),
#             {"provider": "fawry"},
#             format="json",
#         )
#         self.assertEqual(res.status_code, status.HTTP_200_OK)
#         self.assertEqual(res.data["data"]["status"], "processing")

#         # Step 3: Gateway sends success webhook
#         body, sig = signed_fawry_webhook(self.gw, str(txn_id), "success")
#         res = self.client.post(
#             reverse("payments:payment-webhook", kwargs={"provider": "fawry"}),
#             body,
#             format="json",
#             HTTP_X_WEBHOOK_SIGNATURE=sig,
#         )
#         self.assertEqual(res.status_code, status.HTTP_200_OK)
#         self.assertEqual(res.data["data"]["current_status"], "paid")

#         # Step 4: Verify via detail endpoint
#         res = self.client.get(
#             reverse("payments:payment-detail", kwargs={"transaction_id": txn_id})
#         )
#         self.assertEqual(res.status_code, status.HTTP_200_OK)
#         data = res.data["data"]
#         self.assertEqual(data["status"], "paid")
#         # Audit trail should have: initiated → processing → webhook → success
#         event_types = [log["event_type"] for log in data["audit_logs"]]
#         self.assertIn("initiated",  event_types)
#         self.assertIn("processing", event_types)
#         self.assertIn("webhook",    event_types)
#         self.assertIn("success",    event_types)

#     def test_failed_payment_flow(self):
#         # Create + submit
#         res = self.client.post(
#             reverse("payments:payment-start"),
#             {"student_id": "20210001"},
#             format="json",
#         )
#         txn_id = res.data["data"]["transaction_id"]
#         self.client.post(
#             reverse("payments:payment-submit", kwargs={"transaction_id": txn_id}),
#             {"provider": "fawry"},
#             format="json",
#         )

#         # Gateway reports failure
#         body, sig = signed_fawry_webhook(self.gw, str(txn_id), "failed")
#         res = self.client.post(
#             reverse("payments:payment-webhook", kwargs={"provider": "fawry"}),
#             body,
#             format="json",
#             HTTP_X_WEBHOOK_SIGNATURE=sig,
#         )
#         self.assertEqual(res.data["data"]["current_status"], "failed")

#         payment = Payment.objects.get(transaction_id=txn_id)
#         self.assertEqual(payment.status, "failed")


"""
=== FILE: payments/tests/test_phase3_api.py ===
Phase 3 API integration tests — submit and webhook endpoints.

Run with:
    python manage.py test payments.tests.test_phase3_api
"""

import uuid
from decimal import Decimal
from django.test import TestCase, override_settings
from unittest.mock import patch
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.core.cache import cache
from django.contrib.auth import get_user_model

from students.models import Student
from payments.models import Payment, PaymentAuditLog, current_semester
from payments.gateways.fawry    import FawryGateway
from payments.gateways.vodafone import VodafoneGateway
from payments.gateways.bank     import MockBankGateway


def make_student(**kwargs) -> Student:
    defaults = {
        "student_id":    "20210001",
        "name":          "Ahmed Hassan",
        "email":         "ahmed@uni.edu.eg",
        "faculty":       "Engineering",
        "academic_year": 3,
        "gpa":           3.20,
        "allowed_hours": 18,
        "status":        "active",
    }
    defaults.update(kwargs)
    return Student.objects.create(**defaults)


def make_payment(student, **kwargs) -> Payment:
    defaults = {
        "amount":   Decimal("5000.00"),
        "semester": current_semester(),
        "status":   "pending",
        "used":     False,
    }
    defaults.update(kwargs)
    return Payment.objects.create(student=student, **defaults)


def signed_fawry_webhook(
    gw: FawryGateway,
    transaction_id: str,
    status_val: str = "success",
    amount: str = None,          # FIX: accept amount as parameter
    payment: Payment = None,     # FIX: or derive it from the payment object
) -> tuple:
    """
    Build a correctly signed Fawry webhook body + signature.

    Amount priority:
      1. Explicit `amount` argument (string)
      2. `payment.amount` if payment object is passed
      3. Falls back to fetching from DB by transaction_id
    """
    # ── Resolve the correct amount ────────────────────────────────────────────
    if amount is None:
        if payment is not None:
            amount = str(payment.amount)
        else:
            # Fetch from DB so the webhook always matches the real payment amount
            try:
                amount = str(
                    Payment.objects.get(transaction_id=transaction_id).amount
                )
            except Payment.DoesNotExist:
                amount = "5000.00"   # fallback for unknown-txn tests only

    ref = f"FWR-{transaction_id.replace('-', '').upper()[:12]}"
    body = {
        "transaction_id":  transaction_id,
        "fawry_reference": ref,
        "status":          status_val,
        "amount":          amount,
    }
    canonical = gw.build_canonical_string(body)
    sig = gw.compute_hmac_signature(canonical)
    return body, sig


# ── Submit payment endpoint tests ──────────────────────────────────────────────

class SubmitPaymentViewTests(TestCase):
    """POST /api/payments/<uuid>/submit/"""

    def setUp(self):
        self.client  = APIClient()
        self.student = make_student()
        self.payment = make_payment(self.student)
        self.url     = reverse("payments:payment-submit",
                               kwargs={"transaction_id": self.payment.transaction_id})
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

    def test_submit_fawry_succeeds(self):
        res = self.client.post(self.url, {"provider": "fawry"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])
        data = res.data["data"]
        self.assertEqual(data["provider"], "fawry")
        self.assertIn("external_reference", data)
        self.assertIn("instructions", data)

    def test_submit_vodafone_succeeds(self):
        res = self.client.post(self.url, {"provider": "vodafone"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertEqual(data["provider"], "vodafone")
        self.assertTrue(data["external_reference"].startswith("VF-"))

    def test_submit_bank_succeeds(self):
        res = self.client.post(self.url, {"provider": "bank"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertEqual(data["provider"], "bank")
        self.assertTrue(data["external_reference"].startswith("BNK-"))

    def test_payment_status_becomes_processing(self):
        self.client.post(self.url, {"provider": "fawry"}, format="json")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "processing")

    def test_payment_used_flag_set(self):
        self.client.post(self.url, {"provider": "fawry"}, format="json")
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.used)

    def test_gateway_reference_saved(self):
        self.client.post(self.url, {"provider": "fawry"}, format="json")
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.gateway_reference.startswith("FWR-"))

    def test_audit_log_created_on_submit(self):
        self.client.post(self.url, {"provider": "fawry"}, format="json")
        log = PaymentAuditLog.objects.filter(
            payment=self.payment,
            event_type="processing",
        ).first()
        self.assertIsNotNone(log)

    def test_400_invalid_provider(self):
        res = self.client.post(self.url, {"provider": "paypal"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_missing_provider(self):
        res = self.client.post(self.url, {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(res.data.get("success", True))
        self.assertIn("error", res.data)
        self.assertEqual(res.data["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("details", res.data["error"])

    def test_404_unknown_transaction(self):
        url = reverse("payments:payment-submit", kwargs={"transaction_id": uuid.uuid4()})
        res = self.client.post(url, {"provider": "fawry"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_submit_denied_for_other_student(self):
        User = get_user_model()
        other_user = User.objects.create_user(username="other", password="pass")
        make_student(student_id="S002", email="s2@u.eg", user=other_user)
        client = APIClient()
        client.force_authenticate(user=other_user)
        res = client.post(self.url, {"provider": "fawry"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_400_cannot_submit_already_processing(self):
        # Submit once
        self.client.post(self.url, {"provider": "fawry"}, format="json")
        # Try to submit again
        res = self.client.post(self.url, {"provider": "fawry"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_NOT_OPEN")

    def test_400_cannot_submit_expired_payment(self):
        from django.utils import timezone
        from datetime import timedelta

        self.payment.expires_at = timezone.now() - timedelta(minutes=1)
        self.payment.save(update_fields=["expires_at", "updated_at"])

        res = self.client.post(self.url, {"provider": "fawry"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_EXPIRED")

    @override_settings(ABUSE_PAYMENT_SUBMIT_MAX=1, ABUSE_PAYMENT_SUBMIT_WINDOW_SECONDS=300)
    def test_payment_submit_rate_limited(self):
        res1 = self.client.post(self.url, {"provider": "fawry"}, format="json")
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        res2 = self.client.post(self.url, {"provider": "fawry"}, format="json")
        self.assertEqual(res2.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(res2.data["error"]["code"], "PAYMENT_SUBMIT_RATE_LIMITED")

    def test_response_includes_instructions_steps(self):
        res = self.client.post(self.url, {"provider": "fawry"}, format="json")
        instructions = res.data["data"]["instructions"]
        self.assertIn("steps", instructions)
        self.assertIsInstance(instructions["steps"], list)
        self.assertGreater(len(instructions["steps"]), 0)


# ── Webhook endpoint tests ─────────────────────────────────────────────────────

class WebhookViewTests(TestCase):
    """POST /api/payments/webhook/<provider>/"""

    def setUp(self):
        self.client  = APIClient()
        self.student = make_student()
        self.gw      = FawryGateway()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)
        # Create payment already in PROCESSING state (submitted to gateway)
        self.payment = make_payment(
            self.student,
            status="processing",
            used=True,
            payment_method="fawry",
        )
        expected_ref = f"FWR-{str(self.payment.transaction_id).replace('-', '').upper()[:12]}"
        self.payment.gateway_reference = expected_ref
        self.payment.save(update_fields=["gateway_reference", "updated_at"])
        self.webhook_url = reverse("payments:payment-webhook", kwargs={"provider": "fawry"})

    def _post_webhook(self, body, sig):
        return self.client.post(
            self.webhook_url,
            data=body,
            format="json",
            HTTP_X_WEBHOOK_SIGNATURE=sig,
        )

    def test_success_webhook_marks_paid(self):
        body, sig = signed_fawry_webhook(
            self.gw, str(self.payment.transaction_id), "success", payment=self.payment
        )
        res = self._post_webhook(body, sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")

    def test_webhook_uses_task_boundary(self):
        body, sig = signed_fawry_webhook(
            self.gw, str(self.payment.transaction_id), "success", payment=self.payment
        )
        with patch("payments.views.process_webhook_task") as mock_task:
            mock_task.return_value = ({"acknowledged": True, "current_status": "paid"}, None)
            res = self._post_webhook(body, sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])
        mock_task.assert_called_once()
        kwargs = mock_task.call_args.kwargs
        self.assertEqual(kwargs["provider"], "fawry")
        self.assertEqual(kwargs["raw_body"]["transaction_id"], str(self.payment.transaction_id))
        self.assertEqual(kwargs["signature"], sig)

    def test_failed_webhook_marks_failed(self):
        body, sig = signed_fawry_webhook(
            self.gw, str(self.payment.transaction_id), "failed", payment=self.payment
        )
        res = self._post_webhook(body, sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "failed")

    def test_audit_log_written_on_success(self):
        body, sig = signed_fawry_webhook(
            self.gw, str(self.payment.transaction_id), "success", payment=self.payment
        )
        self._post_webhook(body, sig)
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment,
                event_type="success",
            ).exists()
        )

    def test_audit_log_webhook_event_written(self):
        body, sig = signed_fawry_webhook(
            self.gw, str(self.payment.transaction_id), "success", payment=self.payment
        )
        self._post_webhook(body, sig)
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment,
                event_type="webhook",
            ).exists()
        )

    def test_400_invalid_signature(self):
        body, _ = signed_fawry_webhook(
            self.gw, str(self.payment.transaction_id), payment=self.payment
        )
        res = self._post_webhook(body, "bad-signature")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "WEBHOOK_INVALID_SIGNATURE")
        response_text = str(res.data).lower()
        self.assertNotIn("bad-signature", response_text)
        self.assertNotIn("secret", response_text)
        self.assertNotIn("token", response_text)

    def test_header_signature_overrides_body_signature(self):
        body, sig = signed_fawry_webhook(
            self.gw, str(self.payment.transaction_id), "success", payment=self.payment
        )
        body["signature"] = sig
        res = self._post_webhook(body, "bad-signature")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "WEBHOOK_INVALID_SIGNATURE")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "processing")

    @override_settings(DEBUG=False, TESTING=False, WEBHOOK_ALLOWED_IPS=["1.2.3.4"])
    def test_webhook_source_not_allowed_rejected(self):
        body, sig = signed_fawry_webhook(
            self.gw, str(self.payment.transaction_id), "success", payment=self.payment
        )
        res = self.client.post(
            self.webhook_url,
            data=body,
            format="json",
            HTTP_X_WEBHOOK_SIGNATURE=sig,
            REMOTE_ADDR="5.6.7.8",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data["error"]["code"], "WEBHOOK_SOURCE_NOT_ALLOWED")

    @override_settings(
        DEBUG=False,
        TESTING=False,
        WEBHOOK_ALLOWED_IPS=["1.2.3.4"],
        TRUSTED_PROXY_IPS=["9.9.9.9"],
        FAWRY_WEBHOOK_SECRET="test-fawry-secret",
    )
    def test_spoofed_xff_does_not_bypass_allowlist(self):
        gw = FawryGateway()
        body, sig = signed_fawry_webhook(
            gw, str(self.payment.transaction_id), "success", payment=self.payment
        )
        res = self.client.post(
            self.webhook_url,
            data=body,
            format="json",
            HTTP_X_WEBHOOK_SIGNATURE=sig,
            HTTP_X_FORWARDED_FOR="1.2.3.4",
            REMOTE_ADDR="8.8.8.8",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data["error"]["code"], "WEBHOOK_SOURCE_NOT_ALLOWED")

    @override_settings(
        DEBUG=False,
        TESTING=False,
        WEBHOOK_ALLOWED_IPS=["1.2.3.4"],
        TRUSTED_PROXY_IPS=["9.9.9.9"],
        FAWRY_WEBHOOK_SECRET="test-fawry-secret",
    )
    def test_trusted_proxy_xff_allows_allowlisted_source(self):
        gw = FawryGateway()
        body, sig = signed_fawry_webhook(
            gw, str(self.payment.transaction_id), "success", payment=self.payment
        )
        res = self.client.post(
            self.webhook_url,
            data=body,
            format="json",
            HTTP_X_WEBHOOK_SIGNATURE=sig,
            HTTP_X_FORWARDED_FOR="1.2.3.4",
            REMOTE_ADDR="9.9.9.9",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_invalid_payload_does_not_create_malformed_audit_log(self):
        body = {
            "transaction_id": str(self.payment.transaction_id),
            "amount": str(self.payment.amount),
        }
        res = self._post_webhook(body, "sig")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(res.data.get("success", True))
        self.assertIn("error", res.data)
        self.assertEqual(res.data["error"]["code"], "WEBHOOK_VALIDATION_ERROR")
        self.assertIn("details", res.data["error"])
        self.assertFalse(
            PaymentAuditLog.objects.filter(
                payment=self.payment,
                event_type="malformed_webhook_payload",
            ).exists()
        )

    def test_400_invalid_provider(self):
        url = reverse("payments:payment-webhook", kwargs={"provider": "paypal"})
        res = self.client.post(
            url,
            {"transaction_id": str(uuid.uuid4()), "status": "success", "amount": str(self.payment.amount)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "INVALID_PROVIDER")

    def test_idempotency_paid_payment_not_double_processed(self):
        """Second success webhook on an already-paid payment is acknowledged but ignored."""
        body, sig = signed_fawry_webhook(
            self.gw, str(self.payment.transaction_id), "success", payment=self.payment
        )
        # First webhook — marks as paid
        self._post_webhook(body, sig)
        # Second webhook — must not change state
        res = self._post_webhook(body, sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["data"]["acknowledged"])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")

    def test_idempotency_duplicate_webhook_audit_log(self):
        """Duplicate webhook creates a DUPLICATE_WEBHOOK_NOOP audit log entry."""
        body, sig = signed_fawry_webhook(
            self.gw, str(self.payment.transaction_id), "success", payment=self.payment
        )
        self._post_webhook(body, sig)
        self._post_webhook(body, sig)  # duplicate
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment,
                event_type="duplicate_webhook_noop",
            ).exists()
        )

    def test_unknown_transaction_acknowledged_not_error(self):
        """Webhook for an unknown transaction_id returns 200 (not 404) to prevent retries."""
        # amount doesn't matter here — unknown txn is short-circuited before amount check
        body, sig = signed_fawry_webhook(self.gw, str(uuid.uuid4()), "success", amount="5000.00")
        res = self._post_webhook(body, sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["data"]["acknowledged"])

    def test_pending_webhook_no_state_change(self):
        body, sig = signed_fawry_webhook(
            self.gw, str(self.payment.transaction_id), "pending", payment=self.payment
        )
        res = self._post_webhook(body, sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "processing")  # Unchanged

    def test_vodafone_webhook_success(self):
        vf_gw      = VodafoneGateway()
        vf_payment = make_payment(
            make_student(student_id="20210002", email="b@uni.edu.eg"),
            status="processing", used=True, payment_method="vodafone",
        )
        txn_id = str(vf_payment.transaction_id)
        ref    = f"VF-{txn_id.replace('-','').upper()[:10]}"
        amount = str(vf_payment.amount)   # FIX: use actual payment amount
        body   = {
            "transaction_id": txn_id,
            "vf_request_id":  ref,
            "status":         "success",
            "amount":         amount,
        }
        canonical = vf_gw.build_canonical_string(body)
        sig = vf_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "vodafone"})
        res = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        vf_payment.refresh_from_db()
        self.assertEqual(vf_payment.status, "paid")

    def test_vodafone_webhook_invalid_signature(self):
        vf_gw      = VodafoneGateway()
        vf_payment = make_payment(
            make_student(student_id="20210002", email="b@uni.edu.eg"),
            status="processing", used=True, payment_method="vodafone",
        )
        txn_id = str(vf_payment.transaction_id)
        ref    = f"VF-{txn_id.replace('-','').upper()[:10]}"
        amount = str(vf_payment.amount)
        body   = {
            "transaction_id": txn_id,
            "vf_request_id":  ref,
            "status":         "success",
            "amount":         amount,
        }
        canonical = vf_gw.build_canonical_string(body)
        body["signature"] = vf_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "vodafone"})
        res = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE="bad-signature")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "WEBHOOK_INVALID_SIGNATURE")
        vf_payment.refresh_from_db()
        self.assertEqual(vf_payment.status, "processing")

    def test_vodafone_header_signature_overrides_body_signature(self):
        vf_gw      = VodafoneGateway()
        vf_payment = make_payment(
            make_student(student_id="20210003", email="c@uni.edu.eg"),
            status="processing", used=True, payment_method="vodafone",
        )
        txn_id = str(vf_payment.transaction_id)
        ref    = f"VF-{txn_id.replace('-','').upper()[:10]}"
        amount = str(vf_payment.amount)
        body   = {
            "transaction_id": txn_id,
            "vf_request_id":  ref,
            "status":         "success",
            "amount":         amount,
        }
        canonical = vf_gw.build_canonical_string(body)
        body["signature"] = vf_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "vodafone"})
        res = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE="bad-signature")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "WEBHOOK_INVALID_SIGNATURE")
        vf_payment.refresh_from_db()
        self.assertEqual(vf_payment.status, "processing")

    def test_vodafone_duplicate_webhook_acknowledged_no_state_change(self):
        vf_gw      = VodafoneGateway()
        vf_payment = make_payment(
            make_student(student_id="20210004", email="d@uni.edu.eg"),
            status="processing", used=True, payment_method="vodafone",
        )
        txn_id = str(vf_payment.transaction_id)
        ref    = f"VF-{txn_id.replace('-','').upper()[:10]}"
        amount = str(vf_payment.amount)
        body   = {
            "transaction_id": txn_id,
            "vf_request_id":  ref,
            "status":         "success",
            "amount":         amount,
        }
        canonical = vf_gw.build_canonical_string(body)
        sig = vf_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "vodafone"})
        res1 = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        vf_payment.refresh_from_db()
        self.assertEqual(vf_payment.status, "paid")
        res2 = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertTrue(res2.data["data"]["acknowledged"])
        vf_payment.refresh_from_db()
        self.assertEqual(vf_payment.status, "paid")

    def test_vodafone_failed_webhook_marks_failed(self):
        vf_gw      = VodafoneGateway()
        vf_payment = make_payment(
            make_student(student_id="20210005", email="e@uni.edu.eg"),
            status="processing", used=True, payment_method="vodafone",
        )
        txn_id = str(vf_payment.transaction_id)
        ref    = f"VF-{txn_id.replace('-','').upper()[:10]}"
        amount = str(vf_payment.amount)
        body   = {
            "transaction_id": txn_id,
            "vf_request_id":  ref,
            "status":         "failed",
            "amount":         amount,
        }
        canonical = vf_gw.build_canonical_string(body)
        sig = vf_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "vodafone"})
        res = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        vf_payment.refresh_from_db()
        self.assertEqual(vf_payment.status, "failed")

    def test_vodafone_pending_webhook_no_state_change(self):
        vf_gw      = VodafoneGateway()
        vf_payment = make_payment(
            make_student(student_id="20210006", email="f@uni.edu.eg"),
            status="processing", used=True, payment_method="vodafone",
        )
        txn_id = str(vf_payment.transaction_id)
        ref    = f"VF-{txn_id.replace('-','').upper()[:10]}"
        amount = str(vf_payment.amount)
        body   = {
            "transaction_id": txn_id,
            "vf_request_id":  ref,
            "status":         "pending",
            "amount":         amount,
        }
        canonical = vf_gw.build_canonical_string(body)
        sig = vf_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "vodafone"})
        res = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        vf_payment.refresh_from_db()
        self.assertEqual(vf_payment.status, "processing")

    def test_vodafone_missing_fields_returns_error(self):
        vf_payment = make_payment(
            make_student(student_id="20210007", email="g@uni.edu.eg"),
            status="processing", used=True, payment_method="vodafone",
        )
        url = reverse("payments:payment-webhook", kwargs={"provider": "vodafone"})
        body = {"transaction_id": str(vf_payment.transaction_id)}
        res = self.client.post(url, body, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "WEBHOOK_VALIDATION_ERROR")
        vf_payment.refresh_from_db()
        self.assertEqual(vf_payment.status, "processing")

    def test_vodafone_unknown_transaction_acknowledged(self):
        vf_gw = VodafoneGateway()
        txn_id = str(uuid.uuid4())
        ref    = f"VF-{txn_id.replace('-','').upper()[:10]}"
        body   = {
            "transaction_id": txn_id,
            "vf_request_id":  ref,
            "status":         "success",
            "amount":         "5000.00",
        }
        canonical = vf_gw.build_canonical_string(body)
        sig = vf_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "vodafone"})
        res = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["data"]["acknowledged"])

    def test_vodafone_terminal_state_noop(self):
        vf_gw      = VodafoneGateway()
        vf_payment = make_payment(
            make_student(student_id="20210008", email="h@uni.edu.eg"),
            status="paid", used=True, payment_method="vodafone",
        )
        txn_id = str(vf_payment.transaction_id)
        ref    = f"VF-{txn_id.replace('-','').upper()[:10]}"
        amount = str(vf_payment.amount)
        body   = {
            "transaction_id": txn_id,
            "vf_request_id":  ref,
            "status":         "success",
            "amount":         amount,
        }
        canonical = vf_gw.build_canonical_string(body)
        sig = vf_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "vodafone"})
        res = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["data"]["acknowledged"])
        vf_payment.refresh_from_db()
        self.assertEqual(vf_payment.status, "paid")

    def test_bank_webhook_invalid_signature(self):
        bank_gw      = MockBankGateway()
        bank_payment = make_payment(
            make_student(student_id="20210009", email="i@uni.edu.eg"),
            status="processing", used=True, payment_method="bank",
        )
        txn_id = str(bank_payment.transaction_id)
        ref    = f"BNK-{txn_id[:8].upper()}"
        amount = str(bank_payment.amount)
        body   = {
            "transaction_id": txn_id,
            "bank_reference": ref,
            "status":         "success",
            "amount":         amount,
        }
        canonical = bank_gw.build_canonical_string(body)
        body["signature"] = bank_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "bank"})
        res = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE="bad-signature")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "WEBHOOK_INVALID_SIGNATURE")
        bank_payment.refresh_from_db()
        self.assertEqual(bank_payment.status, "processing")

    def test_bank_duplicate_webhook_acknowledged_no_state_change(self):
        bank_gw      = MockBankGateway()
        bank_payment = make_payment(
            make_student(student_id="20210010", email="j@uni.edu.eg"),
            status="processing", used=True, payment_method="bank",
        )
        txn_id = str(bank_payment.transaction_id)
        ref    = f"BNK-{txn_id[:8].upper()}"
        amount = str(bank_payment.amount)
        body   = {
            "transaction_id": txn_id,
            "bank_reference": ref,
            "status":         "success",
            "amount":         amount,
        }
        canonical = bank_gw.build_canonical_string(body)
        sig = bank_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "bank"})
        res1 = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        bank_payment.refresh_from_db()
        self.assertEqual(bank_payment.status, "paid")
        res2 = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertTrue(res2.data["data"]["acknowledged"])
        bank_payment.refresh_from_db()
        self.assertEqual(bank_payment.status, "paid")

    def test_bank_failed_webhook_marks_failed(self):
        bank_gw      = MockBankGateway()
        bank_payment = make_payment(
            make_student(student_id="20210011", email="k@uni.edu.eg"),
            status="processing", used=True, payment_method="bank",
        )
        txn_id = str(bank_payment.transaction_id)
        ref    = f"BNK-{txn_id[:8].upper()}"
        amount = str(bank_payment.amount)
        body   = {
            "transaction_id": txn_id,
            "bank_reference": ref,
            "status":         "failed",
            "amount":         amount,
        }
        canonical = bank_gw.build_canonical_string(body)
        sig = bank_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "bank"})
        res = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        bank_payment.refresh_from_db()
        self.assertEqual(bank_payment.status, "failed")

    def test_bank_pending_webhook_no_state_change(self):
        bank_gw      = MockBankGateway()
        bank_payment = make_payment(
            make_student(student_id="20210012", email="l@uni.edu.eg"),
            status="processing", used=True, payment_method="bank",
        )
        txn_id = str(bank_payment.transaction_id)
        ref    = f"BNK-{txn_id[:8].upper()}"
        amount = str(bank_payment.amount)
        body   = {
            "transaction_id": txn_id,
            "bank_reference": ref,
            "status":         "pending",
            "amount":         amount,
        }
        canonical = bank_gw.build_canonical_string(body)
        sig = bank_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "bank"})
        res = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        bank_payment.refresh_from_db()
        self.assertEqual(bank_payment.status, "processing")

    def test_bank_missing_fields_returns_error(self):
        bank_payment = make_payment(
            make_student(student_id="20210013", email="m@uni.edu.eg"),
            status="processing", used=True, payment_method="bank",
        )
        url = reverse("payments:payment-webhook", kwargs={"provider": "bank"})
        body = {"transaction_id": str(bank_payment.transaction_id)}
        res = self.client.post(url, body, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "WEBHOOK_VALIDATION_ERROR")
        bank_payment.refresh_from_db()
        self.assertEqual(bank_payment.status, "processing")

    def test_bank_unknown_transaction_acknowledged(self):
        bank_gw = MockBankGateway()
        txn_id = str(uuid.uuid4())
        ref    = f"BNK-{txn_id[:8].upper()}"
        body   = {
            "transaction_id": txn_id,
            "bank_reference": ref,
            "status":         "success",
            "amount":         "5000.00",
        }
        canonical = bank_gw.build_canonical_string(body)
        sig = bank_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "bank"})
        res = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["data"]["acknowledged"])

    def test_bank_terminal_state_noop(self):
        bank_gw      = MockBankGateway()
        bank_payment = make_payment(
            make_student(student_id="20210014", email="n@uni.edu.eg"),
            status="paid", used=True, payment_method="bank",
        )
        txn_id = str(bank_payment.transaction_id)
        ref    = f"BNK-{txn_id[:8].upper()}"
        amount = str(bank_payment.amount)
        body   = {
            "transaction_id": txn_id,
            "bank_reference": ref,
            "status":         "success",
            "amount":         amount,
        }
        canonical = bank_gw.build_canonical_string(body)
        sig = bank_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "bank"})
        res = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["data"]["acknowledged"])
        bank_payment.refresh_from_db()
        self.assertEqual(bank_payment.status, "paid")

    def test_bank_header_signature_overrides_body_signature(self):
        bank_gw      = MockBankGateway()
        bank_payment = make_payment(
            make_student(student_id="20210015", email="o@uni.edu.eg"),
            status="processing", used=True, payment_method="bank",
        )
        txn_id = str(bank_payment.transaction_id)
        ref    = f"BNK-{txn_id[:8].upper()}"
        amount = str(bank_payment.amount)
        body   = {
            "transaction_id": txn_id,
            "bank_reference": ref,
            "status":         "success",
            "amount":         amount,
        }
        canonical = bank_gw.build_canonical_string(body)
        body["signature"] = bank_gw.compute_hmac_signature(canonical)
        url = reverse("payments:payment-webhook", kwargs={"provider": "bank"})
        res = self.client.post(url, body, format="json", HTTP_X_WEBHOOK_SIGNATURE="bad-signature")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "WEBHOOK_INVALID_SIGNATURE")
        bank_payment.refresh_from_db()
        self.assertEqual(bank_payment.status, "processing")


# ── Full flow integration test ─────────────────────────────────────────────────

class FullPaymentFlowTests(TestCase):
    """
    End-to-end: create → submit → webhook success → verify paid.
    """

    def setUp(self):
        self.client  = APIClient()
        self.student = make_student()
        self.gw      = FawryGateway()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user_flow",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

    def test_complete_happy_path(self):
        # Step 1: Create payment (amount is calculated server-side from student fees)
        res = self.client.post(
            reverse("payments:payment-start"),
            {"student_id": "20210001"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        txn_id = res.data["data"]["transaction_id"]

        # Step 2: Submit to Fawry
        res = self.client.post(
            reverse("payments:payment-submit", kwargs={"transaction_id": txn_id}),
            {"provider": "fawry"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["data"]["status"], "processing")

        # Step 3: Build webhook using the real payment amount from DB
        # FIX: signed_fawry_webhook now fetches the correct amount automatically
        body, sig = signed_fawry_webhook(self.gw, str(txn_id), "success")
        res = self.client.post(
            reverse("payments:payment-webhook", kwargs={"provider": "fawry"}),
            body,
            format="json",
            HTTP_X_WEBHOOK_SIGNATURE=sig,
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["data"]["current_status"], "paid")

        # Step 4: Verify via detail endpoint
        res = self.client.get(
            reverse("payments:payment-detail", kwargs={"transaction_id": txn_id})
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertEqual(data["status"], "paid")
        # Audit trail must contain all key events
        event_types = [log["event_type"] for log in data["audit_logs"]]
        self.assertIn("initiated",  event_types)
        self.assertIn("processing", event_types)
        self.assertIn("webhook",    event_types)
        self.assertIn("success",    event_types)

    def test_failed_payment_flow(self):
        # Use a DIFFERENT student to avoid collision with test_complete_happy_path.
        # Both tests run in the same semester; if they share student_id="20210001",
        # the second test gets back the already-paid payment from the first test
        # and the idempotency block returns "paid" instead of processing the failure.
        make_student(student_id="20210099", email="fail_test@uni.edu.eg")

        # Step 1: Create payment for the isolated student
        res = self.client.post(
            reverse("payments:payment-start"),
            {"student_id": "20210099"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        txn_id = res.data["data"]["transaction_id"]

        # Step 2: Submit to gateway
        self.client.post(
            reverse("payments:payment-submit", kwargs={"transaction_id": txn_id}),
            {"provider": "fawry"},
            format="json",
        )

        # Step 3: Gateway reports failure — amount fetched from DB automatically
        body, sig = signed_fawry_webhook(self.gw, str(txn_id), "failed")
        res = self.client.post(
            reverse("payments:payment-webhook", kwargs={"provider": "fawry"}),
            body,
            format="json",
            HTTP_X_WEBHOOK_SIGNATURE=sig,
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["data"]["current_status"], "failed")

        payment = Payment.objects.get(transaction_id=txn_id)
        self.assertEqual(payment.status, "failed")
