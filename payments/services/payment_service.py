"""
=== FILE: payments/services/payment_service.py ===

Payment Service — the single orchestration layer for all payment operations.

PRD Flow:
  AI → Tools → Services → Gateways → DB

This file is the "Services" layer. It coordinates:
  - Student + payment validation (via utils.py)
  - Gateway selection (via gateways/registry.py)
  - Payment record lifecycle (create → processing → paid/failed)
  - Duplicate prevention (unique constraint + used flag)
  - Audit logging (every state change logged to PaymentAuditLog)
  - Error propagation (structured error dicts, never raw exceptions to views)

Public functions:
  start_payment(student_id, provider)     ← PRD: full flow in one call
  initiate_with_gateway(payment, provider) ← submit existing payment to gateway
  process_webhook(provider, raw_body, sig) ← handle inbound gateway callback
  validate_provider(provider)             ← provider validation helper

Architecture rules:
  - Views call services. Services never call views.
  - Services call gateways + utils. Neither calls services.
  - All DB writes are inside @db_transaction.atomic blocks.
  - All functions return (result, error) tuples — never raise to views.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from datetime import timedelta
from typing import Optional

from django.utils import timezone
from django.core.cache import cache
from django.conf import settings
from django.db import transaction as db_transaction
from django.db import DatabaseError

from payments.models import Payment, PaymentAuditLog, current_semester
from students.models import Student
from payments.gateways import (
    get_gateway,
    is_valid_provider,
    SUPPORTED_PROVIDERS,
)
from payments.utils import (
    build_error,
    get_student_or_error,
    validate_student_eligibility,
    check_no_open_payment,
    compute_expected_amount,
    validate_amount_match,
    create_payment_record,
)

logger = logging.getLogger(__name__)

_PROVIDER_EXPIRY_WINDOWS = {
    "fawry":    timedelta(hours=72),
    "vodafone": timedelta(minutes=30),
    "bank":     timedelta(hours=48),
}

_PENDING_STALE_WINDOW = timedelta(hours=24)

_DEFAULT_REPLAY_TTL_SECONDS = 1800


def _webhook_replay_key(
    provider: str,
    transaction_id: str,
    transaction_reference: str,
    status: str,
    amount: str,
) -> str:
    return "webhook-replay:%s:%s:%s:%s:%s" % (
        (provider or "").strip().lower(),
        str(transaction_id),
        str(transaction_reference or ""),
        str(status or ""),
        str(amount or ""),
    )


def _record_webhook_replay_key(
    provider: str,
    transaction_id: str,
    transaction_reference: str,
    status: str,
    amount: str,
) -> None:
    ttl = int(getattr(settings, "WEBHOOK_REPLAY_TTL_SECONDS", _DEFAULT_REPLAY_TTL_SECONDS))
    if ttl <= 0:
        return
    key = _webhook_replay_key(provider, transaction_id, transaction_reference, status, amount)
    cache.add(key, True, timeout=ttl)


def _expiry_window_for_provider(provider: str) -> Optional[timedelta]:
    return _PROVIDER_EXPIRY_WINDOWS.get((provider or "").strip().lower())


def _expire_payment_if_needed(
    payment: Payment,
    actor: str = "system",
) -> tuple[bool, Optional[dict]]:
    """
    Expire a payment if its expires_at is in the past.
    Returns (expired, error). Never raises.
    """
    if payment.status == Payment.PaymentStatus.EXPIRED:
        return True, None

    if not payment.expires_at:
        return False, None

    if timezone.now() <= payment.expires_at:
        return False, None

    previous_status = payment.status
    try:
        payment.status = Payment.PaymentStatus.EXPIRED
        payment.save(update_fields=["status", "updated_at"])
        PaymentAuditLog.objects.create(
            payment=payment,
            event_type=PaymentAuditLog.EventType.EXPIRED,
            amount=payment.amount,
            actor=actor,
            payload={
                "previous_status": previous_status,
                "expires_at": payment.expires_at.isoformat(),
            },
        )
        logger.info(
            "[expire_payment] Expired | txn=%s | prev=%s",
            payment.transaction_id_str,
            previous_status,
        )
        return True, None
    except DatabaseError:
        logger.exception(
            "[expire_payment] Failed | txn=%s",
            payment.transaction_id_str,
            extra={
                "event": "payment_expire_failed",
                "transaction_id": payment.transaction_id_str,
            },
        )
        return False, build_error(
            code="EXPIRY_UPDATE_FAILED",
            message="Failed to update payment expiry state.",
            http_status=500,
        )


def _expire_stale_pending_payment(
    payment: Payment,
    actor: str = "system",
) -> tuple[bool, Optional[dict]]:
    """
    Expire a stale pending payment based on created_at age.
    Returns (expired, error). Never raises.
    """
    if payment.status != Payment.PaymentStatus.PENDING or payment.used:
        return False, None

    if timezone.now() - payment.created_at <= _PENDING_STALE_WINDOW:
        return False, None

    previous_status = payment.status
    try:
        payment.status = Payment.PaymentStatus.EXPIRED
        payment.save(update_fields=["status", "updated_at"])
        PaymentAuditLog.objects.create(
            payment=payment,
            event_type=PaymentAuditLog.EventType.EXPIRED,
            amount=payment.amount,
            actor=actor,
            payload={
                "previous_status": previous_status,
                "stale_hours": int(_PENDING_STALE_WINDOW.total_seconds() // 3600),
                "created_at": payment.created_at.isoformat(),
            },
        )
        logger.info(
            "[expire_pending] Expired stale pending | txn=%s",
            payment.transaction_id_str,
        )
        return True, None
    except DatabaseError:
        logger.exception(
            "[expire_pending] Failed | txn=%s",
            payment.transaction_id_str,
            extra={
                "event": "payment_expire_pending_failed",
                "transaction_id": payment.transaction_id_str,
            },
        )
        return False, build_error(
            code="EXPIRY_UPDATE_FAILED",
            message="Failed to update payment expiry state.",
            http_status=500,
        )


# ─── Provider Validation ──────────────────────────────────────────────────────

def validate_provider(provider: str) -> Optional[dict]:
    """
    Validate that the requested provider is registered and supported.

    Args:
        provider: Provider name string (e.g. "fawry", "vodafone", "bank").

    Returns:
        None if valid.
        error_dict if invalid (to be passed directly to error_response() in views).
    """
    if not provider or not isinstance(provider, str):
        return build_error(
            code="PROVIDER_REQUIRED",
            message="A payment provider must be specified.",
            details={"supported_providers": SUPPORTED_PROVIDERS},
            http_status=400,
        )
    if not is_valid_provider(provider):
        return build_error(
            code="INVALID_PROVIDER",
            message=f"Provider '{provider}' is not supported.",
            details={"supported_providers": SUPPORTED_PROVIDERS},
            http_status=400,
        )
    return None




# ─── PRD: start_payment ───────────────────────────────────────────────────────

@db_transaction.atomic
def start_payment(
    student_id:       str,
    provider:         Optional[str] = None,
    requested_amount: Optional[Decimal] = None,
) -> tuple[Optional[dict], Optional[dict]]:
    """
    Create a payment for the current semester.

    Supported modes:
      - provider is supplied  -> create payment then submit to gateway
      - provider is omitted   -> create pending payment only

    This keeps the core service logic centralized while preserving the project's
    layered design and the separate submit endpoint.
    """
    normalized_provider = (provider or "").strip().lower()

    # Provider validation happens before any writes when provider was supplied.
    if normalized_provider:
        err = validate_provider(normalized_provider)
        if err:
            return None, err

    # ── Step 1: Fetch + validate student ─────────────────────────────────────
    student, err = get_student_or_error(student_id)
    if err:
        return None, err
    # Concurrency guard: serialize start_payment per-student to prevent
    # duplicate provider-initiated processing payments under race.
    student = Student.objects.select_for_update().get(pk=student.pk)

    err = validate_student_eligibility(student)
    if err:
        return None, err

    semester = current_semester()

    # ── Step 2: Duplicate guards ─────────────────────────────────────────────
    existing_pending = Payment.objects.filter(
        student=student,
        semester=semester,
        status=Payment.PaymentStatus.PENDING,
        used=False,
    ).order_by("-created_at").first()
    if existing_pending:
        expired, expiry_err = _expire_stale_pending_payment(existing_pending, actor="system")
        if expiry_err:
            return None, expiry_err
        if expired:
            existing_pending = None

    err = check_no_open_payment(student, semester)
    if err:
        return None, err

    in_flight = Payment.objects.filter(
        student=student,
        semester=semester,
        status=Payment.PaymentStatus.PROCESSING,
    ).order_by("-created_at").first()
    if in_flight:
        return None, build_error(
            code="PAYMENT_ALREADY_OPEN",
            message=(
                f"Student '{student.student_id}' already has an in-flight payment for "
                f"semester '{semester}'. Wait for the gateway callback or start a new payment later."
            ),
            details={
                "existing_transaction_id": in_flight.transaction_id_str,
                "amount": str(in_flight.amount),
                "created_at": in_flight.created_at.isoformat(),
                "status": in_flight.status,
            },
            http_status=400,
        )

    paid = Payment.objects.filter(
        student=student,
        semester=semester,
        status=Payment.PaymentStatus.PAID,
    ).order_by("-created_at").first()
    if paid:
        return None, build_error(
            code="PAYMENT_ALREADY_PAID",
            message=(
                f"Student '{student.student_id}' already has a paid payment for "
                f"semester '{semester}'."
            ),
            details={
                "existing_transaction_id": paid.transaction_id_str,
                "amount": str(paid.amount),
                "created_at": paid.created_at.isoformat(),
                "status": paid.status,
            },
            http_status=400,
        )

    refunded = Payment.objects.filter(
        student=student,
        semester=semester,
        status=Payment.PaymentStatus.REFUNDED,
    ).order_by("-created_at").first()
    if refunded:
        return None, build_error(
            code="PAYMENT_ALREADY_REFUNDED",
            message=(
                f"Student '{student.student_id}' has a refunded payment for "
                f"semester '{semester}'."
            ),
            details={
                "existing_transaction_id": refunded.transaction_id_str,
                "amount": str(refunded.amount),
                "created_at": refunded.created_at.isoformat(),
                "status": refunded.status,
            },
            http_status=400,
        )

    # ── Step 3: Compute + validate amount ────────────────────────────────────
    expected_amount = compute_expected_amount(student)
    err = validate_amount_match(requested_amount, expected_amount)
    if err:
        return None, err

    # ── Step 4: Create Payment record ────────────────────────────────────────
    try:
        payment = create_payment_record(
            student=student,
            amount=expected_amount,
            semester=semester,
        )
    except DatabaseError:
        logger.exception(
            "[start_payment] DB error creating payment | student=%s", student_id,
            extra={
                "event": "payment_start_db_error",
                "student_id": student_id,
            },
        )
        return None, build_error(
            code="DATABASE_ERROR",
            message="Failed to create payment record. Please try again.",
            http_status=500,
        )

    if not normalized_provider:
        return {
            "transaction_id": payment.transaction_id_str,
            "student_id": payment.student.student_id,
            "student_name": payment.student.name,
            "amount": str(payment.amount),
            "status": payment.status,
            "payment_method": payment.payment_method,
            "semester": payment.semester,
            "used": payment.used,
            "gateway_reference": payment.gateway_reference,
            "created_at": payment.created_at.isoformat(),
        }, None

    # ── Step 5: Submit to gateway ────────────────────────────────────────────
    gateway_result, err = _submit_to_gateway(payment, normalized_provider)
    if err:
        return None, err

    return gateway_result, None


def get_start_payment_status(
    student,
) -> tuple[bool, Optional[str], Optional[Payment]]:
    """
    Read-only helper for student-facing payment eligibility status.
    Returns (can_start, reason_code, current_payment).
    """
    semester = current_semester()
    now = timezone.now()

    err = validate_student_eligibility(student)
    if err:
        latest = Payment.objects.filter(
            student=student,
            semester=semester,
        ).order_by("-created_at").first()
        return False, err["payload"]["error"]["code"], latest

    existing_pending = Payment.objects.filter(
        student=student,
        semester=semester,
        status=Payment.PaymentStatus.PENDING,
        used=False,
    ).order_by("-created_at").first()
    if existing_pending:
        if now - existing_pending.created_at <= _PENDING_STALE_WINDOW:
            return False, "PAYMENT_ALREADY_OPEN", existing_pending

    in_flight = Payment.objects.filter(
        student=student,
        semester=semester,
        status=Payment.PaymentStatus.PROCESSING,
    ).order_by("-created_at").first()
    if in_flight:
        return False, "PAYMENT_ALREADY_OPEN", in_flight

    paid = Payment.objects.filter(
        student=student,
        semester=semester,
        status=Payment.PaymentStatus.PAID,
    ).order_by("-created_at").first()
    if paid:
        return False, "PAYMENT_ALREADY_PAID", paid

    refunded = Payment.objects.filter(
        student=student,
        semester=semester,
        status=Payment.PaymentStatus.REFUNDED,
    ).order_by("-created_at").first()
    if refunded:
        return False, "PAYMENT_ALREADY_REFUNDED", refunded

    latest = Payment.objects.filter(
        student=student,
        semester=semester,
    ).order_by("-created_at").first()
    return True, None, latest



# ─── Gateway Submission ───────────────────────────────────────────────────────

@db_transaction.atomic
def initiate_with_gateway(
    payment:  Payment,
    provider: str,
) -> tuple[Optional[dict], Optional[dict]]:
    """
    Submit an EXISTING PENDING payment to the chosen gateway.

    Use start_payment() for the common case (creates + submits in one call).
    Use this function when the payment was already created and you want to
    submit it to a gateway separately (e.g. student chose provider after creation).

    Args:
        payment:  An existing Payment instance with status=PENDING.
        provider: Gateway provider name.

    Returns:
        (response_dict, None)  on success
        (None, error_dict)     on failure
    """
    expired, err = _expire_payment_if_needed(payment, actor="system")
    if err:
        return None, err
    if expired:
        return None, build_error(
            code="PAYMENT_EXPIRED",
            message="Payment has expired and cannot be submitted.",
            details={"transaction_id": payment.transaction_id_str},
            http_status=400,
        )

    err = validate_provider(provider)
    if err:
        return None, err

    return _submit_to_gateway(payment, provider)


def _submit_to_gateway(
    payment:  Payment,
    provider: str,
) -> tuple[Optional[dict], Optional[dict]]:
    """
    Internal: call gateway.create_payment() and update Payment record.

    Separated from the public functions so start_payment() and
    initiate_with_gateway() share the same gateway logic without duplication.

    Steps:
      1. Guard: payment must be PENDING and not used
      2. Call gateway.create_payment(payment)  [PRD interface]
      3. Transition: PENDING → PROCESSING
      4. Store transaction_reference on Payment
      5. Set used=True (replay prevention)
      6. Write audit log
    """
    # ── Guard: payment must be open ───────────────────────────────────────────
    payment = (
        Payment.objects
        .select_for_update()
        .select_related("student")
        .get(transaction_id=payment.transaction_id)
    )
    if not payment.is_open:
        return None, build_error(
            code="PAYMENT_NOT_OPEN",
            message=(
                f"Payment status is '{payment.status}'"
                + (" and has already been submitted to a gateway." if payment.used else ".")
            ),
            details={
                "transaction_id": payment.transaction_id_str,
                "status":         payment.status,
                "used":           payment.used,
            },
            http_status=400,
        )

    # ── Call gateway ──────────────────────────────────────────────────────────
    gateway = get_gateway(provider)

    try:
        # PRD interface: create_payment(payment) → GatewayResponse
        gateway_response = gateway.create_payment(payment)
    except Exception as exc:
        logger.exception(
            "[_submit_to_gateway] Gateway exception | provider=%s | txn=%s",
            provider, payment.transaction_id_str,
            extra={
                "event": "payment_submit_gateway_exception",
                "transaction_id": payment.transaction_id_str,
                "provider": provider,
            },
        )
        PaymentAuditLog.objects.create(
            payment=payment,
            event_type=PaymentAuditLog.EventType.FAILURE,
            amount=payment.amount,
            actor=provider,
            payload={"error": str(exc), "step": "create_payment"},
        )
        return None, build_error(
            code="GATEWAY_ERROR",
            message="The payment gateway returned an unexpected error. Please try again.",
            http_status=502,
        )

    if not gateway_response.success:
        PaymentAuditLog.objects.create(
            payment=payment,
            event_type=PaymentAuditLog.EventType.FAILURE,
            amount=payment.amount,
            actor=provider,
            payload=gateway_response.raw_payload,
        )
        return None, build_error(
            code="GATEWAY_REJECTED",
            message=gateway_response.error_message or "Gateway rejected the payment request.",
            details={"error_code": gateway_response.error_code},
            http_status=502,
        )

    # ── Update Payment: PENDING → PROCESSING ─────────────────────────────────
    payment.status             = "processing"
    payment.payment_method     = provider
    payment.gateway_reference  = gateway_response.transaction_reference
    payment.used               = True   # Prevents replay — this txn is now live
    if not payment.expires_at:
        window = _expiry_window_for_provider(provider)
        if window:
            payment.expires_at = timezone.now() + window
    payment.save(update_fields=[
        "status", "payment_method", "gateway_reference",
        "used", "expires_at", "updated_at",
    ])

    # ── Audit: gateway request ─────────────────────────────────────────────────
    PaymentAuditLog.objects.create(
        payment=payment,
        event_type=PaymentAuditLog.EventType.PROCESSING,
        amount=payment.amount,
        actor=provider,
        payload=gateway_response.raw_payload,
    )

    logger.info(
        "[_submit_to_gateway] Submitted | txn=%s | provider=%s | ref=%s",
        payment.transaction_id_str,
        provider,
        gateway_response.transaction_reference,
        extra={
            "event": "payment_submit_success",
            "transaction_id": payment.transaction_id_str,
            "provider": provider,
            "status": payment.status,
        },
    )

    # return {
    #     "transaction_id":        payment.transaction_id_str,
    #     "transaction_reference": gateway_response.transaction_reference,
    #     "status":                payment.status,
    #     "provider":              provider,
    #     "amount":                str(payment.amount),
    #     "semester":              payment.semester,
    #     "instructions":          gateway_response.instructions,
    # }, None
    return {
    "transaction_id":        payment.transaction_id_str,
    "transaction_reference": gateway_response.transaction_reference,
    "external_reference":    gateway_response.transaction_reference,
    "status":                payment.status,
    "provider":              provider,
    "amount":                str(payment.amount),
    "semester":              payment.semester,
    "instructions":          gateway_response.instructions,
}, None


# ─── Webhook Processing ───────────────────────────────────────────────────────

# ─── Student Activation ──────────────────────────────────────────────────────────

# ─── Cancel Payment ─────────────────────────────────────────────────────────────

@db_transaction.atomic
def cancel_payment(
    payment: Payment,
    actor: str = "student",
    reason: str = "Cancelled by user.",
) -> tuple[Optional[dict], Optional[dict]]:
    """
    Cancel an open payment (pending, unused) if not expired.
    """
    payment = Payment.objects.select_for_update().get(
        transaction_id=payment.transaction_id
    )

    expired, err = _expire_payment_if_needed(payment, actor=actor)
    if err:
        return None, err
    if expired:
        return None, build_error(
            code="PAYMENT_EXPIRED",
            message="Payment has expired and cannot be cancelled.",
            details={"transaction_id": payment.transaction_id_str},
            http_status=400,
        )

    if not payment.is_open:
        return None, build_error(
            "PAYMENT_NOT_CANCELLABLE",
            f"Payment cannot be cancelled — current status is '{payment.status}'.",
            details={"current_status": payment.status, "used": payment.used},
            http_status=400,
        )

    payment.status = Payment.PaymentStatus.CANCELLED
    payment.save(update_fields=["status", "updated_at"])

    PaymentAuditLog.objects.create(
        payment=payment,
        event_type=PaymentAuditLog.EventType.CANCELLED,
        amount=payment.amount,
        actor=actor,
        payload={"reason": reason},
    )

    return {
        "transaction_id": payment.transaction_id_str,
        "status": payment.status,
    }, None


def _activate_student_after_payment(payment: Payment) -> dict:
    """
    Business completion: activate student after successful payment.

    Rules:
      - active     → no change
      - inactive   → set to active
      - suspended / graduated → do not auto-activate

    Must never raise; failures are reported in the returned dict and logged.
    """
    student = payment.student
    current_status = student.status

    if current_status == "active":
        return {"action": "none", "status": "active"}

    if current_status == "inactive":
        try:
            # Nested atomic block to avoid breaking the payment transaction
            # if the student update fails.
            with db_transaction.atomic():
                student.status = "active"
                student.save(update_fields=["status", "updated_at"])
            return {
                "action": "activated",
                "previous_status": "inactive",
                "new_status": "active",
            }
        except DatabaseError as exc:
            logger.exception(
                "[activate_student] Failed | student=%s | txn=%s",
                student.student_id, payment.transaction_id_str,
                extra={
                    "event": "payment_activation_failed",
                    "transaction_id": payment.transaction_id_str,
                    "student_id": student.student_id,
                },
            )
            return {
                "action": "failed",
                "previous_status": "inactive",
                "error": str(exc),
            }

    if current_status in {"suspended", "graduated"}:
        return {
            "action": "skipped",
            "status": current_status,
            "reason": "status_not_auto_activatable",
        }

    return {
        "action": "skipped",
        "status": current_status,
        "reason": "unknown_status",
    }


@db_transaction.atomic
def process_webhook(
    provider:   str,
    raw_body:   dict,
    signature:  str,
) -> tuple[Optional[dict], Optional[dict]]:
    """
    [PRD: Webhook System + Idempotency Protection]

    Process an inbound webhook callback from a payment gateway.

    Full flow (all atomic):
      1. Validate provider
      2. Call gateway.verify_payment(data)  [PRD interface]
      3. Parse into WebhookPayload
      4. Fetch Payment record
      5. Write webhook-received audit log
      6. Idempotency check — reject if already in terminal status
      7. Amount sanity check
      8. Transition: PROCESSING → PAID | FAILED
      9. Write status-change audit log

    Idempotency: duplicate webhooks on terminal payments write REPLAY_BLOCKED
    audit log and return 200 (not 409) to prevent gateway retry storms.

    Args:
        provider:  Gateway provider name.
        raw_body:  Raw webhook body dict.
        signature: HMAC signature (from header or body).

    Returns:
        (response_dict, None)  on success (acknowledged = True)
        (None, error_dict)     on validation failure
    """
    # ── Validate provider ─────────────────────────────────────────────────────
    err = validate_provider(provider)
    if err:
        return None, err

    gateway = get_gateway(provider)

    def _audit_if_payment_found(
        event_type: str,
        amount: Decimal = Decimal("0.00"),
        payload: Optional[dict] = None,
    ) -> None:
        txn_id = raw_body.get("transaction_id")
        if not txn_id:
            return
        try:
            payment = Payment.objects.get(transaction_id=txn_id)
        except Exception:
            return
        PaymentAuditLog.objects.create(
            payment=payment,
            event_type=event_type,
            amount=amount,
            actor=provider,
            payload=payload or {},
        )

    # Inject signature into body for verify_payment (PRD: verify_payment(data))
    # Header signature (if provided) must take precedence over body signature.
    if signature:
        raw_body = {**raw_body, "signature": signature}

    # ── PRD: verify_payment(data) ─────────────────────────────────────────────
    validation = gateway.verify_payment(raw_body)
    if not validation.is_valid:
        logger.warning(
            "[process_webhook] Invalid webhook | provider=%s | code=%s",
            provider, validation.error_code,
            extra={
                "event": "payment_webhook_rejected",
                "transaction_id": raw_body.get("transaction_id", ""),
                "provider": provider,
                "error_code": validation.error_code,
            },
        )
        if validation.error_code == "WEBHOOK_INVALID_SIGNATURE":
            event_type = PaymentAuditLog.EventType.INVALID_WEBHOOK_SIGNATURE
        else:
            event_type = PaymentAuditLog.EventType.MALFORMED_WEBHOOK_PAYLOAD
        _audit_if_payment_found(
            event_type=event_type,
            payload={"error_code": validation.error_code},
        )
        safe_message = validation.error_message or "Webhook validation failed."
        if validation.error_message and any(
            token in validation.error_message
            for token in ("Traceback", "Exception", "Error:")
        ):
            safe_message = "Webhook validation failed."
        return None, build_error(
            code=validation.error_code or "WEBHOOK_INVALID",
            message=safe_message,
            http_status=400,
        )

    # ── Parse webhook ─────────────────────────────────────────────────────────
    try:
        webhook = gateway.parse_webhook(raw_body)
    except (ValueError, KeyError) as exc:
        _audit_if_payment_found(
            event_type=PaymentAuditLog.EventType.MALFORMED_WEBHOOK_PAYLOAD,
            payload={"error": str(exc)},
        )
        return None, build_error(
            code="WEBHOOK_PARSE_ERROR",
            message="Failed to parse webhook payload.",
            http_status=400,
        )

    # ── Fetch Payment ─────────────────────────────────────────────────────────
    try:
        payment = (
            Payment.objects
            .select_for_update()
            .select_related("student")
            .get(transaction_id=webhook.transaction_id)
        )
    except Payment.DoesNotExist:
        logger.warning(
            "[process_webhook] Unknown transaction | txn=%s | provider=%s",
            webhook.transaction_id, provider,
            extra={
                "event": "payment_webhook_unknown_transaction",
                "transaction_id": str(webhook.transaction_id),
                "provider": provider,
            },
        )
        # Return 200 — don't error, prevents gateway retry storms
        return {"acknowledged": True, "note": "Transaction not found — no action taken."}, None

    # ── Audit: webhook received ───────────────────────────────────────────────
    replay_key = _webhook_replay_key(
        provider,
        payment.transaction_id_str,
        webhook.transaction_reference,
        webhook.status,
        str(webhook.amount),
    )

    # Pending webhooks may be replayed frequently by providers.
    # Deduplicate them before writing audit logs to avoid unbounded growth.
    if webhook.status == "pending" and cache.get(replay_key):
        logger.info(
            "[process_webhook] Pending replay deduped | txn=%s | status=%s",
            payment.transaction_id_str, payment.status,
            extra={
                "event": "payment_webhook_replay_noop",
                "transaction_id": payment.transaction_id_str,
                "status": payment.status,
                "provider": provider,
            },
        )
        return {
            "acknowledged":  True,
            "transaction_id": payment.transaction_id_str,
            "current_status": payment.status,
            "note": "Pending webhook replay deduped — no state change.",
        }, None

    PaymentAuditLog.objects.create(
        payment=payment,
        event_type=PaymentAuditLog.EventType.WEBHOOK,
        amount=webhook.amount,
        actor=provider,
        payload={
            "transaction_reference": webhook.transaction_reference,
            "status": webhook.status,
        },
    )
    if cache.get(replay_key):
        logger.info(
            "[process_webhook] Replay webhook deduped | txn=%s | status=%s",
            payment.transaction_id_str, payment.status,
            extra={
                "event": "payment_webhook_replay_noop",
                "transaction_id": payment.transaction_id_str,
                "status": payment.status,
                "provider": provider,
            },
        )
        PaymentAuditLog.objects.create(
            payment=payment,
            event_type=PaymentAuditLog.EventType.DUPLICATE_WEBHOOK_NOOP,
            amount=webhook.amount,
            actor=provider,
            payload={
                "webhook_status": webhook.status,
                "note": "replay_dedup",
            },
        )
        if payment.status == "expired":
            note = "Payment expired - acknowledged, no state change."
        elif payment.status == "cancelled":
            note = "Payment cancelled - acknowledged, no state change."
        else:
            note = "Payment already processed - acknowledged, no state change."
        return {
            "acknowledged":  True,
            "transaction_id": payment.transaction_id_str,
            "current_status": payment.status,
            "note": note,
        }, None

    # ── State policy: hard vs soft terminal ───────────────────────────────────
    hard_terminal = {"paid", "failed", "refunded"}
    soft_terminal = {"expired", "cancelled"}

    if payment.status in hard_terminal:
        logger.info(
            "[process_webhook] Duplicate webhook blocked | txn=%s | status=%s",
            payment.transaction_id_str, payment.status,
            extra={
                "event": "payment_webhook_duplicate_noop",
                "transaction_id": payment.transaction_id_str,
                "status": payment.status,
                "provider": provider,
            },
        )
        PaymentAuditLog.objects.create(
            payment=payment,
            event_type=PaymentAuditLog.EventType.DUPLICATE_WEBHOOK_NOOP,
            amount=webhook.amount,
            actor=provider,
            payload={
                "webhook_status": webhook.status,
            },
        )
        _record_webhook_replay_key(
            provider,
            payment.transaction_id_str,
            webhook.transaction_reference,
            webhook.status,
            str(webhook.amount),
        )
        return {
            "acknowledged":  True,
            "transaction_id": payment.transaction_id_str,
            "current_status": payment.status,
            "note": "Payment already processed — acknowledged, no state change.",
        }, None

    if payment.status in soft_terminal and webhook.status != "success":
        logger.info(
            "[process_webhook] Soft-terminal webhook no-op | txn=%s | status=%s",
            payment.transaction_id_str, payment.status,
            extra={
                "event": "payment_webhook_duplicate_noop",
                "transaction_id": payment.transaction_id_str,
                "status": payment.status,
                "provider": provider,
            },
        )
        PaymentAuditLog.objects.create(
            payment=payment,
            event_type=PaymentAuditLog.EventType.DUPLICATE_WEBHOOK_NOOP,
            amount=webhook.amount,
            actor=provider,
            payload={
                "webhook_status": webhook.status,
                "note": "soft_terminal_noop",
            },
        )
        _record_webhook_replay_key(
            provider,
            payment.transaction_id_str,
            webhook.transaction_reference,
            webhook.status,
            str(webhook.amount),
        )
        return {
            "acknowledged":  True,
            "transaction_id": payment.transaction_id_str,
            "current_status": payment.status,
            "note": (
                "Payment expired — acknowledged, no state change."
                if payment.status == "expired"
                else "Payment cancelled — acknowledged, no state change."
            ),
        }, None

    # If local expiry has passed and webhook is not success, expire then no-op.
    if webhook.status != "success" and payment.expires_at and timezone.now() > payment.expires_at:
        expired, err = _expire_payment_if_needed(payment, actor=provider)
        if err:
            return None, err
        if expired:
            PaymentAuditLog.objects.create(
                payment=payment,
                event_type=PaymentAuditLog.EventType.DUPLICATE_WEBHOOK_NOOP,
                amount=webhook.amount,
                actor=provider,
                payload={
                    "webhook_status": webhook.status,
                    "note": "expired_by_webhook_noop",
                },
            )
            _record_webhook_replay_key(
                provider,
                payment.transaction_id_str,
                webhook.transaction_reference,
                webhook.status,
                str(webhook.amount),
            )
            return {
                "acknowledged":  True,
                "transaction_id": payment.transaction_id_str,
                "current_status": payment.status,
                "note": "Payment expired — acknowledged, no state change.",
            }, None
# ── Amount sanity check ───────────────────────────────────────────────────
    # Consistency: must be a submitted payment for this provider/reference
    if not payment.used:
        return None, build_error(
            code="WEBHOOK_PAYMENT_NOT_SUBMITTED",
            message="Payment was not submitted to a gateway.",
            details={"transaction_id": payment.transaction_id_str},
            http_status=400,
        )

    if payment.payment_method and payment.payment_method != provider:
        return None, build_error(
            code="WEBHOOK_PROVIDER_MISMATCH",
            message="Webhook provider does not match payment method.",
            details={
                "transaction_id": payment.transaction_id_str,
                "payment_method": payment.payment_method,
                "provider": provider,
            },
            http_status=400,
        )

    if payment.gateway_reference and webhook.transaction_reference:
        if payment.gateway_reference != webhook.transaction_reference:
            return None, build_error(
                code="WEBHOOK_REFERENCE_MISMATCH",
                message="Webhook reference does not match payment record.",
                details={
                    "transaction_id": payment.transaction_id_str,
                    "expected_reference": payment.gateway_reference,
                    "received_reference": webhook.transaction_reference,
                },
                http_status=400,
            )

    if abs(webhook.amount - payment.amount) > Decimal("0.01"):
        logger.error(
            "[process_webhook] Amount mismatch | txn=%s | expected=%s | got=%s",
            payment.transaction_id_str, payment.amount, webhook.amount,
            extra={
                "event": "payment_webhook_amount_mismatch",
                "transaction_id": payment.transaction_id_str,
                "provider": provider,
                "error_code": "WEBHOOK_AMOUNT_MISMATCH",
            },
        )
        return None, build_error(
            code="WEBHOOK_AMOUNT_MISMATCH",
            message="Webhook amount does not match the payment record.",
            details={
                "expected": str(payment.amount),
                "received": str(webhook.amount),
            },
            http_status=400,
        )

    # ── Transition status ─────────────────────────────────────────────────────
    if webhook.status == "success":
        new_status  = "paid"
        audit_event = PaymentAuditLog.EventType.SUCCESS
    elif webhook.status == "failed":
        new_status  = "failed"
        audit_event = PaymentAuditLog.EventType.FAILURE
    else:
        # "pending" ? gateway still processing, acknowledge but don't change state
        _record_webhook_replay_key(
            provider,
            payment.transaction_id_str,
            webhook.transaction_reference,
            webhook.status,
            str(webhook.amount),
        )
        return {
            "acknowledged":  True,
            "transaction_id": payment.transaction_id_str,
            "current_status": payment.status,
            "note": "Gateway reported pending ? no state change.",
        }, None

    previous_status  = payment.status
    payment.status   = new_status
    payment.save(update_fields=["status", "updated_at"])

    activation_result = None
    if new_status == "paid":
        activation_result = _activate_student_after_payment(payment)

    # ── Audit: status change ──────────────────────────────────────────────────
    PaymentAuditLog.objects.create(
        payment=payment,
        event_type=audit_event,
        amount=webhook.amount,
        actor=provider,
        payload={
            "webhook_status":        webhook.status,
            "transaction_reference": webhook.transaction_reference,
            "provider":              provider,
            "student_activation":    activation_result,
        },
    )

    _record_webhook_replay_key(
        provider,
        payment.transaction_id_str,
        webhook.transaction_reference,
        webhook.status,
        str(webhook.amount),
    )

    logger.info(
        "[process_webhook] Status updated | txn=%s | %s → %s | provider=%s",
        payment.transaction_id_str, previous_status, new_status, provider,
        extra={
            "event": "payment_webhook_accepted",
            "transaction_id": payment.transaction_id_str,
            "provider": provider,
            "status": new_status,
        },
    )

    return {
        "acknowledged":          True,
        "transaction_id":        payment.transaction_id_str,
        "transaction_reference": webhook.transaction_reference,
        "previous_status":       previous_status,
        "current_status":        new_status,
        "provider":              provider,
    }, None
