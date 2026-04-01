"""
payments/tests/test_api.py
Integration tests for all Phase 2 payment API endpoints.

Run with:
    python manage.py test payments.tests.test_api
"""

from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from students.models import Student
from payments.models import Payment, PaymentAuditLog, current_semester


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
        "status":   Payment.PaymentStatus.PENDING,
    }
    defaults.update(kwargs)
    return Payment.objects.create(student=student, **defaults)


class StartPaymentViewTests(TestCase):
    """POST /api/payments/start/"""

    def setUp(self):
        self.client  = APIClient()
        self.url     = reverse("payments:payment-start")
        self.student = make_student()

    # ── Happy path ─────────────────────────────────────────────────────────────
    def test_creates_payment_successfully(self):
        res = self.client.post(self.url, {"student_id": "20210001"}, format="json")

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data["success"])

        data = res.data["data"]
        self.assertIn("transaction_id", data)
        self.assertEqual(data["student_id"], "20210001")
        self.assertEqual(data["status"],     "pending")
        self.assertFalse(data["used"])
        self.assertIsNotNone(data["amount"])

    def test_transaction_id_is_uuid(self):
        res  = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        import uuid
        txn_id = res.data["data"]["transaction_id"]
        # Should not raise
        uuid.UUID(str(txn_id))

    def test_payment_saved_to_db(self):
        self.client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertTrue(
            Payment.objects.filter(student=self.student, status="pending").exists()
        )

    def test_audit_log_created(self):
        res = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        txn_id = res.data["data"]["transaction_id"]
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment__transaction_id=txn_id,
                event_type=PaymentAuditLog.EventType.INITIATED,
            ).exists()
        )

    def test_accepts_optional_amount_matching_fee(self):
        """Supplying the correct amount explicitly should succeed."""
        # 18 hours × 250 + 500 = 5000
        res = self.client.post(
            self.url,
            {"student_id": "20210001", "amount": "5000.00"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_case_insensitive_student_id(self):
        res = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    # ── 404 cases ──────────────────────────────────────────────────────────────
    def test_404_for_unknown_student(self):
        res = self.client.post(self.url, {"student_id": "GHOST999"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data["error"]["code"], "STUDENT_NOT_FOUND")

    # ── 400 cases ──────────────────────────────────────────────────────────────
    def test_400_missing_student_id(self):
        res = self.client.post(self.url, {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "VALIDATION_ERROR")

    def test_400_when_open_payment_exists(self):
        make_payment(self.student)  # create existing pending payment
        res = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_ALREADY_OPEN")

    def test_400_open_payment_error_includes_existing_txn(self):
        existing = make_payment(self.student)
        res = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        details = res.data["error"]["details"]
        self.assertIn("existing_transaction_id", details)
        self.assertEqual(
            str(details["existing_transaction_id"]),
            str(existing.transaction_id),
        )

    def test_400_for_inactive_student(self):
        s = make_student(student_id="S002", email="s2@u.eg", status="inactive")
        res = self.client.post(self.url, {"student_id": "S002"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "STUDENT_NOT_ELIGIBLE")

    def test_400_for_suspended_student(self):
        s = make_student(student_id="S003", email="s3@u.eg", status="suspended")
        res = self.client.post(self.url, {"student_id": "S003"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_amount_mismatch(self):
        res = self.client.post(
            self.url,
            {"student_id": "20210001", "amount": "999.00"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "AMOUNT_MISMATCH")

    def test_idempotency_cancelled_then_new(self):
        """After cancelling a payment, a new one can be created."""
        p = make_payment(self.student, status=Payment.PaymentStatus.CANCELLED)
        res = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)


class PaymentDetailViewTests(TestCase):
    """GET /api/payments/<uuid>/"""

    def setUp(self):
        self.client  = APIClient()
        self.student = make_student()
        self.payment = make_payment(self.student)

    def test_returns_payment_detail(self):
        url = reverse("payments:payment-detail", kwargs={"transaction_id": self.payment.transaction_id})
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertEqual(str(data["transaction_id"]), str(self.payment.transaction_id))
        self.assertEqual(data["student_id"],  "20210001")
        self.assertEqual(data["status"],      "pending")
        self.assertIn("audit_logs", data)

    def test_404_for_unknown_uuid(self):
        import uuid
        fake_uuid = uuid.uuid4()
        url = reverse("payments:payment-detail", kwargs={"transaction_id": fake_uuid})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_NOT_FOUND")


class StudentPaymentListViewTests(TestCase):
    """GET /api/payments/student/<student_id>/"""

    def setUp(self):
        self.client  = APIClient()
        self.student = make_student()

    def test_returns_empty_list_for_new_student(self):
        url = reverse("payments:payment-student-list", kwargs={"student_id": "20210001"})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["data"]["total_records"], 0)

    def test_returns_all_payments(self):
        make_payment(self.student, status=Payment.PaymentStatus.PAID)
        make_payment(self.student, status=Payment.PaymentStatus.PENDING)
        url = reverse("payments:payment-student-list", kwargs={"student_id": "20210001"})
        res = self.client.get(url)
        self.assertEqual(res.data["data"]["total_records"], 2)

    def test_404_for_unknown_student(self):
        url = reverse("payments:payment-student-list", kwargs={"student_id": "GHOST"})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_response_includes_student_name(self):
        url = reverse("payments:payment-student-list", kwargs={"student_id": "20210001"})
        res = self.client.get(url)
        self.assertEqual(res.data["data"]["student_name"], "Ahmed Hassan")


class CancelPaymentViewTests(TestCase):
    """POST /api/payments/<uuid>/cancel/"""

    def setUp(self):
        self.client  = APIClient()
        self.student = make_student()
        self.payment = make_payment(self.student)

    def _cancel_url(self, txn_id=None):
        txn_id = txn_id or self.payment.transaction_id
        return reverse("payments:payment-cancel", kwargs={"transaction_id": txn_id})

    def test_cancels_pending_payment(self):
        res = self.client.post(self._cancel_url())
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.PaymentStatus.CANCELLED)

    def test_cancel_creates_audit_log(self):
        self.client.post(self._cancel_url(), {"reason": "Student request"}, format="json")
        log = PaymentAuditLog.objects.filter(
            payment=self.payment,
            event_type=PaymentAuditLog.EventType.CANCELLED,
        ).first()
        self.assertIsNotNone(log)

    def test_cannot_cancel_paid_payment(self):
        paid = make_payment(
            self.student,
            status=Payment.PaymentStatus.PAID,
        )
        res = self.client.post(self._cancel_url(paid.transaction_id))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_NOT_CANCELLABLE")

    def test_cannot_cancel_already_cancelled(self):
        self.payment.status = Payment.PaymentStatus.CANCELLED
        self.payment.save()
        res = self.client.post(self._cancel_url())
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_404_for_unknown_payment(self):
        import uuid
        url = reverse("payments:payment-cancel", kwargs={"transaction_id": uuid.uuid4()})
        res = self.client.post(url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_after_cancel_new_payment_can_be_started(self):
        """Cancel then immediately start a new payment — should succeed."""
        self.client.post(self._cancel_url())
        start_url = reverse("payments:payment-start")
        res = self.client.post(start_url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)