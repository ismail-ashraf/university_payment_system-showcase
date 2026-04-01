"""
=== FILE: payments/migrations/0003_payment_processing_status_and_methods.py ===

Phase 3 Step 1 migration:
  - Expands PaymentMethod choices to include short-form provider names
    ("fawry", "vodafone", "bank") used by the gateway registry
  - Ensures PROCESSING status is present in choices
  - No schema changes (choices are validated at Python level, not DB level)
    but migration keeps Django's state in sync
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0002_phase3_processing_status"),
    ]

    operations = [
        # Expand payment_method choices to include new short-form provider names
        migrations.AlterField(
            model_name="payment",
            name="payment_method",
            field=models.CharField(
                blank=True,
                choices=[
                    # Phase 3 Step 1 — short provider names used by gateway registry
                    ("fawry",         "Fawry"),
                    ("vodafone",      "Vodafone Cash"),
                    ("bank",          "Bank Transfer"),
                    # Legacy names (Phase 2 compatibility)
                    ("banque_misr",   "Banque Misr"),
                    ("vodafone_cash", "Vodafone Cash (legacy)"),
                    ("bank_transfer", "Bank Transfer (legacy)"),
                    ("cash",          "Cash (on-site)"),
                ],
                help_text="Gateway selected by the student.",
                max_length=30,
                null=True,
            ),
        ),
        # Ensure PROCESSING appears in status choices
        migrations.AlterField(
            model_name="payment",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending",    "Pending"),
                    ("processing", "Processing at Gateway"),
                    ("paid",       "Paid"),
                    ("failed",     "Failed"),
                    ("cancelled",  "Cancelled"),
                    ("refunded",   "Refunded"),
                ],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
    ]