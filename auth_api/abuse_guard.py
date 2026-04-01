from __future__ import annotations

from django.conf import settings
from django.core.cache import cache


def _cache_key(prefix: str, *parts: str) -> str:
    safe_parts = [p.strip().lower() for p in parts if p is not None]
    return "abuse:%s:%s" % (prefix, ":".join(safe_parts))


def _get_limit(setting_name: str, default: int) -> int:
    return int(getattr(settings, setting_name, default))


def _get_window(setting_name: str, default: int) -> int:
    return int(getattr(settings, setting_name, default))


def _is_blocked(key: str, max_attempts: int) -> bool:
    count = cache.get(key, 0)
    try:
        return int(count) >= max_attempts
    except (TypeError, ValueError):
        return False


def _increment(key: str, window_seconds: int) -> int:
    try:
        return cache.incr(key)
    except ValueError:
        cache.add(key, 1, timeout=window_seconds)
        return 1


def _reset(key: str) -> None:
    cache.delete(key)


def get_client_ip(request) -> str:
    remote_addr = request.META.get("REMOTE_ADDR", "") or ""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    trusted = set(getattr(settings, "TRUSTED_PROXY_IPS", []) or [])
    if forwarded and remote_addr in trusted:
        return forwarded.split(",")[0].strip()
    return remote_addr


def is_login_blocked(username: str, ip: str) -> bool:
    key = _cache_key("login", username or "", ip or "")
    max_attempts = _get_limit("ABUSE_LOGIN_MAX_ATTEMPTS", 5)
    return _is_blocked(key, max_attempts)


def record_login_failure(username: str, ip: str) -> None:
    key = _cache_key("login", username or "", ip or "")
    window = _get_window("ABUSE_LOGIN_WINDOW_SECONDS", 300)
    _increment(key, window)


def clear_login_failures(username: str, ip: str) -> None:
    key = _cache_key("login", username or "", ip or "")
    _reset(key)


def is_payment_start_blocked(student_id: str, ip: str) -> bool:
    key = _cache_key("start", student_id or "", ip or "")
    max_attempts = _get_limit("ABUSE_PAYMENT_START_MAX", 10)
    return _is_blocked(key, max_attempts)


def record_payment_start_attempt(student_id: str, ip: str) -> None:
    key = _cache_key("start", student_id or "", ip or "")
    window = _get_window("ABUSE_PAYMENT_START_WINDOW_SECONDS", 60)
    _increment(key, window)


def is_payment_submit_blocked(transaction_id: str, ip: str) -> bool:
    key = _cache_key("submit", transaction_id or "", ip or "")
    max_attempts = _get_limit("ABUSE_PAYMENT_SUBMIT_MAX", 10)
    return _is_blocked(key, max_attempts)


def record_payment_submit_attempt(transaction_id: str, ip: str) -> None:
    key = _cache_key("submit", transaction_id or "", ip or "")
    window = _get_window("ABUSE_PAYMENT_SUBMIT_WINDOW_SECONDS", 60)
    _increment(key, window)


def is_student_verify_blocked(student_id: str, ip: str) -> bool:
    key = _cache_key("student_verify", student_id or "", ip or "")
    max_attempts = _get_limit("ABUSE_STUDENT_VERIFY_MAX", 5)
    return _is_blocked(key, max_attempts)


def record_student_verify_attempt(student_id: str, ip: str) -> None:
    key = _cache_key("student_verify", student_id or "", ip or "")
    window = _get_window("ABUSE_STUDENT_VERIFY_WINDOW_SECONDS", 300)
    _increment(key, window)


def clear_student_verify_attempts(student_id: str, ip: str) -> None:
    key = _cache_key("student_verify", student_id or "", ip or "")
    _reset(key)
