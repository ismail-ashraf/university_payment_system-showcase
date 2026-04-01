from django.test import TestCase, RequestFactory
from django.http import HttpResponse

from config.middleware import RequestIdMiddleware


class RequestIdMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _get_response(self, request):
        return HttpResponse("ok")

    def test_valid_request_id_preserved(self):
        request = self.factory.get("/", HTTP_X_REQUEST_ID="abc-123-XYZ")
        middleware = RequestIdMiddleware(self._get_response)
        response = middleware(request)
        self.assertEqual(request.request_id, "abc-123-XYZ")
        self.assertEqual(response["X-Request-ID"], "abc-123-XYZ")

    def test_invalid_request_id_replaced(self):
        request = self.factory.get("/", HTTP_X_REQUEST_ID="bad\nid")
        middleware = RequestIdMiddleware(self._get_response)
        response = middleware(request)
        self.assertNotEqual(response["X-Request-ID"], "bad\nid")
        self.assertRegex(response["X-Request-ID"], r"^[a-f0-9\\-]{36}$")

    def test_oversized_request_id_replaced(self):
        request = self.factory.get("/", HTTP_X_REQUEST_ID="a" * 200)
        middleware = RequestIdMiddleware(self._get_response)
        response = middleware(request)
        self.assertNotEqual(response["X-Request-ID"], "a" * 200)
        self.assertRegex(response["X-Request-ID"], r"^[a-f0-9\\-]{36}$")
