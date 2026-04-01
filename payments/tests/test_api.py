"""
payments/tests/test_api.py
Integration tests for all Phase 2 payment API endpoints.

Run with:
    python manage.py test payments.tests.test_api
"""

from decimal import Decimal
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.core.cache import cache
from django.contrib.auth import get_user_model

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
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

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
        # 18 hours × 500 + 200 + 100 = 9300
        res = self.client.post(
            self.url,
            {"student_id": "20210001", "amount": "9300.00"},
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

    @override_settings(ABUSE_PAYMENT_START_MAX=1, ABUSE_PAYMENT_START_WINDOW_SECONDS=300)
    def test_payment_start_rate_limited(self):
        res1 = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        res2 = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res2.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(res2.data["error"]["code"], "PAYMENT_START_RATE_LIMITED")

    def test_idempotency_cancelled_then_new(self):
        """After cancelling a payment, a new one can be created."""
        p = make_payment(self.student, status=Payment.PaymentStatus.CANCELLED)
        res = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_expired_payment_allows_new(self):
        from django.utils import timezone
        from datetime import timedelta

        make_payment(
            self.student,
            status=Payment.PaymentStatus.EXPIRED,
            expires_at=timezone.now() - timedelta(days=1),
        )
        res = self.client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_student_cannot_start_for_other_student(self):
        User = get_user_model()
        student_user = User.objects.create_user(username="student_user", password="testpass123")
        make_student(student_id="S002", email="s2@u.eg", user=student_user)
        client = APIClient()
        client.force_authenticate(user=student_user)
        res = client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_user_without_student_profile_denied(self):
        User = get_user_model()
        unlinked_user = User.objects.create_user(username="no_profile", password="pass")
        client = APIClient()
        client.force_authenticate(user=unlinked_user)
        res = client.post(self.url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data["error"]["code"], "STUDENT_PROFILE_MISSING")


class PaymentDetailViewTests(TestCase):
    """GET /api/payments/<uuid>/"""

    def setUp(self):
        self.client  = APIClient()
        self.student = make_student()
        self.payment = make_payment(self.student)
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

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

    def test_forbidden_for_other_student(self):
        User = get_user_model()
        other_user = User.objects.create_user(username="other", password="pass")
        make_student(student_id="S002", email="s2@u.eg", user=other_user)
        client = APIClient()
        client.force_authenticate(user=other_user)
        url = reverse("payments:payment-detail", kwargs={"transaction_id": self.payment.transaction_id})
        res = client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_forbidden_without_student_profile(self):
        User = get_user_model()
        user = User.objects.create_user(username="no_profile", password="pass")
        client = APIClient()
        client.force_authenticate(user=user)
        url = reverse("payments:payment-detail", kwargs={"transaction_id": self.payment.transaction_id})
        res = client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_student_receives_sanitized_detail(self):
        User = get_user_model()
        student_user = User.objects.create_user(username="student_user", password="pass")
        student = make_student(student_id="S002", email="s2@u.eg", user=student_user)
        payment = make_payment(student, status=Payment.PaymentStatus.PENDING)
        PaymentAuditLog.objects.create(
            payment=payment,
            event_type=PaymentAuditLog.EventType.WEBHOOK,
            amount=payment.amount,
            actor="fawry",
            payload={"transaction_reference": "FWR-SECRET-REF"},
        )
        client = APIClient()
        client.force_authenticate(user=student_user)
        url = reverse("payments:payment-detail", kwargs={"transaction_id": payment.transaction_id})
        res = client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertIn("transaction_id", data)
        self.assertIn("status", data)
        self.assertIn("amount", data)
        self.assertNotIn("audit_logs", data)


class StudentPaymentListViewTests(TestCase):
    """GET /api/payments/student/<student_id>/"""

    def setUp(self):
        self.client  = APIClient()
        self.student = make_student()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

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

    def test_forbidden_for_other_student(self):
        User = get_user_model()
        student_user = User.objects.create_user(username="student_user", password="pass")
        make_student(student_id="S002", email="s2@u.eg", user=student_user)
        client = APIClient()
        client.force_authenticate(user=student_user)
        url = reverse("payments:payment-student-list", kwargs={"student_id": "20210001"})
        res = client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


class StudentPaymentStatusViewTests(TestCase):
    """GET /api/payments/student/status/"""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="student_user", password="pass")
        self.student = make_student(user=self.user)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("payments:payment-student-status")

    def test_status_allows_start_for_new_student(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertEqual(data["student_id"], self.student.student_id)
        self.assertTrue(data["can_start_payment"])
        self.assertIsNone(data["reason_code"])
        self.assertIsNone(data["current_payment"])

    def test_status_blocks_processing_payment(self):
        make_payment(
            self.student,
            status=Payment.PaymentStatus.PROCESSING,
            used=True,
            payment_method="fawry",
        )
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertFalse(data["can_start_payment"])
        self.assertEqual(data["reason_code"], "PAYMENT_ALREADY_OPEN")
        self.assertEqual(data["current_payment"]["status"], "processing")

    def test_status_blocks_paid_payment(self):
        make_payment(
            self.student,
            status=Payment.PaymentStatus.PAID,
            used=True,
        )
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertFalse(data["can_start_payment"])
        self.assertEqual(data["reason_code"], "PAYMENT_ALREADY_PAID")
        self.assertEqual(data["current_payment"]["status"], "paid")

    def test_unauthenticated_rejected(self):
        client = APIClient()
        res = client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class StudentPaymentHistoryViewTests(TestCase):
    """GET /api/payments/student/payments/"""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="student_user", password="pass")
        self.student = make_student(user=self.user)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("payments:payment-student-history")

    def test_returns_only_current_student_payments(self):
        other_student = make_student(student_id="S002", email="s2@u.eg")
        make_payment(other_student, status=Payment.PaymentStatus.PAID)
        p1 = make_payment(self.student, status=Payment.PaymentStatus.PAID)
        p2 = make_payment(self.student, status=Payment.PaymentStatus.PENDING)

        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        items = res.data["data"]["payments"]
        ids = {item["transaction_id"] for item in items}
        self.assertEqual(ids, {str(p1.transaction_id), str(p2.transaction_id)})

    def test_returns_newest_first(self):
        from django.utils import timezone
        from datetime import timedelta

        older = make_payment(self.student, status=Payment.PaymentStatus.PAID)
        newer = make_payment(self.student, status=Payment.PaymentStatus.PENDING)
        Payment.objects.filter(transaction_id=older.transaction_id).update(
            created_at=timezone.now() - timedelta(days=1)
        )
        Payment.objects.filter(transaction_id=newer.transaction_id).update(
            created_at=timezone.now()
        )

        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        items = res.data["data"]["payments"]
        self.assertEqual(items[0]["transaction_id"], str(newer.transaction_id))
        self.assertEqual(items[1]["transaction_id"], str(older.transaction_id))

    def test_unauthenticated_rejected(self):
        client = APIClient()
        res = client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class StudentPaymentDetailViewTests(TestCase):
    """GET /api/payments/student/payments/<uuid>/"""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="student_user", password="pass")
        self.student = make_student(user=self.user)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_student_can_fetch_own_payment_detail(self):
        payment = make_payment(self.student, status=Payment.PaymentStatus.PAID)
        url = reverse("payments:payment-student-detail", kwargs={"transaction_id": payment.transaction_id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertEqual(data["transaction_id"], str(payment.transaction_id))
        self.assertEqual(data["status"], payment.status)

    def test_student_cannot_fetch_other_payment(self):
        other_student = make_student(student_id="S002", email="s2@u.eg")
        other_payment = make_payment(other_student, status=Payment.PaymentStatus.PAID)
        url = reverse("payments:payment-student-detail", kwargs={"transaction_id": other_payment.transaction_id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_rejected(self):
        payment = make_payment(self.student, status=Payment.PaymentStatus.PAID)
        client = APIClient()
        url = reverse("payments:payment-student-detail", kwargs={"transaction_id": payment.transaction_id})
        res = client.get(url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class StudentPaymentNextActionViewTests(TestCase):
    """GET /api/payments/student/next-action/"""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="student_user", password="pass")
        self.student = make_student(user=self.user)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("payments:payment-student-next-action")

    def test_pending_maps_to_submit(self):
        make_payment(self.student, status=Payment.PaymentStatus.PENDING, used=False)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertEqual(data["next_action"], "submit")
        self.assertEqual(data["reason_code"], "PAYMENT_ALREADY_OPEN")

    def test_processing_maps_to_wait(self):
        make_payment(
            self.student,
            status=Payment.PaymentStatus.PROCESSING,
            used=True,
            payment_method="fawry",
        )
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertEqual(data["next_action"], "wait")
        self.assertEqual(data["reason_code"], "PAYMENT_ALREADY_OPEN")

    def test_paid_maps_to_none(self):
        make_payment(self.student, status=Payment.PaymentStatus.PAID, used=True)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertEqual(data["next_action"], "none")
        self.assertEqual(data["reason_code"], "PAYMENT_ALREADY_PAID")

    def test_unauthenticated_rejected(self):
        client = APIClient()
        res = client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class CancelPaymentViewTests(TestCase):
    """POST /api/payments/<uuid>/cancel/"""

    def setUp(self):
        self.client  = APIClient()
        self.student = make_student()
        self.payment = make_payment(self.student)
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

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

    def test_actor_is_server_controlled(self):
        self.client.post(
            self._cancel_url(),
            {"reason": "Test", "actor": "student"},
            format="json",
        )
        log = PaymentAuditLog.objects.filter(
            payment=self.payment,
            event_type=PaymentAuditLog.EventType.CANCELLED,
        ).order_by("-created_at").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, "admin")

    def test_student_cannot_spoof_admin_actor(self):
        User = get_user_model()
        student_user = User.objects.create_user(username="student_user", password="pass")
        student = make_student(student_id="S010", email="s10@u.eg", user=student_user)
        payment = make_payment(student)
        client = APIClient()
        client.force_authenticate(user=student_user)
        url = reverse("payments:payment-cancel", kwargs={"transaction_id": payment.transaction_id})
        res = client.post(url, {"reason": "Test", "actor": "admin"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        log = PaymentAuditLog.objects.filter(
            payment=payment,
            event_type=PaymentAuditLog.EventType.CANCELLED,
        ).order_by("-created_at").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, "student")

    def test_cannot_cancel_paid_payment(self):
        paid = make_payment(
            self.student,
            status=Payment.PaymentStatus.PAID,
        )
        res = self.client.post(self._cancel_url(paid.transaction_id))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_NOT_CANCELLABLE")

    def test_cannot_cancel_processing_payment(self):
        processing = make_payment(
            self.student,
            status=Payment.PaymentStatus.PROCESSING,
            used=True,
            payment_method="fawry",
        )
        res = self.client.post(self._cancel_url(processing.transaction_id))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_NOT_CANCELLABLE")

    def test_cannot_cancel_failed_or_refunded_payment(self):
        failed = make_payment(
            self.student,
            status=Payment.PaymentStatus.FAILED,
            used=True,
        )
        refunded = make_payment(
            self.student,
            status=Payment.PaymentStatus.REFUNDED,
            used=True,
        )
        res_failed = self.client.post(self._cancel_url(failed.transaction_id))
        self.assertEqual(res_failed.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res_failed.data["error"]["code"], "PAYMENT_NOT_CANCELLABLE")
        res_refunded = self.client.post(self._cancel_url(refunded.transaction_id))
        self.assertEqual(res_refunded.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res_refunded.data["error"]["code"], "PAYMENT_NOT_CANCELLABLE")

    def test_cannot_cancel_pending_used_payment(self):
        pending_used = make_payment(
            make_student(student_id="S009", email="s9@u.eg"),
            status=Payment.PaymentStatus.PENDING,
            used=True,
        )
        res = self.client.post(self._cancel_url(pending_used.transaction_id))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_NOT_CANCELLABLE")

    def test_cannot_cancel_already_cancelled(self):
        self.payment.status = Payment.PaymentStatus.CANCELLED
        self.payment.save()
        res = self.client.post(self._cancel_url())
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_cancel_expired_payment(self):
        from django.utils import timezone
        from datetime import timedelta

        self.payment.status = Payment.PaymentStatus.EXPIRED
        self.payment.expires_at = timezone.now() - timedelta(days=1)
        self.payment.save(update_fields=["status", "expires_at", "updated_at"])
        res = self.client.post(self._cancel_url())
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_EXPIRED")

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

    def test_student_cannot_cancel_other_payment(self):
        User = get_user_model()
        student_user = User.objects.create_user(username="student_user", password="pass")
        make_student(student_id="S002", email="s2@u.eg", user=student_user)
        client = APIClient()
        client.force_authenticate(user=student_user)
        res = client.post(self._cancel_url())
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.PaymentStatus.PENDING)
        self.assertFalse(
            PaymentAuditLog.objects.filter(
                payment=self.payment,
                event_type=PaymentAuditLog.EventType.CANCELLED,
            ).exists()
        )
