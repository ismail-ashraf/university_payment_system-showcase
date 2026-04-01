from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model

from students.models import Student
from payments.models import Payment, PaymentAuditLog, current_semester
from payments.gateways.fawry import FawryGateway
from payments.gateways.vodafone import VodafoneGateway
from payments.gateways.bank import MockBankGateway


def make_student(**kwargs):
    defaults = {
        "student_id": "20210001",
        "name": "Ahmed Hassan",
        "email": "ahmed@uni.edu.eg",
        "faculty": "Engineering",
        "academic_year": 3,
        "gpa": Decimal("3.20"),
        "allowed_hours": 18,
        "status": "active",
    }
    defaults.update(kwargs)
    return Student.objects.create(**defaults)


def build_signed_webhook(provider, txn_id, amount, webhook_status="success"):
    if provider == "fawry":
        gw = FawryGateway()
        ref = f"FWR-{txn_id.replace('-', '').upper()[:12]}"
        body = {"transaction_id": txn_id, "fawry_reference": ref, "status": webhook_status, "amount": str(amount)}
    elif provider == "vodafone":
        gw = VodafoneGateway()
        ref = f"VF-{txn_id.replace('-', '').upper()[:10]}"
        body = {"transaction_id": txn_id, "vf_request_id": ref, "status": webhook_status, "amount": str(amount)}
    else:
        gw = MockBankGateway()
        ref = f"BNK-{txn_id[:8].upper()}"
        body = {"transaction_id": txn_id, "bank_reference": ref, "status": webhook_status, "amount": str(amount)}

    canonical = gw.build_canonical_string(body)
    sig = gw.compute_hmac_signature(canonical)
    return body, sig


@override_settings(FEE_PER_CREDIT_HOUR=250, FIXED_SEMESTER_FEE=500)
class PaymentSystemIntegrityTests(TestCase):
    """Backup end-to-end tests that exercise the supported flows across all providers."""

    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

    def test_create_submit_webhook_roundtrip_all_providers(self):
        for index, provider in enumerate(["fawry", "vodafone", "bank"], start=1):
            student = make_student(
                student_id=f"2021A{index:03d}",
                email=f"student{index}@uni.edu.eg",
            )

            start_res = self.client.post(
                reverse("payments:payment-start"),
                {"student_id": student.student_id},
                format="json",
            )
            self.assertEqual(start_res.status_code, status.HTTP_201_CREATED)
            txn_id = start_res.data["data"]["transaction_id"]

            submit_res = self.client.post(
                reverse("payments:payment-submit", kwargs={"transaction_id": txn_id}),
                {"provider": provider},
                format="json",
            )
            self.assertEqual(submit_res.status_code, status.HTTP_200_OK)
            self.assertEqual(submit_res.data["data"]["status"], "processing")

            payment = Payment.objects.get(transaction_id=txn_id)
            body, sig = build_signed_webhook(provider, txn_id, payment.amount, "success")
            webhook_res = self.client.post(
                reverse("payments:payment-webhook", kwargs={"provider": provider}),
                body,
                format="json",
                HTTP_X_WEBHOOK_SIGNATURE=sig,
            )
            self.assertEqual(webhook_res.status_code, status.HTTP_200_OK)
            payment.refresh_from_db()
            self.assertEqual(payment.status, Payment.PaymentStatus.PAID)

            events = list(
                PaymentAuditLog.objects.filter(payment=payment)
                .order_by("created_at")
                .values_list("event_type", flat=True)
            )
            self.assertEqual(events, ["initiated", "processing", "webhook", "success"])

    def test_duplicate_webhook_does_not_mutate_terminal_payment(self):
        student = make_student()
        start_res = self.client.post(reverse("payments:payment-start"), {"student_id": student.student_id, "provider": "fawry"}, format="json")
        self.assertEqual(start_res.status_code, status.HTTP_201_CREATED)
        txn_id = start_res.data["data"]["transaction_id"]
        payment = Payment.objects.get(transaction_id=txn_id)

        body, sig = build_signed_webhook("fawry", txn_id, payment.amount, "success")
        first = self.client.post(reverse("payments:payment-webhook", kwargs={"provider": "fawry"}), body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)
        second = self.client.post(reverse("payments:payment-webhook", kwargs={"provider": "fawry"}), body, format="json", HTTP_X_WEBHOOK_SIGNATURE=sig)

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.PaymentStatus.PAID)
        self.assertTrue(PaymentAuditLog.objects.filter(payment=payment, event_type="duplicate_webhook_noop").exists())
