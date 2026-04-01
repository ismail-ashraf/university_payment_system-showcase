from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from students.models import Student
from payments.models import Payment, current_semester


def make_student(**kwargs) -> Student:
    defaults = {
        "student_id":    "20210001",
        "name":          "Ahmed Hassan",
        "email":         "ahmed.hassan@university.edu.eg",
        "faculty":       "Engineering",
        "academic_year": 3,
        "gpa":           3.20,
        "allowed_hours": 18,
        "status":        "active",
    }
    defaults.update(kwargs)
    return Student.objects.create(**defaults)


class StudentAccessControlTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="student_user", password="testpass123")
        self.other_user = get_user_model().objects.create_user(username="student_other", password="testpass123")
        self.admin = get_user_model().objects.create_user(
            username="admin_user", password="testpass123", is_staff=True
        )

        self.student = make_student(student_id="20210001", user=self.user)
        self.other_student = make_student(student_id="20210002", email="s2@u.eg", user=self.other_user)
        self.payment = Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.PAID,
        )

    def test_student_can_access_own_profile(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("students:student-profile", kwargs={"student_id": "20210001"})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])

    def test_student_cannot_access_other_student(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("students:student-profile", kwargs={"student_id": "20210002"})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data["error"]["code"], "FORBIDDEN")

    def test_admin_can_access_any_student(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse("students:student-profile", kwargs={"student_id": "20210002"})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_authenticated_user_without_student_profile_gets_403(self):
        unlinked_user = get_user_model().objects.create_user(username="no_student", password="testpass123")
        self.client.force_authenticate(user=unlinked_user)
        url = reverse("students:student-profile", kwargs={"student_id": "20210001"})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data["error"]["code"], "STUDENT_PROFILE_MISSING")

    def test_student_cannot_access_other_student_payment(self):
        self.client.force_authenticate(user=self.user)
        url = reverse(
            "students:student-payment-detail",
            kwargs={"student_id": "20210002", "transaction_id": self.payment.transaction_id},
        )
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
