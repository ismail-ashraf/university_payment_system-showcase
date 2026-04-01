"""
=== FILE: payments/admin.py ===

Django Admin — Production-grade interface for payment management.

Features:
  - Color-coded status badges in list view
  - Full audit trail inline (append-only, no edit/delete)
  - Provider-aware display with gateway reference
  - Advanced search + filters for operations team
  - Custom actions: mark_cancelled, export summary
  - Summary statistics in changelist header
"""

from django.contrib import admin
from decimal import Decimal, InvalidOperation
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.db.models import Count, Sum, Q
from django.utils import timezone

from .models import Payment, PaymentAuditLog


# ── Status badge colours ──────────────────────────────────────────────────────

_STATUS_COLORS = {
    "pending":    "#f59e0b",   # amber
    "processing": "#3b82f6",   # blue
    "paid":       "#10b981",   # green
    "failed":     "#ef4444",   # red
    "cancelled":  "#6b7280",   # gray
    "refunded":   "#8b5cf6",   # purple
}


def _status_badge(status_value: str) -> str:
    color = _STATUS_COLORS.get(status_value, "#94a3b8")
    return format_html(
        '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;'
        'font-size:11px;font-weight:600;text-transform:uppercase;">{}</span>',
        color,
        status_value,
    )

def _format_amount(value) -> str:
    """
    Safe formatter for amounts that may be Decimal, number, string, SafeString, or None.
    Falls back to a plain string if formatting is not possible.
    """
    if value is None:
        return "-"
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    if isinstance(value, (int, float)):
        return f"{Decimal(str(value)):,.2f}"
    try:
        return f"{Decimal(str(value)):,.2f}"
    except (InvalidOperation, ValueError, TypeError):
        return str(value)

# ── Audit Log Inline ──────────────────────────────────────────────────────────

class PaymentAuditLogInline(admin.TabularInline):
    """
    Append-only audit trail shown inside the Payment detail page.
    No add/edit/delete — audit logs are immutable.
    """
    model           = PaymentAuditLog
    extra           = 0
    can_delete      = False
    ordering        = ("created_at",)  # Chronological — oldest first
    readonly_fields = ("event_type", "amount_display", "actor", "payload_display", "created_at")
    fields          = ("created_at", "event_type", "amount_display", "actor", "payload_display")

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Amount (EGP)")
    def amount_display(self, obj):
        return f"{_format_amount(obj.amount)} EGP"

    @admin.display(description="Payload (truncated)")
    def payload_display(self, obj):
        """Show first 200 chars of payload as preformatted text."""
        text = str(obj.payload)
        if len(text) > 200:
            text = text[:200] + "…"
        return format_html("<pre style='font-size:11px;margin:0;'>{}</pre>", text)


# ── Payment Admin ─────────────────────────────────────────────────────────────

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """
    Full payment management interface.
    Used by the operations team to monitor and manage payments.
    """

    # ── List view ──────────────────────────────────────────────────────────────
    list_display  = (
        "short_txn_id",
        "student_link",
        "amount_display",
        "status_badge",
        "payment_method",
        "gateway_reference",
        "semester",
        "used_icon",
        "created_at",
    )
    list_filter   = (
        "status",
        "payment_method",
        "semester",
        "used",
    )
    search_fields = (
        "transaction_id",
        "student__student_id",
        "student__name",
        "gateway_reference",
    )
    ordering      = ("-created_at",)
    date_hierarchy = "created_at"

    # ── Detail view ────────────────────────────────────────────────────────────
    readonly_fields = (
        "transaction_id",
        "student",
        "amount",
        "semester",
        "created_at",
        "updated_at",
        "status_badge_detail",
        "audit_summary",
    )
    inlines     = [PaymentAuditLogInline]
    fieldsets   = (
        ("Transaction Identity", {
            "fields": ("transaction_id", "student", "amount", "semester"),
        }),
        ("Gateway Status", {
            "fields": (
                "status_badge_detail",
                "status",
                "payment_method",
                "gateway_reference",
                "used",
            ),
        }),
        ("Notes", {
            "fields": ("notes",),
            "classes": ("collapse",),
        }),
        ("Audit Summary", {
            "fields": ("audit_summary",),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    # ── Custom actions ─────────────────────────────────────────────────────────
    actions = ["action_cancel_payments"]

    @admin.action(description="Cancel selected PENDING payments")
    def action_cancel_payments(self, request, queryset):
        cancellable = queryset.filter(status="pending", used=False)
        count       = 0
        for payment in cancellable:
            payment.status = "cancelled"
            payment.save(update_fields=["status", "updated_at"])
            PaymentAuditLog.objects.create(
                payment=payment,
                event_type=PaymentAuditLog.EventType.CANCELLED,
                amount=payment.amount,
                actor=f"admin:{request.user}",
                payload={"reason": "Cancelled via Django Admin batch action."},
            )
            count += 1
        skipped = queryset.count() - count
        self.message_user(
            request,
            f"Cancelled {count} payment(s). "
            + (f"Skipped {skipped} (already processing/paid/failed)." if skipped else ""),
        )

    # ── Display helpers ────────────────────────────────────────────────────────

    @admin.display(description="Transaction ID", ordering="transaction_id")
    def short_txn_id(self, obj) -> str:
        full = str(obj.transaction_id)
        return format_html(
            '<span title="{}" style="font-family:monospace;font-size:12px;">{}</span>',
            full,
            full[:8] + "…",
        )

    @admin.display(description="Student", ordering="student__student_id")
    def student_link(self, obj) -> str:
        return format_html(
            "<strong>{}</strong><br/><small style='color:#6b7280;'>{}</small>",
            obj.student.student_id,
            obj.student.name,
        )

    @admin.display(description="Amount", ordering="amount")
    def amount_display(self, obj) -> str:
        return format_html(
            "<strong>{}</strong> <small>EGP</small>",
            _format_amount(obj.amount),
        )

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj) -> str:
        return _status_badge(obj.status)

    @admin.display(description="Status")
    def status_badge_detail(self, obj) -> str:
        return _status_badge(obj.status)

    @admin.display(description="Used", boolean=True)
    def used_icon(self, obj) -> bool:
        return obj.used

    @admin.display(description="Audit Trail Summary")
    def audit_summary(self, obj) -> str:
        logs = obj.audit_logs.order_by("created_at")
        if not logs.exists():
            return "No audit logs yet."
        rows = "".join(
            f"<tr>"
            f"<td style='padding:4px 8px;font-size:11px;color:#6b7280;'>{l.created_at.strftime('%Y-%m-%d %H:%M:%S')}</td>"
            f"<td style='padding:4px 8px;font-size:11px;font-weight:600;'>{l.event_type}</td>"
            f"<td style='padding:4px 8px;font-size:11px;'>{l.actor}</td>"
            f"<td style='padding:4px 8px;font-size:11px;'>{_format_amount(l.amount)} EGP</td>"
            f"</tr>"
            for l in logs
        )
        return mark_safe(
            f"<table style='border-collapse:collapse;width:100%;'>"
            f"<thead><tr>"
            f"<th style='text-align:left;padding:4px 8px;font-size:11px;background:#f1f5f9;'>Time</th>"
            f"<th style='text-align:left;padding:4px 8px;font-size:11px;background:#f1f5f9;'>Event</th>"
            f"<th style='text-align:left;padding:4px 8px;font-size:11px;background:#f1f5f9;'>Actor</th>"
            f"<th style='text-align:left;padding:4px 8px;font-size:11px;background:#f1f5f9;'>Amount</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )

    def get_queryset(self, request):
        """Optimise list queries — select student in same query."""
        return super().get_queryset(request).select_related("student")


# ── Audit Log Admin (standalone) ──────────────────────────────────────────────

@admin.register(PaymentAuditLog)
class PaymentAuditLogAdmin(admin.ModelAdmin):
    """
    Read-only audit log browser.
    The operations team can search all audit events across all payments.
    """
    list_display   = ("id", "payment_short", "event_type", "amount_display", "actor", "created_at")
    list_filter    = ("event_type", "actor")
    search_fields  = (
        "payment__transaction_id",
        "payment__student__student_id",
        "payment__student__name",
    )
    ordering       = ("-created_at",)
    date_hierarchy = "created_at"
    readonly_fields = (
        "payment", "event_type", "amount", "actor", "payload", "created_at"
    )

    def has_add_permission(self, request):
        return False   # Audit log is system-only

    def has_change_permission(self, request, obj=None):
        return False   # Immutable

    def has_delete_permission(self, request, obj=None):
        return False   # Never delete audit history

    @admin.display(description="Payment", ordering="payment__transaction_id")
    def payment_short(self, obj) -> str:
        txn = str(obj.payment.transaction_id)
        return format_html(
            '<span style="font-family:monospace;font-size:11px;">{}</span>'
            '<br/><small style="color:#6b7280;">{}</small>',
            txn[:8] + "…",
            obj.payment.student.student_id,
        )

    @admin.display(description="Amount", ordering="amount")
    def amount_display(self, obj) -> str:
        return f"{_format_amount(obj.amount)} EGP"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "payment", "payment__student"
        )
