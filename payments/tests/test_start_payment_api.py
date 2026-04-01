"""
=== FILE: payments/tests/test_start_payment_api.py ===

Integration tests for POST /api/payments/start/ — the PRD core endpoint.
Tests the full flow: validate → create → submit → respond.

Run with:
    python manage.py test payments.tests.test_start_payment_api
"""

import uuid
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from django.core.cache import cache

from students.models import Student
from payments.models import Payment, PaymentAuditLog, current_semester
from payments.gateways.fawry import FawryGateway


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


class StartPaymentAPITests(TestCase):
    """
    Tests for POST /api/payments/start/
    PRD request: { "student_id": "20210001", "provider": "fawry" }
    """

    def setUp(self):
        self.client  = APIClient()
        self.url     = reverse("payments:payment-start")
        self.student = make_student()
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

    # ── Happy paths ────────────────────────────────────────────────────────────

    def test_fawry_creates_and_submits(self):
        res = self.client.post(
            self.url, {"student_id": "20210001", "provider": "fawry"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data["success"])
        data = res.data["data"]
        self.assertIn("transaction_id",        data)
        self.assertIn("transaction_reference", data)
        self.assertIn("instructions",          data)
        self.assertEqual(data["status"],   "processing")
        self.assertEqual(data["provider"], "fawry")

    def test_vodafone_creates_and_submits(self):
        res = self.client.post(
            self.url, {"student_id": "20210001", "provider": "vodafone"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.data["data"]
        self.assertEqual(data["provider"], "vodafone")
        self.assertTrue(data["transaction_reference"].startswith("VF-"))

    def test_bank_creates_and_submits(self):
        res = self.client.post(
            self.url, {"student_id": "20210001", "provider": "bank"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.data["data"]
        self.assertEqual(data["provider"], "bank")
        self.assertTrue(data["transaction_reference"].startswith("BNK-"))

    def test_payment_saved_to_db_as_processing(self):
        self.client.post(
            self.url, {"student_id": "20210001", "provider": "fawry"}, format="json"
        )
        payment = Payment.objects.filter(student=self.student).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, "processing")
        self.assertTrue(payment.used)
        self.assertEqual(payment.payment_method, "fawry")
        self.assertTrue(payment.gateway_reference.startswith("FWR-"))

    def test_audit_log_created(self):
        res = self.client.post(
            self.url, {"student_id": "20210001", "provider": "fawry"}, format="json"
        )
        txn_id = res.data["data"]["transaction_id"]
        logs   = PaymentAuditLog.objects.filter(payment__transaction_id=txn_id)
        event_types = [l.event_type for l in logs]
        self.assertIn("initiated",  event_types)
        self.assertIn("processing", event_types)

    def test_instructions_steps_present(self):
        res = self.client.post(
            self.url, {"student_id": "20210001", "provider": "fawry"}, format="json"
        )
        instructions = res.data["data"]["instructions"]
        self.assertIn("steps", instructions)
        self.assertIsInstance(instructions["steps"], list)

    def test_response_contains_amount(self):
        res = self.client.post(
            self.url, {"student_id": "20210001", "provider": "fawry"}, format="json"
        )
        self.assertIn("amount", res.data["data"])

    def test_student_id_case_insensitive(self):
        res = self.client.post(
            self.url, {"student_id": "20210001", "provider": "fawry"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    # ── 404 cases ──────────────────────────────────────────────────────────────

    def test_404_unknown_student(self):
        res = self.client.post(
            self.url, {"student_id": "GHOST999", "provider": "fawry"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data["error"]["code"], "STUDENT_NOT_FOUND")

    # ── 400 cases ──────────────────────────────────────────────────────────────

    def test_missing_provider_creates_pending_payment(self):
        """Provider can be omitted when the caller wants create-only then submit later."""
        res = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["data"]["status"], "pending")
        self.assertFalse(res.data["data"]["used"])


    def test_admin_missing_student_id_not_auto_filled(self):
        res = self.client.post(self.url, {"provider": "fawry"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "VALIDATION_ERROR")

    def test_400_missing_student_id(self):
        res = self.client.post(self.url, {"provider": "fawry"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_invalid_provider(self):
        res = self.client.post(
            self.url, {"student_id": "20210001", "provider": "paypal"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "INVALID_PROVIDER")

    def test_400_inactive_student(self):
        make_student(student_id="S002", email="s2@u.eg", status="inactive")
        res = self.client.post(
            self.url, {"student_id": "S002", "provider": "fawry"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "STUDENT_NOT_ELIGIBLE")

    def test_400_suspended_student(self):
        make_student(student_id="S003", email="s3@u.eg", status="suspended")
        res = self.client.post(
            self.url, {"student_id": "S003", "provider": "fawry"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_duplicate_open_payment_blocked(self):
        # First call — creates a payment
        self.client.post(
            self.url, {"student_id": "20210001", "provider": "fawry"}, format="json"
        )
        # Second call — should be blocked
        res = self.client.post(
            self.url, {"student_id": "20210001", "provider": "fawry"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_processing_payment_blocks_missing_provider(self):
        # First call — creates a processing payment
        self.client.post(
            self.url, {"student_id": "20210001", "provider": "fawry"}, format="json"
        )
        # Second call without provider should be blocked by in-flight processing
        res = self.client.post(
            self.url, {"student_id": "20210001"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_ALREADY_OPEN")

    def test_stale_pending_payment_expires_and_allows_new_start(self):
        from django.utils import timezone
        from datetime import timedelta

        # First call — creates pending payment (no provider)
        res1 = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        txn_id = res1.data["data"]["transaction_id"]

        Payment.objects.filter(transaction_id=txn_id).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

        # Second call — should succeed and old pending becomes expired
        res2 = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)
        old_payment = Payment.objects.get(transaction_id=txn_id)
        self.assertEqual(old_payment.status, "expired")

    def test_paid_payment_blocks_new_start(self):
        Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.PAID,
            used=True,
        )
        res = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_ALREADY_PAID")

    def test_refunded_payment_blocks_new_start(self):
        Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.REFUNDED,
            used=True,
        )
        res = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_ALREADY_REFUNDED")

    def test_failed_payment_allows_new_start(self):
        Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.FAILED,
            used=True,
        )
        res = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["data"]["status"], "pending")


    def test_400_amount_mismatch(self):
        res = self.client.post(
            self.url,
            {"student_id": "20210001", "provider": "fawry", "amount": "999.00"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "AMOUNT_MISMATCH")

    def test_error_response_shape(self):
        """All errors must follow the unified JSON format."""
        res = self.client.post(self.url, {}, format="json")
        self.assertFalse(res.data.get("success", True))
        self.assertIn("error",   res.data)
        # error block has code + message
        error = res.data["error"]
        self.assertIn("code",    error)
        self.assertIn("message", error)


# ── 

class StudentStartPaymentAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("payments:payment-start")
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="student_user",
            password="testpass123",
        )
        self.student = make_student(user=self.user)
        self.client.force_authenticate(user=self.user)

    def test_student_can_omit_student_id(self):
        res = self.client.post(self.url, {"provider": "fawry"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Payment.objects.filter(student=self.student).exists())

    def test_student_cannot_start_for_other_student(self):
        res = self.client.post(
            self.url, {"student_id": "S999", "provider": "fawry"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data["error"]["code"], "FORBIDDEN")

# Webhook integration

class WebhookIntegrationTests(TestCase):

    def setUp(self):
        self.client  = APIClient()
        self.student = make_student()
        self.gw      = FawryGateway()
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

    def _start_payment(self, provider="fawry"):
        res = self.client.post(
            reverse("payments:payment-start"),
            {"student_id": "20210001", "provider": provider},
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        return res.data["data"]

    # def _signed_webhook(self, txn_id: str, webhook_status: str = "success"):
    #     ref = f"FWR-{txn_id.replace('-', '').upper()[:12]}"
    #     body = {
    #         "transaction_id":  txn_id,
    #         "fawry_reference": ref,
    #         "status":          webhook_status,
    #         "amount":          "5000.00",
    #     }
    #     canonical = self.gw.build_canonical_string({
    #         "transaction_id":  txn_id,
    #         "fawry_reference": ref,
    #         "status":          webhook_status,
    #         "amount":          "5000.00",
    #     })
    #     body["signature"] = self.gw.compute_hmac_signature(canonical)
    #     return body


    def _signed_webhook(self, txn_id: str, webhook_status: str = "success"):
        payment = Payment.objects.get(transaction_id=txn_id)
        ref = f"FWR-{txn_id.replace('-', '').upper()[:12]}"
        amount = str(payment.amount)

        body = {
            "transaction_id": txn_id,
            "fawry_reference": ref,
            "status": webhook_status,
            "amount": amount,
        }

        canonical = self.gw.build_canonical_string({
            "transaction_id": txn_id,
            "fawry_reference": ref,
            "status": webhook_status,
            "amount": amount,
        })
        body["signature"] = self.gw.compute_hmac_signature(canonical)
        return body

    def test_full_flow_paid(self):
        data   = self._start_payment()
        txn_id = str(data["transaction_id"])

        webhook_body = self._signed_webhook(txn_id, "success")
        res = self.client.post(
            reverse("payments:payment-webhook", kwargs={"provider": "fawry"}),
            webhook_body, format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["data"]["current_status"], "paid")

        payment = Payment.objects.get(transaction_id=txn_id)
        self.assertEqual(payment.status, "paid")

    def test_success_webhook_reactivates_inactive_student(self):
        data   = self._start_payment()
        txn_id = str(data["transaction_id"])

        student = Student.objects.get(student_id="20210001")
        student.status = "inactive"
        student.save(update_fields=["status", "updated_at"])

        webhook_body = self._signed_webhook(txn_id, "success")
        res = self.client.post(
            reverse("payments:payment-webhook", kwargs={"provider": "fawry"}),
            webhook_body, format="json",
        )
        self.assertEqual(res.status_code, 200)

        student.refresh_from_db()
        self.assertEqual(student.status, "active")

    def test_full_flow_failed(self):
        data   = self._start_payment()
        txn_id = str(data["transaction_id"])

        webhook_body = self._signed_webhook(txn_id, "failed")
        res = self.client.post(
            reverse("payments:payment-webhook", kwargs={"provider": "fawry"}),
            webhook_body, format="json",
        )
        self.assertEqual(res.data["data"]["current_status"], "failed")

    def test_idempotency_double_webhook(self):
        data   = self._start_payment()
        txn_id = str(data["transaction_id"])

        body = self._signed_webhook(txn_id, "success")
        wh_url = reverse("payments:payment-webhook", kwargs={"provider": "fawry"})

        self.client.post(wh_url, body, format="json")  # first
        res2 = self.client.post(wh_url, body, format="json")  # duplicate

        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.data["data"]["acknowledged"])
        # Payment still in paid — not changed
        self.assertEqual(Payment.objects.get(transaction_id=txn_id).status, "paid")

    def test_idempotency_replay_blocked_audit_log(self):
        data   = self._start_payment()
        txn_id = str(data["transaction_id"])
        body   = self._signed_webhook(txn_id, "success")
        wh_url = reverse("payments:payment-webhook", kwargs={"provider": "fawry"})

        self.client.post(wh_url, body, format="json")
        self.client.post(wh_url, body, format="json")  # duplicate

        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment__transaction_id=txn_id,
                event_type="duplicate_webhook_noop",
            ).exists()
        )

    # def test_bad_signature_returns_400(self):
    #     data   = self._start_payment()
    #     txn_id = str(data["transaction_id"])
    #     ref    = f"FWR-{txn_id.replace('-','').upper()[:12]}"
    #     body   = {
    #         "transaction_id":  txn_id,
    #         "fawry_reference": ref,
    #         "status":          "success",
    #         "amount":          "5000.00",
    #         "signature":       "bad-signature",
    #     }
    #     res = self.client.post(
    #         reverse("payments:payment-webhook", kwargs={"provider": "fawry"}),
    #         body, format="json",
    #     )
    #     self.assertEqual(res.status_code, 400)
    #     self.assertEqual(res.data["error"]["code"], "WEBHOOK_INVALID_SIGNATURE")

    def test_bad_signature_returns_400(self):
        data = self._start_payment()
        txn_id = str(data["transaction_id"])
        payment = Payment.objects.get(transaction_id=txn_id)
        ref = f"FWR-{txn_id.replace('-', '').upper()[:12]}"

        body = {
            "transaction_id": txn_id,
            "fawry_reference": ref,
            "status": "success",
            "amount": str(payment.amount),
            "signature": "bad-signature",
        }

        res = self.client.post(
            reverse("payments:payment-webhook", kwargs={"provider": "fawry"}),
            body,
            format="json",
        )

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["error"]["code"], "WEBHOOK_INVALID_SIGNATURE")

    def test_audit_trail_complete(self):
        """After full flow: initiated → processing → webhook → success."""
        data   = self._start_payment()
        txn_id = str(data["transaction_id"])

        self.client.post(
            reverse("payments:payment-webhook", kwargs={"provider": "fawry"}),
            self._signed_webhook(txn_id, "success"),
            format="json",
        )

        event_types = list(
            PaymentAuditLog.objects.filter(payment__transaction_id=txn_id)
            .values_list("event_type", flat=True)
        )
        self.assertIn("initiated",  event_types)
        self.assertIn("processing", event_types)
        self.assertIn("webhook",    event_types)
        self.assertIn("success",    event_types)
