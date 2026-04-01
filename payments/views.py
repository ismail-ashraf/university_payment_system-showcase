"""
=== FILE: payments/views.py ===

Payment API Views — ZERO business logic here.

Architecture rule: Views only:
  1. Parse + validate HTTP input (via serializers)
  2. Extract auth token
  3. Delegate to services layer
  4. Map service results to HTTP responses

All logic lives in: services/payment_service.py, utils.py, gateways/

Endpoints:
  POST /api/payments/start/                  → PRD: create + submit in one call
  POST /api/payments/<uuid>/submit/          → submit existing payment to gateway
  POST /api/payments/webhook/<provider>/     → receive gateway callback
  GET  /api/payments/<uuid>/                 → payment detail + audit trail
  GET  /api/payments/student/<student_id>/   → all payments for a student
  POST /api/payments/<uuid>/cancel/          → cancel open payment
"""

import logging
from decimal import Decimal
from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from .models import Payment, PaymentAuditLog, current_semester
from students.models import Student
from auth_api.permissions import (
    require_authenticated_user,
    get_student_for_request,
    require_payment_ownership,
    is_admin_user,
)
from auth_api.abuse_guard import (
    get_client_ip,
    is_payment_start_blocked,
    record_payment_start_attempt,
    is_payment_submit_blocked,
    record_payment_submit_attempt,
)
from .serializers import (
    StartPaymentSerializer,
    SubmitPaymentSerializer,
    WebhookInputSerializer,
    PaymentResponseSerializer,
    PaymentDetailSerializer,
    StudentPaymentDetailSerializer,
    AdminPaymentListSerializer,
    AdminPaymentDetailSerializer,
    PaymentAuditLogSerializer,
)
from .utils import build_error
from .services.payment_service import (
    start_payment,
    initiate_with_gateway,
    cancel_payment,
    get_start_payment_status,
)
from .tasks import process_webhook_task

logger = logging.getLogger(__name__)


# ── Response helpers ──────────────────────────────────────────────────────────

def success_response(data, http_status=status.HTTP_200_OK) -> Response:
    return Response({"success": True, "data": data}, status=http_status)


def error_response(error_dict: dict) -> Response:
    """Convert a utils.build_error() dict into a DRF Response."""
    return Response(error_dict["payload"], status=error_dict["http_status"])


# ── POST /api/payments/start/ ─────────────────────────────────────────────────

class StartPaymentView(APIView):
    """
    [PRD: POST /api/payments/start/ → { student_id, provider }]

    Single-call payment initiation:
      1. Validate student_id + provider
      2. Delegate to services.start_payment() (full flow)
      3. Return payment status + instructions

    Views do NOT know about gateways, fee calculation, or DB writes.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "payment_start"

    def post(self, request) -> Response:
        data = request.data.copy()
        raw_student_id = data.get("student_id")
        if not raw_student_id or not str(raw_student_id).strip():
            if request.user and request.user.is_authenticated and not is_admin_user(request):
                try:
                    data["student_id"] = request.user.student_profile.student_id
                except Student.DoesNotExist:
                    return error_response(build_error(
                        code="STUDENT_PROFILE_MISSING",
                        message="Authenticated user has no linked student.",
                        http_status=403,
                    ))

        # Validate input
        serializer = StartPaymentSerializer(data=data)
        if not serializer.is_valid():
            return error_response(build_error(
                code="VALIDATION_ERROR",
                message="Input validation failed.",
                details=serializer.errors,
                http_status=400,
            ))

        student_id       = serializer.validated_data["student_id"]
        provider         = serializer.validated_data.get("provider") or None
        requested_amount = serializer.validated_data.get("amount")
        client_ip        = get_client_ip(request)

        _, auth_err = get_student_for_request(request, student_id)
        if auth_err:
            return error_response(auth_err)

        if is_payment_start_blocked(student_id, client_ip):
            return error_response(build_error(
                code="PAYMENT_START_RATE_LIMITED",
                message="Too many payment start attempts. Please wait and try again.",
                http_status=429,
            ))
        record_payment_start_attempt(student_id, client_ip)

        # Delegate everything to the service layer
        result, err = start_payment(
            student_id=student_id,
            provider=provider,
            requested_amount=requested_amount,
        )
        if err:
            logger.info(
                "payment_start_failed",
                extra={
                    "event": "payment_start_failed",
                    "request_id": getattr(request, "request_id", ""),
                    "student_id": student_id,
                    "provider": provider or "",
                    "error_code": err["payload"]["error"]["code"],
                },
            )
            return error_response(err)

        logger.info(
            "payment_start_success",
            extra={
                "event": "payment_start_success",
                "request_id": getattr(request, "request_id", ""),
                "student_id": student_id,
                "provider": provider or "",
                "transaction_id": result.get("transaction_id"),
            },
        )
        return success_response(result, http_status=status.HTTP_201_CREATED)


# ── POST /api/payments/<uuid>/submit/ ────────────────────────────────────────

class SubmitPaymentView(APIView):
    """
    Submit an existing PENDING payment to a chosen gateway.
    Use this when payment was created via start/ without a provider,
    or when the student wants to change provider.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "payment_submit"

    def post(self, request, transaction_id) -> Response:
        logger.info(
            "payment_submit_received",
            extra={
                "event": "payment_submit_received",
                "request_id": getattr(request, "request_id", ""),
                "transaction_id": str(transaction_id),
            },
        )
        serializer = SubmitPaymentSerializer(data=request.data)
        if not serializer.is_valid():
            logger.info(
                "payment_submit_failed",
                extra={
                    "event": "payment_submit_failed",
                    "request_id": getattr(request, "request_id", ""),
                    "transaction_id": str(transaction_id),
                    "error_code": "VALIDATION_ERROR",
                },
            )
            return error_response(build_error(
                code="VALIDATION_ERROR",
                message="Input validation failed.",
                details=serializer.errors,
                http_status=400,
            ))

        provider = serializer.validated_data["provider"]
        client_ip = get_client_ip(request)

        try:
            payment = Payment.objects.select_related("student").get(
                transaction_id=transaction_id
            )
        except Payment.DoesNotExist:
            logger.info(
                "payment_submit_failed",
                extra={
                    "event": "payment_submit_failed",
                    "request_id": getattr(request, "request_id", ""),
                    "transaction_id": str(transaction_id),
                    "error_code": "PAYMENT_NOT_FOUND",
                },
            )
            if is_payment_submit_blocked("unknown", client_ip):
                return error_response(build_error(
                    code="PAYMENT_SUBMIT_RATE_LIMITED",
                    message="Too many payment submit attempts. Please wait and try again.",
                    http_status=429,
                ))
            record_payment_submit_attempt("unknown", client_ip)
            return error_response(build_error(
                "PAYMENT_NOT_FOUND",
                f"No payment found with transaction ID '{transaction_id}'.",
                http_status=404,
            ))

        auth_err = require_payment_ownership(request, payment)
        if auth_err:
            logger.info(
                "payment_submit_failed",
                extra={
                    "event": "payment_submit_failed",
                    "request_id": getattr(request, "request_id", ""),
                    "transaction_id": str(transaction_id),
                    "student_id": payment.student.student_id,
                    "error_code": auth_err["payload"]["error"]["code"],
                },
            )
            return error_response(auth_err)

        txn_key = str(transaction_id)
        if is_payment_submit_blocked(txn_key, client_ip):
            return error_response(build_error(
                code="PAYMENT_SUBMIT_RATE_LIMITED",
                message="Too many payment submit attempts. Please wait and try again.",
                http_status=429,
            ))
        record_payment_submit_attempt(txn_key, client_ip)

        result, err = initiate_with_gateway(payment, provider)
        if err:
            logger.info(
                "payment_submit_failed",
                extra={
                    "event": "payment_submit_failed",
                    "request_id": getattr(request, "request_id", ""),
                    "transaction_id": str(transaction_id),
                    "student_id": payment.student.student_id,
                    "provider": provider or "",
                    "error_code": err["payload"]["error"]["code"],
                },
            )
            return error_response(err)

        logger.info(
            "payment_submit_success",
            extra={
                "event": "payment_submit_success",
                "request_id": getattr(request, "request_id", ""),
                "transaction_id": str(transaction_id),
                "student_id": payment.student.student_id,
                "provider": provider or "",
                "status": result.get("status", ""),
            },
        )
        return success_response(result, http_status=status.HTTP_200_OK)


# ── POST /api/payments/webhook/<provider>/ ───────────────────────────────────

class WebhookView(APIView):
    """
    [PRD: Webhook System + Idempotency Protection]

    Receive and process gateway callbacks.

    Security:
      - Signature validated BEFORE any DB changes
      - Duplicate webhooks return 200 (not 409) to prevent retry storms
      - Amount cross-checked against Payment record

    Signature location: X-Webhook-Signature header (preferred) or body field.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "payment_webhook"

    def post(self, request, provider: str) -> Response:
        logger.info(
            "payment_webhook_received",
            extra={
                "event": "payment_webhook_received",
                "request_id": getattr(request, "request_id", ""),
                "provider": provider,
                "transaction_id": request.data.get("transaction_id", ""),
            },
        )
        if not getattr(settings, "DEBUG", False) and not getattr(settings, "TESTING", False):
            allowed_ips = set(getattr(settings, "WEBHOOK_ALLOWED_IPS", []) or [])
            if allowed_ips:
                client_ip = get_client_ip(request)
                if client_ip not in allowed_ips:
                    return error_response(build_error(
                        code="WEBHOOK_SOURCE_NOT_ALLOWED",
                        message="Webhook source is not allowed.",
                        http_status=403,
                    ))
        # Minimal structural validation
        serializer = WebhookInputSerializer(data=request.data)
        if not serializer.is_valid():
            logger.info(
                "payment_webhook_malformed",
                extra={
                    "event": "payment_webhook_malformed",
                    "request_id": getattr(request, "request_id", ""),
                    "provider": provider,
                    "transaction_id": request.data.get("transaction_id", ""),
                    "error_code": "WEBHOOK_VALIDATION_ERROR",
                },
            )
            return error_response(build_error(
                code="WEBHOOK_VALIDATION_ERROR",
                message="Webhook payload validation failed.",
                details=serializer.errors,
                http_status=400,
            ))

        # Extract signature from header (preferred) or body
        signature = (
            request.headers.get("X-Webhook-Signature", "")
            or request.data.get("signature", "")
        )

        result, err = process_webhook_task(
            provider=provider,
            raw_body=request.data,
            signature=signature,
        )
        if err:
            logger.info(
                "payment_webhook_failed",
                extra={
                    "event": "payment_webhook_failed",
                    "request_id": getattr(request, "request_id", ""),
                    "provider": provider,
                    "transaction_id": request.data.get("transaction_id", ""),
                    "error_code": err["payload"]["error"]["code"],
                },
            )
            return error_response(err)

        logger.info(
            "payment_webhook_success",
            extra={
                "event": "payment_webhook_success",
                "request_id": getattr(request, "request_id", ""),
                "provider": provider,
                "transaction_id": request.data.get("transaction_id", ""),
            },
        )
        return success_response(result, http_status=status.HTTP_200_OK)


# ── GET /api/payments/<uuid>/ ────────────────────────────────────────────────

class PaymentDetailView(APIView):

    def get(self, request, transaction_id) -> Response:
        try:
            payment = (
                Payment.objects
                .select_related("student")
                .prefetch_related("audit_logs")
                .get(transaction_id=transaction_id)
            )
        except Payment.DoesNotExist:
            return error_response(build_error(
                "PAYMENT_NOT_FOUND",
                f"No payment found with transaction ID '{transaction_id}'.",
                http_status=404,
            ))
        except Exception:
            return error_response(build_error(
                "INVALID_TRANSACTION_ID",
                "The transaction ID format is invalid.",
                http_status=400,
            ))

        auth_err = require_payment_ownership(request, payment)
        if auth_err:
            return error_response(auth_err)

        if is_admin_user(request):
            return success_response(PaymentDetailSerializer(payment).data)
        return success_response(StudentPaymentDetailSerializer(payment).data)


# ── GET /api/payments/student/<student_id>/ ──────────────────────────────────

class StudentPaymentListView(APIView):

    def get(self, request, student_id: str) -> Response:
        student, err = get_student_for_request(request, student_id)
        if err:
            return error_response(err)

        payments = (
            Payment.objects
            .filter(student=student)
            .select_related("student")
            .order_by("-created_at")
        )

        return success_response({
            "student_id":    student.student_id,
            "student_name":  student.name,
            "total_records": payments.count(),
            "payments":      PaymentResponseSerializer(payments, many=True).data,
        })


# ─── GET /api/payments/student/status/ ──────────────────────────────────────────

class StudentPaymentStatusView(APIView):

    def get(self, request) -> Response:
        auth_err = require_authenticated_user(request)
        if auth_err:
            return error_response(auth_err)

        try:
            student = request.user.student_profile
        except Student.DoesNotExist:
            return error_response(build_error(
                code="STUDENT_PROFILE_MISSING",
                message="Authenticated user has no linked student.",
                http_status=403,
            ))

        can_start, reason_code, payment = get_start_payment_status(student)

        current_payment = None
        if payment:
            current_payment = {
                "transaction_id": payment.transaction_id_str,
                "status": payment.status,
                "amount": str(payment.amount),
                "created_at": payment.created_at.isoformat(),
            }
            if payment.expires_at:
                current_payment["expires_at"] = payment.expires_at.isoformat()

        return success_response({
            "student_id": student.student_id,
            "can_start_payment": can_start,
            "reason_code": reason_code,
            "current_payment": current_payment,
        })


# GET /api/payments/student/payments/

class StudentPaymentHistoryView(APIView):

    def get(self, request) -> Response:
        auth_err = require_authenticated_user(request)
        if auth_err:
            return error_response(auth_err)

        try:
            student = request.user.student_profile
        except Student.DoesNotExist:
            return error_response(build_error(
                code="STUDENT_PROFILE_MISSING",
                message="Authenticated user has no linked student.",
                http_status=403,
            ))

        payments = (
            Payment.objects
            .filter(student=student)
            .order_by("-created_at")[:20]
        )

        items = []
        for payment in payments:
            item = {
                "transaction_id": payment.transaction_id_str,
                "status": payment.status,
                "amount": str(payment.amount),
                "created_at": payment.created_at.isoformat(),
            }
            if payment.expires_at:
                item["expires_at"] = payment.expires_at.isoformat()
            items.append(item)

        return success_response({"payments": items})


# GET /api/payments/student/payments/<uuid>/

class StudentPaymentDetailView(APIView):

    def get(self, request, transaction_id) -> Response:
        try:
            payment = Payment.objects.select_related("student").get(
                transaction_id=transaction_id
            )
        except Payment.DoesNotExist:
            return error_response(build_error(
                "PAYMENT_NOT_FOUND",
                f"No payment found with transaction ID '{transaction_id}'.",
                http_status=404,
            ))
        except Exception:
            return error_response(build_error(
                "INVALID_TRANSACTION_ID",
                "The transaction ID format is invalid.",
                http_status=400,
            ))

        auth_err = require_payment_ownership(request, payment)
        if auth_err:
            return error_response(auth_err)

        return success_response(StudentPaymentDetailSerializer(payment).data)


# GET /api/payments/student/next-action/

class StudentPaymentNextActionView(APIView):

    def get(self, request) -> Response:
        auth_err = require_authenticated_user(request)
        if auth_err:
            return error_response(auth_err)

        try:
            student = request.user.student_profile
        except Student.DoesNotExist:
            return error_response(build_error(
                code="STUDENT_PROFILE_MISSING",
                message="Authenticated user has no linked student.",
                http_status=403,
            ))

        can_start, reason_code, payment = get_start_payment_status(student)

        if can_start:
            return success_response({
                "next_action": "none",
                "reason_code": None,
            })

        next_action = "none"
        status_value = payment.status if payment else ""
        if status_value == Payment.PaymentStatus.PENDING:
            next_action = "submit"
        elif status_value == Payment.PaymentStatus.PROCESSING:
            next_action = "wait"
        elif status_value in {
            Payment.PaymentStatus.PAID,
            Payment.PaymentStatus.REFUNDED,
        }:
            next_action = "none"

        return success_response({
            "next_action": next_action,
            "reason_code": reason_code,
        })


# ── POST /api/payments/<uuid>/cancel/ ────────────────────────────────────────

class CancelPaymentView(APIView):

    def post(self, request, transaction_id) -> Response:
        try:
            payment = Payment.objects.select_related("student").get(
                transaction_id=transaction_id
            )
        except Payment.DoesNotExist:
            return error_response(build_error(
                "PAYMENT_NOT_FOUND",
                f"No payment found with transaction ID '{transaction_id}'.",
                http_status=404,
            ))

        auth_err = require_payment_ownership(request, payment)
        if auth_err:
            return error_response(auth_err)

        actor = "admin" if (request.user and (request.user.is_staff or request.user.is_superuser)) else "student"
        result, err = cancel_payment(
            payment=payment,
            actor=actor,
            reason=request.data.get("reason", "Cancelled by user."),
        )
        if err:
            return error_response(err)

        payment.refresh_from_db()
        return success_response(PaymentResponseSerializer(payment).data)


# ─── Admin Reporting APIs (Read-only) ───────────────────────────────────────────

class AdminPaymentSummaryView(APIView):
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]

    def get(self, request) -> Response:
        from django.db.models import Count, Sum

        status_counts = {
            row["status"]: row["count"]
            for row in Payment.objects.values("status").annotate(count=Count("transaction_id"))
        }
        total_paid_amount = (
            Payment.objects.filter(status=Payment.PaymentStatus.PAID)
            .aggregate(total=Sum("amount"))
            .get("total")
        )

        return success_response({
            "total_count": Payment.objects.count(),
            "status_counts": status_counts,
            "total_paid_amount": str(total_paid_amount or "0"),
        })


class AdminPaymentRecentView(APIView):
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]

    def get(self, request) -> Response:
        recent = (
            Payment.objects
            .select_related("student")
            .order_by("-created_at")[:20]
        )
        return success_response({
            "total_records": recent.count(),
            "payments": AdminPaymentListSerializer(recent, many=True).data,
        })


class AdminPaymentListView(APIView):
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]

    def get(self, request) -> Response:
        from django.utils.dateparse import parse_datetime, parse_date
        from django.utils import timezone

        qs = Payment.objects.select_related("student").order_by("-created_at")

        status_filter = request.query_params.get("status")
        provider_filter = request.query_params.get("provider")
        student_id = request.query_params.get("student_id")
        semester = request.query_params.get("semester")
        transaction_id = request.query_params.get("transaction_id")
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        if status_filter:
            qs = qs.filter(status__iexact=status_filter)
        if provider_filter:
            qs = qs.filter(payment_method__iexact=provider_filter)
        if student_id:
            qs = qs.filter(student__student_id__iexact=student_id)
        if semester:
            qs = qs.filter(semester__iexact=semester)
        if transaction_id:
            qs = qs.filter(transaction_id__iexact=transaction_id)

        def _parse_dt(value: str):
            dt = parse_datetime(value) or (
                timezone.make_aware(
                    timezone.datetime.combine(parse_date(value), timezone.datetime.min.time())
                )
                if parse_date(value) else None
            )
            return dt

        if date_from:
            dt = _parse_dt(date_from)
            if not dt:
                return error_response(build_error(
                    code="INVALID_DATE_FROM",
                    message="date_from must be an ISO date or datetime.",
                    http_status=400,
                ))
            qs = qs.filter(created_at__gte=dt)

        if date_to:
            dt = _parse_dt(date_to)
            if not dt:
                return error_response(build_error(
                    code="INVALID_DATE_TO",
                    message="date_to must be an ISO date or datetime.",
                    http_status=400,
                ))
            qs = qs.filter(created_at__lte=dt)

        page = int(request.query_params.get("page", "1"))
        page_size = int(request.query_params.get("page_size", "20"))
        if page < 1 or page_size < 1 or page_size > 200:
            return error_response(build_error(
                code="INVALID_PAGINATION",
                message="page must be >=1 and page_size must be 1..200.",
                http_status=400,
            ))

        start = (page - 1) * page_size
        end = start + page_size
        total = qs.count()
        items = qs[start:end]

        return success_response({
            "total_records": total,
            "page": page,
            "page_size": page_size,
            "payments": AdminPaymentListSerializer(items, many=True).data,
        })


class AdminPaymentDetailView(APIView):
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]

    def get(self, request, transaction_id) -> Response:
        try:
            payment = (
                Payment.objects
                .select_related("student")
                .prefetch_related("audit_logs")
                .get(transaction_id=transaction_id)
            )
        except Payment.DoesNotExist:
            return error_response(build_error(
                "PAYMENT_NOT_FOUND",
                f"No payment found with transaction ID '{transaction_id}'.",
                http_status=404,
            ))
        except Exception:
            return error_response(build_error(
                "INVALID_TRANSACTION_ID",
                "The transaction ID format is invalid.",
                http_status=400,
            ))

        return success_response(AdminPaymentDetailSerializer(payment).data)


class AdminAuditLogListView(APIView):
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admin_audit_log"

    def get(self, request) -> Response:
        qs = PaymentAuditLog.objects.select_related("payment", "payment__student").order_by("-created_at")

        event_type = request.query_params.get("event_type")
        transaction_id = request.query_params.get("transaction_id")
        student_id = request.query_params.get("student_id")
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        actor = request.query_params.get("actor")

        if event_type:
            qs = qs.filter(event_type__iexact=event_type)
        if transaction_id:
            qs = qs.filter(payment__transaction_id__iexact=transaction_id)
        if student_id:
            qs = qs.filter(payment__student__student_id__iexact=student_id)
        if actor:
            qs = qs.filter(actor__iexact=actor)

        if date_from:
            from django.utils.dateparse import parse_datetime, parse_date
            from django.utils import timezone

            dt = parse_datetime(date_from) or (
                timezone.make_aware(
                    timezone.datetime.combine(parse_date(date_from), timezone.datetime.min.time())
                )
                if parse_date(date_from) else None
            )
            if not dt:
                return error_response(build_error(
                    code="INVALID_DATE_FROM",
                    message="date_from must be an ISO date or datetime.",
                    http_status=400,
                ))
            qs = qs.filter(created_at__gte=dt)

        if date_to:
            from django.utils.dateparse import parse_datetime, parse_date
            from django.utils import timezone

            dt = parse_datetime(date_to) or (
                timezone.make_aware(
                    timezone.datetime.combine(parse_date(date_to), timezone.datetime.min.time())
                )
                if parse_date(date_to) else None
            )
            if not dt:
                return error_response(build_error(
                    code="INVALID_DATE_TO",
                    message="date_to must be an ISO date or datetime.",
                    http_status=400,
                ))
            qs = qs.filter(created_at__lte=dt)

        page = int(request.query_params.get("page", "1"))
        page_size = int(request.query_params.get("page_size", "20"))
        if page < 1 or page_size < 1 or page_size > 200:
            return error_response(build_error(
                code="INVALID_PAGINATION",
                message="page must be >=1 and page_size must be 1..200.",
                http_status=400,
            ))

        start = (page - 1) * page_size
        end = start + page_size
        total = qs.count()
        items = qs[start:end]

        return success_response({
            "total_records": total,
            "page": page,
            "page_size": page_size,
            "audit_logs": PaymentAuditLogSerializer(items, many=True).data,
        })
