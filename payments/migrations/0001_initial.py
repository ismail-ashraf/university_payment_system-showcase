"""
payments/migrations/0001_initial.py
Initial migration for Payment and PaymentAuditLog models.
"""

import django.db.models.deletion
import django.db.models.functions.datetime
import uuid
from django.db import migrations, models
import payments.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("students", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("transaction_id", models.UUIDField(
                    default=uuid.uuid4, editable=False, primary_key=True, serialize=False,
                    help_text="Globally unique transaction identifier (UUID4).",
                )),
                ("student", models.ForeignKey(
                    db_index=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="payments",
                    to="students.student",
                )),
                ("amount", models.DecimalField(
                    decimal_places=2, max_digits=10,
                    help_text="Expected fee amount in EGP at the time this order was created.",
                )),
                ("status", models.CharField(
                    choices=[
                        ("pending",   "Pending"),
                        ("paid",      "Paid"),
                        ("failed",    "Failed"),
                        ("cancelled", "Cancelled"),
                        ("refunded",  "Refunded"),
                    ],
                    db_index=True,
                    default="pending",
                    max_length=20,
                )),
                ("payment_method", models.CharField(
                    blank=True, null=True, max_length=30,
                    choices=[
                        ("fawry",          "Fawry"),
                        ("banque_misr",    "Banque Misr"),
                        ("vodafone_cash",  "Vodafone Cash"),
                        ("bank_transfer",  "Bank Transfer"),
                        ("cash",           "Cash (on-site)"),
                    ],
                    help_text="Filled in Phase 3 when the student selects a gateway.",
                )),
                ("semester", models.CharField(
                    default=payments.models.current_semester,
                    max_length=20,
                    help_text="Semester this payment belongs to (e.g. '2025-Spring').",
                )),
                ("used", models.BooleanField(
                    db_index=True, default=False,
                    help_text="True after the transaction has been submitted to a payment gateway.",
                )),
                ("gateway_reference", models.CharField(
                    blank=True, null=True, max_length=200,
                    help_text="Reference number returned by the payment provider.",
                )),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "payments",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="PaymentAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("payment", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="audit_logs",
                    to="payments.payment",
                )),
                ("event_type", models.CharField(
                    db_index=True, max_length=30,
                    choices=[
                        ("initiated",      "Payment Initiated"),
                        ("processing",     "Processing at Gateway"),
                        ("success",        "Payment Confirmed"),
                        ("failure",        "Payment Failed"),
                        ("cancelled",      "Cancelled by Student/Admin"),
                        ("webhook",        "Webhook Received"),
                        ("refund",         "Refund Issued"),
                        ("replay_blocked", "Replay Attack Blocked"),
                    ],
                )),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("actor", models.CharField(
                    default="system", max_length=100,
                    help_text="Who triggered this event: 'system', 'student', 'admin', or gateway name.",
                )),
                ("payload", models.JSONField(
                    default=dict,
                    help_text="Raw data associated with this event (gateway response, etc.).",
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "payment_audit_logs",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(fields=["student", "semester"], name="idx_pay_student_semester"),
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(fields=["status", "semester"], name="idx_pay_status_semester"),
        ),
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.UniqueConstraint(
                condition=models.Q(status="pending"),
                fields=["student", "semester"],
                name="uniq_pending_payment_per_student_semester",
            ),
        ),
    ]