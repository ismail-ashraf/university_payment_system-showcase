from __future__ import annotations

import threading
import time
from decimal import Decimal
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.db import connection
from django.db.utils import OperationalError
from django.contrib.auth import get_user_model

from students.models import Student
from payments.models import Payment, PaymentAuditLog, current_semester
from payments.services import process_webhook, initiate_with_gateway, cancel_payment
from payments.gateways.fawry import FawryGateway


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


class ConcurrencyStartTests(TransactionTestCase):
    reset_sequences = True

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
        try:
            client = APIClient()
            client.force_authenticate(user=self.admin)
            client.post(self.url, {"student_id": "20210001"}, format="json")
        except Exception as exc:
            self._errors.append(exc)

    def test_concurrent_start_no_duplicate_open_payment(self):
        t1 = threading.Thread(target=self._post_start)
        t2 = threading.Thread(target=self._post_start)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        for err in self._errors:
            if isinstance(err, OperationalError) and "database table is locked" in str(err).lower():
                continue
            self.fail(f"Unexpected error during concurrent start: {err}")

        payments = Payment.objects.filter(
            student=self.student,
            semester=current_semester(),
            status=Payment.PaymentStatus.PENDING,
        )
        self.assertLessEqual(payments.count(), 1)
        # Valid states only
        statuses = set(
            Payment.objects.filter(student=self.student).values_list("status", flat=True)
        )
        for status_val in statuses:
            self.assertIn(
                status_val,
                {
                    Payment.PaymentStatus.PENDING,
                    Payment.PaymentStatus.PROCESSING,
                    Payment.PaymentStatus.PAID,
                    Payment.PaymentStatus.FAILED,
                    Payment.PaymentStatus.CANCELLED,
                    Payment.PaymentStatus.EXPIRED,
                },
            )

    def test_concurrent_start_with_provider_invariants(self):
        def _post_start_with_provider():
            try:
                client = APIClient()
                client.force_authenticate(user=self.admin)
                client.post(
                    self.url,
                    {"student_id": "20210001", "provider": "fawry"},
                    format="json",
                )
            except Exception as exc:
                self._errors.append(exc)

        t1 = threading.Thread(target=_post_start_with_provider)
        t2 = threading.Thread(target=_post_start_with_provider)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        for err in self._errors:
            if isinstance(err, OperationalError) and "database table is locked" in str(err).lower():
                continue
            self.fail(f"Unexpected error during concurrent start+provider: {err}")

        payments = Payment.objects.filter(
            student=self.student,
            semester=current_semester(),
        )
        processing = payments.filter(status=Payment.PaymentStatus.PROCESSING)
        self.assertLessEqual(processing.count(), 1)

        gateway_refs = list(
            payments.exclude(gateway_reference__isnull=True)
            .exclude(gateway_reference__exact="")
            .values_list("gateway_reference", flat=True)
        )
        self.assertLessEqual(len(set(gateway_refs)), 1)

        processing_logs = PaymentAuditLog.objects.filter(
            payment__student=self.student,
            payment__semester=current_semester(),
            event_type=PaymentAuditLog.EventType.PROCESSING,
        )
        self.assertLessEqual(processing_logs.count(), 1)

        terminal_logs = PaymentAuditLog.objects.filter(
            payment__student=self.student,
            payment__semester=current_semester(),
            event_type__in=[
                PaymentAuditLog.EventType.SUCCESS,
                PaymentAuditLog.EventType.FAILURE,
            ],
        )
        self.assertEqual(terminal_logs.count(), 0)


class ConcurrencySubmitTests(TransactionTestCase):
    reset_sequences = True

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
        try:
            client = APIClient()
            client.force_authenticate(user=self.admin)
            res = client.post(self.url, {"provider": "fawry"}, format="json")
            self._responses.append(res.status_code)
        except Exception as exc:
            self._errors.append(exc)

    def test_concurrent_submit_state_valid(self):
        self._responses: list[int] = []
        t1 = threading.Thread(target=self._post_submit)
        t2 = threading.Thread(target=self._post_submit)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        for err in self._errors:
            if isinstance(err, OperationalError) and "database table is locked" in str(err).lower():
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

    def test_concurrent_submit_single_gateway_submission(self):
        self._responses = []
        threads = [threading.Thread(target=self._post_submit) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for err in self._errors:
            if isinstance(err, OperationalError) and "database table is locked" in str(err).lower():
                continue
            self.fail(f"Unexpected error during concurrent submit: {err}")

        success_count = sum(1 for code in self._responses if code == status.HTTP_200_OK)
        self.assertLessEqual(success_count, 1)

        self.payment.refresh_from_db()
        processing_logs = PaymentAuditLog.objects.filter(
            payment=self.payment,
            event_type="processing",
        )
        self.assertLessEqual(processing_logs.count(), 1)
        if self.payment.status == Payment.PaymentStatus.PROCESSING:
            self.assertTrue(self.payment.used)
            self.assertIsNotNone(self.payment.gateway_reference)


class ConcurrencyWebhookTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.student = make_student()
        self.payment = make_payment(
            self.student,
            status=Payment.PaymentStatus.PROCESSING,
            used=True,
            payment_method="fawry",
        )
        self.gw = FawryGateway()

    def test_duplicate_webhook_terminal_state_not_moved_backwards(self):
        body = signed_fawry_webhook(
            self.gw,
            str(self.payment.transaction_id),
            "success",
            str(self.payment.amount),
        )

        result1, err1 = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err1)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.PaymentStatus.PAID)

        result2, err2 = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err2)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.PaymentStatus.PAID)

    def test_conflicting_webhooks_only_one_terminal_transition(self):
        body_success = signed_fawry_webhook(
            self.gw,
            str(self.payment.transaction_id),
            "success",
            str(self.payment.amount),
        )
        body_failed = signed_fawry_webhook(
            self.gw,
            str(self.payment.transaction_id),
            "failed",
            str(self.payment.amount),
        )

        errors: list[Exception] = []

        def _call(body: dict):
            try:
                process_webhook("fawry", body, body["signature"])
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=_call, args=(body_success,))
        t2 = threading.Thread(target=_call, args=(body_failed,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        for err in errors:
            if isinstance(err, OperationalError) and "database table is locked" in str(err).lower():
                continue
            self.fail(f"Unexpected error during concurrent webhook: {err}")

        self.payment.refresh_from_db()
        terminal_logs = PaymentAuditLog.objects.filter(
            payment=self.payment,
            event_type__in=["success", "failure"],
        )
        # SQLite locking/thread scheduling can leave the payment in PROCESSING
        # if both threads are blocked; assert invariants instead of timing.
        self.assertIn(terminal_logs.count(), {0, 1})
        if terminal_logs.count() == 0:
            self.assertEqual(self.payment.status, Payment.PaymentStatus.PROCESSING)
        else:
            self.assertIn(
                self.payment.status,
                {Payment.PaymentStatus.PAID, Payment.PaymentStatus.FAILED},
            )

    def test_webhook_replay_burst_on_terminal_payment(self):
        body = signed_fawry_webhook(
            self.gw,
            str(self.payment.transaction_id),
            "success",
            str(self.payment.amount),
        )
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)
        self.assertTrue(result["acknowledged"])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.PaymentStatus.PAID)

        for _ in range(50):
            process_webhook("fawry", body, body["signature"])

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.PaymentStatus.PAID)
        self.assertEqual(
            PaymentAuditLog.objects.filter(
                payment=self.payment,
                event_type="success",
            ).count(),
            1,
        )
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment,
                event_type="duplicate_webhook_noop",
            ).exists()
        )

    def test_conflicting_webhook_burst_invariants(self):
        body_success = signed_fawry_webhook(
            self.gw,
            str(self.payment.transaction_id),
            "success",
            str(self.payment.amount),
        )
        body_failed = signed_fawry_webhook(
            self.gw,
            str(self.payment.transaction_id),
            "failed",
            str(self.payment.amount),
        )

        errors: list[Exception] = []

        def _call(body: dict):
            try:
                process_webhook("fawry", body, body["signature"])
            except Exception as exc:
                errors.append(exc)

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=_call, args=(body_success,)))
            threads.append(threading.Thread(target=_call, args=(body_failed,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for err in errors:
            if isinstance(err, OperationalError) and "database table is locked" in str(err).lower():
                continue
            self.fail(f"Unexpected error during conflicting webhook burst: {err}")

        self.payment.refresh_from_db()
        terminal_logs = PaymentAuditLog.objects.filter(
            payment=self.payment,
            event_type__in=["success", "failure"],
        )
        self.assertIn(terminal_logs.count(), {0, 1})
        if terminal_logs.count() == 0:
            self.assertEqual(self.payment.status, Payment.PaymentStatus.PROCESSING)
        else:
            self.assertIn(
                self.payment.status,
                {Payment.PaymentStatus.PAID, Payment.PaymentStatus.FAILED},
            )

    def test_webhook_during_submit_invariants(self):
        payment = make_payment(self.student)
        gw = FawryGateway()

        errors: list[Exception] = []

        def _submit():
            try:
                fresh = Payment.objects.get(transaction_id=payment.transaction_id)
                initiate_with_gateway(fresh, "fawry")
            except Exception as exc:
                errors.append(exc)

        def _webhook():
            try:
                body = signed_fawry_webhook(
                    gw,
                    str(payment.transaction_id),
                    "success",
                    str(payment.amount),
                )
                process_webhook("fawry", body, body["signature"])
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=_submit)
        t2 = threading.Thread(target=_webhook)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        for err in errors:
            if isinstance(err, OperationalError) and "database table is locked" in str(err).lower():
                continue
            self.fail(f"Unexpected error during submit/webhook overlap: {err}")

        payment.refresh_from_db()

        self.assertIn(
            payment.status,
            {
                Payment.PaymentStatus.PENDING,
                Payment.PaymentStatus.PROCESSING,
                Payment.PaymentStatus.PAID,
                Payment.PaymentStatus.FAILED,
                Payment.PaymentStatus.EXPIRED,
            },
        )

        terminal_success = PaymentAuditLog.objects.filter(
            payment=payment,
            event_type=PaymentAuditLog.EventType.SUCCESS,
        ).count()
        terminal_failure = PaymentAuditLog.objects.filter(
            payment=payment,
            event_type=PaymentAuditLog.EventType.FAILURE,
        ).count()
        processing_logs = PaymentAuditLog.objects.filter(
            payment=payment,
            event_type=PaymentAuditLog.EventType.PROCESSING,
        ).count()

        self.assertLessEqual(terminal_success, 1)
        self.assertLessEqual(terminal_failure, 1)
        self.assertLessEqual(processing_logs, 1)
        self.assertFalse(terminal_success and terminal_failure)

        if payment.status in {Payment.PaymentStatus.PAID, Payment.PaymentStatus.FAILED}:
            self.assertEqual(processing_logs, 1)
        elif payment.status == Payment.PaymentStatus.PENDING:
            self.assertFalse(payment.used)
            self.assertEqual(processing_logs, 0)

    def test_webhook_waits_for_submit_and_applies_once(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL row-locking semantics")

        payment = make_payment(self.student)
        gw = FawryGateway()

        errors: list[Exception] = []

        def _submit():
            try:
                fresh = Payment.objects.get(transaction_id=payment.transaction_id)
                initiate_with_gateway(fresh, "fawry")
            except Exception as exc:
                errors.append(exc)

        def _webhook():
            try:
                body = signed_fawry_webhook(
                    gw,
                    str(payment.transaction_id),
                    "success",
                    str(payment.amount),
                )
                process_webhook("fawry", body, body["signature"])
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=_submit)
        t1.start()

        deadline = time.time() + 5.0
        while time.time() < deadline:
            payment.refresh_from_db()
            if payment.status == Payment.PaymentStatus.PROCESSING:
                break
            time.sleep(0.05)

        t2 = threading.Thread(target=_webhook)
        t2.start()
        t1.join()
        t2.join()

        if errors:
            self.fail(f"Unexpected error during PG submit/webhook overlap: {errors}")

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.PaymentStatus.PAID)
        self.assertTrue(payment.used)
        self.assertEqual(payment.payment_method, "fawry")
        self.assertIsNotNone(payment.gateway_reference)

        self.assertEqual(
            PaymentAuditLog.objects.filter(
                payment=payment,
                event_type=PaymentAuditLog.EventType.PROCESSING,
            ).count(),
            1,
        )
        self.assertEqual(
            PaymentAuditLog.objects.filter(
                payment=payment,
                event_type=PaymentAuditLog.EventType.SUCCESS,
            ).count(),
            1,
        )
        self.assertEqual(
            PaymentAuditLog.objects.filter(
                payment=payment,
                event_type=PaymentAuditLog.EventType.FAILURE,
            ).count(),
            0,
        )

class ReplayBurstTerminalTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.student = make_student()
        self.gw = FawryGateway()

    def _make_terminal_payment(self, status: str) -> Payment:
        payment = make_payment(
            self.student,
            status=status,
            used=True,
            payment_method="fawry",
        )
        expected_ref = f"FWR-{str(payment.transaction_id).replace('-', '').upper()[:12]}"
        payment.gateway_reference = expected_ref
        payment.save(update_fields=["gateway_reference", "updated_at"])
        return payment

    def test_large_replay_burst_terminal_payment(self):
        payment = self._make_terminal_payment(Payment.PaymentStatus.PAID)
        PaymentAuditLog.objects.create(
            payment=payment,
            event_type=PaymentAuditLog.EventType.SUCCESS,
            amount=payment.amount,
            actor="fawry",
            payload={"note": "seed"},
        )

        body = signed_fawry_webhook(
            self.gw,
            str(payment.transaction_id),
            "success",
            str(payment.amount),
        )

        burst_count = 300
        for _ in range(burst_count):
            result, err = process_webhook("fawry", body, body["signature"])
            self.assertIsNone(err)
            self.assertTrue(result["acknowledged"])

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.PaymentStatus.PAID)
        self.assertTrue(payment.used)
        self.assertEqual(payment.payment_method, "fawry")
        self.assertIsNotNone(payment.gateway_reference)

        self.assertEqual(
            PaymentAuditLog.objects.filter(
                payment=payment,
                event_type=PaymentAuditLog.EventType.SUCCESS,
            ).count(),
            1,
        )
        self.assertEqual(
            PaymentAuditLog.objects.filter(
                payment=payment,
                event_type=PaymentAuditLog.EventType.FAILURE,
            ).count(),
            0,
        )
        self.assertEqual(
            PaymentAuditLog.objects.filter(
                payment=payment,
                event_type=PaymentAuditLog.EventType.DUPLICATE_WEBHOOK_NOOP,
            ).count(),
            burst_count,
        )

    def test_replay_burst_mixed_terminal_statuses(self):
        paid = self._make_terminal_payment(Payment.PaymentStatus.PAID)
        failed = self._make_terminal_payment(Payment.PaymentStatus.FAILED)

        PaymentAuditLog.objects.create(
            payment=paid,
            event_type=PaymentAuditLog.EventType.SUCCESS,
            amount=paid.amount,
            actor="fawry",
            payload={"note": "seed"},
        )
        PaymentAuditLog.objects.create(
            payment=failed,
            event_type=PaymentAuditLog.EventType.FAILURE,
            amount=failed.amount,
            actor="fawry",
            payload={"note": "seed"},
        )

        body_paid_success = signed_fawry_webhook(
            self.gw,
            str(paid.transaction_id),
            "success",
            str(paid.amount),
        )
        body_paid_failed = signed_fawry_webhook(
            self.gw,
            str(paid.transaction_id),
            "failed",
            str(paid.amount),
        )
        body_failed_success = signed_fawry_webhook(
            self.gw,
            str(failed.transaction_id),
            "success",
            str(failed.amount),
        )
        body_failed_failed = signed_fawry_webhook(
            self.gw,
            str(failed.transaction_id),
            "failed",
            str(failed.amount),
        )

        burst_each = 100
        for _ in range(burst_each):
            process_webhook("fawry", body_paid_success, body_paid_success["signature"])
            process_webhook("fawry", body_paid_failed, body_paid_failed["signature"])
            process_webhook("fawry", body_failed_success, body_failed_success["signature"])
            process_webhook("fawry", body_failed_failed, body_failed_failed["signature"])

        paid.refresh_from_db()
        failed.refresh_from_db()

        self.assertEqual(paid.status, Payment.PaymentStatus.PAID)
        self.assertEqual(failed.status, Payment.PaymentStatus.FAILED)

        self.assertEqual(
            PaymentAuditLog.objects.filter(
                payment=paid,
                event_type=PaymentAuditLog.EventType.SUCCESS,
            ).count(),
            1,
        )
        self.assertEqual(
            PaymentAuditLog.objects.filter(
                payment=paid,
                event_type=PaymentAuditLog.EventType.FAILURE,
            ).count(),
            0,
        )
        self.assertEqual(
            PaymentAuditLog.objects.filter(
                payment=failed,
                event_type=PaymentAuditLog.EventType.FAILURE,
            ).count(),
            1,
        )
        self.assertEqual(
            PaymentAuditLog.objects.filter(
                payment=failed,
                event_type=PaymentAuditLog.EventType.SUCCESS,
            ).count(),
            0,
        )

        expected_noops = burst_each * 2
        self.assertEqual(
            PaymentAuditLog.objects.filter(
                payment=paid,
                event_type=PaymentAuditLog.EventType.DUPLICATE_WEBHOOK_NOOP,
            ).count(),
            expected_noops,
        )
        self.assertEqual(
            PaymentAuditLog.objects.filter(
                payment=failed,
                event_type=PaymentAuditLog.EventType.DUPLICATE_WEBHOOK_NOOP,
            ).count(),
            expected_noops,
        )


class ConcurrencyCancelSubmitTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.student = make_student()
        self.payment = make_payment(self.student)

    def test_cancel_does_not_override_submit(self):
        errors: list[Exception] = []

        def _submit():
            try:
                fresh = Payment.objects.get(transaction_id=self.payment.transaction_id)
                initiate_with_gateway(fresh, "fawry")
            except Exception as exc:
                errors.append(exc)

        def _cancel():
            try:
                fresh = Payment.objects.get(transaction_id=self.payment.transaction_id)
                cancel_payment(fresh, actor="student", reason="test")
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=_submit)
        t2 = threading.Thread(target=_cancel)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        for err in errors:
            if isinstance(err, OperationalError) and "database table is locked" in str(err).lower():
                continue
            self.fail(f"Unexpected error during cancel/submit race: {err}")

        self.payment.refresh_from_db()
        if self.payment.status == Payment.PaymentStatus.CANCELLED:
            self.assertFalse(self.payment.used)
            self.assertIsNone(self.payment.payment_method)
            self.assertIsNone(self.payment.gateway_reference)
            self.assertEqual(
                PaymentAuditLog.objects.filter(
                    payment=self.payment,
                    event_type=PaymentAuditLog.EventType.CANCELLED,
                ).count(),
                1,
            )
            self.assertEqual(
                PaymentAuditLog.objects.filter(
                    payment=self.payment,
                    event_type=PaymentAuditLog.EventType.PROCESSING,
                ).count(),
                0,
            )
        elif self.payment.status == Payment.PaymentStatus.PENDING:
            # If both threads are blocked, pending should remain clean
            self.assertFalse(self.payment.used)
            self.assertIsNone(self.payment.payment_method)
            self.assertIsNone(self.payment.gateway_reference)
            self.assertEqual(
                PaymentAuditLog.objects.filter(
                    payment=self.payment,
                    event_type=PaymentAuditLog.EventType.CANCELLED,
                ).count(),
                0,
            )
            self.assertEqual(
                PaymentAuditLog.objects.filter(
                    payment=self.payment,
                    event_type=PaymentAuditLog.EventType.PROCESSING,
                ).count(),
                0,
            )
        else:
            self.assertIn(
                self.payment.status,
                {
                    Payment.PaymentStatus.PROCESSING,
                    Payment.PaymentStatus.PAID,
                    Payment.PaymentStatus.FAILED,
                    Payment.PaymentStatus.EXPIRED,
                },
            )
            if self.payment.status == Payment.PaymentStatus.PROCESSING:
                self.assertTrue(self.payment.used)
                self.assertEqual(self.payment.payment_method, "fawry")
            if self.payment.status in {
                Payment.PaymentStatus.PROCESSING,
                Payment.PaymentStatus.PAID,
                Payment.PaymentStatus.FAILED,
            }:
                self.assertEqual(
                    PaymentAuditLog.objects.filter(
                        payment=self.payment,
                        event_type=PaymentAuditLog.EventType.PROCESSING,
                    ).count(),
                    1,
                )
            self.assertEqual(
                PaymentAuditLog.objects.filter(
                    payment=self.payment,
                    event_type=PaymentAuditLog.EventType.CANCELLED,
                ).count(),
                0,
            )

class BurstAbuseGuardTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.client = APIClient()
        self.student = make_student()
        self.start_url = reverse("payments:payment-start")
        self.payment = make_payment(self.student)
        self.submit_url = reverse("payments:payment-submit", kwargs={"transaction_id": self.payment.transaction_id})
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

    @override_settings(ABUSE_PAYMENT_START_MAX=2, ABUSE_PAYMENT_START_WINDOW_SECONDS=300)
    def test_burst_start_eventually_rate_limited(self):
        self.client.post(self.start_url, {"student_id": "20210001"}, format="json")
        self.client.post(self.start_url, {"student_id": "20210001"}, format="json")
        res = self.client.post(self.start_url, {"student_id": "20210001"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_START_RATE_LIMITED")

    @override_settings(ABUSE_PAYMENT_SUBMIT_MAX=2, ABUSE_PAYMENT_SUBMIT_WINDOW_SECONDS=300)
    def test_burst_submit_eventually_rate_limited(self):
        self.client.post(self.submit_url, {"provider": "fawry"}, format="json")
        self.client.post(self.submit_url, {"provider": "fawry"}, format="json")
        res = self.client.post(self.submit_url, {"provider": "fawry"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(res.data["error"]["code"], "PAYMENT_SUBMIT_RATE_LIMITED")

    @override_settings(ABUSE_PAYMENT_SUBMIT_MAX=3, ABUSE_PAYMENT_SUBMIT_WINDOW_SECONDS=300)
    def test_submit_burst_rate_limit_and_state_coherent(self):
        responses = []
        for _ in range(6):
            res = self.client.post(self.submit_url, {"provider": "fawry"}, format="json")
            responses.append(res.status_code)

        self.assertIn(status.HTTP_429_TOO_MANY_REQUESTS, responses)

        self.payment.refresh_from_db()
        self.assertIn(
            self.payment.status,
            {
                Payment.PaymentStatus.PENDING,
                Payment.PaymentStatus.PROCESSING,
                Payment.PaymentStatus.PAID,
                Payment.PaymentStatus.FAILED,
                Payment.PaymentStatus.EXPIRED,
            },
        )
        self.assertLessEqual(
            PaymentAuditLog.objects.filter(
                payment=self.payment,
                event_type=PaymentAuditLog.EventType.PROCESSING,
            ).count(),
            1,
        )
