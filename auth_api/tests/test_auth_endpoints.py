from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.test import APIClient
from django.core.cache import cache

from students.models import Student


class AuthEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username="student_user",
            password="testpass123",
        )
        self.student = Student.objects.create(
            student_id="20210001",
            name="Ahmed Hassan",
            email="ahmed.hassan@university.edu.eg",
            faculty="Engineering",
            academic_year=3,
            gpa=3.2,
            allowed_hours=18,
            status="active",
            user=self.user,
        )
        cache.clear()

    def test_login_success(self):
        url = reverse("auth_api:login")
        res = self.client.post(url, {"username": "student_user", "password": "testpass123"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])
        self.assertTrue(res.data["data"]["is_authenticated"])
        self.assertEqual(res.data["data"]["student_id"], "20210001")

    def test_login_failure(self):
        url = reverse("auth_api:login")
        res = self.client.post(url, {"username": "student_user", "password": "bad"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(res.data["success"])
        self.assertEqual(res.data["error"]["code"], "INVALID_CREDENTIALS")
        response_text = str(res.data).lower()
        self.assertNotIn("bad", response_text)
        self.assertNotIn("token", response_text)
        self.assertNotIn("secret", response_text)

    def test_login_without_csrf_token(self):
        csrf_client = APIClient(enforce_csrf_checks=True)
        url = reverse("auth_api:login")
        res = csrf_client.post(
            url,
            {"username": "student_user", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_login_with_valid_csrf_token(self):
        csrf_client = APIClient(enforce_csrf_checks=True)
        whoami_url = reverse("auth_api:whoami")
        resp = csrf_client.get(whoami_url)
        token = get_token(resp.wsgi_request)
        csrf_client.cookies["csrftoken"] = token
        url = reverse("auth_api:login")
        res = csrf_client.post(
            url,
            {"username": "student_user", "password": "testpass123"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    @override_settings(ABUSE_LOGIN_MAX_ATTEMPTS=1, ABUSE_LOGIN_WINDOW_SECONDS=300)
    def test_login_cooldown_blocks_with_429(self):
        url = reverse("auth_api:login")
        self.client.post(url, {"username": "student_user", "password": "bad"}, format="json")
        res = self.client.post(url, {"username": "student_user", "password": "testpass123"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(res.data["error"]["code"], "LOGIN_COOLDOWN_ACTIVE")

    @override_settings(ABUSE_LOGIN_MAX_ATTEMPTS=2, ABUSE_LOGIN_WINDOW_SECONDS=300)
    def test_login_success_clears_cooldown_counter(self):
        url = reverse("auth_api:login")
        self.client.post(url, {"username": "student_user", "password": "bad"}, format="json")
        res = self.client.post(url, {"username": "student_user", "password": "testpass123"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        res2 = self.client.post(url, {"username": "student_user", "password": "bad"}, format="json")
        self.assertEqual(res2.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("auth_api:logout")
        res = self.client.post(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])

    def test_whoami_authenticated(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("auth_api:whoami")
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])
        self.assertTrue(res.data["data"]["is_authenticated"])
        self.assertEqual(res.data["data"]["student_id"], "20210001")

    def test_whoami_unauthenticated(self):
        url = reverse("auth_api:whoami")
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])
        self.assertFalse(res.data["data"]["is_authenticated"])
