"""
=== FILE: payments/gateways/base.py ===

Abstract Base Gateway — the only interface the service layer touches.

PRD Interface Contract:
  create_payment(payment: Payment) -> dict
  verify_payment(data: dict) -> dict

Extended with:
  - Immutable DTOs for type safety (GatewayRequest, GatewayResponse, WebhookPayload)
  - HMAC signature helpers shared by all providers
  - WebhookValidationResult for structured webhook validation

Architecture rule: Views and services NEVER import concrete gateway classes.
They call get_gateway(provider) from registry.py and work through this interface.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from uuid import UUID

# Avoid circular import — Payment model only needed for type hints
if TYPE_CHECKING:
    from payments.models import Payment


# ─── Data Transfer Objects ────────────────────────────────────────────────────
# Frozen dataclasses = immutable value objects. Passing these through the stack
# ensures no mutation happens between gateway and service layers.

@dataclass(frozen=True)
class GatewayRequest:
    """
    Immutable payload sent TO a gateway's create_payment().
    Constructed by the service layer from a Payment instance.
    """
    transaction_id: UUID       # Our internal UUID — sent to gateway as correlation ID
    student_id:     str        # For gateway reporting / receipts
    amount:         Decimal    # Always EGP, always Decimal — never float
    semester:       str        # e.g. "2025-Spring"
    provider:       str        # "fawry" | "vodafone" | "bank"
    metadata:       dict = field(default_factory=dict)  # Optional extras (student name, etc.)


@dataclass(frozen=True)
class GatewayResponse:
    """
    Immutable result returned FROM a gateway's create_payment().
    Contains everything needed to update the Payment record and
    display instructions to the student.
    """
    success:             bool
    transaction_reference: str    # PRD field: gateway's own reference ID
    status:              str      # "success" | "failed" | "pending"
    provider:            str
    instructions:        dict     # Human-readable steps for the student
    raw_payload:         dict     # Full response stored in audit log
    error_code:          Optional[str] = None
    error_message:       Optional[str] = None

    # Alias so existing Phase 3 code that uses external_reference still works
    @property
    def external_reference(self) -> str:
        return self.transaction_reference


@dataclass(frozen=True)
class WebhookPayload:
    """
    Parsed, validated inbound webhook from a gateway.
    Created by parse_webhook() after verify_payment() confirms authenticity.
    """
    transaction_id:      UUID
    transaction_reference: str
    provider:            str
    status:              str     # "success" | "failed" | "pending"
    amount:              Decimal
    signature:           str
    raw_body:            dict

    # Alias for backward compatibility
    @property
    def external_reference(self) -> str:
        return self.transaction_reference


@dataclass(frozen=True)
class WebhookValidationResult:
    """Structured result of verify_payment() webhook validation."""
    is_valid:      bool
    error_code:    Optional[str] = None
    error_message: Optional[str] = None


# ─── Abstract Base Gateway ────────────────────────────────────────────────────

class BasePaymentGateway(ABC):
    """
    Contract that every payment gateway adapter MUST satisfy.

    PRD-specified interface:
      create_payment(payment)  → initiate a payment with the provider
      verify_payment(data)     → validate an inbound webhook/callback

    Concrete implementations: FawryGateway, VodafoneGateway, MockBankGateway

    Financial rules enforced at this level:
      - All amounts are Decimal — never float
      - All transaction IDs are UUID — never int
      - All methods return structured DTOs — never raw dicts from subclasses
    """

    # ── Class-level config — override in each subclass ────────────────────────
    PROVIDER_NAME:   str = ""
    WEBHOOK_SECRET:  str = "dev-secret-change-in-production"

    # ── PRD Core Interface ─────────────────────────────────────────────────────

    @abstractmethod
    def create_payment(self, payment: "Payment") -> GatewayResponse:
        """
        [PRD: create_payment(payment: Payment) -> dict]

        Submit a payment order to the external provider.

        Behaviour:
          - Builds a GatewayRequest from the Payment instance
          - Simulates the provider's API call
          - Returns GatewayResponse with transaction_reference and instructions
          - MUST NOT mark the payment as complete — that happens via webhook

        Args:
            payment: The Payment model instance (status must be PENDING).

        Returns:
            GatewayResponse with success=True and instructions on success,
            or success=False with error details on failure.
        """
        ...

    @abstractmethod
    def verify_payment(self, data: dict) -> WebhookValidationResult:
        """
        [PRD: verify_payment(data: dict) -> dict]

        Validate an inbound webhook/callback from the provider.

        Behaviour:
          - Checks HMAC signature (constant-time comparison)
          - Verifies all required fields are present
          - Validates status value is a known value
          - NEVER raises — all errors returned as WebhookValidationResult

        Args:
            data: Raw webhook body dict. Signature is expected under
                  data["signature"] or passed separately via the view header.

        Returns:
            WebhookValidationResult(is_valid=True) on success,
            or is_valid=False with error_code and error_message on failure.
        """
        ...

    @abstractmethod
    def parse_webhook(self, raw_body: dict) -> WebhookPayload:
        """
        Parse a validated raw webhook body into a typed WebhookPayload.
        Called ONLY after verify_payment() returns is_valid=True.

        Args:
            raw_body: The raw webhook body dict (already validated).

        Returns:
            WebhookPayload with all fields populated.
        """
        ...

    # ── Shared Utilities ───────────────────────────────────────────────────────
    # These are available to all subclasses — centralises crypto logic so
    # no provider re-implements HMAC differently.

    def _build_gateway_request(self, payment: "Payment") -> GatewayRequest:
        """
        Convenience: construct a GatewayRequest from a Payment model instance.
        Subclasses can call this in create_payment() to avoid boilerplate.
        """
        return GatewayRequest(
            transaction_id=payment.transaction_id,
            student_id=payment.student.student_id,
            amount=payment.amount,
            semester=payment.semester,
            provider=self.PROVIDER_NAME,
            metadata={"student_name": payment.student.name},
        )

    def compute_hmac_signature(self, payload: str, secret: Optional[str] = None) -> str:
        """
        Compute HMAC-SHA256 over a canonical payload string.
        Used to sign outbound requests AND verify inbound webhooks.
        """
        key_str = secret or self.WEBHOOK_SECRET
        if not key_str:
            return ""
        key = key_str.encode("utf-8")
        return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_signature(
        self,
        payload:            str,
        received_signature: str,
        secret:             Optional[str] = None,
    ) -> bool:
        """
        Constant-time HMAC comparison — prevents timing side-channel attacks.
        Always use this instead of == when comparing signatures.
        """
        key_str = secret or self.WEBHOOK_SECRET
        if not key_str:
            return False
        expected = self.compute_hmac_signature(payload, key_str)
        return hmac.compare_digest(expected, received_signature)

    def build_canonical_string(self, data: dict) -> str:
        """
        Deterministic canonical string for signature computation.
        Keys are alphabetically sorted so field order in the payload doesn't matter.
        Format: "amount=5000.00&status=success&transaction_id=abc..."
        """
        return "&".join(f"{k}={v}" for k, v in sorted(data.items()))

    def _allow_fallback_secret(self) -> bool:
        """
        Allow static fallback secrets only when explicitly enabled and loopback-only.
        """
        from django.conf import settings

        allow_flag = bool(getattr(settings, "ALLOW_WEBHOOK_SECRET_FALLBACK", False))
        if not allow_flag:
            return False

        debug_or_testing = bool(getattr(settings, "DEBUG", False) or getattr(settings, "TESTING", False))
        if not debug_or_testing:
            return False

        allowed_ips = getattr(settings, "WEBHOOK_ALLOWED_IPS", []) or []
        loopback = {"127.0.0.1", "::1"}
        return bool(allowed_ips) and all(ip in loopback for ip in allowed_ips)

    def normalize_amount(self, value) -> str:
        """
        Canonicalize amount for signature verification to avoid float/string drift.
        Returns a 2-decimal string when possible.
        """
        try:
            dec = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return f"{dec:.2f}"
        except (InvalidOperation, ValueError, TypeError):
            return str(value)

    @property
    def provider(self) -> str:
        """Provider name string — matches registry key and PaymentMethod choices."""
        return self.PROVIDER_NAME
# Avoid circular import — Payment model only needed for type hints
