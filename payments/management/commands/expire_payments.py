"""
Expire stale payments based on expires_at.

Usage:
    python manage.py expire_payments
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from payments.models import Payment
from payments.services.payment_service import _expire_payment_if_needed


class Command(BaseCommand):
    help = "Expire payments whose expires_at is in the past."

    def handle(self, *args, **options):
        now = timezone.now()
        qs = Payment.objects.filter(
            expires_at__isnull=False,
            expires_at__lt=now,
        ).exclude(status=Payment.PaymentStatus.EXPIRED)

        expired_count = 0
        for payment in qs.select_related("student"):
            expired, err = _expire_payment_if_needed(payment, actor="system")
            if err:
                self.stderr.write(
                    f"Failed to expire {payment.transaction_id_str}: {err['payload']['error']['code']}"
                )
                continue
            if expired:
                expired_count += 1

        self.stdout.write(f"Expired payments: {expired_count}")
