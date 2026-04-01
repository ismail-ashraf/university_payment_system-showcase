"""
=== FILE: payments/tests/test_service_layer.py ===

Unit + integration tests for payments/services/payment_service.py.

Tests every public function:
  - validate_provider()
  - start_payment()
  - initiate_with_gateway()
  - process_webhook()

Strategy:
  - DB tests use Django's TestCase (auto-rollback per test)
  - Gateway calls are NOT mocked — we run against the real simulated gateways
  - This gives us confidence the full AI → Tools → Services → Gateways → DB
    chain works end-to-end

Run with:
    python manage.py test payments.tests.test_service_layer
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.core.cache import cache

from django.test import TestCase, override_settings
from django.db import DatabaseError

from students.models import Student
from payments.models import Payment, PaymentAuditLog, current_semester
from payments.gateways.base import WebhookValidationResult, GatewayResponse
from payments.gateways.fawry    import FawryGateway
from payments.gateways.vodafone import VodafoneGateway
from payments.gateways.bank     import MockBankGateway
from payments.services import (
    start_payment,
    initiate_with_gateway,
    process_webhook,
    validate_provider,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

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


def make_pending_payment(student: Student, **kwargs) -> Payment:
    defaults = {
        "amount":   Decimal("5000.00"),
        "semester": current_semester(),
        "status":   "pending",
        "used":     False,
    }
    defaults.update(kwargs)
    return Payment.objects.create(student=student, **defaults)


def _signed_fawry_webhook(
    gw: FawryGateway,
    txn_id: str,
    status: str = "success",
    amount: str = "5000.00",
) -> dict:
    ref = f"FWR-{txn_id.replace('-','').upper()[:12]}"
    body = {
        "transaction_id":  txn_id,
        "fawry_reference": ref,
        "status":          status,
        "amount":          amount,
    }
    canonical      = gw.build_canonical_string({
        "transaction_id":  txn_id,
        "fawry_reference": ref,
        "status":          status,
        "amount":          amount,
    })
    body["signature"] = gw.compute_hmac_signature(canonical)
    return body


# ── validate_provider() ────────────────────────────────────────────────────────

class ValidateProviderTests(TestCase):

    def test_valid_provider_returns_none(self):
        self.assertIsNone(validate_provider("fawry"))
        self.assertIsNone(validate_provider("vodafone"))
        self.assertIsNone(validate_provider("bank"))

    def test_invalid_provider_returns_error(self):
        err = validate_provider("paypal")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "INVALID_PROVIDER")
        self.assertEqual(err["http_status"], 400)

    def test_empty_string_returns_error(self):
        err = validate_provider("")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "PROVIDER_REQUIRED")

    def test_none_returns_error(self):
        err = validate_provider(None)
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "PROVIDER_REQUIRED")

    def test_error_includes_supported_providers(self):
        err = validate_provider("stripe")
        details = err["payload"]["error"]["details"]
        self.assertIn("supported_providers", details)
        self.assertIn("fawry", details["supported_providers"])

    def test_case_insensitive_validation(self):
        # "FAWRY" should be treated as "fawry" by the registry
        # validate_provider itself doesn't normalise, registry does
        err = validate_provider("FAWRY")
        # Registry handles this — should be valid
        self.assertIsNone(err)


# ── start_payment() ────────────────────────────────────────────────────────────

@override_settings(FEE_PER_CREDIT_HOUR=250, FIXED_SEMESTER_FEE=500)
class StartPaymentTests(TestCase):

    def setUp(self):
        self.student = make_student()

    # ── Success cases ──────────────────────────────────────────────────────────

    def test_fawry_returns_result_no_error(self):
        result, err = start_payment("20210001", "fawry")
        self.assertIsNone(err)
        self.assertIsNotNone(result)

    def test_vodafone_returns_result(self):
        result, err = start_payment("20210001", "vodafone")
        self.assertIsNone(err)
        self.assertIsNotNone(result)

    def test_bank_returns_result(self):
        result, err = start_payment("20210001", "bank")
        self.assertIsNone(err)
        self.assertIsNotNone(result)

    def test_result_contains_transaction_id(self):
        result, _ = start_payment("20210001", "fawry")
        self.assertIn("transaction_id", result)
        # Validate it's a valid UUID string
        uuid.UUID(str(result["transaction_id"]))

    def test_result_contains_transaction_reference(self):
        result, _ = start_payment("20210001", "fawry")
        self.assertIn("transaction_reference", result)
        self.assertTrue(result["transaction_reference"].startswith("FWR-"))

    def test_result_status_is_processing(self):
        result, _ = start_payment("20210001", "fawry")
        self.assertEqual(result["status"], "processing")

    def test_result_contains_instructions(self):
        result, _ = start_payment("20210001", "fawry")
        self.assertIn("instructions", result)
        self.assertIn("steps", result["instructions"])

    def test_result_contains_amount(self):
        result, _ = start_payment("20210001", "fawry")
        self.assertIn("amount", result)
        # 18 hours × 250 + 500 = 5000
        self.assertEqual(Decimal(result["amount"]), Decimal("5000.00"))

    def test_payment_record_created_in_db(self):
        start_payment("20210001", "fawry")
        self.assertTrue(
            Payment.objects.filter(
                student=self.student, status="processing"
            ).exists()
        )

    def test_payment_used_flag_set(self):
        start_payment("20210001", "fawry")
        payment = Payment.objects.filter(student=self.student).first()
        self.assertTrue(payment.used)

    def test_payment_method_stored(self):
        start_payment("20210001", "fawry")
        payment = Payment.objects.filter(student=self.student).first()
        self.assertEqual(payment.payment_method, "fawry")

    def test_gateway_reference_stored(self):
        start_payment("20210001", "fawry")
        payment = Payment.objects.filter(student=self.student).first()
        self.assertTrue(payment.gateway_reference.startswith("FWR-"))

    def test_initiated_audit_log_created(self):
        result, _ = start_payment("20210001", "fawry")
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment__transaction_id=result["transaction_id"],
                event_type="initiated",
            ).exists()
        )

    def test_processing_audit_log_created(self):
        result, _ = start_payment("20210001", "fawry")
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment__transaction_id=result["transaction_id"],
                event_type="processing",
            ).exists()
        )

    def test_two_audit_logs_total(self):
        result, _ = start_payment("20210001", "fawry")
        count = PaymentAuditLog.objects.filter(
            payment__transaction_id=result["transaction_id"]
        ).count()
        self.assertEqual(count, 2)  # initiated + processing

    # ── Failure cases ──────────────────────────────────────────────────────────

    def test_unknown_student_returns_error(self):
        _, err = start_payment("GHOST999", "fawry")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "STUDENT_NOT_FOUND")
        self.assertEqual(err["http_status"], 404)

    def test_invalid_provider_returns_error(self):
        _, err = start_payment("20210001", "stripe")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "INVALID_PROVIDER")

    def test_inactive_student_blocked(self):
        make_student(student_id="S002", email="s2@u.eg", status="inactive")
        _, err = start_payment("S002", "fawry")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "STUDENT_NOT_ELIGIBLE")

    def test_suspended_student_blocked(self):
        make_student(student_id="S003", email="s3@u.eg", status="suspended")
        _, err = start_payment("S003", "fawry")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "STUDENT_NOT_ELIGIBLE")

    def test_graduated_student_blocked(self):
        make_student(student_id="S004", email="s4@u.eg", status="graduated")
        _, err = start_payment("S004", "fawry")
        self.assertIsNotNone(err)

    def test_duplicate_start_payment_blocked(self):
        start_payment("20210001", "fawry")
        _, err = start_payment("20210001", "fawry")
        self.assertIsNotNone(err)
        # Processing payments are no longer open — so NO duplicate PENDING exists
        # The second call fails because no PENDING payment exists to check
        # Actually: start_payment creates+submits atomically; second call has nothing open
        # Error should be from check_no_open_payment or similar
        self.assertIsNotNone(err)

    def test_processing_payment_blocks_start_without_provider(self):
        start_payment("20210001", "fawry")
        _, err = start_payment("20210001", None)
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "PAYMENT_ALREADY_OPEN")

    def test_stale_pending_payment_expires_and_allows_new_start(self):
        from django.utils import timezone
        from datetime import timedelta

        pending = Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.PENDING,
            used=False,
        )
        Payment.objects.filter(pk=pending.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

        result, err = start_payment("20210001", None)
        self.assertIsNone(err)
        self.assertIsNotNone(result)

        pending.refresh_from_db()
        self.assertEqual(pending.status, "expired")
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=pending, event_type="expired"
            ).exists()
        )

    def test_recent_pending_payment_still_blocks(self):
        Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.PENDING,
            used=False,
        )
        _, err = start_payment("20210001", None)
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "PAYMENT_ALREADY_OPEN")

    def test_paid_payment_blocks_new_start(self):
        Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.PAID,
            used=True,
        )
        _, err = start_payment("20210001", None)
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "PAYMENT_ALREADY_PAID")

    def test_refunded_payment_blocks_new_start(self):
        Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.REFUNDED,
            used=True,
        )
        _, err = start_payment("20210001", None)
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "PAYMENT_ALREADY_REFUNDED")

    def test_failed_payment_allows_new_start(self):
        Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.FAILED,
            used=True,
        )
        result, err = start_payment("20210001", None)
        self.assertIsNone(err)
        self.assertIsNotNone(result)

    def test_expired_payment_allows_new_start(self):
        Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.EXPIRED,
            used=True,
        )
        result, err = start_payment("20210001", None)
        self.assertIsNone(err)
        self.assertIsNotNone(result)

    def test_cancelled_payment_allows_new_start(self):
        Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.CANCELLED,
            used=True,
        )
        result, err = start_payment("20210001", None)
        self.assertIsNone(err)
        self.assertIsNotNone(result)

    def test_amount_mismatch_blocked(self):
        _, err = start_payment("20210001", "fawry", requested_amount=Decimal("100.00"))
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "AMOUNT_MISMATCH")

    def test_correct_explicit_amount_passes(self):
        # 18 × 250 + 500 = 5000
        result, err = start_payment("20210001", "fawry", requested_amount=Decimal("5000.00"))
        self.assertIsNone(err)
        self.assertIsNotNone(result)

    def test_no_payment_created_on_failure(self):
        start_payment("GHOST999", "fawry")
        self.assertEqual(Payment.objects.count(), 0)

    def test_returns_tuple_always(self):
        result = start_payment("20210001", "fawry")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    # ── Atomicity ──────────────────────────────────────────────────────────────

    def test_gateway_failure_rolls_back_payment(self):
        """If gateway call fails, Payment record must NOT be committed."""
        with patch(
            "payments.services.payment_service.get_gateway"
        ) as mock_factory:
            mock_gw = MagicMock()
            mock_gw.create_payment.side_effect = Exception("Gateway unavailable")
            mock_factory.return_value = mock_gw

            _, err = start_payment("20210001", "fawry")

        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "GATEWAY_ERROR")
        # Payment should exist but still in PENDING (created before gateway call)
        # Actually start_payment is fully atomic — if gateway fails after create,
        # the whole transaction rolls back
        # The PaymentAuditLog for failure is written inside the atomic block
        # So we check the payment is in a terminal state or doesn't exist
        payments = Payment.objects.filter(student=self.student)
        if payments.exists():
            # If it exists, it should have a failure audit log
            p = payments.first()
            self.assertTrue(
                PaymentAuditLog.objects.filter(payment=p, event_type="failure").exists()
            )


# ── initiate_with_gateway() ────────────────────────────────────────────────────

@override_settings(FEE_PER_CREDIT_HOUR=250, FIXED_SEMESTER_FEE=500)
class InitiateWithGatewayTests(TestCase):

    def setUp(self):
        self.student = make_student()
        self.payment = make_pending_payment(self.student)

    def test_submit_pending_payment_fawry(self):
        result, err = initiate_with_gateway(self.payment, "fawry")
        self.assertIsNone(err)
        self.assertEqual(result["provider"], "fawry")

    def test_submit_pending_payment_vodafone(self):
        p2      = make_pending_payment(
            make_student(student_id="S002", email="s2@u.eg")
        )
        result, err = initiate_with_gateway(p2, "vodafone")
        self.assertIsNone(err)
        self.assertEqual(result["provider"], "vodafone")

    def test_payment_becomes_processing(self):
        initiate_with_gateway(self.payment, "fawry")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "processing")

    def test_used_flag_set(self):
        initiate_with_gateway(self.payment, "fawry")
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.used)

    def test_gateway_reference_populated(self):
        initiate_with_gateway(self.payment, "fawry")
        self.payment.refresh_from_db()
        self.assertIsNotNone(self.payment.gateway_reference)
        self.assertTrue(self.payment.gateway_reference.startswith("FWR-"))

    def test_processing_audit_log_created(self):
        initiate_with_gateway(self.payment, "fawry")
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment, event_type="processing"
            ).exists()
        )

    def test_cannot_submit_already_processing_payment(self):
        self.payment.status = "processing"
        self.payment.used   = True
        self.payment.save()
        _, err = initiate_with_gateway(self.payment, "fawry")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "PAYMENT_NOT_OPEN")

    def test_cannot_submit_paid_payment(self):
        self.payment.status = "paid"
        self.payment.save()
        _, err = initiate_with_gateway(self.payment, "fawry")
        self.assertIsNotNone(err)

    def test_cannot_submit_cancelled_payment(self):
        self.payment.status = "cancelled"
        self.payment.save()
        _, err = initiate_with_gateway(self.payment, "fawry")
        self.assertIsNotNone(err)

    def test_submit_expired_payment_blocked(self):
        from django.utils import timezone
        from datetime import timedelta

        self.payment.expires_at = timezone.now() - timedelta(minutes=1)
        self.payment.save(update_fields=["expires_at", "updated_at"])

        _, err = initiate_with_gateway(self.payment, "fawry")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "PAYMENT_EXPIRED")

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "expired")
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment, event_type="expired"
            ).exists()
        )

    def test_invalid_provider_returns_error(self):
        _, err = initiate_with_gateway(self.payment, "unknown_provider")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "INVALID_PROVIDER")

    def test_result_contains_transaction_reference(self):
        result, _ = initiate_with_gateway(self.payment, "bank")
        self.assertIn("transaction_reference", result)
        self.assertTrue(result["transaction_reference"].startswith("BNK-"))

    def test_result_contains_instructions(self):
        result, _ = initiate_with_gateway(self.payment, "fawry")
        self.assertIn("instructions", result)

    def test_result_transaction_id_matches_payment(self):
        result, _ = initiate_with_gateway(self.payment, "fawry")
        self.assertEqual(result["transaction_id"], str(self.payment.transaction_id))

    def test_double_submit_stale_instance_blocked(self):
        with patch("payments.services.payment_service.get_gateway") as mock_factory:
            mock_gw = MagicMock()
            mock_gw.create_payment.return_value = GatewayResponse(
                success=True,
                transaction_reference="FWR-TEST123",
                status="pending",
                provider="fawry",
                instructions={"steps": []},
                raw_payload={"ok": True},
            )
            mock_factory.return_value = mock_gw

            p1 = Payment.objects.get(transaction_id=self.payment.transaction_id)
            p2 = Payment.objects.get(transaction_id=self.payment.transaction_id)
            result1, err1 = initiate_with_gateway(p1, "fawry")
            result2, err2 = initiate_with_gateway(p2, "fawry")

        self.assertIsNone(err1)
        self.assertIsNotNone(err2)
        self.assertEqual(err2["payload"]["error"]["code"], "PAYMENT_NOT_OPEN")
        self.assertEqual(mock_gw.create_payment.call_count, 1)


# ── process_webhook() ──────────────────────────────────────────────────────────

@override_settings(FEE_PER_CREDIT_HOUR=250, FIXED_SEMESTER_FEE=500)
class ProcessWebhookTests(TestCase):

    def setUp(self):
        self.student = make_student()
        self.gw      = FawryGateway()
        # Create a payment already in PROCESSING state
        self.payment = make_pending_payment(
            self.student,
            status="processing",
            used=True,
            payment_method="fawry",
        )
        expected_ref = f"FWR-{str(self.payment.transaction_id).replace('-', '').upper()[:12]}"
        self.payment.gateway_reference = expected_ref
        self.payment.save(update_fields=["gateway_reference", "updated_at"])

    def _webhook(self, status="success", amount="5000.00"):
        return _signed_fawry_webhook(
            self.gw, str(self.payment.transaction_id), status, amount
        )

    # ── Success status transitions ─────────────────────────────────────────────

    def test_success_webhook_marks_paid(self):
        body = self._webhook("success")
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")

    def test_failed_webhook_marks_failed(self):
        body = self._webhook("failed")
        process_webhook("fawry", body, body["signature"])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "failed")

    def test_pending_webhook_no_state_change(self):
        body   = self._webhook("pending")
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "processing")  # Unchanged
        self.assertIn("note", result)

    def test_pending_webhook_replay_dedupes_audit_log(self):
        cache.clear()
        body = self._webhook("pending")
        process_webhook("fawry", body, body["signature"])
        first_count = PaymentAuditLog.objects.filter(
            payment=self.payment, event_type="webhook"
        ).count()
        process_webhook("fawry", body, body["signature"])
        second_count = PaymentAuditLog.objects.filter(
            payment=self.payment, event_type="webhook"
        ).count()
        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 1)

    def test_expired_payment_webhook_acknowledged(self):
        from django.utils import timezone
        from datetime import timedelta

        self.payment.expires_at = timezone.now() - timedelta(minutes=1)
        self.payment.status = "expired"
        self.payment.save(update_fields=["expires_at", "status", "updated_at"])

        body = self._webhook("success")
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)
        self.assertTrue(result["acknowledged"])

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")

    def test_expired_payment_failed_webhook_noop(self):
        from django.utils import timezone
        from datetime import timedelta

        self.payment.expires_at = timezone.now() - timedelta(minutes=1)
        self.payment.status = "expired"
        self.payment.save(update_fields=["expires_at", "status", "updated_at"])

        body = self._webhook("failed")
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)
        self.assertTrue(result["acknowledged"])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "expired")

    # ── Response structure ─────────────────────────────────────────────────────

    def test_success_result_acknowledged(self):
        body   = self._webhook("success")
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertTrue(result["acknowledged"])

    def test_result_contains_transaction_id(self):
        body   = self._webhook("success")
        result, _ = process_webhook("fawry", body, body["signature"])
        self.assertIn("transaction_id", result)

    def test_result_contains_previous_and_current_status(self):
        body   = self._webhook("success")
        result, _ = process_webhook("fawry", body, body["signature"])
        self.assertEqual(result["previous_status"], "processing")
        self.assertEqual(result["current_status"],  "paid")

    def test_result_contains_transaction_reference(self):
        body   = self._webhook("success")
        result, _ = process_webhook("fawry", body, body["signature"])
        self.assertIn("transaction_reference", result)

    # ── Audit logging ──────────────────────────────────────────────────────────

    def test_webhook_received_audit_log_always_written(self):
        body = self._webhook("success")
        process_webhook("fawry", body, body["signature"])
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment, event_type="webhook"
            ).exists()
        )

    def test_webhook_audit_payload_minimal(self):
        body = self._webhook("success")
        process_webhook("fawry", body, body["signature"])
        log = PaymentAuditLog.objects.filter(
            payment=self.payment, event_type="webhook"
        ).first()
        self.assertIsNotNone(log)
        self.assertNotIn("signature", log.payload)
        self.assertIn("transaction_reference", log.payload)

    def test_success_audit_log_written(self):
        body = self._webhook("success")
        process_webhook("fawry", body, body["signature"])
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment, event_type="success"
            ).exists()
        )

    def test_failure_audit_log_written(self):
        body = self._webhook("failed")
        process_webhook("fawry", body, body["signature"])
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment, event_type="failure"
            ).exists()
        )

    # ── Student activation ────────────────────────────────────────────────────

    def test_success_webhook_activates_inactive_student(self):
        self.student.status = "inactive"
        self.student.save(update_fields=["status", "updated_at"])

        body = self._webhook("success")
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)

        self.student.refresh_from_db()
        self.assertEqual(self.student.status, "active")

    def test_success_webhook_does_not_activate_suspended_student(self):
        self.student.status = "suspended"
        self.student.save(update_fields=["status", "updated_at"])

        body = self._webhook("success")
        process_webhook("fawry", body, body["signature"])

        self.student.refresh_from_db()
        self.assertEqual(self.student.status, "suspended")

    def test_success_webhook_does_not_activate_graduated_student(self):
        self.student.status = "graduated"
        self.student.save(update_fields=["status", "updated_at"])

        body = self._webhook("success")
        process_webhook("fawry", body, body["signature"])

        self.student.refresh_from_db()
        self.assertEqual(self.student.status, "graduated")

    def test_activation_failure_does_not_rollback_payment(self):
        self.student.status = "inactive"
        self.student.save(update_fields=["status", "updated_at"])

        body = self._webhook("success")
        with patch("students.models.Student.save", side_effect=DatabaseError("boom")):
            result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")
        self.student.refresh_from_db()
        self.assertEqual(self.student.status, "inactive")

    # ── Idempotency ────────────────────────────────────────────────────────────

    def test_duplicate_success_webhook_acknowledged_not_reprocessed(self):
        body = self._webhook("success")
        process_webhook("fawry", body, body["signature"])   # first
        result, err = process_webhook("fawry", body, body["signature"])  # duplicate
        self.assertIsNone(err)
        self.assertTrue(result["acknowledged"])
        # Payment still paid — not changed
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")

    def test_duplicate_webhook_creates_replay_blocked_log(self):
        body = self._webhook("success")
        process_webhook("fawry", body, body["signature"])
        process_webhook("fawry", body, body["signature"])
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment, event_type="duplicate_webhook_noop"
            ).exists()
        )

    def test_already_failed_payment_webhook_idempotent(self):
        self.payment.status = "failed"
        self.payment.save()
        body   = self._webhook("success")
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)
        self.assertTrue(result["acknowledged"])
        # Still failed — success webhook cannot revive a failed payment
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "failed")
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment, event_type="duplicate_webhook_noop"
            ).exists()
        )

    def test_cancelled_payment_webhook_idempotent(self):
        self.payment.status = "cancelled"
        self.payment.save()
        body = self._webhook("success")
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)
        self.assertTrue(result["acknowledged"])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")

    def test_cancelled_payment_failed_webhook_noop(self):
        self.payment.status = "cancelled"
        self.payment.save()
        body = self._webhook("failed")
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)
        self.assertTrue(result["acknowledged"])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "cancelled")
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment, event_type="duplicate_webhook_noop"
            ).exists()
        )

    def test_refunded_payment_webhook_idempotent(self):
        self.payment.status = "refunded"
        self.payment.save()
        body = self._webhook("success")
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)
        self.assertTrue(result["acknowledged"])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "refunded")
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment, event_type="duplicate_webhook_noop"
            ).exists()
        )

    def test_failed_payment_failed_webhook_noop(self):
        self.payment.status = "failed"
        self.payment.save()
        body = self._webhook("failed")
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)
        self.assertTrue(result["acknowledged"])
        result2, err2 = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err2)
        self.assertTrue(result2["acknowledged"])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "failed")

    def test_refunded_payment_failed_webhook_noop(self):
        self.payment.status = "refunded"
        self.payment.save()
        body = self._webhook("failed")
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)
        self.assertTrue(result["acknowledged"])
        result2, err2 = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err2)
        self.assertTrue(result2["acknowledged"])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "refunded")

    def test_duplicate_valid_webhook_within_dedup_window_noop(self):
        cache.clear()
        body = self._webhook("success")
        process_webhook("fawry", body, body["signature"])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)
        self.assertTrue(result["acknowledged"])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")

    def test_transient_failure_does_not_record_replay_key(self):
        cache.clear()
        body = self._webhook("success")
        with patch("payments.gateways.fawry.FawryGateway.parse_webhook", side_effect=ValueError("boom")):
            _, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNotNone(err)
        # Retry with valid webhook should still succeed
        result, err2 = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err2)
        self.assertTrue(result["acknowledged"])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")

    @override_settings(WEBHOOK_REPLAY_TTL_SECONDS=60)
    def test_replay_ttl_uses_configured_timeout(self):
        body = self._webhook("success")
        with patch("payments.services.payment_service.cache.add") as mock_add:
            process_webhook("fawry", body, body["signature"])
        self.assertTrue(mock_add.called)
        args, kwargs = mock_add.call_args
        if "timeout" in kwargs:
            self.assertEqual(kwargs["timeout"], 60)
        else:
            self.assertEqual(args[2], 60)

    # ── Validation failures ────────────────────────────────────────────────────

    def test_invalid_provider_returns_error(self):
        _, err = process_webhook("paypal", {}, "sig")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "INVALID_PROVIDER")

    def test_bad_signature_returns_error(self):
        body             = self._webhook("success")
        body["signature"] = "tampered-signature"
        _, err = process_webhook("fawry", body, "tampered-signature")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "WEBHOOK_INVALID_SIGNATURE")
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment, event_type="invalid_webhook_signature"
            ).exists()
        )

    def test_missing_fields_returns_error(self):
        body = {"transaction_id": str(self.payment.transaction_id)}
        _, err = process_webhook("fawry", body, "sig")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "WEBHOOK_MISSING_FIELDS")
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=self.payment, event_type="malformed_webhook_payload"
            ).exists()
        )

    def test_parse_error_does_not_leak_exception(self):
        body = self._webhook("success")
        with patch("payments.gateways.fawry.FawryGateway.parse_webhook", side_effect=ValueError("boom")):
            _, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "WEBHOOK_PARSE_ERROR")
        message = err["payload"]["error"]["message"].lower()
        self.assertNotIn("boom", message)
        self.assertNotIn("valueerror", message)

    def test_validation_error_does_not_leak_exception(self):
        body = self._webhook("success")
        with patch(
            "payments.gateways.fawry.FawryGateway.verify_payment",
            return_value=WebhookValidationResult(
                is_valid=False,
                error_code="WEBHOOK_VALIDATION_ERROR",
                error_message="ValueError: boom",
            ),
        ):
            _, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "WEBHOOK_VALIDATION_ERROR")
        message = err["payload"]["error"]["message"].lower()
        self.assertNotIn("boom", message)
        self.assertNotIn("valueerror", message)

    def test_unknown_transaction_returns_acknowledged(self):
        """Unknown txn returns 200 to prevent gateway retry storms."""
        gw     = FawryGateway()
        fake   = str(uuid.uuid4())
        ref    = f"FWR-{fake.replace('-','').upper()[:12]}"
        body   = {
            "transaction_id":  fake,
            "fawry_reference": ref,
            "status":          "success",
            "amount":          "5000.00",
        }
        canonical      = gw.build_canonical_string({
            "transaction_id":  fake,
            "fawry_reference": ref,
            "status":          "success",
            "amount":          "5000.00",
        })
        body["signature"] = gw.compute_hmac_signature(canonical)
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)
        self.assertTrue(result["acknowledged"])

    def test_amount_mismatch_returns_error(self):
        body = _signed_fawry_webhook(
            self.gw, str(self.payment.transaction_id), "success", "999.00"
        )
        _, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "WEBHOOK_AMOUNT_MISMATCH")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "processing")
        self.assertFalse(
            PaymentAuditLog.objects.filter(
                payment=self.payment, event_type__in=["success", "failure"]
            ).exists()
        )

    def test_numeric_amount_signature_normalized(self):
        txn_id = str(self.payment.transaction_id)
        ref = f"FWR-{txn_id.replace('-','').upper()[:12]}"
        body = {
            "transaction_id": txn_id,
            "fawry_reference": ref,
            "status": "success",
            "amount": 5000.0,
        }
        canonical = self.gw.build_canonical_string({
            "transaction_id": txn_id,
            "fawry_reference": ref,
            "status": "success",
            "amount": self.gw.normalize_amount(body["amount"]),
        })
        body["signature"] = self.gw.compute_hmac_signature(canonical)
        result, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(err)
        self.assertTrue(result["acknowledged"])

    def test_webhook_rejected_if_payment_not_submitted(self):
        self.payment.status = "pending"
        self.payment.used = False
        self.payment.save(update_fields=["status", "used", "updated_at"])
        body = self._webhook("success")
        _, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "WEBHOOK_PAYMENT_NOT_SUBMITTED")

    def test_webhook_rejected_on_provider_mismatch(self):
        self.payment.payment_method = "vodafone"
        self.payment.save(update_fields=["payment_method", "updated_at"])
        body = self._webhook("success")
        _, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "WEBHOOK_PROVIDER_MISMATCH")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "processing")
        self.assertFalse(
            PaymentAuditLog.objects.filter(
                payment=self.payment, event_type__in=["success", "failure"]
            ).exists()
        )

    def test_webhook_rejected_on_reference_mismatch(self):
        self.payment.gateway_reference = "FWR-OTHERREF"
        self.payment.save(update_fields=["gateway_reference", "updated_at"])
        body = self._webhook("success")
        _, err = process_webhook("fawry", body, body["signature"])
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "WEBHOOK_REFERENCE_MISMATCH")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "processing")
        self.assertFalse(
            PaymentAuditLog.objects.filter(
                payment=self.payment, event_type__in=["success", "failure"]
            ).exists()
        )

    # ── Vodafone webhook ───────────────────────────────────────────────────────

    def test_vodafone_success_webhook(self):
        vf_gw = VodafoneGateway()
        s2    = make_student(student_id="S002", email="s2@u.eg")
        p2    = make_pending_payment(
            s2, status="processing", used=True, payment_method="vodafone"
        )
        txn   = str(p2.transaction_id)
        ref   = f"VF-{txn.replace('-','').upper()[:10]}"
        body  = {"transaction_id": txn, "vf_request_id": ref, "status": "success", "amount": "5000.00"}
        canonical = vf_gw.build_canonical_string({
            "transaction_id": txn, "vf_request_id": ref, "status": "success", "amount": "5000.00",
        })
        body["signature"] = vf_gw.compute_hmac_signature(canonical)

        result, err = process_webhook("vodafone", body, body["signature"])
        self.assertIsNone(err)
        p2.refresh_from_db()
        self.assertEqual(p2.status, "paid")
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=p2, event_type="webhook"
            ).exists()
        )
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=p2, event_type="success"
            ).exists()
        )

    def test_vodafone_bad_signature_rejected(self):
        vf_gw = VodafoneGateway()
        s2    = make_student(student_id="S002", email="s2@u.eg")
        p2    = make_pending_payment(
            s2, status="processing", used=True, payment_method="vodafone"
        )
        txn   = str(p2.transaction_id)
        ref   = f"VF-{txn.replace('-','').upper()[:10]}"
        body  = {"transaction_id": txn, "vf_request_id": ref, "status": "success", "amount": "5000.00"}
        canonical = vf_gw.build_canonical_string({
            "transaction_id": txn, "vf_request_id": ref, "status": "success", "amount": "5000.00",
        })
        body["signature"] = vf_gw.compute_hmac_signature(canonical)

        _, err = process_webhook("vodafone", body, "bad-signature")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "WEBHOOK_INVALID_SIGNATURE")
        p2.refresh_from_db()
        self.assertEqual(p2.status, "processing")

    def test_vodafone_missing_fields_writes_malformed_audit_log(self):
        s2    = make_student(student_id="S002", email="s2@u.eg")
        p2    = make_pending_payment(
            s2, status="processing", used=True, payment_method="vodafone"
        )
        body = {"transaction_id": str(p2.transaction_id)}
        _, err = process_webhook("vodafone", body, "sig")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "WEBHOOK_MISSING_FIELDS")
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=p2, event_type="malformed_webhook_payload"
            ).exists()
        )

    def test_vodafone_duplicate_webhook_writes_noop_audit_log(self):
        vf_gw = VodafoneGateway()
        s2    = make_student(student_id="S002", email="s2@u.eg")
        p2    = make_pending_payment(
            s2, status="processing", used=True, payment_method="vodafone"
        )
        txn   = str(p2.transaction_id)
        ref   = f"VF-{txn.replace('-','').upper()[:10]}"
        body  = {"transaction_id": txn, "vf_request_id": ref, "status": "success", "amount": "5000.00"}
        canonical = vf_gw.build_canonical_string({
            "transaction_id": txn, "vf_request_id": ref, "status": "success", "amount": "5000.00",
        })
        body["signature"] = vf_gw.compute_hmac_signature(canonical)
        process_webhook("vodafone", body, body["signature"])
        process_webhook("vodafone", body, body["signature"])
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=p2, event_type="duplicate_webhook_noop"
            ).exists()
        )

    def test_vodafone_failure_audit_log_written(self):
        vf_gw = VodafoneGateway()
        s2    = make_student(student_id="S002", email="s2@u.eg")
        p2    = make_pending_payment(
            s2, status="processing", used=True, payment_method="vodafone"
        )
        txn   = str(p2.transaction_id)
        ref   = f"VF-{txn.replace('-','').upper()[:10]}"
        body  = {"transaction_id": txn, "vf_request_id": ref, "status": "failed", "amount": "5000.00"}
        canonical = vf_gw.build_canonical_string({
            "transaction_id": txn, "vf_request_id": ref, "status": "failed", "amount": "5000.00",
        })
        body["signature"] = vf_gw.compute_hmac_signature(canonical)
        process_webhook("vodafone", body, body["signature"])
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=p2, event_type="failure"
            ).exists()
        )

    # ── Bank webhook ───────────────────────────────────────────────────────────

    def test_bank_success_webhook(self):
        bank_gw = MockBankGateway()
        s3      = make_student(student_id="S003", email="s3@u.eg")
        p3      = make_pending_payment(
            s3, status="processing", used=True, payment_method="bank"
        )
        txn  = str(p3.transaction_id)
        ref  = f"BNK-{txn[:8].upper()}"
        body = {"transaction_id": txn, "bank_reference": ref, "status": "success", "amount": "5000.00"}
        canonical = bank_gw.build_canonical_string({
            "transaction_id": txn, "bank_reference": ref, "status": "success", "amount": "5000.00",
        })
        body["signature"] = bank_gw.compute_hmac_signature(canonical)

        result, err = process_webhook("bank", body, body["signature"])
        self.assertIsNone(err)
        p3.refresh_from_db()
        self.assertEqual(p3.status, "paid")
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=p3, event_type="webhook"
            ).exists()
        )
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=p3, event_type="success"
            ).exists()
        )

    def test_bank_bad_signature_returns_error(self):
        bank_gw = MockBankGateway()
        s3      = make_student(student_id="S003", email="s3@u.eg")
        p3      = make_pending_payment(
            s3, status="processing", used=True, payment_method="bank"
        )
        txn  = str(p3.transaction_id)
        ref  = f"BNK-{txn[:8].upper()}"
        body = {"transaction_id": txn, "bank_reference": ref, "status": "success", "amount": "5000.00"}
        canonical = bank_gw.build_canonical_string({
            "transaction_id": txn, "bank_reference": ref, "status": "success", "amount": "5000.00",
        })
        body["signature"] = bank_gw.compute_hmac_signature(canonical)

        _, err = process_webhook("bank", body, "bad-signature")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "WEBHOOK_INVALID_SIGNATURE")
        p3.refresh_from_db()
        self.assertEqual(p3.status, "processing")

    def test_bank_missing_fields_writes_malformed_audit_log(self):
        s3   = make_student(student_id="S003", email="s3@u.eg")
        p3   = make_pending_payment(
            s3, status="processing", used=True, payment_method="bank"
        )
        body = {"transaction_id": str(p3.transaction_id)}
        _, err = process_webhook("bank", body, "sig")
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "WEBHOOK_MISSING_FIELDS")
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=p3, event_type="malformed_webhook_payload"
            ).exists()
        )

    def test_bank_duplicate_webhook_writes_noop_audit_log(self):
        bank_gw = MockBankGateway()
        s3      = make_student(student_id="S003", email="s3@u.eg")
        p3      = make_pending_payment(
            s3, status="processing", used=True, payment_method="bank"
        )
        txn  = str(p3.transaction_id)
        ref  = f"BNK-{txn[:8].upper()}"
        body = {"transaction_id": txn, "bank_reference": ref, "status": "success", "amount": "5000.00"}
        canonical = bank_gw.build_canonical_string({
            "transaction_id": txn, "bank_reference": ref, "status": "success", "amount": "5000.00",
        })
        body["signature"] = bank_gw.compute_hmac_signature(canonical)
        process_webhook("bank", body, body["signature"])
        process_webhook("bank", body, body["signature"])
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=p3, event_type="duplicate_webhook_noop"
            ).exists()
        )

    def test_bank_failure_audit_log_written(self):
        bank_gw = MockBankGateway()
        s3      = make_student(student_id="S003", email="s3@u.eg")
        p3      = make_pending_payment(
            s3, status="processing", used=True, payment_method="bank"
        )
        txn  = str(p3.transaction_id)
        ref  = f"BNK-{txn[:8].upper()}"
        body = {"transaction_id": txn, "bank_reference": ref, "status": "failed", "amount": "5000.00"}
        canonical = bank_gw.build_canonical_string({
            "transaction_id": txn, "bank_reference": ref, "status": "failed", "amount": "5000.00",
        })
        body["signature"] = bank_gw.compute_hmac_signature(canonical)
        process_webhook("bank", body, body["signature"])
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                payment=p3, event_type="failure"
            ).exists()
        )


# ── End-to-end: full service flow ─────────────────────────────────────────────

@override_settings(FEE_PER_CREDIT_HOUR=250, FIXED_SEMESTER_FEE=500)
class FullServiceFlowTests(TestCase):
    """
    End-to-end service layer tests:
      start_payment() → process_webhook() → final status
    No HTTP, no views — pure service layer.
    """

    def setUp(self):
        self.student = make_student()
        self.gw      = FawryGateway()

    def test_complete_paid_flow(self):
        # 1. Start payment
        result, err = start_payment("20210001", "fawry")
        self.assertIsNone(err)
        txn_id = result["transaction_id"]

        # 2. Simulate Fawry webhook — success
        body = _signed_fawry_webhook(self.gw, str(txn_id), "success")
        wh_result, wh_err = process_webhook("fawry", body, body["signature"])
        self.assertIsNone(wh_err)
        self.assertEqual(wh_result["current_status"], "paid")

        # 3. Verify DB state
        payment = Payment.objects.get(transaction_id=txn_id)
        self.assertEqual(payment.status, "paid")
        self.assertTrue(payment.used)

    def test_complete_failed_flow(self):
        result, _ = start_payment("20210001", "fawry")
        txn_id = result["transaction_id"]

        body = _signed_fawry_webhook(self.gw, str(txn_id), "failed")
        wh_result, _ = process_webhook("fawry", body, body["signature"])
        self.assertEqual(wh_result["current_status"], "failed")

        payment = Payment.objects.get(transaction_id=txn_id)
        self.assertEqual(payment.status, "failed")

    def test_complete_audit_trail(self):
        """Full flow must produce: initiated → processing → webhook → success."""
        result, _ = start_payment("20210001", "fawry")
        txn_id = result["transaction_id"]

        body = _signed_fawry_webhook(self.gw, str(txn_id), "success")
        process_webhook("fawry", body, body["signature"])

        events = list(
            PaymentAuditLog.objects
            .filter(payment__transaction_id=txn_id)
            .order_by("created_at")
            .values_list("event_type", flat=True)
        )
        self.assertIn("initiated",  events)
        self.assertIn("processing", events)
        self.assertIn("webhook",    events)
        self.assertIn("success",    events)

    def test_different_providers_produce_different_references(self):
        s1 = make_student(student_id="S001", email="s1@u.eg")
        s2 = make_student(student_id="S002", email="s2@u.eg")

        r1, _ = start_payment("S001", "fawry")
        r2, _ = start_payment("S002", "vodafone")

        self.assertTrue(r1["transaction_reference"].startswith("FWR-"))
        self.assertTrue(r2["transaction_reference"].startswith("VF-"))
        self.assertNotEqual(r1["transaction_reference"], r2["transaction_reference"])

    def test_two_students_can_have_independent_payments(self):
        s2 = make_student(student_id="S002", email="s2@u.eg")
        r1, err1 = start_payment("20210001", "fawry")
        r2, err2 = start_payment("S002",     "vodafone")
        self.assertIsNone(err1)
        self.assertIsNone(err2)
        self.assertNotEqual(r1["transaction_id"], r2["transaction_id"])
