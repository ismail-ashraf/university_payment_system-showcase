"""

Financial Agent API View.

Single endpoint: POST /ai-agent/chat/

Request:
    Auth:     Session-based (authenticated user)
    Body:     {"message": "What is my current balance?"}

Responses:
    200 OK:
        {
            "success": true,
            "response": "Your current balance is 1,200 EGP.",
            "intent": "balance"
        }

    400 Bad Request (validation error or write attempt):
        {
            "success": false,
            "error": "This assistant cannot perform payments. Read-only access."
        }

    401 Unauthorized (not authenticated):
        {
            "success": false,
            "error": "Authentication required."
        }

    500 Internal Server Error:
        {
            "success": false,
            "error": "An unexpected error occurred. Please try again."
        }

Security:
    - Requires authenticated session user
    - Write-intent requests rejected before any tool is called
"""

from __future__ import annotations

import logging

from rest_framework.decorators import api_view, throttle_classes
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.exceptions import Throttled
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status

from .services import chat_with_agent
from .serializers import AgentQuerySerializer
from payments.utils import build_error, get_student_or_error
from auth_api.permissions import (
    is_admin_user,
    get_student_for_request,
    require_payment_ownership,
)
from payments.models import Payment
from payments.serializers import PaymentResponseSerializer
from students.serializers import StudentSerializer
from students.models import Student
from students.utils import get_verified_session_status
from decimal import Decimal
from django.conf import settings
from django.db.models import Count, Sum

logger = logging.getLogger(__name__)

ALLOWED_OPERATIONS = {
    "get_payment",
    "get_student",
    "get_student_payments",
    "get_fee_breakdown",
    "get_admin_payment_summary",
}

MAX_CONTEXT_MESSAGES = 15
MAX_CONTEXT_MESSAGE_LENGTH = 500
MAX_CONTEXT_TOTAL_CHARS = 4000


def _sanitize_context_messages(raw_messages, latest_message: str) -> list[dict[str, str]]:
    if not isinstance(raw_messages, list):
        return []

    sanitized: list[dict[str, str]] = []
    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"}:
            continue
        if not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue
        if len(content) > MAX_CONTEXT_MESSAGE_LENGTH:
            content = content[:MAX_CONTEXT_MESSAGE_LENGTH]
        sanitized.append({"role": role, "content": content})

    if len(sanitized) > MAX_CONTEXT_MESSAGES:
        sanitized = sanitized[-MAX_CONTEXT_MESSAGES:]

    if sanitized and latest_message:
        last = sanitized[-1]
        if last["role"] == "user" and last["content"] == latest_message:
            sanitized = sanitized[:-1]

    total = sum(len(item["content"]) for item in sanitized)
    while sanitized and total > MAX_CONTEXT_TOTAL_CHARS:
        removed = sanitized.pop(0)
        total -= len(removed["content"])

    return sanitized

class ChatScopedRateThrottle(ScopedRateThrottle):
    scope = "ai_agent_chat"

    def get_rate(self):
        from django.conf import settings
        rates = getattr(settings, "REST_FRAMEWORK", {}).get("DEFAULT_THROTTLE_RATES", {})
        return rates.get(self.scope)

    def get_cache_key(self, request, view):
        if getattr(request, "user", None) and request.user.is_authenticated:
            ident = f"user-{request.user.pk}"
        else:
            ident = self.get_ident(request) or "unknown"
        return self.cache_format % {"scope": self.scope, "ident": ident}

    def allow_request(self, request, view):
        rate = self.get_rate()
        if rate is None:
            setattr(request, "_ai_chat_throttle_checked", True)
            setattr(request, "_ai_chat_throttle_allowed", True)
            return True

        self.num_requests, self.duration = self.parse_rate(rate)
        key = self.get_cache_key(request, view)
        if not key:
            setattr(request, "_ai_chat_throttle_checked", True)
            setattr(request, "_ai_chat_throttle_allowed", True)
            return True

        self.history = self.cache.get(key, [])
        now = self.timer()
        self.history = [ts for ts in self.history if ts > now - self.duration]

        if len(self.history) >= self.num_requests:
            setattr(request, "_ai_chat_throttle_checked", True)
            setattr(request, "_ai_chat_throttle_allowed", False)
            return True

        self.history.insert(0, now)
        self.cache.set(key, self.history, self.duration)
        setattr(request, "_ai_chat_throttle_checked", True)
        setattr(request, "_ai_chat_throttle_allowed", True)
        return True

def _success(data, http_status=status.HTTP_200_OK) -> Response:
    return Response({"success": True, "data": data}, status=http_status)


def _error(code: str, message: str, details: dict | None = None, http_status: int = 400) -> Response:
    return Response(build_error(code, message, details or {}, http_status)["payload"], status=http_status)


def _safe_payment_detail(payment: Payment) -> dict:
    return {
        "transaction_id": payment.transaction_id_str,
        "student_id": payment.student.student_id,
        "student_name": payment.student.name,
        "amount": str(payment.amount),
        "status": payment.status,
        "payment_method": payment.payment_method,
        "semester": payment.semester,
        "gateway_reference": payment.gateway_reference,
        "created_at": payment.created_at.isoformat(),
        "updated_at": payment.updated_at.isoformat(),
        "expires_at": payment.expires_at.isoformat() if payment.expires_at else None,
    }


class QueryView(APIView):
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_agent_query"
    """
    POST /api/ai-agent/query/
    Read-only AI agent operations.
    """
    def post(self, request: Request) -> Response:
        serializer = AgentQuerySerializer(data=request.data)
        if not serializer.is_valid():
            return _error(
                code="VALIDATION_ERROR",
                message="Input validation failed.",
                details=serializer.errors,
                http_status=400,
            )

        operation = serializer.validated_data["operation"]
        params = serializer.validated_data.get("params") or {}

        if operation not in ALLOWED_OPERATIONS:
            logger.info(
                "ai_agent_query_blocked",
                extra={
                    "event": "ai_agent_query_blocked",
                    "request_id": getattr(request, "request_id", ""),
                    "operation": operation,
                    "user": getattr(request.user, "username", ""),
                },
            )
            return _error(
                code="READ_ONLY_BLOCKED",
                message="This AI agent is read-only and cannot perform write actions.",
                details={"requested_operation": operation, "allowed_operations": sorted(ALLOWED_OPERATIONS)},
                http_status=400,
            )

        logger.info(
            "ai_agent_query_received",
            extra={
                "event": "ai_agent_query_received",
                "request_id": getattr(request, "request_id", ""),
                "operation": operation,
                "user": getattr(request.user, "username", ""),
            },
        )

        if operation == "get_payment":
            txn_id = params.get("transaction_id")
            if not txn_id:
                return _error("VALIDATION_ERROR", "transaction_id is required.", http_status=400)
            try:
                payment = Payment.objects.select_related("student").get(transaction_id=txn_id)
            except Payment.DoesNotExist:
                return _error("PAYMENT_NOT_FOUND", f"No payment found with transaction ID '{txn_id}'.", http_status=404)
            except Exception:
                return _error("INVALID_TRANSACTION_ID", "The transaction ID format is invalid.", http_status=400)
            auth_err = require_payment_ownership(request, payment)
            if auth_err:
                return _error(auth_err["payload"]["error"]["code"], auth_err["payload"]["error"]["message"], http_status=auth_err["http_status"])
            logger.info(
                "ai_agent_query_success",
                extra={
                    "event": "ai_agent_query_success",
                    "request_id": getattr(request, "request_id", ""),
                    "operation": operation,
                    "user": getattr(request.user, "username", ""),
                },
            )
            return _success(_safe_payment_detail(payment))

        if operation == "get_student":
            student_id = params.get("student_id")
            if not student_id:
                return _error("VALIDATION_ERROR", "student_id is required.", http_status=400)
            student, err = get_student_for_request(request, student_id)
            if err:
                return _error(err["payload"]["error"]["code"], err["payload"]["error"]["message"], http_status=err["http_status"])
            logger.info(
                "ai_agent_query_success",
                extra={
                    "event": "ai_agent_query_success",
                    "request_id": getattr(request, "request_id", ""),
                    "operation": operation,
                    "user": getattr(request.user, "username", ""),
                },
            )
            return _success(StudentSerializer(student).data)

        if operation == "get_student_payments":
            student_id = params.get("student_id")
            if not student_id:
                return _error("VALIDATION_ERROR", "student_id is required.", http_status=400)
            student, err = get_student_for_request(request, student_id)
            if err:
                return _error(err["payload"]["error"]["code"], err["payload"]["error"]["message"], http_status=err["http_status"])
            payments = (
                Payment.objects
                .filter(student=student)
                .select_related("student")
                .order_by("-created_at")
            )
            logger.info(
                "ai_agent_query_success",
                extra={
                    "event": "ai_agent_query_success",
                    "request_id": getattr(request, "request_id", ""),
                    "operation": operation,
                    "user": getattr(request.user, "username", ""),
                },
            )
            return _success({
                "student_id": student.student_id,
                "student_name": student.name,
                "total_records": payments.count(),
                "payments": PaymentResponseSerializer(payments, many=True).data,
            })

        if operation == "get_fee_breakdown":
            student_id = params.get("student_id")
            if not student_id:
                return _error("VALIDATION_ERROR", "student_id is required.", http_status=400)
            student, err = get_student_for_request(request, student_id)
            if err:
                return _error(err["payload"]["error"]["code"], err["payload"]["error"]["message"], http_status=err["http_status"])

            fee_per_hour = Decimal(str(getattr(settings, "FEE_PER_CREDIT_HOUR", "250")))
            fixed_fee = Decimal(str(getattr(settings, "FIXED_SEMESTER_FEE", "500")))

            base_tuition = Decimal(str(student.allowed_hours)) * fee_per_hour
            total = base_tuition + fixed_fee

            logger.info(
                "ai_agent_query_success",
                extra={
                    "event": "ai_agent_query_success",
                    "request_id": getattr(request, "request_id", ""),
                    "operation": operation,
                    "user": getattr(request.user, "username", ""),
                },
            )
            return _success({
                "student_id": student.student_id,
                "base_tuition": int(base_tuition),
                "fixed_fee": int(fixed_fee),
                "total": int(total),
                "currency": "EGP",
                "line_items": [
                    {"label": "Base Tuition", "amount": int(base_tuition)},
                    {"label": "Fixed Fee", "amount": int(fixed_fee)},
                ],
            })

        if operation == "get_admin_payment_summary":
            if not is_admin_user(request):
                return _error("FORBIDDEN", "Admin access required.", http_status=403)
            status_counts = {
                row["status"]: row["count"]
                for row in Payment.objects.values("status").annotate(count=Count("transaction_id"))
            }
            total_paid_amount = (
                Payment.objects.filter(status=Payment.PaymentStatus.PAID)
                .aggregate(total=Sum("amount"))
                .get("total")
            )
            logger.info(
                "ai_agent_query_success",
                extra={
                    "event": "ai_agent_query_success",
                    "request_id": getattr(request, "request_id", ""),
                    "operation": operation,
                    "user": getattr(request.user, "username", ""),
                },
            )
            return _success({
                "total_count": Payment.objects.count(),
                "status_counts": status_counts,
                "total_paid_amount": str(total_paid_amount or "0"),
            })

        logger.info(
            "ai_agent_query_success",
            extra={
                "event": "ai_agent_query_success",
                "request_id": getattr(request, "request_id", ""),
                "operation": operation,
                "user": getattr(request.user, "username", ""),
            },
        )
        return _error("INVALID_OPERATION", "Operation not supported.", http_status=400)


query_view = QueryView.as_view()



# ── Chat view ──────────────────────────────────────────────────────────────────

@api_view(["POST"])
@throttle_classes([ChatScopedRateThrottle])
def chat_view(request: Request) -> Response:
    """
    POST /ai-agent/chat/

    Accepts a student's natural-language financial query and returns
    a clear, helpful response powered by LLaMA 3 (via Groq).

    The view:
      1. Validates Content-Type and request body
      2. Uses authenticated session user for access control
      3. Delegates all logic to services.chat_with_agent()
      4. Maps service results to HTTP responses
    """
    user = getattr(request, "user", None)
    if not getattr(request, "_ai_chat_throttle_checked", False):
        ChatScopedRateThrottle().allow_request(request, chat_view)
    if getattr(request, "_ai_chat_throttle_allowed", True) is False:
        return Response(
            {"success": False, "error": "Too many requests. Please try again later."},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    verified_session = None
    if not user or not user.is_authenticated:
        verified_session = get_verified_session_status(request)
        if not verified_session["verified"]:
            return Response(
                {"success": False, "error": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

    student_id = None
    if user and user.is_authenticated and not is_admin_user(request):
        try:
            student_id = user.student_profile.student_id
        except Student.DoesNotExist:
            return Response(
                {"success": False, "error": "Authenticated user has no linked student."},
                status=status.HTTP_403_FORBIDDEN,
            )
    elif verified_session and verified_session["verified"]:
        student_id = verified_session["student_id"]

    # ── Body validation ────────────────────────────────────────────────────────
    if not request.data:
        return Response(
            {
                "success": False,
                "error":   "Request body is required. Send JSON with a 'message' field.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    message = request.data.get("message")
    if not message:
        return Response(
            {
                "success": False,
                "error":   "'message' field is required and cannot be empty.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not isinstance(message, str):
        return Response(
            {
                "success": False,
                "error":   "'message' must be a string.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    context_messages = _sanitize_context_messages(
        request.data.get("messages"),
        message,
    )

    # ── Delegate to service ────────────────────────────────────────────────────
    try:
        # Use a server-derived placeholder so client token is never forwarded.
        result = chat_with_agent(
            message=message,
            token="session-authenticated",
            context_messages=context_messages,
            student_id=student_id,
        )
    except Exception:
        logger.exception("Unhandled error in chat_view")
        return Response(
            {
                "success": False,
                "error":   "An unexpected error occurred. Please try again.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # ── Map service result to HTTP response ────────────────────────────────────
    if not result["success"]:
        error_msg = result.get("error", "An error occurred.")

        # Write-attempt → 400
        if result.get("intent") == "write_blocked":
            return Response(
                {"success": False, "error": error_msg},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if result.get("error_code") == "AI_UNAVAILABLE":
            return Response(
                {"success": False, "error": error_msg},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if result.get("error_code") == "AI_PROVIDER_ERROR":
            return Response(
                {"success": False, "error": error_msg},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Auth-related errors from tools → 401
        auth_keywords = ("expired", "invalid", "token", "log in")
        if any(kw in error_msg.lower() for kw in auth_keywords):
            return Response(
                {"success": False, "error": error_msg},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # All other service errors → 400
        return Response(
            {"success": False, "error": error_msg},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Success
    return Response(
        {
            "success":  True,
            "response": result["response"],
            "intent":   result["intent"],
        },
        status=status.HTTP_200_OK,
    )

# Ensure throttle classes are attached to the wrapped APIView as well.
chat_view.throttle_classes = [ChatScopedRateThrottle]
if hasattr(chat_view, "cls"):
    chat_view.cls.throttle_classes = [ChatScopedRateThrottle]
