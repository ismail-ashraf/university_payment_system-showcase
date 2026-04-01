"""
=== FILE: payments/models.py ===
Phase 3 — Extended Payment model with PROCESSING status + gateway fields.
"""

import uuid
from django.db import models
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from students.models import Student


def current_semester() -> str:
    now   = timezone.now()
    year  = now.year
    month = now.month
    if month >= 10:
        return f"{year}-Fall"
    elif month >= 7:
        return f"{year}-Summer"
    else:
        return f"{year}-Spring"


class Payment(models.Model):

    class PaymentStatus(models.TextChoices):
        PENDING    = "pending",    "Pending"
        PROCESSING = "processing", "Processing at Gateway"
        PAID       = "paid",       "Paid"
        FAILED     = "failed",     "Failed"
        CANCELLED  = "cancelled",  "Cancelled"
        REFUNDED   = "refunded",   "Refunded"
        EXPIRED    = "expired",    "Expired"

    class PaymentMethod(models.TextChoices):
        FAWRY         = "fawry",         "Fawry"
        VODAFONE      = "vodafone",      "Vodafone Cash"
        BANK          = "bank",          "Bank Transfer"
        BANQUE_MISR   = "banque_misr",   "Banque Misr"
        VODAFONE_CASH = "vodafone_cash", "Vodafone Cash (legacy)"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer (legacy)"
        CASH          = "cash",          "Cash (on-site)"

    transaction_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Globally unique transaction identifier (UUID4).",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name="payments",
        db_index=True,
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Expected fee amount in EGP.",
    )
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
    )
    payment_method = models.CharField(
        max_length=30,
        choices=PaymentMethod.choices,
        null=True,
        blank=True,
        help_text="Gateway selected by the student.",
    )
    semester = models.CharField(
        max_length=20,
        default=current_semester,
        help_text="Semester this payment belongs to (e.g. '2025-Spring').",
    )
    used = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True after submitted to a payment gateway — prevents replay.",
    )
    gateway_reference = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Reference number from the payment provider.",
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When this payment expires and becomes terminal.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payments"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["student", "semester"], name="idx_pay_student_semester"),
            models.Index(fields=["status", "semester"],  name="idx_pay_status_semester"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "semester"],
                condition=models.Q(status="pending"),
                name="uniq_pending_payment_per_student_semester",
            )
        ]

    def __str__(self):
        return (
            f"Payment {str(self.transaction_id)[:8]}… | "
            f"{self.student.student_id} | {self.amount} EGP | {self.status}"
        )

    @property
    def is_open(self) -> bool:
        return self.status == self.PaymentStatus.PENDING and not self.used

    @property
    def transaction_id_str(self) -> str:
        return str(self.transaction_id)


class PaymentAuditLogQuerySet(models.QuerySet):
    def delete(self, *args, **kwargs):
        raise ProtectedError("PaymentAuditLog entries are immutable.", self)

    def update(self, *args, **kwargs):
        raise ProtectedError("PaymentAuditLog entries are immutable.", self)

    def bulk_update(self, *args, **kwargs):
        raise ProtectedError("PaymentAuditLog entries are immutable.", self)


class PaymentAuditLog(models.Model):

    class EventType(models.TextChoices):
        INITIATED      = "initiated",      "Payment Initiated"
        PROCESSING     = "processing",     "Processing at Gateway"
        SUCCESS        = "success",        "Payment Confirmed"
        FAILURE        = "failure",        "Payment Failed"
        CANCELLED      = "cancelled",      "Cancelled by Student/Admin"
        WEBHOOK        = "webhook",        "Webhook Received"
        REFUND         = "refund",         "Refund Issued"
        INVALID_WEBHOOK_SIGNATURE = "invalid_webhook_signature", "Invalid Webhook Signature"
        MALFORMED_WEBHOOK_PAYLOAD = "malformed_webhook_payload", "Malformed Webhook Payload"
        DUPLICATE_WEBHOOK_NOOP    = "duplicate_webhook_noop",    "Duplicate Webhook No-Op"
        TERMINAL_STATE_NOOP       = "terminal_state_noop",       "Terminal State No-Op"
        EXPIRED        = "expired",        "Payment Expired"

    payment    = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="audit_logs",
    )
    event_type = models.CharField(max_length=30, choices=EventType.choices, db_index=True)
    amount     = models.DecimalField(max_digits=10, decimal_places=2)
    actor      = models.CharField(
        max_length=100,
        default="system",
        help_text="Who triggered this event.",
    )
    payload    = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PaymentAuditLogQuerySet.as_manager()

    class Meta:
        db_table = "payment_audit_logs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"AuditLog | {self.event_type} | Payment {str(self.payment_id)[:8]}…"

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            raise ProtectedError("PaymentAuditLog entries are immutable.", [self])
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ProtectedError("PaymentAuditLog entries are immutable.", [self])
