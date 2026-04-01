from decimal import Decimal
from django.test import TestCase
from django.conf import settings
from rest_framework.settings import api_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle
from django.contrib.auth import get_user_model

from students.models import Student
from payments.models import Payment, current_semester
from payments.views import StartPaymentView, SubmitPaymentView, WebhookView, AdminAuditLogListView


class PaymentThrottleLoggingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self._orig_rates = settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {}).copy()
        self.student = Student.objects.create(
            student_id="20210001",
            name="Ahmed Hassan",
            email="ahmed.hassan@university.edu.eg",
            faculty="Engineering",
            academic_year=3,
            gpa=3.2,
            allowed_hours=18,
            status="active",
        )
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

    def tearDown(self):
        settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = self._orig_rates
        api_settings.reload()

    def _set_rate(self, scope: str, rate: str) -> None:
        rates = self._orig_rates.copy()
        rates[scope] = rate
        settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = rates
        api_settings.reload()

    def _assert_throttle(self, scope: str, expected_rate: str, view_cls) -> None:
        view = view_cls()
        view.throttle_scope = scope
        throttle = ScopedRateThrottle()
        throttle.scope = view.throttle_scope
        self.assertEqual(throttle.get_rate(), expected_rate)

    def test_payment_start_throttled(self):
        self._assert_throttle("payment_start", "10/min", StartPaymentView)

    def test_payment_start_logs_minimal(self):
        url = reverse("payments:payment-start")
        payload = {"student_id": "20210001", "provider": "fawry"}
        with self.assertLogs("payments.views", level="INFO") as captured:
            self.client.post(url, payload, format="json")
        combined = " ".join(captured.output)
        self.assertIn("payment_start", combined)
        self.assertNotIn("password", combined)

    def test_webhook_throttled(self):
        self._assert_throttle("payment_webhook", "120/min", WebhookView)

    def test_admin_audit_log_throttled(self):
        self._assert_throttle("admin_audit_log", "30/min", AdminAuditLogListView)

    def test_submit_throttled(self):
        payment = Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.PENDING,
        )
        self._assert_throttle("payment_submit", "10/min", SubmitPaymentView)

    def test_webhook_logs_minimal(self):
        url = reverse("payments:payment-webhook", kwargs={"provider": "fawry"})
        payload = {"transaction_id": "00000000-0000-0000-0000-000000000000", "status": "success", "amount": "10"}
        with self.assertLogs("payments.views", level="INFO") as captured:
            self.client.post(url, payload, format="json")
        combined = " ".join(captured.output)
        self.assertIn("payment_webhook", combined)
        self.assertNotIn("signature", combined)

    def test_submit_throttled(self):
        payment = Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.PENDING,
        )
        self._assert_throttle("payment_submit", "10/min", SubmitPaymentView)

    def test_submit_logs_minimal_on_validation_error(self):
        import uuid
        url = reverse("payments:payment-submit", kwargs={"transaction_id": uuid.uuid4()})
        payload = {}
        with self.assertLogs("payments.views", level="INFO") as captured:
            self.client.post(url, payload, format="json")
        combined = " ".join(captured.output)
        self.assertIn("payment_submit_received", combined)
        self.assertIn("payment_submit_failed", combined)
        self.assertNotIn("password", combined)

    def test_webhook_logs_malformed_minimal(self):
        url = reverse("payments:payment-webhook", kwargs={"provider": "fawry"})
        payload = {"transaction_id": "00000000-0000-0000-0000-000000000000"}
        with self.assertLogs("payments.views", level="INFO") as captured:
            self.client.post(url, payload, format="json")
        combined = " ".join(captured.output)
        self.assertIn("payment_webhook_malformed", combined)
        self.assertNotIn("signature", combined)
