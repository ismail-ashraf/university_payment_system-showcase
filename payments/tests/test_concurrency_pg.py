from __future__ import annotations

import os
import threading
import unittest
from decimal import Decimal

from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.db import connection, close_old_connections
from django.db.utils import OperationalError
from django.contrib.auth import get_user_model

from students.models import Student
from payments.models import Payment, PaymentAuditLog, current_semester
from payments.services import process_webhook
from payments.gateways.fawry import FawryGateway


def _is_postgres_enabled() -> bool:
    vendor = connection.vendor
    flag = os.getenv("PG_CONCURRENCY_TESTS", "").strip().lower()
    return vendor == "postgresql" and flag in {"1", "true", "yes"}


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


def make_payment(student, **kwargs) -> Payment:
    defaults = {
        "amount":   Decimal("5000.00"),
        "semester": current_semester(),
        "status":   Payment.PaymentStatus.PENDING,
    }
    defaults.update(kwargs)
    return Payment.objects.create(student=student, **defaults)


def signed_fawry_webhook(gw: FawryGateway, transaction_id: str, status_val: str, amount: str) -> dict:
    ref = f"FWR-{transaction_id.replace('-', '').upper()[:12]}"
    body = {
        "transaction_id":  transaction_id,
        "fawry_reference": ref,
        "status":          status_val,
        "amount":          amount,
    }
    canonical = gw.build_canonical_string(body)
    body["signature"] = gw.compute_hmac_signature(canonical)
    return body


class PGConcurrencyStartTests(TransactionTestCase):
    reset_sequences = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not _is_postgres_enabled():
            raise unittest.SkipTest("PostgreSQL concurrency tests are disabled.")

    def setUp(self):
        self.url = reverse("payments:payment-start")
        self.student = make_student()
        self._errors: list[Exception] = []
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )

    def _post_start(self):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(user=self.admin)
            client.post(self.url, {"student_id": "20210001"}, format="json")
        except Exception as exc:
            self._errors.append(exc)
        finally:
            close_old_connections()

    def test_concurrent_start_no_duplicate_open_payment(self):
        t1 = threading.Thread(target=self._post_start)
        t2 = threading.Thread(target=self._post_start)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        close_old_connections()

        for err in self._errors:
            if isinstance(err, OperationalError):
                continue
            self.fail(f"Unexpected error during concurrent start: {err}")

        payments = Payment.objects.filter(
            student=self.student,
            semester=current_semester(),
            status=Payment.PaymentStatus.PENDING,
        )
        self.assertLessEqual(payments.count(), 1)


class PGConcurrencySubmitTests(TransactionTestCase):
    reset_sequences = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not _is_postgres_enabled():
            raise unittest.SkipTest("PostgreSQL concurrency tests are disabled.")

    def setUp(self):
        self.student = make_student()
        self.payment = make_payment(self.student)
        self.url = reverse("payments:payment-submit", kwargs={"transaction_id": self.payment.transaction_id})
        self._errors: list[Exception] = []
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )

    def _post_submit(self):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(user=self.admin)
            client.post(self.url, {"provider": "fawry"}, format="json")
        except Exception as exc:
            self._errors.append(exc)
        finally:
            close_old_connections()

    def test_concurrent_submit_state_valid(self):
        t1 = threading.Thread(target=self._post_submit)
        t2 = threading.Thread(target=self._post_submit)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        close_old_connections()

        for err in self._errors:
            if isinstance(err, OperationalError):
                continue
            self.fail(f"Unexpected error during concurrent submit: {err}")

        self.payment.refresh_from_db()
        self.assertIn(
            self.payment.status,
            {
                Payment.PaymentStatus.PENDING,
                Payment.PaymentStatus.PROCESSING,
                Payment.PaymentStatus.PAID,
                Payment.PaymentStatus.FAILED,
                Payment.PaymentStatus.CANCELLED,
                Payment.PaymentStatus.EXPIRED,
            },
        )


class PGConcurrencySubmitWebhookTests(TransactionTestCase):
    reset_sequences = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not _is_postgres_enabled():
            raise unittest.SkipTest("PostgreSQL concurrency tests are disabled.")

    def setUp(self):
        self.student = make_student()
        self.payment = make_payment(
            self.student,
            status=Payment.PaymentStatus.PROCESSING,
            used=True,
            payment_method="fawry",
        )
        self.submit_url = reverse("payments:payment-submit", kwargs={"transaction_id": self.payment.transaction_id})
        self.gw = FawryGateway()
        self._errors: list[Exception] = []
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )

    def _post_submit(self):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(user=self.admin)
            client.post(self.submit_url, {"provider": "fawry"}, format="json")
        except Exception as exc:
            self._errors.append(exc)
        finally:
            close_old_connections()

    def _post_webhook(self):
        close_old_connections()
        try:
            body = signed_fawry_webhook(
                self.gw,
                str(self.payment.transaction_id),
                "success",
                str(self.payment.amount),
            )
            process_webhook("fawry", body, body["signature"])
        except Exception as exc:
            self._errors.append(exc)
        finally:
            close_old_connections()

    def test_submit_vs_webhook_overlap_invariants(self):
        t1 = threading.Thread(target=self._post_submit)
        t2 = threading.Thread(target=self._post_webhook)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        close_old_connections()

        for err in self._errors:
            if isinstance(err, OperationalError):
                continue
            self.fail(f"Unexpected error during submit/webhook overlap: {err}")

        self.payment.refresh_from_db()
        self.assertIn(
            self.payment.status,
            {
                Payment.PaymentStatus.PROCESSING,
                Payment.PaymentStatus.PAID,
                Payment.PaymentStatus.FAILED,
                Payment.PaymentStatus.CANCELLED,
                Payment.PaymentStatus.EXPIRED,
            },
        )
        if self.payment.status == Payment.PaymentStatus.PAID:
            self.assertTrue(self.payment.used)


class PGConcurrencyStartWithProviderTests(TransactionTestCase):
    """
    PG-only: concurrent provider-initiated start should not create duplicate
    processing payments or duplicate gateway submissions.
    """
    reset_sequences = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not _is_postgres_enabled():
            raise unittest.SkipTest("PostgreSQL concurrency tests are disabled.")

    def setUp(self):
        self.url = reverse("payments:payment-start")
        self.student = make_student()
        self._errors: list[Exception] = []
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user_start_provider",
            password="testpass123",
            is_staff=True,
        )

    def _post_start_with_provider(self):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(user=self.admin)
            client.post(
                self.url,
                {"student_id": self.student.student_id, "provider": "fawry"},
                format="json",
            )
        except Exception as exc:
            self._errors.append(exc)
        finally:
            close_old_connections()

    def test_concurrent_start_with_provider_single_processing_payment(self):
        t1 = threading.Thread(target=self._post_start_with_provider)
        t2 = threading.Thread(target=self._post_start_with_provider)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        close_old_connections()

        for err in self._errors:
            if isinstance(err, OperationalError):
                continue
            self.fail(f"Unexpected error during concurrent start+provider: {err}")

        payments = Payment.objects.filter(
            student=self.student,
            semester=current_semester(),
        )
        processing = payments.filter(status=Payment.PaymentStatus.PROCESSING)
        self.assertLessEqual(
            processing.count(),
            1,
            "More than one processing payment created for same student/semester.",
        )

        gateway_refs = list(
            payments.exclude(gateway_reference__isnull=True)
            .exclude(gateway_reference__exact="")
            .values_list("gateway_reference", flat=True)
        )
        self.assertLessEqual(
            len(set(gateway_refs)),
            1,
            "More than one gateway reference created for same student/semester.",
        )

        processing_logs = PaymentAuditLog.objects.filter(
            payment__student=self.student,
            payment__semester=current_semester(),
            event_type=PaymentAuditLog.EventType.PROCESSING,
        )
        self.assertLessEqual(
            processing_logs.count(),
            1,
            "More than one gateway submission audit log detected.",
        )
