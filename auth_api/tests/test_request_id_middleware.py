from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient


class RequestIdMiddlewareTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_request_id_generated_when_missing(self):
        url = reverse("auth_api:whoami")
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertIn("X-Request-ID", res)
        self.assertTrue(res["X-Request-ID"])

    def test_request_id_echoed_when_provided(self):
        url = reverse("auth_api:whoami")
        res = self.client.get(url, HTTP_X_REQUEST_ID="req-12345")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["X-Request-ID"], "req-12345")

    def test_request_id_in_auth_log(self):
        url = reverse("auth_api:login")
        with self.assertLogs("auth_api.views", level="INFO") as cm:
            res = self.client.post(
                url,
                {"username": "nope", "password": "bad"},
                format="json",
                HTTP_X_REQUEST_ID="req-log-1",
            )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res["X-Request-ID"], "req-log-1")
        self.assertTrue(
            any(getattr(record, "request_id", "") == "req-log-1" for record in cm.records)
        )
