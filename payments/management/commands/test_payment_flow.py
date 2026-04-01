"""
=== FILE: payments/management/commands/test_payment_flow.py ===

Management command to run a full payment flow end-to-end in a dev environment.
Useful for manual testing and verifying gateway integrations without needing curl.

Usage:
    # Test full flow for a student with Fawry
    python manage.py test_payment_flow --student 20210001 --provider fawry

    # Test all three providers for a student
    python manage.py test_payment_flow --student 20210001 --provider all

    # Dry run (show what would happen, no DB writes)
    python manage.py test_payment_flow --student 20210001 --provider fawry --dry-run

    # Simulate webhook after payment is submitted
    python manage.py test_payment_flow --student 20210001 --provider fawry --webhook success

Output: Coloured terminal output showing each step + response.
"""

from __future__ import annotations

import json
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction

from students.models import Student
from payments.models import Payment, PaymentAuditLog, current_semester
from payments.services import start_payment, process_webhook
from payments.gateways import get_gateway, SUPPORTED_PROVIDERS


class Command(BaseCommand):
    help = "Run an end-to-end payment flow for testing purposes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--student",
            required=True,
            help="Student ID to test with (must exist in DB).",
        )
        parser.add_argument(
            "--provider",
            default="fawry",
            choices=SUPPORTED_PROVIDERS + ["all"],
            help=f"Gateway provider. Choices: {', '.join(SUPPORTED_PROVIDERS)}, all",
        )
        parser.add_argument(
            "--webhook",
            choices=["success", "failed", "pending", "none"],
            default="success",
            help="Simulate a webhook after payment submission (default: success).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would happen without writing to the database.",
        )

    def handle(self, *args, **options):
        student_id   = options["student"].upper()
        provider_arg = options["provider"]
        webhook_status = options["webhook"]
        dry_run      = options["dry_run"]

        providers = SUPPORTED_PROVIDERS if provider_arg == "all" else [provider_arg]

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 65))
        self.stdout.write(self.style.SUCCESS("  University Payment System — Flow Test"))
        self.stdout.write(self.style.SUCCESS("=" * 65))
        self.stdout.write(f"  Student:  {student_id}")
        self.stdout.write(f"  Provider: {provider_arg}")
        self.stdout.write(f"  Webhook:  {webhook_status}")
        self.stdout.write(f"  Dry run:  {'YES — no DB writes' if dry_run else 'NO'}")
        self.stdout.write(self.style.SUCCESS("=" * 65))
        self.stdout.write("")

        # Validate student exists
        try:
            student = Student.objects.get(student_id=student_id)
            self.stdout.write(f"  ✅ Student found: {student.name} (status={student.status})")
        except Student.DoesNotExist:
            raise CommandError(
                f"Student '{student_id}' not found. Run: python manage.py seed_students first."
            )

        if dry_run:
            self.stdout.write(self.style.WARNING("\n  [DRY RUN] No changes will be made to the database.\n"))
            for provider in providers:
                self._show_dry_run(student, provider)
            return

        for provider in providers:
            if provider_arg == "all":
                self.stdout.write(f"\n  {'─' * 60}")
                self.stdout.write(f"  Provider: {provider.upper()}")
                self.stdout.write(f"  {'─' * 60}")

            self._reset_student_payments(student_id)
            self._run_flow(student_id, provider, webhook_status)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 65))
        self.stdout.write(self.style.SUCCESS("  Test complete."))
        self.stdout.write(self.style.SUCCESS("=" * 65))
        self.stdout.write("")

    def _reset_student_payments(self, student_id: str):
        """Keep the manual test command repeatable across multiple runs."""
        PaymentAuditLog.objects.filter(payment__student__student_id=student_id).delete()
        Payment.objects.filter(
            student__student_id=student_id,
            semester=current_semester(),
        ).delete()

    def _run_flow(self, student_id: str, provider: str, webhook_status: str):
        """Run one complete payment flow for a provider."""

        # Step 1: start_payment
        self.stdout.write(f"\n  [1/3] Calling start_payment({student_id!r}, {provider!r})…")
        result, err = start_payment(student_id, provider)

        if err:
            self.stdout.write(
                self.style.ERROR(
                    f"  ❌ start_payment failed: {err['payload']['error']['code']} — "
                    f"{err['payload']['error']['message']}"
                )
            )
            return

        txn_id = result["transaction_id"]
        ref    = result["transaction_reference"]
        self.stdout.write(self.style.SUCCESS(f"  ✅ Payment created and submitted to {provider.upper()}"))
        self.stdout.write(f"     transaction_id:        {txn_id}")
        self.stdout.write(f"     transaction_reference: {ref}")
        self.stdout.write(f"     status:                {result['status']}")
        self.stdout.write(f"     amount:                {result['amount']} EGP")

        # Step 2: Show instructions
        instructions = result.get("instructions", {})
        self.stdout.write(f"\n  [2/3] Payment Instructions:")
        for step in instructions.get("steps", []):
            self.stdout.write(f"     • {step}")

        # Step 3: Simulate webhook
        if webhook_status == "none":
            self.stdout.write(f"\n  [3/3] Webhook simulation skipped.")
            return

        self.stdout.write(f"\n  [3/3] Simulating {provider.upper()} webhook (status={webhook_status})…")
        body = self._build_signed_webhook(provider, str(txn_id), webhook_status, result["amount"])

        wh_result, wh_err = process_webhook(provider, body, body["signature"])

        if wh_err:
            self.stdout.write(
                self.style.ERROR(
                    f"  ❌ Webhook failed: {wh_err['payload']['error']['code']} — "
                    f"{wh_err['payload']['error']['message']}"
                )
            )
            return

        final_status = wh_result.get("current_status", "unknown")
        status_color = self.style.SUCCESS if final_status == "paid" else self.style.WARNING
        self.stdout.write(status_color(f"  ✅ Webhook processed. Final status: {final_status.upper()}"))

        # Show audit trail
        self.stdout.write(f"\n  Audit Trail:")
        logs = PaymentAuditLog.objects.filter(
            payment__transaction_id=txn_id
        ).order_by("created_at")
        for log in logs:
            ts = log.created_at.strftime("%H:%M:%S")
            self.stdout.write(f"     {ts} | {log.event_type:<16} | {log.actor}")

    def _build_signed_webhook(
        self, provider: str, txn_id: str, status: str, amount: str
    ) -> dict:
        """Build a correctly signed webhook body for the given provider."""
        gw = get_gateway(provider)

        if provider == "fawry":
            ref  = f"FWR-{txn_id.replace('-','').upper()[:12]}"
            body = {
                "transaction_id":  txn_id,
                "fawry_reference": ref,
                "status":          status,
                "amount":          amount,
            }
            canonical = gw.build_canonical_string({
                "transaction_id":  txn_id,
                "fawry_reference": ref,
                "status":          status,
                "amount":          amount,
            })
        elif provider == "vodafone":
            ref  = f"VF-{txn_id.replace('-','').upper()[:10]}"
            body = {
                "transaction_id": txn_id,
                "vf_request_id":  ref,
                "status":         status,
                "amount":         amount,
            }
            canonical = gw.build_canonical_string({
                "transaction_id": txn_id,
                "vf_request_id":  ref,
                "status":         status,
                "amount":         amount,
            })
        else:  # bank
            ref  = f"BNK-{txn_id[:8].upper()}"
            body = {
                "transaction_id": txn_id,
                "bank_reference": ref,
                "status":         status,
                "amount":         amount,
            }
            canonical = gw.build_canonical_string({
                "transaction_id": txn_id,
                "bank_reference": ref,
                "status":         status,
                "amount":         amount,
            })

        body["signature"] = gw.compute_hmac_signature(canonical)
        return body

    def _show_dry_run(self, student: Student, provider: str):
        """Print what would happen without doing it."""
        from students.fee_calculator import calculate_student_fees
        breakdown = calculate_student_fees(allowed_hours=student.allowed_hours)
        self.stdout.write(f"\n  Provider: {provider.upper()}")
        self.stdout.write(f"  Would create Payment:")
        self.stdout.write(f"    student_id:    {student.student_id}")
        self.stdout.write(f"    amount:        {breakdown.total} EGP")
        self.stdout.write(f"    semester:      {current_semester()}")
        self.stdout.write(f"    provider:      {provider}")
        self.stdout.write(f"    initial_status: pending → processing (after gateway)")
        self.stdout.write(f"  Gateway: would call {provider}.create_payment()")
        self.stdout.write(f"  Webhook: would call process_webhook('{provider}', ...)")