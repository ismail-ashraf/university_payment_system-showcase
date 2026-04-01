from __future__ import annotations

import uuid


class RequestIdMiddleware:
    """
    Attach a request ID to each request and echo it in the response.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.META.get("HTTP_X_REQUEST_ID", "").strip()
        if not self._is_valid_request_id(request_id):
            request_id = str(uuid.uuid4())

        request.request_id = request_id
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        return response

    @staticmethod
    def _is_valid_request_id(value: str) -> bool:
        """
        Accept only bounded, safe request IDs to avoid header/log injection.
        """
        if not value:
            return False
        if len(value) > 64:
            return False
        for ch in value:
            if not (ch.isalnum() or ch == "-"):
                return False
        return True
