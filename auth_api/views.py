from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
import logging
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from payments.utils import build_error
from .abuse_guard import (
    get_client_ip,
    is_login_blocked,
    record_login_failure,
    clear_login_failures,
)


def success_response(data, http_status=status.HTTP_200_OK) -> Response:
    return Response({"success": True, "data": data}, status=http_status)


def error_response(code: str, message: str, http_status: int) -> Response:
    return Response(
        {"success": False, "error": {"code": code, "message": message}},
        status=http_status,
    )


class LoginView(APIView):
    """
    POST /api/auth/login/
    Session-based login using Django auth.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_login"

    @method_decorator(csrf_protect)
    def post(self, request) -> Response:
        username = request.data.get("username")
        password = request.data.get("password")
        client_ip = get_client_ip(request)

        if not username or not password:
            return error_response(
                "VALIDATION_ERROR",
                "username and password are required.",
                status.HTTP_400_BAD_REQUEST,
            )

        if is_login_blocked(username, client_ip):
            return Response(
                build_error(
                    code="LOGIN_COOLDOWN_ACTIVE",
                    message="Too many failed login attempts. Please wait and try again.",
                    http_status=429,
                )["payload"],
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        user = authenticate(request, username=username, password=password)
        if user is None or not user.is_active:
            logger.info(
                "auth_login_failed",
                extra={
                    "event": "auth_login_failed",
                    "request_id": getattr(request, "request_id", ""),
                    "user_id": "",
                    "error_code": "INVALID_CREDENTIALS",
                },
            )
            record_login_failure(username, client_ip)
            return error_response(
                "INVALID_CREDENTIALS",
                "Invalid username or password.",
                status.HTTP_401_UNAUTHORIZED,
            )

        login(request, user)
        clear_login_failures(username, client_ip)
        student_id = getattr(getattr(user, "student_profile", None), "student_id", None)

        return success_response(
            {
                "is_authenticated": True,
                "is_admin": bool(user.is_staff or user.is_superuser),
                "student_id": student_id,
                "username": user.get_username(),
            }
        )


class LogoutView(APIView):
    """
    POST /api/auth/logout/
    """

    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request) -> Response:
        logout(request)
        return success_response({"message": "Logged out."})


class WhoAmIView(APIView):
    """
    GET /api/auth/whoami/
    """

    authentication_classes = [SessionAuthentication, BasicAuthentication]

    def get(self, request) -> Response:
        user = request.user
        if not user or not user.is_authenticated:
            return success_response(
                {
                    "is_authenticated": False,
                    "is_admin": False,
                    "student_id": None,
                }
            )

        student_id = getattr(getattr(user, "student_profile", None), "student_id", None)
        return success_response(
            {
                "is_authenticated": True,
                "is_admin": bool(user.is_staff or user.is_superuser),
                "student_id": student_id,
            }
        )
logger = logging.getLogger(__name__)
