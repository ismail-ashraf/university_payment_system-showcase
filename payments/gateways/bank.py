"""
=== FILE: payments/gateways/bank.py ===

Mock Bank (Direct Bank Transfer) Gateway Adapter (Simulated).

Real bank transfer flow:
  1. System generates a unique virtual IBAN per transaction
  2. Student transfers exact amount with the reference in the memo
  3. Bank sends a webhook confirming receipt and matching

Simulation decisions:
  - create_payment() returns a virtual IBAN + bank reference
  - Virtual IBAN derived from transaction UUID (unique per payment)
  - Student must transfer EXACT amount or transfer is rejected
  - Expires in 48 hours
  - Webhook validated via HMAC-SHA256
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


class MockBankGateway(BasePaymentGateway):
    """
    Mock Bank integration — simulates direct bank transfer with virtual IBAN.
    Each transaction gets a unique virtual account number for exact matching.
    """

    PROVIDER_NAME  = "bank"
    WEBHOOK_SECRET = "bank-webhook-secret-dev"

    def __init__(self):
        secret = getattr(settings, "BANK_WEBHOOK_SECRET", None)
        if secret:
            self.WEBHOOK_SECRET = secret
        elif self._allow_fallback_secret():
            self.WEBHOOK_SECRET = "bank-webhook-secret-dev"
        else:
            self.WEBHOOK_SECRET = None

    # Simulated bank details
    BANK_NAME     = "University Partner Bank (Simulated)"
    ACCOUNT_NAME  = "University Smart Payment System"

    # ── PRD Interface ──────────────────────────────────────────────────────────

    def create_payment(self, payment: "Payment") -> GatewayResponse:
        """
        [PRD: create_payment(payment: Payment) -> dict]

        Simulate a bank transfer initiation.
        Returns a virtual IBAN unique to this transaction.
        The student must transfer the exact amount with the reference in the memo.
        """
        req = self._build_gateway_request(payment)

        # Virtual IBAN: deterministic from transaction UUID — unique per payment
        txn_hex        = str(req.transaction_id).replace("-", "").upper()[:16]
        virtual_iban   = f"EG{txn_hex}"
        bank_reference = f"BNK-{str(req.transaction_id)[:8].upper()}"

        canonical    = self.build_canonical_string({
            "transaction_id": str(req.transaction_id),
            "amount":         str(req.amount),
            "student_id":     req.student_id,
        })
        outbound_sig = self.compute_hmac_signature(canonical)

        raw_payload = {
            "provider":           self.PROVIDER_NAME,
            "bank_reference":     bank_reference,
            "virtual_iban":       virtual_iban,
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
            "provider":        self.BANK_NAME,
            "bank_reference":  bank_reference,
            "virtual_iban":    virtual_iban,
            "account_name":    self.ACCOUNT_NAME,
            "amount":          str(req.amount),
            "currency":        "EGP",
            "expires_in":      "48 hours",
            "steps": [
                "Log in to your online banking portal or visit any bank branch.",
                f"Transfer exactly {req.amount} EGP to the following account:",
                f"  Account Name : {self.ACCOUNT_NAME}",
                f"  Virtual IBAN : {virtual_iban}",
                f"  Reference    : {bank_reference}",
                "The reference MUST appear in the transfer memo for automatic matching.",
                "Payment confirmed within 1 business day.",
            ],
            "critical": (
                f"You MUST transfer exactly {req.amount} EGP. "
                "Transfers of any other amount will be automatically rejected."
            ),
        }

        logger.info(
            "[MockBankGateway.create_payment] ref=%s iban=%s txn=%s amount=%s",
            bank_reference, virtual_iban, str(req.transaction_id)[:8], req.amount,
            extra={
                "event": "payment_gateway_create_payment",
                "transaction_id": str(req.transaction_id),
                "provider": self.PROVIDER_NAME,
            },
        )

        return GatewayResponse(
            success=True,
            transaction_reference=bank_reference,
            status="pending",
            provider=self.PROVIDER_NAME,
            instructions=instructions,
            raw_payload=raw_payload,
        )

    def verify_payment(self, data: dict) -> WebhookValidationResult:
        """
        [PRD: verify_payment(data: dict) -> dict]

        Validate an inbound bank webhook.
        Expected fields: transaction_id, bank_reference, status, amount, signature.
        """
        if not self.WEBHOOK_SECRET:
            return WebhookValidationResult(
                is_valid=False,
                error_code="WEBHOOK_SECRET_MISSING",
                error_message="Webhook secret is not configured.",
            )

        required = {"transaction_id", "bank_reference", "status", "amount"}
        missing  = required - data.keys()
        if missing:
            return WebhookValidationResult(
                is_valid=False,
                error_code="WEBHOOK_MISSING_FIELDS",
                error_message=f"Missing required fields: {', '.join(sorted(missing))}",
            )

        signature = data.get("signature", "")
        canonical = self.build_canonical_string({
            "transaction_id": data["transaction_id"],
            "bank_reference": data["bank_reference"],
            "status":         data["status"],
            "amount":         self.normalize_amount(data["amount"]),
        })
        if not self.verify_signature(canonical, signature):
            logger.warning(
                "[MockBankGateway.verify_payment] Bad signature | txn=%s",
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

        if data["status"] not in ("success", "failed", "pending"):
            return WebhookValidationResult(
                is_valid=False,
                error_code="WEBHOOK_INVALID_STATUS",
                error_message=f"Unknown status: '{data['status']}'",
            )

        return WebhookValidationResult(is_valid=True)

    def parse_webhook(self, raw_body: dict) -> WebhookPayload:
        """Parse a validated bank webhook body into a typed WebhookPayload."""
        return WebhookPayload(
            transaction_id=UUID(raw_body["transaction_id"]),
            transaction_reference=raw_body["bank_reference"],
            provider=self.PROVIDER_NAME,
            status=raw_body["status"],
            amount=Decimal(str(raw_body["amount"])),
            signature=raw_body.get("signature", ""),
            raw_body=raw_body,
        )
