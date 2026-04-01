"""
=== FILE: payments/serializers.py ===
Phase 3 — Serializers for all payment endpoints.

StartPaymentSerializer   → POST /api/payments/start/  (student_id + provider)
WebhookInputSerializer   → POST /api/payments/webhook/<provider>/
PaymentResponseSerializer → outbound payment shape
PaymentDetailSerializer  → outbound detail with audit trail
"""

from decimal import Decimal
from rest_framework import serializers
from .models import Payment, PaymentAuditLog
from .gateways import SUPPORTED_PROVIDERS


# class StartPaymentSerializer(serializers.Serializer):
#     """
#     [PRD: POST /api/payments/start/ → { student_id, provider }]
#     Validates both required fields in one step.
#     """
#     student_id = serializers.CharField(
#         max_length=20,
#         help_text="University-issued student ID (e.g. '20210001').",
#     )
#     provider = serializers.ChoiceField(
#         choices=SUPPORTED_PROVIDERS,
#         help_text=f"Payment provider. Supported: {', '.join(SUPPORTED_PROVIDERS)}",
#     )
#     # Optional: caller can supply expected amount for cross-validation
#     amount = serializers.DecimalField(
#         max_digits=10, decimal_places=2,
#         required=False, allow_null=True, default=None,
#         min_value=Decimal("1.00"),
#         help_text="(Optional) Expected fee amount in EGP. Cross-validated against computed fee.",
#     )

#     def validate_student_id(self, value: str) -> str:
#         cleaned = value.strip().upper()
#         if not cleaned:
#             raise serializers.ValidationError("student_id cannot be blank.")
#         if not all(c.isalnum() or c == "-" for c in cleaned):
#             raise serializers.ValidationError(
#                 "student_id must contain only alphanumeric characters or hyphens."
#             )
#         return cleaned

class StartPaymentSerializer(serializers.Serializer):
    student_id = serializers.CharField(
        max_length=20,
        help_text="University-issued student ID (e.g. '20210001').",
    )
    provider = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional payment provider name. If omitted, only a pending payment is created.",
    )
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2,
        required=False, allow_null=True, default=None,
        min_value=Decimal("1.00"),
        help_text="(Optional) Expected fee amount in EGP. Cross-validated against computed fee.",
    )

    def validate_student_id(self, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise serializers.ValidationError("student_id cannot be blank.")
        if not all(c.isalnum() or c == "-" for c in cleaned):
            raise serializers.ValidationError(
                "student_id must contain only alphanumeric characters or hyphens."
            )
        return cleaned


class SubmitPaymentSerializer(serializers.Serializer):
    """For POST /api/payments/<uuid>/submit/ — select gateway for existing payment."""
    provider = serializers.ChoiceField(
        choices=SUPPORTED_PROVIDERS,
        help_text=f"Payment provider. Supported: {', '.join(SUPPORTED_PROVIDERS)}",
    )


class WebhookInputSerializer(serializers.Serializer):
    """Structural validation for inbound webhooks. Deep validation is in gateways."""
    transaction_id = serializers.CharField(required=True)
    status         = serializers.ChoiceField(choices=["success", "failed", "pending"])
    amount         = serializers.DecimalField(max_digits=10, decimal_places=2)

    def validate_transaction_id(self, value: str) -> str:
        import uuid as _uuid
        try:
            _uuid.UUID(value)
        except ValueError:
            raise serializers.ValidationError("transaction_id must be a valid UUID.")
        return value


class PaymentAuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model        = PaymentAuditLog
        fields       = ["id", "event_type", "amount", "actor", "payload", "created_at"]
        read_only_fields = fields


class PaymentResponseSerializer(serializers.ModelSerializer):
    """Lightweight response for list / create endpoints."""
    # transaction_id = serializers.UUIDField(source="transaction_id")
    transaction_id = serializers.UUIDField(read_only=True)
    student_id     = serializers.CharField(source="student.student_id", read_only=True)
    student_name   = serializers.CharField(source="student.name",       read_only=True)

    class Meta:
        model  = Payment
        fields = [
            "transaction_id", "student_id", "student_name",
            "amount", "status", "payment_method", "semester",
            "used", "gateway_reference", "created_at",
        ]
        read_only_fields = fields


class PaymentDetailSerializer(serializers.ModelSerializer):
    """Full detail including audit trail — used by GET /api/payments/<uuid>/"""
    # transaction_id = serializers.UUIDField(source="transaction_id")
    transaction_id = serializers.UUIDField(read_only=True)
    student_id     = serializers.CharField(source="student.student_id", read_only=True)
    student_name   = serializers.CharField(source="student.name",       read_only=True)
    audit_logs     = PaymentAuditLogSerializer(many=True, read_only=True)

    class Meta:
        model  = Payment
        fields = [
            "transaction_id", "student_id", "student_name",
            "amount", "status", "payment_method", "semester",
            "used", "gateway_reference", "notes",
            "created_at", "updated_at", "audit_logs",
        ]
        read_only_fields = fields


class AdminPaymentListSerializer(serializers.ModelSerializer):
    """Admin list serializer (same shape as PaymentResponseSerializer)."""
    transaction_id = serializers.UUIDField(read_only=True)
    student_id     = serializers.CharField(source="student.student_id", read_only=True)
    student_name   = serializers.CharField(source="student.name",       read_only=True)

    class Meta:
        model  = Payment
        fields = [
            "transaction_id", "student_id", "student_name",
            "amount", "status", "payment_method", "semester",
            "used", "gateway_reference", "created_at", "updated_at",
        ]
        read_only_fields = fields


class AdminPaymentDetailSerializer(serializers.ModelSerializer):
    """Admin detail with bounded audit log serializer."""
    transaction_id = serializers.UUIDField(read_only=True)
    student_id     = serializers.CharField(source="student.student_id", read_only=True)
    student_name   = serializers.CharField(source="student.name",       read_only=True)
    audit_logs     = PaymentAuditLogSerializer(many=True, read_only=True)

    class Meta:
        model  = Payment
        fields = [
            "transaction_id", "student_id", "student_name",
            "amount", "status", "payment_method", "semester",
            "used", "gateway_reference", "expires_at",
            "created_at", "updated_at", "audit_logs",
        ]
        read_only_fields = fields


class StudentPaymentDetailSerializer(serializers.ModelSerializer):
    """Student-safe payment detail (no audit logs)."""
    transaction_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Payment
        fields = [
            "transaction_id",
            "status",
            "amount",
            "created_at",
            "expires_at",
        ]
        read_only_fields = fields
