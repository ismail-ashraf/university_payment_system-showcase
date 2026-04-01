"""

Financial Agent Tools — read-only wrappers around the existing payment system API.

Each function:
  • Accepts a validated JWT token string
  • Calls the relevant internal endpoint via requests
  • Returns a structured dict: {"ok": bool, "data": ..., "error": ...}
  • Never raises — all errors are caught and surfaced in the return dict

Available tools:
  get_balance(token)      → student balance from /api/balance/
  get_transactions(token) → recent transactions from /api/transactions/
  get_fees(token, student_id) → fee summary from /api/students/<student_id>/fees/

Design notes:
  - BASE_URL is read from Django settings so it works in all environments
  - Timeout of 10s per request prevents agent hanging
  - All HTTP errors and network errors are caught
  - Token is passed as Bearer in Authorization header — never logged
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────

# Internal base URL — can be overridden via settings for test environments
_BASE_URL: str = getattr(settings, "AGENT_API_BASE_URL", "http://localhost:8000")
_TIMEOUT: int  = getattr(settings, "AGENT_API_TIMEOUT", 10)


# ── Private helpers ────────────────────────────────────────────────────────────

def _auth_headers(token: str) -> dict[str, str]:
    """Build Authorization header dict from a raw JWT token string."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def _safe_get(url: str, token: str, tool_name: str) -> dict[str, Any]:
    """
    Execute an authenticated GET request and return a normalised result dict.

    Returns:
        {"ok": True,  "data": <response_json>}           on success
        {"ok": False, "error": <human-readable message>}  on any failure
    """
    try:
        response = requests.get(
            url,
            headers=_auth_headers(token),
            timeout=_TIMEOUT,
        )
    except requests.exceptions.ConnectionError:
        logger.error("[%s] Connection refused — is the server running at %s?", tool_name, _BASE_URL)
        return {
            "ok":    False,
            "error": "Could not connect to the payment system. Please try again later.",
        }
    except requests.exceptions.Timeout:
        logger.error("[%s] Request timed out after %ds", tool_name, _TIMEOUT)
        return {
            "ok":    False,
            "error": "The payment system took too long to respond. Please try again.",
        }
    except requests.exceptions.RequestException as exc:
        logger.exception("[%s] Unexpected network error: %s", tool_name, exc)
        return {
            "ok":    False,
            "error": "A network error occurred while fetching your data.",
        }

    # HTTP-level errors
    if response.status_code == 401:
        return {
            "ok":    False,
            "error": "Your session has expired or the token is invalid. Please log in again.",
        }
    if response.status_code == 403:
        return {
            "ok":    False,
            "error": "You do not have permission to access this resource.",
        }
    if response.status_code == 404:
        return {
            "ok":    False,
            "error": "The requested resource was not found.",
        }
    if response.status_code >= 500:
        logger.error("[%s] Server error %d from %s", tool_name, response.status_code, url)
        return {
            "ok":    False,
            "error": "The payment system encountered an internal error. Please try again later.",
        }
    if not response.ok:
        return {
            "ok":    False,
            "error": f"Unexpected response from the payment system (HTTP {response.status_code}).",
        }

    # Parse JSON
    try:
        data = response.json()
    except ValueError:
        logger.error("[%s] Non-JSON response body from %s", tool_name, url)
        return {
            "ok":    False,
            "error": "The payment system returned an unreadable response.",
        }

    return {"ok": True, "data": data}


# ── Public tool functions ──────────────────────────────────────────────────────

def get_balance(token: str) -> dict[str, Any]:
    """
    Fetch the authenticated student's current balance.

    Args:
        token: Raw JWT string (without 'Bearer ' prefix).

    Returns:
        {"ok": True,  "data": {"balance": ..., "currency": "EGP", ...}}
        {"ok": False, "error": "<human-readable message>"}
    """
    if not token or not isinstance(token, str):
        return {"ok": False, "error": "A valid authentication token is required."}

    url = f"{_BASE_URL.rstrip('/')}/api/balance/"
    result = _safe_get(url, token, tool_name="get_balance")
    logger.info("[get_balance] ok=%s", result["ok"])
    return result


def get_transactions(token: str, limit: int = 10) -> dict[str, Any]:
    """
    Fetch the authenticated student's recent payment transactions.

    Args:
        token: Raw JWT string.
        limit: Maximum number of transactions to return (default 10, max 50).

    Returns:
        {"ok": True,  "data": {"transactions": [...], "total": ...}}
        {"ok": False, "error": "<human-readable message>"}
    """
    if not token or not isinstance(token, str):
        return {"ok": False, "error": "A valid authentication token is required."}

    # Clamp limit to a safe range
    safe_limit = max(1, min(int(limit), 50))
    url = f"{_BASE_URL.rstrip('/')}/api/transactions/?limit={safe_limit}"
    result = _safe_get(url, token, tool_name="get_transactions")
    logger.info("[get_transactions] ok=%s limit=%d", result["ok"], safe_limit)
    return result


def get_fees(token: str, student_id: str | None = None) -> dict[str, Any]:
    """
    Fetch the authenticated student's fee summary for the current semester.

    Args:
        token: Raw JWT string.
        student_id: Student ID for the fee lookup route.

    Returns:
        {"ok": True,  "data": {"total_fees": ..., "paid": ..., "remaining": ..., ...}}
        {"ok": False, "error": "<human-readable message>"}
    """
    if not token or not isinstance(token, str):
        return {"ok": False, "error": "A valid authentication token is required."}

    if not student_id:
        return {"ok": False, "error": "student_id is required for fee lookup."}

    safe_student_id = str(student_id).strip()
    url = f"{_BASE_URL.rstrip('/')}/api/students/{safe_student_id}/fees/"
    result = _safe_get(url, token, tool_name="get_fees")
    logger.info("[get_fees] ok=%s", result["ok"])
    return result
