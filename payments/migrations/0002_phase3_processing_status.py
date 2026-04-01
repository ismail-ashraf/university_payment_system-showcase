"""
=== FILE: payments/migrations/0002_phase3_processing_status.py ===
Add PROCESSING to PaymentStatus choices and expand PaymentMethod choices.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
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
        migrations.AlterField(
            model_name="payment",
            name="payment_method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("fawry",         "Fawry"),
                    ("vodafone",      "Vodafone Cash"),
                    ("bank",          "Bank Transfer"),
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
    ]
