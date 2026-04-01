from typing import Tuple
from datetime import datetime, timedelta
import re

from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

from payments.utils import get_student_or_error, build_error
from .models import Student


STUDENT_VERIFIED_FLAG = "student_verified"
STUDENT_VERIFIED_ID = "student_verified_id"
STUDENT_VERIFIED_AT = "student_verified_at"
STUDENT_VERIFIED_EXPIRES = "student_verified_expires_at"


def get_student_for_request(request, student_id: str) -> Tuple[Student | None, dict | None]:
    """
    Enforce student ownership for student-facing routes.

    Rules:
      - Admin users can access any student.
      - Authenticated students can access only their own student_id.
      - Authenticated users without a linked Student are forbidden.
    """
    user = getattr(request, "user", AnonymousUser())

    if not user or not user.is_authenticated:
        return None, build_error(
            code="NOT_AUTHENTICATED",
            message="Authentication required.",
            http_status=401,
        )

    if user.is_staff or user.is_superuser:
        return get_student_or_error(student_id)

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


def normalize_student_id(value: str) -> str:
    return (value or "").strip().upper()


def normalize_national_id(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def verify_national_id(raw_value: str, stored_value: str | None) -> bool:
    if not stored_value:
        return False
    normalized = normalize_national_id(raw_value)
    if not normalized:
        return False
    return normalized == normalize_national_id(stored_value)


def clear_verified_session(request) -> None:
    session = getattr(request, "session", None)
    if session is None:
        return
    for key in [
        STUDENT_VERIFIED_FLAG,
        STUDENT_VERIFIED_ID,
        STUDENT_VERIFIED_AT,
        STUDENT_VERIFIED_EXPIRES,
    ]:
        if key in session:
            del session[key]
    session.modified = True


def set_verified_session(request, student_id: str, ttl_seconds: int) -> dict:
    now = timezone.now()
    expires_at = now + timedelta(seconds=ttl_seconds)
    session = request.session
    session[STUDENT_VERIFIED_FLAG] = True
    session[STUDENT_VERIFIED_ID] = normalize_student_id(student_id)
    session[STUDENT_VERIFIED_AT] = now.isoformat()
    session[STUDENT_VERIFIED_EXPIRES] = expires_at.isoformat()
    session.modified = True
    return {
        "student_id": session[STUDENT_VERIFIED_ID],
        "verified_until": session[STUDENT_VERIFIED_EXPIRES],
    }


def get_verified_session_status(request) -> dict:
    session = getattr(request, "session", None)
    if session is None:
        return {"verified": False, "student_id": None, "expires_at": None}

    if not session.get(STUDENT_VERIFIED_FLAG):
        return {"verified": False, "student_id": None, "expires_at": None}

    raw_expires = session.get(STUDENT_VERIFIED_EXPIRES)
    try:
        expires_at = datetime.fromisoformat(str(raw_expires))
        if timezone.is_naive(expires_at):
            expires_at = timezone.make_aware(expires_at, timezone.get_current_timezone())
    except Exception:
        clear_verified_session(request)
        return {"verified": False, "student_id": None, "expires_at": None}

    now = timezone.now()
    if expires_at <= now:
        clear_verified_session(request)
        return {"verified": False, "student_id": None, "expires_at": None}

    return {
        "verified": True,
        "student_id": session.get(STUDENT_VERIFIED_ID),
        "expires_at": raw_expires,
    }


def get_student_for_request_or_verified(
    request, student_id: str
) -> Tuple[Student | None, dict | None]:
    user = getattr(request, "user", AnonymousUser())
    if user and user.is_authenticated:
        return get_student_for_request(request, student_id)

    status = get_verified_session_status(request)
    if not status["verified"]:
        return None, build_error(
            code="NOT_AUTHENTICATED",
            message="Authentication required.",
            http_status=401,
        )

    requested_id = normalize_student_id(student_id)
    if status["student_id"] != requested_id:
        return None, build_error(
            code="FORBIDDEN",
            message="You do not have access to this student.",
            http_status=403,
        )

    return get_student_or_error(requested_id)
