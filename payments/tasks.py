"""
Minimal task-style boundary for payment webhook processing.

This is intentionally synchronous for now to preserve current behavior.
Future phases can route this through a real async worker without changing the view.
"""

from .services.payment_service import process_webhook


def process_webhook_task(*, provider: str, raw_body: dict, signature: str):
    return process_webhook(
        provider=provider,
        raw_body=raw_body,
        signature=signature,
    )

