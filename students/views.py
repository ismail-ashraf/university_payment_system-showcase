from decimal import Decimal
import logging

from django.conf import settings
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework.permissions import IsAdminUser
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .models import Student
from .serializers import StudentSerializer, StudentPaymentDetailSerializer
from payments.models import Payment
from payments.serializers import PaymentResponseSerializer, StartPaymentSerializer
from payments.services.payment_service import start_payment
from payments.utils import get_student_or_error, build_error
from .utils import (
    clear_verified_session,
    get_student_for_request_or_verified,
    get_verified_session_status,
    normalize_student_id,
    set_verified_session,
    verify_national_id,
)
from auth_api.abuse_guard import (
    get_client_ip,
    is_payment_start_blocked,
    record_payment_start_attempt,
    is_student_verify_blocked,
    record_student_verify_attempt,
    clear_student_verify_attempts,
)

logger = logging.getLogger(__name__)

class StudentViewSet(viewsets.ModelViewSet):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer
    lookup_field = 'student_id'
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get all active students"""
        active_students = Student.objects.filter(status='active')
        serializer = self.get_serializer(active_students, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def payments(self, request, student_id=None):
        """Get payments for a specific student"""
        student = self.get_object()
        payments = student.payments.all()
        return Response({
            'student_id': student.student_id,
            'name': student.name,
            'payments_count': payments.count(),
        })


# ─── Response helpers ───────────────────────────────────────────────────────────

def success_response(data, http_status=status.HTTP_200_OK) -> Response:
    return Response({"success": True, "data": data}, status=http_status)


def error_response(error_dict: dict) -> Response:
    return Response(error_dict["payload"], status=error_dict["http_status"])


def verification_failed_response() -> Response:
    return error_response(build_error(
        code="VERIFICATION_FAILED",
        message="Verification failed.",
        http_status=401,
    ))


# ─── Student-Facing APIs ────────────────────────────────────────────────────────

class StudentVerifyView(APIView):
    authentication_classes = [SessionAuthentication, BasicAuthentication]

    @method_decorator(csrf_protect)
    def post(self, request) -> Response:
        student_id = normalize_student_id(request.data.get("student_id", ""))
        national_id = request.data.get("national_id", "")
        client_ip = get_client_ip(request)

        if not student_id or not national_id:
            record_student_verify_attempt(student_id, client_ip)
            return verification_failed_response()

        if is_student_verify_blocked(student_id, client_ip):
            return error_response(build_error(
                code="STUDENT_VERIFY_RATE_LIMITED",
                message="Too many verification attempts. Please wait and try again.",
                http_status=429,
            ))

        student, err = get_student_or_error(student_id)
        if err:
            logger.info(
                "student_verify_failed",
                extra={
                    "event": "student_verify_failed",
                    "request_id": getattr(request, "request_id", ""),
                    "student_id": student_id,
                    "error_code": "STUDENT_NOT_FOUND",
                },
            )
            record_student_verify_attempt(student_id, client_ip)
            return verification_failed_response()

        if not verify_national_id(national_id, student.national_id):
            logger.info(
                "student_verify_failed",
                extra={
                    "event": "student_verify_failed",
                    "request_id": getattr(request, "request_id", ""),
                    "student_id": student_id,
                    "error_code": "INVALID_NATIONAL_ID",
                },
            )
            record_student_verify_attempt(student_id, client_ip)
            return verification_failed_response()

        clear_student_verify_attempts(student_id, client_ip)
        payload = set_verified_session(
            request,
            student_id=student_id,
            ttl_seconds=getattr(settings, "STUDENT_VERIFICATION_TTL_SECONDS", 1800),
        )

        logger.info(
            "student_verify_success",
            extra={
                "event": "student_verify_success",
                "request_id": getattr(request, "request_id", ""),
                "student_id": student_id,
            },
        )
        return success_response(payload)


class StudentVerifyStatusView(APIView):
    authentication_classes = [SessionAuthentication, BasicAuthentication]

    def get(self, request) -> Response:
        get_token(request)
        status = get_verified_session_status(request)
        return success_response(
            {
                "verified": status["verified"],
                "student_id": status["student_id"],
                "expires_at": status["expires_at"],
            }
        )


class StudentVerifyLogoutView(APIView):
    authentication_classes = [SessionAuthentication, BasicAuthentication]

    @method_decorator(csrf_protect)
    def post(self, request) -> Response:
        clear_verified_session(request)
        return success_response({"message": "Logged out."})


class StudentProfileView(APIView):
    def get(self, request, student_id: str) -> Response:
        student, err = get_student_for_request_or_verified(request, student_id)
        if err:
            return error_response(err)
        return success_response(StudentSerializer(student).data)


class StudentFeesView(APIView):
    def get(self, request, student_id: str) -> Response:
        student, err = get_student_for_request_or_verified(request, student_id)
        if err:
            return error_response(err)

        is_late = str(request.query_params.get("is_late", "")).lower() in {"1", "true", "yes"}
        scholarship_raw = request.query_params.get("scholarship_pct")

        fee_per_hour = Decimal(str(getattr(settings, "FEE_PER_CREDIT_HOUR", "250")))
        fixed_fee = getattr(settings, "FIXED_SEMESTER_FEE", "500")

        base_tuition = Decimal(str(student.allowed_hours)) * fee_per_hour
        fixed_fee_amount = Decimal(str(fixed_fee))

        total = base_tuition + fixed_fee_amount
        late_penalty = Decimal("200") if is_late else Decimal("0")
        total += late_penalty

        scholarship_discount = Decimal("0")
        if scholarship_raw is not None:
            try:
                scholarship_pct = Decimal(str(scholarship_raw))
            except Exception:
                return error_response(build_error(
                    code="INVALID_SCHOLARSHIP_PCT",
                    message="scholarship_pct must be a number between 0 and 1.",
                    http_status=400,
                ))
            if scholarship_pct < 0 or scholarship_pct > 1:
                return error_response(build_error(
                    code="INVALID_SCHOLARSHIP_PCT",
                    message="scholarship_pct must be between 0 and 1.",
                    http_status=400,
                ))
            scholarship_discount = (total * scholarship_pct)
            total -= scholarship_discount

        line_items = [
            {"label": "Base Tuition", "amount": int(base_tuition)},
        ]
        if fixed_fee_amount > 0:
            line_items.append({"label": "Fixed Fee", "amount": int(fixed_fee_amount)})
        if late_penalty > 0:
            line_items.append({"label": "Late Penalty", "amount": int(late_penalty)})
        if scholarship_discount > 0:
            line_items.append({"label": "Scholarship Discount", "amount": -int(scholarship_discount)})

        return success_response({
            "student_id": student.student_id,
            "base_tuition": int(base_tuition),
            "fixed_fee": int(fixed_fee_amount),
            "late_penalty": int(late_penalty),
            "scholarship_discount": int(scholarship_discount),
            "total": int(total),
            "currency": "EGP",
            "line_items": line_items,
        })


class StudentPaymentListView(APIView):
    def get(self, request, student_id: str) -> Response:
        student, err = get_student_for_request_or_verified(request, student_id)
        if err:
            return error_response(err)

        payments = (
            Payment.objects
            .filter(student=student)
            .select_related("student")
            .order_by("-created_at")
        )

        return success_response({
            "student_id": student.student_id,
            "student_name": student.name,
            "total_records": payments.count(),
            "payments": PaymentResponseSerializer(payments, many=True).data,
        })


class StudentPaymentDetailView(APIView):
    def get(self, request, student_id: str, transaction_id) -> Response:
        student, err = get_student_for_request_or_verified(request, student_id)
        if err:
            return error_response(err)

        try:
            payment = Payment.objects.get(
                transaction_id=transaction_id,
                student=student,
            )
        except Payment.DoesNotExist:
            return error_response(build_error(
                "PAYMENT_NOT_FOUND",
                f"No payment found with transaction ID '{transaction_id}'.",
                http_status=404,
            ))

        return success_response(StudentPaymentDetailSerializer(payment).data)


class StudentPaymentStartView(APIView):
    def post(self, request, student_id: str) -> Response:
        _, err = get_student_for_request_or_verified(request, student_id)
        if err:
            return error_response(err)
        body_student_id = request.data.get("student_id")
        if body_student_id and str(body_student_id).strip().upper() != student_id.upper():
            return error_response(build_error(
                code="STUDENT_ID_MISMATCH",
                message="student_id in request body must match the URL.",
                http_status=400,
            ))
        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        data["student_id"] = student_id
        serializer = StartPaymentSerializer(data=data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Input validation failed.",
                        "details": serializer.errors,
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        provider = serializer.validated_data.get("provider") or None
        requested_amount = serializer.validated_data.get("amount")
        client_ip = get_client_ip(request)

        if is_payment_start_blocked(student_id, client_ip):
            return error_response(build_error(
                code="PAYMENT_START_RATE_LIMITED",
                message="Too many payment start attempts. Please wait and try again.",
                http_status=429,
            ))
        record_payment_start_attempt(student_id, client_ip)

        result, err = start_payment(
            student_id=student_id,
            provider=provider,
            requested_amount=requested_amount,
        )
        if err:
            return error_response(err)

        return success_response(result, http_status=status.HTTP_201_CREATED)


class StudentListCreateView(APIView):
    """
    GET: list students (paginated) with optional filters.
    POST: create student with standard envelope.
    """
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]

    def get(self, request) -> Response:
        qs = Student.objects.all().order_by("student_id")

        status_filter = request.query_params.get("status")
        faculty_filter = request.query_params.get("faculty")
        if status_filter:
            qs = qs.filter(status__iexact=status_filter)
        if faculty_filter:
            qs = qs.filter(faculty__iexact=faculty_filter)

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = StudentSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request) -> Response:
        serializer = StudentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Input validation failed.",
                        "details": serializer.errors,
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        student = serializer.save()
        return success_response(StudentSerializer(student).data, http_status=status.HTTP_201_CREATED)


class StudentDetailView(APIView):
    """
    GET/PATCH/PUT student detail with envelope.
    """
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]

    def get(self, request, student_id: str) -> Response:
        student, err = get_student_or_error(student_id)
        if err:
            return error_response(build_error(
                code="NOT_FOUND",
                message="Student not found.",
                http_status=404,
            ))
        return success_response(StudentSerializer(student).data)

    def patch(self, request, student_id: str) -> Response:
        student, err = get_student_or_error(student_id)
        if err:
            return error_response(build_error(
                code="NOT_FOUND",
                message="Student not found.",
                http_status=404,
            ))
        serializer = StudentSerializer(student, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Input validation failed.",
                        "details": serializer.errors,
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        student = serializer.save()
        return success_response(StudentSerializer(student).data)

    def put(self, request, student_id: str) -> Response:
        student, err = get_student_or_error(student_id)
        if err:
            return error_response(build_error(
                code="NOT_FOUND",
                message="Student not found.",
                http_status=404,
            ))
        serializer = StudentSerializer(student, data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Input validation failed.",
                        "details": serializer.errors,
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        student = serializer.save()
        return success_response(StudentSerializer(student).data)
