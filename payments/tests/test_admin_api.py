"""
Admin reporting API tests for payments.
"""

from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from students.models import Student
from payments.models import Payment, PaymentAuditLog, current_semester
from django.contrib.auth import get_user_model


def make_student(**kwargs) -> Student:
    defaults = {
        "student_id":    "20210001",
        "name":          "Ahmed Hassan",
        "email":         "ahmed@uni.edu.eg",
        "faculty":       "Engineering",
        "academic_year": 3,
        "gpa":           Decimal("3.20"),
        "allowed_hours": 18,
        "status":        "active",
    }
    defaults.update(kwargs)
    return Student.objects.create(**defaults)


def make_payment(student, status="pending", amount="5000.00"):
    return Payment.objects.create(
        student=student,
        amount=Decimal(amount),
        semester=current_semester(),
        status=status,
    )


class AdminPaymentSummaryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.anon_client = APIClient()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin", password="pass", is_staff=True, is_superuser=True
        )
        self.non_admin = User.objects.create_user(
            username="user", password="pass", is_staff=False, is_superuser=False
        )
        self.non_admin_client = APIClient()
        self.non_admin_client.force_authenticate(user=self.non_admin)
        self.client.force_authenticate(user=self.admin)
        s1 = make_student()
        s2 = make_student(student_id="S002", email="s2@u.eg")
        make_payment(s1, status="paid", amount="1000.00")
        make_payment(s1, status="failed", amount="2000.00")
        make_payment(s2, status="paid", amount="3000.00")

    def test_summary_response(self):
        url = reverse("payments:admin-payment-summary")
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertEqual(data["total_count"], 3)
        self.assertEqual(data["status_counts"]["paid"], 2)
        self.assertEqual(data["status_counts"]["failed"], 1)
        self.assertEqual(Decimal(data["total_paid_amount"]), Decimal("4000.00"))

    def test_requires_admin(self):
        url = reverse("payments:admin-payment-summary")
        res = self.non_admin_client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.anon_client.get(url)
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_student_profile_cannot_access_summary(self):
        User = get_user_model()
        student_user = User.objects.create_user(username="student_user", password="pass")
        make_student(student_id="S010", email="s10@u.eg", user=student_user)
        client = APIClient()
        client.force_authenticate(user=student_user)
        url = reverse("payments:admin-payment-summary")
        res = client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


class AdminPaymentRecentTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.anon_client = APIClient()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin", password="pass", is_staff=True, is_superuser=True
        )
        self.non_admin = User.objects.create_user(
            username="user", password="pass", is_staff=False, is_superuser=False
        )
        self.non_admin_client = APIClient()
        self.non_admin_client.force_authenticate(user=self.non_admin)
        self.client.force_authenticate(user=self.admin)
        s1 = make_student()
        make_payment(s1, status="paid")

    def test_recent_response(self):
        url = reverse("payments:admin-payment-recent")
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertIn("payments", data)

    def test_requires_admin(self):
        url = reverse("payments:admin-payment-recent")
        res = self.non_admin_client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.anon_client.get(url)
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


class AdminPaymentListTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.anon_client = APIClient()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin", password="pass", is_staff=True, is_superuser=True
        )
        self.non_admin = User.objects.create_user(
            username="user", password="pass", is_staff=False, is_superuser=False
        )
        self.non_admin_client = APIClient()
        self.non_admin_client.force_authenticate(user=self.non_admin)
        self.client.force_authenticate(user=self.admin)
        s1 = make_student()
        s2 = make_student(student_id="S002", email="s2@u.eg")
        make_payment(s1, status="paid")
        make_payment(s2, status="failed")

    def test_filter_by_status(self):
        url = reverse("payments:admin-payment-list")
        res = self.client.get(url, {"status": "paid"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["data"]["total_records"], 1)

    def test_filter_by_transaction_id(self):
        url = reverse("payments:admin-payment-list")
        txn_id = str(Payment.objects.filter(status="paid").first().transaction_id)
        res = self.client.get(url, {"transaction_id": txn_id})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["data"]["total_records"], 1)

    def test_invalid_date_filter(self):
        url = reverse("payments:admin-payment-list")
        res = self.client.get(url, {"date_from": "not-a-date"})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "INVALID_DATE_FROM")

    def test_requires_admin(self):
        url = reverse("payments:admin-payment-list")
        res = self.non_admin_client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.anon_client.get(url)
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


class AdminPaymentDetailTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.anon_client = APIClient()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin", password="pass", is_staff=True, is_superuser=True
        )
        self.non_admin = User.objects.create_user(
            username="user", password="pass", is_staff=False, is_superuser=False
        )
        self.non_admin_client = APIClient()
        self.non_admin_client.force_authenticate(user=self.non_admin)
        self.client.force_authenticate(user=self.admin)
        self.student = make_student()
        self.payment = make_payment(self.student, status="paid")
        PaymentAuditLog.objects.create(
            payment=self.payment,
            event_type=PaymentAuditLog.EventType.SUCCESS,
            amount=self.payment.amount,
            actor="system",
            payload={"note": "ok"},
        )

    def test_detail_includes_audit_logs(self):
        url = reverse("payments:admin-payment-detail", kwargs={"transaction_id": self.payment.transaction_id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertIn("audit_logs", data)
        self.assertGreaterEqual(len(data["audit_logs"]), 1)

    def test_detail_not_found(self):
        import uuid
        url = reverse("payments:admin-payment-detail", kwargs={"transaction_id": uuid.uuid4()})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_NOT_FOUND")

    def test_requires_admin(self):
        url = reverse("payments:admin-payment-detail", kwargs={"transaction_id": self.payment.transaction_id})
        res = self.non_admin_client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.anon_client.get(url)
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_student_profile_cannot_access_detail(self):
        User = get_user_model()
        student_user = User.objects.create_user(username="student_user", password="pass")
        make_student(student_id="S011", email="s11@u.eg", user=student_user)
        client = APIClient()
        client.force_authenticate(user=student_user)
        url = reverse("payments:admin-payment-detail", kwargs={"transaction_id": self.payment.transaction_id})
        res = client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


class AdminAuditLogListTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.anon_client = APIClient()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin", password="pass", is_staff=True, is_superuser=True
        )
        self.non_admin = User.objects.create_user(
            username="user", password="pass", is_staff=False, is_superuser=False
        )
        self.non_admin_client = APIClient()
        self.non_admin_client.force_authenticate(user=self.non_admin)
        self.client.force_authenticate(user=self.admin)
        self.student = make_student()
        self.payment = make_payment(self.student, status="paid")
        PaymentAuditLog.objects.create(
            payment=self.payment,
            event_type=PaymentAuditLog.EventType.SUCCESS,
            amount=self.payment.amount,
            actor="system",
            payload={"note": "ok"},
        )
        PaymentAuditLog.objects.create(
            payment=self.payment,
            event_type=PaymentAuditLog.EventType.FAILURE,
            amount=Decimal("0.00"),
            actor="system",
            payload={"note": "fail"},
        )

    def test_admin_can_list_audit_logs(self):
        url = reverse("payments:admin-audit-log-list")
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertIn("audit_logs", data)

    def test_requires_admin(self):
        url = reverse("payments:admin-audit-log-list")
        res = self.non_admin_client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.anon_client.get(url)
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_event_type_filter(self):
        url = reverse("payments:admin-audit-log-list")
        res = self.client.get(url, {"event_type": "success"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        logs = res.data["data"]["audit_logs"]
        self.assertTrue(logs)
        for entry in logs:
            self.assertEqual(entry["event_type"], PaymentAuditLog.EventType.SUCCESS)

    def test_student_id_filter(self):
        url = reverse("payments:admin-audit-log-list")
        res = self.client.get(url, {"student_id": self.student.student_id})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        logs = res.data["data"]["audit_logs"]
        self.assertEqual(len(logs), 2)

    def test_date_range_filter(self):
        from django.utils import timezone
        from unittest.mock import patch

        now = timezone.now()
        with patch("django.utils.timezone.now", return_value=now - timezone.timedelta(days=5)):
            PaymentAuditLog.objects.create(
                payment=self.payment,
                event_type=PaymentAuditLog.EventType.SUCCESS,
                amount=Decimal("0.00"),
                actor="system",
                payload={"note": "older"},
            )

        url = reverse("payments:admin-audit-log-list")
        res = self.client.get(url, {"date_from": (now - timezone.timedelta(days=1)).isoformat()})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        logs = res.data["data"]["audit_logs"]
        expected_recent = PaymentAuditLog.objects.filter(
            created_at__gte=now - timezone.timedelta(days=1)
        ).count()
        self.assertEqual(len(logs), expected_recent)

    def test_actor_filter(self):
        url = reverse("payments:admin-audit-log-list")
        res = self.client.get(url, {"actor": "system"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        logs = res.data["data"]["audit_logs"]
        self.assertTrue(logs)
        for entry in logs:
            self.assertEqual(entry["actor"], "system")
