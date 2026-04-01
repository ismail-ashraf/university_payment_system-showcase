"""
=== FILE: payments/gateways/fawry.py ===

Fawry Payment Gateway Adapter (Simulated).

Real Fawry flow:
  1. Merchant POSTs payment → Fawry returns a numeric reference code
  2. Student pays at any Fawry outlet or via Fawry app using the code
  3. Fawry sends a webhook (callback) confirming payment

Simulation decisions:
  - create_payment() always succeeds, returns FWR- reference
  - Webhook with status="success" → payment confirmed (PAID)
  - Webhook with status="failed"  → payment rejected (FAILED)
  - Invalid/missing signature     → rejected with clear error code
  - Reference code derived from transaction UUID (deterministic + unique)
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID
from django.conf import settings

from .base import (
    BasePaymentGateway,
    GatewayRequest,
    GatewayResponse,
    WebhookPayload,
    WebhookValidationResult,
)

if TYPE_CHECKING:
    from payments.models import Payment

logger = logging.getLogger(__name__)


class FawryGateway(BasePaymentGateway):
    """
    Fawry integration — simulates reference-code-based cash payment.
    Students receive a reference code and pay at any Fawry outlet.
    """

    PROVIDER_NAME  = "fawry"
    WEBHOOK_SECRET = "fawry-webhook-secret-dev"

    def __init__(self):
        secret = getattr(settings, "FAWRY_WEBHOOK_SECRET", None)
        if secret:
            self.WEBHOOK_SECRET = secret
        elif self._allow_fallback_secret():
            self.WEBHOOK_SECRET = "fawry-webhook-secret-dev"
        else:
            self.WEBHOOK_SECRET = None

    # ── PRD Interface ──────────────────────────────────────────────────────────

    def create_payment(self, payment: "Payment") -> GatewayResponse:
        """
        [PRD: create_payment(payment: Payment) -> dict]

        Simulate submitting a payment to Fawry.
        Returns a reference code the student uses at a Fawry outlet.

        Args:
            payment: Payment instance with status=PENDING.

        Returns:
            GatewayResponse with transaction_reference, status="pending",
            and step-by-step payment instructions.
        """
        req = self._build_gateway_request(payment)

        # Derive a short reference code from the transaction UUID
        # In production this would be returned by Fawry's REST API
        fawry_reference = f"FWR-{str(req.transaction_id).replace('-', '').upper()[:12]}"

        # Sign the outbound request so the webhook handler can verify callbacks
        canonical = self.build_canonical_string({
            "transaction_id": str(req.transaction_id),
            "amount":         str(req.amount),
            "student_id":     req.student_id,
        })
        outbound_sig = self.compute_hmac_signature(canonical)

        raw_payload = {
            "provider":           self.PROVIDER_NAME,
            "fawry_reference":    fawry_reference,
            "transaction_id":     str(req.transaction_id),
            "amount":             str(req.amount),
            "currency":           "EGP",
            "student_id":         req.student_id,
            "semester":           req.semester,
            "status":             "pending",
            "outbound_signature": outbound_sig,
            "simulated":          True,
        }

        instructions = {
            "provider":       "Fawry",
            "reference_code": fawry_reference,
            "amount":         str(req.amount),
            "currency":       "EGP",
            "expires_in":     "72 hours",
            "steps": [
                "Visit any Fawry outlet or open the Fawry app.",
                f"Enter reference code: {fawry_reference}",
                f"Pay exactly {req.amount} EGP.",
                "Keep your receipt - it contains your confirmation number.",
            ],
            "note": "Payment confirmed automatically after processing (up to 24 hours).",
        }

        logger.info(
            "[FawryGateway.create_payment] reference=%s txn=%s amount=%s",
            fawry_reference, str(req.transaction_id)[:8], req.amount,
            extra={
                "event": "payment_gateway_create_payment",
                "transaction_id": str(req.transaction_id),
                "provider": self.PROVIDER_NAME,
            },
        )

        return GatewayResponse(
            success=True,
            transaction_reference=fawry_reference,
            status="pending",
            provider=self.PROVIDER_NAME,
            instructions=instructions,
            raw_payload=raw_payload,
        )

    def verify_payment(self, data: dict) -> WebhookValidationResult:
        """
        [PRD: verify_payment(data: dict) -> dict]

        Validate an inbound Fawry webhook.
        Checks: required fields, HMAC signature, status value.

        Args:
            data: Raw webhook body. Expects keys:
                  transaction_id, fawry_reference, status, amount, signature.

        Returns:
            WebhookValidationResult(is_valid=True) or is_valid=False with details.
        """
        if not self.WEBHOOK_SECRET:
            return WebhookValidationResult(
                is_valid=False,
                error_code="WEBHOOK_SECRET_MISSING",
                error_message="Webhook secret is not configured.",
            )

        # 1. Required field check
        required = {"transaction_id", "fawry_reference", "status", "amount"}
        missing  = required - data.keys()
        if missing:
            return WebhookValidationResult(
                is_valid=False,
                error_code="WEBHOOK_MISSING_FIELDS",
                error_message=f"Missing required fields: {', '.join(sorted(missing))}",
            )

        # 2. HMAC signature verification
        signature = data.get("signature", "")
        canonical = self.build_canonical_string({
            "transaction_id":  data["transaction_id"],
            "fawry_reference": data["fawry_reference"],
            "status":          data["status"],
            "amount":          self.normalize_amount(data["amount"]),
        })
        if not self.verify_signature(canonical, signature):
            logger.warning(
                "[FawryGateway.verify_payment] Invalid signature | txn=%s",
                data.get("transaction_id", "?")[:8],
                extra={
                    "event": "payment_gateway_invalid_signature",
                    "transaction_id": data.get("transaction_id", ""),
                    "provider": self.PROVIDER_NAME,
                    "error_code": "WEBHOOK_INVALID_SIGNATURE",
                },
            )
            return WebhookValidationResult(
                is_valid=False,
                error_code="WEBHOOK_INVALID_SIGNATURE",
                error_message="Webhook signature verification failed.",
            )

        # 3. Status value validation
        if data["status"] not in ("success", "failed", "pending"):
            return WebhookValidationResult(
                is_valid=False,
                error_code="WEBHOOK_INVALID_STATUS",
                error_message=f"Unknown status: '{data['status']}'",
            )

        return WebhookValidationResult(is_valid=True)

    def parse_webhook(self, raw_body: dict) -> WebhookPayload:
        """Parse a validated Fawry webhook body into a typed WebhookPayload."""
        return WebhookPayload(
            transaction_id=UUID(raw_body["transaction_id"]),
            transaction_reference=raw_body["fawry_reference"],
            provider=self.PROVIDER_NAME,
            status=raw_body["status"],
            amount=Decimal(str(raw_body["amount"])),
            signature=raw_body.get("signature", ""),
            raw_body=raw_body,
        )
