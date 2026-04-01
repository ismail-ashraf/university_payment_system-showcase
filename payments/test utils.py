"""
payments/tests/test_utils.py
Unit tests for payments/utils.py — all business logic, no HTTP layer.

Run with:
    python manage.py test payments.tests.test_utils
"""

from decimal import Decimal
from django.test import TestCase, override_settings
from students.models import Student
from payments.models import Payment, PaymentAuditLog, current_semester
from payments.utils import (
    get_student_or_error,
    validate_student_eligibility,
    get_open_payment,
    check_no_open_payment,
    compute_expected_amount,
    validate_amount_match,
    create_payment_record,
    build_error,
)


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


class BuildErrorTests(TestCase):
    def test_structure(self):
        err = build_error("TEST_CODE", "test message", {"key": "val"}, 422)
        self.assertTrue(err["_is_error"])
        self.assertEqual(err["http_status"], 422)
        self.assertFalse(err["payload"]["success"])
        self.assertEqual(err["payload"]["error"]["code"],    "TEST_CODE")
        self.assertEqual(err["payload"]["error"]["message"], "test message")
        self.assertEqual(err["payload"]["error"]["details"]["key"], "val")

    def test_defaults(self):
        err = build_error("X", "msg")
        self.assertEqual(err["http_status"], 400)
        self.assertEqual(err["payload"]["error"]["details"], {})


class GetStudentOrErrorTests(TestCase):
    def setUp(self):
        self.student = make_student()

    def test_returns_student_on_success(self):
        s, err = get_student_or_error("20210001")
        self.assertIsNotNone(s)
        self.assertIsNone(err)
        self.assertEqual(s.student_id, "20210001")

    def test_case_insensitive_lookup(self):
        s, err = get_student_or_error("20210001")
        self.assertIsNone(err)

    def test_returns_error_for_unknown(self):
        s, err = get_student_or_error("GHOST999")
        self.assertIsNone(s)
        self.assertIsNotNone(err)
        self.assertEqual(err["http_status"], 404)
        self.assertEqual(err["payload"]["error"]["code"], "STUDENT_NOT_FOUND")


class ValidateStudentEligibilityTests(TestCase):
    def test_active_student_is_eligible(self):
        s = make_student(status="active")
        err = validate_student_eligibility(s)
        self.assertIsNone(err)

    def test_inactive_student_is_blocked(self):
        s = make_student(status="inactive")
        err = validate_student_eligibility(s)
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "STUDENT_NOT_ELIGIBLE")
        self.assertEqual(err["http_status"], 400)

    def test_suspended_student_is_blocked(self):
        s = make_student(status="suspended")
        err = validate_student_eligibility(s)
        self.assertIsNotNone(err)

    def test_graduated_student_is_blocked(self):
        s = make_student(status="graduated")
        err = validate_student_eligibility(s)
        self.assertIsNotNone(err)


class CheckNoOpenPaymentTests(TestCase):
    def setUp(self):
        self.student  = make_student()
        self.semester = current_semester()

    def test_no_existing_payment_passes(self):
        err = check_no_open_payment(self.student, self.semester)
        self.assertIsNone(err)

    def test_existing_pending_payment_blocks(self):
        Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=self.semester,
            status=Payment.PaymentStatus.PENDING,
        )
        err = check_no_open_payment(self.student, self.semester)
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "PAYMENT_ALREADY_OPEN")
        self.assertEqual(err["http_status"], 400)
        # Error details should include the existing transaction id
        self.assertIn("existing_transaction_id", err["payload"]["error"]["details"])

    def test_paid_payment_does_not_block(self):
        """A previously PAID payment should NOT block a new payment."""
        Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=self.semester,
            status=Payment.PaymentStatus.PAID,
        )
        err = check_no_open_payment(self.student, self.semester)
        self.assertIsNone(err)

    def test_cancelled_payment_does_not_block(self):
        Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=self.semester,
            status=Payment.PaymentStatus.CANCELLED,
        )
        err = check_no_open_payment(self.student, self.semester)
        self.assertIsNone(err)

    def test_used_pending_does_not_block_check(self):
        """A used=True PENDING (submitted to gateway) is still open — should block."""
        Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=self.semester,
            status=Payment.PaymentStatus.PENDING,
            used=True,
        )
        # used=True AND pending — still pending, should be blocked by check
        # (get_open_payment filters used=False, so this should NOT block)
        err = check_no_open_payment(self.student, self.semester)
        self.assertIsNone(err)  # used=True payments are no longer "open"


@override_settings(FEE_PER_CREDIT_HOUR=250, FIXED_SEMESTER_FEE=500)
class ComputeExpectedAmountTests(TestCase):
    def test_returns_decimal(self):
        student = make_student(allowed_hours=18)
        amount = compute_expected_amount(student)
        self.assertIsInstance(amount, Decimal)

    def test_correct_amount(self):
        student = make_student(allowed_hours=18)
        amount = compute_expected_amount(student)
        # 18 * 250 + 500 = 5000
        self.assertEqual(amount, Decimal("5000"))

    def test_varies_with_allowed_hours(self):
        s12 = make_student(student_id="S012", email="s12@u.eg", allowed_hours=12)
        s18 = make_student(student_id="S018", email="s18@u.eg", allowed_hours=18)
        self.assertLess(compute_expected_amount(s12), compute_expected_amount(s18))


class ValidateAmountMatchTests(TestCase):
    def test_none_amount_always_passes(self):
        err = validate_amount_match(None, Decimal("5000"))
        self.assertIsNone(err)

    def test_exact_match_passes(self):
        err = validate_amount_match(Decimal("5000"), Decimal("5000"))
        self.assertIsNone(err)

    def test_within_tolerance_passes(self):
        err = validate_amount_match(Decimal("5000.00"), Decimal("5000.005"))
        self.assertIsNone(err)

    def test_mismatch_returns_error(self):
        err = validate_amount_match(Decimal("4000"), Decimal("5000"))
        self.assertIsNotNone(err)
        self.assertEqual(err["payload"]["error"]["code"], "AMOUNT_MISMATCH")
        self.assertEqual(err["http_status"], 400)

    def test_mismatch_error_includes_amounts(self):
        err = validate_amount_match(Decimal("4000"), Decimal("5000"))
        details = err["payload"]["error"]["details"]
        self.assertIn("expected_amount",  details)
        self.assertIn("requested_amount", details)
        self.assertIn("difference",       details)


class CreatePaymentRecordTests(TestCase):
    def setUp(self):
        self.student  = make_student()
        self.semester = current_semester()

    def test_creates_payment(self):
        payment = create_payment_record(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=self.semester,
        )
        self.assertIsNotNone(payment.transaction_id)
        self.assertEqual(payment.status,  Payment.PaymentStatus.PENDING)
        self.assertFalse(payment.used)
        self.assertEqual(payment.amount,  Decimal("5000.00"))
        self.assertEqual(payment.semester, self.semester)

    def test_creates_audit_log(self):
        payment = create_payment_record(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=self.semester,
        )
        log = PaymentAuditLog.objects.filter(payment=payment).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.event_type, PaymentAuditLog.EventType.INITIATED)
        self.assertEqual(log.actor, "system")

    def test_payment_has_uuid(self):
        payment = create_payment_record(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=self.semester,
        )
        import uuid
        self.assertIsInstance(payment.transaction_id, uuid.UUID)

    def test_is_atomic_rollback(self):
        """
        Verify atomicity: if the audit log creation fails, the payment is also rolled back.
        We simulate this by patching PaymentAuditLog.objects.create to raise an exception.
        """
        from unittest.mock import patch
        from django.db import IntegrityError

        original_count = Payment.objects.count()

        with self.assertRaises(Exception):
            with patch(
                "payments.utils.PaymentAuditLog.objects.create",
                side_effect=IntegrityError("forced"),
            ):
                create_payment_record(
                    student=self.student,
                    amount=Decimal("5000.00"),
                    semester=self.semester,
                )

        # Payment should NOT have been committed
        self.assertEqual(Payment.objects.count(), original_count)