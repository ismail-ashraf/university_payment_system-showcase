from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from students.models import Student
from students.utils import (
    normalize_national_id,
    STUDENT_VERIFIED_AT,
    STUDENT_VERIFIED_EXPIRES,
    STUDENT_VERIFIED_FLAG,
    STUDENT_VERIFIED_ID,
)


def make_student(**kwargs) -> Student:
    defaults = {
        "student_id": "20210001",
        "name": "Ahmed Hassan",
        "email": "ahmed.hassan@university.edu.eg",
        "faculty": "Engineering",
        "academic_year": 3,
        "gpa": 3.20,
        "allowed_hours": 18,
        "status": "active",
    }
    defaults.update(kwargs)
    return Student.objects.create(**defaults)


class StudentVerificationTests(TestCase):
    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.student = make_student()
        self.student.national_id = normalize_national_id("29501011234567")
        self.student.save()
        self.verify_url = reverse("students:student-verify")
        self.status_url = reverse("students:student-verify-status")
        self.profile_url = reverse("students:student-profile", kwargs={"student_id": "20210001"})

    def _csrf_token(self):
        self.client.get(self.status_url)
        return self.client.cookies.get("csrftoken").value

    def test_verify_success_sets_session(self):
        token = self._csrf_token()
        res = self.client.post(
            self.verify_url,
            {"student_id": "20210001", "national_id": "29501011234567"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        session = self.client.session
        self.assertTrue(session.get(STUDENT_VERIFIED_FLAG))
        self.assertEqual(session.get(STUDENT_VERIFIED_ID), "20210001")
        self.assertTrue(session.get(STUDENT_VERIFIED_EXPIRES))

    def test_verify_failure_is_generic(self):
        token = self._csrf_token()
        res = self.client.post(
            self.verify_url,
            {"student_id": "20210001", "national_id": "00000000000000"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(res.data["error"]["code"], "VERIFICATION_FAILED")

    @override_settings(ABUSE_STUDENT_VERIFY_MAX=1, ABUSE_STUDENT_VERIFY_WINDOW_SECONDS=300)
    def test_verify_rate_limited(self):
        token = self._csrf_token()
        self.client.post(
            self.verify_url,
            {"student_id": "20210001", "national_id": "00000000000000"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        res = self.client.post(
            self.verify_url,
            {"student_id": "20210001", "national_id": "00000000000000"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(res.data["error"]["code"], "STUDENT_VERIFY_RATE_LIMITED")

    def test_verified_session_allows_access(self):
        session = self.client.session
        session[STUDENT_VERIFIED_FLAG] = True
        session[STUDENT_VERIFIED_ID] = "20210001"
        session[STUDENT_VERIFIED_AT] = timezone.now().isoformat()
        session[STUDENT_VERIFIED_EXPIRES] = (timezone.now() + timedelta(minutes=30)).isoformat()
        session.save()

        res = self.client.get(self.profile_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_verified_session_rejects_other_student(self):
        session = self.client.session
        session[STUDENT_VERIFIED_FLAG] = True
        session[STUDENT_VERIFIED_ID] = "20210001"
        session[STUDENT_VERIFIED_AT] = timezone.now().isoformat()
        session[STUDENT_VERIFIED_EXPIRES] = (timezone.now() + timedelta(minutes=30)).isoformat()
        session.save()

        other_url = reverse("students:student-profile", kwargs={"student_id": "20210002"})
        res = self.client.get(other_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_verified_session_expired(self):
        session = self.client.session
        session[STUDENT_VERIFIED_FLAG] = True
        session[STUDENT_VERIFIED_ID] = "20210001"
        session[STUDENT_VERIFIED_AT] = (timezone.now() - timedelta(minutes=60)).isoformat()
        session[STUDENT_VERIFIED_EXPIRES] = (timezone.now() - timedelta(minutes=1)).isoformat()
        session.save()

        res = self.client.get(self.profile_url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
