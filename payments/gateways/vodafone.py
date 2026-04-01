"""
=== FILE: payments/gateways/vodafone.py ===

Vodafone Cash Payment Gateway Adapter (Simulated).

Real Vodafone Cash flow:
  1. Merchant sends request with customer's mobile number
  2. Customer receives USSD push on their Vodafone number to approve
  3. Vodafone sends a webhook confirming approval or rejection

Simulation decisions:
  - create_payment() returns a VF- request ID and mobile approval instructions
  - Reference derived from transaction UUID (deterministic)
  - Webhook validated with HMAC-SHA256 on canonical fields
  - Expires in 30 minutes (stated in instructions — not enforced in simulation)
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID
from django.conf import settings

from .base import (
    BasePaymentGateway,
    GatewayResponse,
    WebhookPayload,
    WebhookValidationResult,
)

if TYPE_CHECKING:
    from payments.models import Payment

logger = logging.getLogger(__name__)


class VodafoneGateway(BasePaymentGateway):
    """
    Vodafone Cash integration — simulates mobile wallet push payment.
    Student receives a USSD push on their registered mobile number.
    """

    PROVIDER_NAME  = "vodafone"
    WEBHOOK_SECRET = "vodafone-webhook-secret-dev"

    def __init__(self):
        secret = getattr(settings, "VODAFONE_WEBHOOK_SECRET", None)
        if secret:
            self.WEBHOOK_SECRET = secret
        elif self._allow_fallback_secret():
            self.WEBHOOK_SECRET = "vodafone-webhook-secret-dev"
        else:
            self.WEBHOOK_SECRET = None

    # ── PRD Interface ──────────────────────────────────────────────────────────

    def create_payment(self, payment: "Payment") -> GatewayResponse:
        """
        [PRD: create_payment(payment: Payment) -> dict]

        Simulate submitting a payment to Vodafone Cash.
        Returns a request ID and instructions for mobile approval.
        """
        req = self._build_gateway_request(payment)

        vf_request_id = f"VF-{str(req.transaction_id).replace('-', '').upper()[:10]}"

        canonical    = self.build_canonical_string({
            "transaction_id": str(req.transaction_id),
            "amount":         str(req.amount),
            "student_id":     req.student_id,
        })
        outbound_sig = self.compute_hmac_signature(canonical)

        raw_payload = {
            "provider":           self.PROVIDER_NAME,
            "vf_request_id":      vf_request_id,
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
            "provider":    "Vodafone Cash",
            "request_id":  vf_request_id,
            "amount":      str(req.amount),
            "currency":    "EGP",
            "expires_in":  "30 minutes",
            "steps": [
                "Open your Vodafone Cash app or dial *9#.",
                "Select 'Pay Bills' → 'University Fees'.",
                f"Enter request ID: {vf_request_id}",
                f"Confirm payment of {req.amount} EGP.",
                "You will receive an SMS confirmation once approved.",
            ],
            "warning": "This request expires in 30 minutes. Do not approve it after expiry.",
        }

        logger.info(
            "[VodafoneGateway.create_payment] request_id=%s txn=%s amount=%s",
            vf_request_id, str(req.transaction_id)[:8], req.amount,
            extra={
                "event": "payment_gateway_create_payment",
                "transaction_id": str(req.transaction_id),
                "provider": self.PROVIDER_NAME,
            },
        )

        return GatewayResponse(
            success=True,
            transaction_reference=vf_request_id,
            status="pending",
            provider=self.PROVIDER_NAME,
            instructions=instructions,
            raw_payload=raw_payload,
        )

    def verify_payment(self, data: dict) -> WebhookValidationResult:
        """
        [PRD: verify_payment(data: dict) -> dict]

        Validate an inbound Vodafone Cash webhook.
        Expected fields: transaction_id, vf_request_id, status, amount, signature.
        """
        if not self.WEBHOOK_SECRET:
            return WebhookValidationResult(
                is_valid=False,
                error_code="WEBHOOK_SECRET_MISSING",
                error_message="Webhook secret is not configured.",
            )

        # Required fields
        required = {"transaction_id", "vf_request_id", "status", "amount"}
        missing  = required - data.keys()
        if missing:
            return WebhookValidationResult(
                is_valid=False,
                error_code="WEBHOOK_MISSING_FIELDS",
                error_message=f"Missing required fields: {', '.join(sorted(missing))}",
            )

        # Signature check
        signature = data.get("signature", "")
        canonical = self.build_canonical_string({
            "transaction_id": data["transaction_id"],
            "vf_request_id":  data["vf_request_id"],
            "status":         data["status"],
            "amount":         self.normalize_amount(data["amount"]),
        })
        if not self.verify_signature(canonical, signature):
            logger.warning(
                "[VodafoneGateway.verify_payment] Bad signature | txn=%s",
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

        # Status validation
        if data["status"] not in ("success", "failed", "pending"):
            return WebhookValidationResult(
                is_valid=False,
                error_code="WEBHOOK_INVALID_STATUS",
                error_message=f"Unknown status: '{data['status']}'",
            )

        return WebhookValidationResult(is_valid=True)

    def parse_webhook(self, raw_body: dict) -> WebhookPayload:
        """Parse a validated Vodafone webhook body into a typed WebhookPayload."""
        return WebhookPayload(
            transaction_id=UUID(raw_body["transaction_id"]),
            transaction_reference=raw_body["vf_request_id"],
            provider=self.PROVIDER_NAME,
            status=raw_body["status"],
            amount=Decimal(str(raw_body["amount"])),
            signature=raw_body.get("signature", ""),
            raw_body=raw_body,
        )
