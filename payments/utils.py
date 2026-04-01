"""
payments/utils.py
Phase 2 — Payment utility functions.

All business logic lives here, NEVER in views.py.
Each function has a single responsibility and is independently testable.

Functions:
  get_student_or_error()        → fetch Student or return structured error dict
  get_open_payment()            → check for existing PENDING payment
  compute_expected_amount()     → call fee_calculator and return Decimal
  validate_amount_match()       → compare requested vs expected amount
  create_payment_record()       → atomically create Payment + initial AuditLog
  build_error()                 → standardised error dict factory
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from django.db import transaction as db_transaction

from students.models import Student
from students.fee_calculator import calculate_student_fees
from .models import Payment, PaymentAuditLog, current_semester

logger = logging.getLogger(__name__)


# ─── Error dict factory ────────────────────────────────────────────────────────

def build_error(code: str, message: str, details: dict = None, http_status: int = 400) -> dict:
    """
    Returns a structured error dict.
    Views convert this to a DRF Response — utils never import Response directly
    so they stay framework-agnostic and testable without a request context.
    """
    return {
        "_is_error": True,
        "http_status": http_status,
        "payload": {
            "success": False,
            "error": {
                "code":    code,
                "message": message,
                "details": details or {},
            },
        },
    }


# ─── Student validation ────────────────────────────────────────────────────────

def get_student_or_error(student_id: str) -> tuple[Optional[Student], Optional[dict]]:
    """
    Fetch Student by student_id (case-insensitive).
    Returns (student, None) on success, (None, error_dict) on failure.
    """
    try:
        student = Student.objects.select_related().get(student_id=student_id.upper().strip())
        return student, None
    except Student.DoesNotExist:
        return None, build_error(
            code="STUDENT_NOT_FOUND",
            message=f"Student with ID '{student_id}' was not found.",
            http_status=404,
        )


def validate_student_eligibility(student: Student) -> Optional[dict]:
    """
    Check that the student is allowed to initiate a payment.
    Rules:
      - Status must be 'active' (suspended/graduated students cannot pay)
    Returns None if eligible, error_dict otherwise.
    """
    if student.status != "active":
        return build_error(
            code="STUDENT_NOT_ELIGIBLE",
            message=(
                f"Student '{student.student_id}' has status '{student.status}' "
                f"and is not eligible to initiate a payment."
            ),
            http_status=400,
        )
    return None


# ─── Duplicate / open-payment check ───────────────────────────────────────────

# def get_open_payment(student: Student, semester: str) -> Optional[Payment]:
#     """
#     Return the existing PENDING (and not used) payment for this student/semester,
#     or None if there isn't one.
#     Uses only indexed columns in the WHERE clause.
#     """
#     return (
#         Payment.objects
#         .filter(
#             student=student,
#             semester=semester,
#             status=Payment.PaymentStatus.PENDING,
#             used=False,
#         )
#         .first()
#     )

def get_open_payment(student: Student, semester: str) -> Optional[Payment]:
    """
    Return the existing payment that is still editable by the student.

    In the original Phase 2 flow, only a fresh PENDING payment with used=False is
    considered "open" for create/cancel operations. Once a payment is submitted to a
    gateway (used=True / processing), it is no longer cancellable through this path.
    """
    return (
        Payment.objects.filter(
            student=student,
            semester=semester,
            status=Payment.PaymentStatus.PENDING,
            used=False,
        )
        .order_by("-created_at")
        .first()
    )


def check_no_open_payment(student: Student, semester: str) -> Optional[dict]:
    """
    Ensure the student does NOT already have an open payment this semester.
    Returns None if safe to proceed, error_dict if blocked.
    """
    existing = get_open_payment(student, semester)
    if existing:
        return build_error(
            code="PAYMENT_ALREADY_OPEN",
            message=(
                f"Student '{student.student_id}' already has an open payment for "
                f"semester '{semester}'. Complete or cancel it before starting a new one."
            ),
            details={
                "existing_transaction_id": existing.transaction_id_str,
                "amount":  str(existing.amount),
                "created_at": existing.created_at.isoformat(),
            },
            http_status=400,
        )
    return None


# ─── Amount calculation & validation ──────────────────────────────────────────

def compute_expected_amount(student: Student) -> Decimal:
    """
    Calculate the expected semester fee for this student using fee_calculator.
    Returns a Decimal so it can be stored in DecimalField without precision loss.
    """
    breakdown = calculate_student_fees(allowed_hours=student.allowed_hours)
    return Decimal(str(breakdown.total))


def validate_amount_match(
    requested_amount: Optional[Decimal],
    expected_amount: Decimal,
    tolerance: Decimal = Decimal("0.01"),
) -> Optional[dict]:
    """
    If the caller supplies an explicit amount, verify it matches the computed fee
    within a small tolerance (to handle floating-point edge cases).

    If no amount is supplied (None), skip validation — the system uses the
    computed amount automatically.
    """
    if requested_amount is None:
        return None

    diff = abs(requested_amount - expected_amount)
    if diff > tolerance:
        return build_error(
            code="AMOUNT_MISMATCH",
            message=(
                f"The requested amount ({requested_amount} EGP) does not match "
                f"the expected semester fee ({expected_amount} EGP)."
            ),
            details={
                "expected_amount":  str(expected_amount),
                "requested_amount": str(requested_amount),
                "difference":       str(diff),
            },
            http_status=400,
        )
    return None


# ─── Payment creation ──────────────────────────────────────────────────────────

@db_transaction.atomic
def create_payment_record(student: Student, amount: Decimal, semester: str) -> Payment:
    """
    Atomically:
      1. Create a new Payment record (status=PENDING, used=False).
      2. Insert the initial 'initiated' AuditLog entry.

    The atomic block means both writes succeed or both roll back — the DB
    never ends up with a Payment that has no audit trail.
    """
    payment = Payment.objects.create(
        student=student,
        amount=amount,
        semester=semester,
        status=Payment.PaymentStatus.PENDING,
        used=False,
    )

    PaymentAuditLog.objects.create(
        payment=payment,
        event_type=PaymentAuditLog.EventType.INITIATED,
        amount=amount,
        actor="system",
        payload={
            "student_id":    student.student_id,
            "semester":      semester,
            "allowed_hours": student.allowed_hours,
            "gpa":           str(student.gpa),
        },
    )

    logger.info(
        "Payment initiated | student=%s | semester=%s | amount=%s | txn=%s",
        student.student_id,
        semester,
        amount,
        payment.transaction_id_str,
        extra={
            "event": "payment_initiated",
            "transaction_id": payment.transaction_id_str,
            "student_id": student.student_id,
        },
    )

    return payment
