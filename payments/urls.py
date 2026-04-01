"""
=== FILE: payments/urls.py ===
All payment endpoint routes.
"""
from django.urls import path
from .views import (
    StartPaymentView,
    SubmitPaymentView,
    WebhookView,
    PaymentDetailView,
    StudentPaymentListView,
    StudentPaymentStatusView,
    StudentPaymentHistoryView,
    StudentPaymentDetailView,
    StudentPaymentNextActionView,
    CancelPaymentView,
    AdminPaymentSummaryView,
    AdminPaymentRecentView,
    AdminPaymentListView,
    AdminPaymentDetailView,
    AdminAuditLogListView,
)

app_name = "payments"

urlpatterns = [
    # PRD: POST /api/payments/start/ → { student_id, provider }
    path("start/",                          StartPaymentView.as_view(),       name="payment-start"),
    # Phase 3: Submit existing payment to gateway
    path("<uuid:transaction_id>/submit/",   SubmitPaymentView.as_view(),      name="payment-submit"),
    # PRD: Webhook endpoint
    path("webhook/<str:provider>/",         WebhookView.as_view(),            name="payment-webhook"),
    # Detail + audit trail
    path("<uuid:transaction_id>/",          PaymentDetailView.as_view(),      name="payment-detail"),
    # Student payment status (current authenticated student)
    path("student/status/",                StudentPaymentStatusView.as_view(), name="payment-student-status"),
    # Student payment history (current authenticated student)
    path("student/payments/",              StudentPaymentHistoryView.as_view(), name="payment-student-history"),
    # Student payment detail (current authenticated student)
    path("student/payments/<uuid:transaction_id>/", StudentPaymentDetailView.as_view(), name="payment-student-detail"),
    # Student next action (current authenticated student)
    path("student/next-action/",            StudentPaymentNextActionView.as_view(), name="payment-student-next-action"),
    # All payments for a student
    path("student/<str:student_id>/",       StudentPaymentListView.as_view(), name="payment-student-list"),
    # Cancel
    path("<uuid:transaction_id>/cancel/",   CancelPaymentView.as_view(),      name="payment-cancel"),

    # Admin reporting (read-only)
    path("admin/payments/summary/",         AdminPaymentSummaryView.as_view(), name="admin-payment-summary"),
    path("admin/payments/recent/",          AdminPaymentRecentView.as_view(),  name="admin-payment-recent"),
    path("admin/payments/",                 AdminPaymentListView.as_view(),    name="admin-payment-list"),
    path("admin/payments/<uuid:transaction_id>/", AdminPaymentDetailView.as_view(), name="admin-payment-detail"),
    path("admin/audit-logs/",               AdminAuditLogListView.as_view(),   name="admin-audit-log-list"),
]
