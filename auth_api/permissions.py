from typing import Tuple
from django.contrib.auth.models import AnonymousUser
from payments.utils import build_error
from students.models import Student
from payments.models import Payment


def _get_user(request):
    return getattr(request, "user", AnonymousUser())


def is_admin_user(request) -> bool:
    user = _get_user(request)
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


def require_authenticated_user(request) -> dict | None:
    user = _get_user(request)
    if not user or not user.is_authenticated:
        return build_error(
            code="NOT_AUTHENTICATED",
            message="Authentication required.",
            http_status=401,
        )
    return None


def require_admin(request) -> dict | None:
    if not is_admin_user(request):
        return build_error(
            code="FORBIDDEN",
            message="Admin access required.",
            http_status=403,
        )
    return None


def get_student_for_request(request, student_id: str) -> Tuple[Student | None, dict | None]:
    """
    Enforce student ownership.
    - Admins can access any student.
    - Students can access only their linked student_id.
    - Authenticated users without a linked Student are denied.
    """
    auth_error = require_authenticated_user(request)
    if auth_error:
        return None, auth_error

    if is_admin_user(request):
        try:
            student = Student.objects.get(student_id=student_id.upper().strip())
            return student, None
        except Student.DoesNotExist:
            return None, build_error(
                code="STUDENT_NOT_FOUND",
                message=f"Student with ID '{student_id}' was not found.",
                http_status=404,
            )

    user = _get_user(request)
    try:
        student = user.student_profile
    except Student.DoesNotExist:
        return None, build_error(
            code="STUDENT_PROFILE_MISSING",
            message="Authenticated user has no linked student.",
            http_status=403,
        )

    if student.student_id != student_id:
        return None, build_error(
            code="FORBIDDEN",
            message="You do not have access to this student.",
            http_status=403,
        )

    return student, None


def require_payment_ownership(request, payment: Payment) -> dict | None:
    """
    Admins can access any payment.
    Students can access only payments linked to their student profile.
    """
    auth_error = require_authenticated_user(request)
    if auth_error:
        return auth_error

    if is_admin_user(request):
        return None

    user = _get_user(request)
    try:
        student = user.student_profile
    except Student.DoesNotExist:
        return build_error(
            code="STUDENT_PROFILE_MISSING",
            message="Authenticated user has no linked student.",
            http_status=403,
        )

    if payment.student_id != student.id:
        return build_error(
            code="FORBIDDEN",
            message="You do not have access to this payment.",
            http_status=403,
        )

    return None
