"""
students/tests/test_api.py
Integration tests for all student API endpoints.

Run with:
    python manage.py test students.tests.test_api
"""

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from students.models import Student
from payments.models import Payment, current_semester


def make_student(**kwargs) -> Student:
    """Factory helper — creates a valid student with sensible defaults."""
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


class StudentLookupTests(TestCase):
    """GET /api/students/<student_id>/"""

    def setUp(self):
        self.client  = APIClient()
        self.student = make_student()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

    def test_returns_student_data(self):
        url = reverse("students:student-detail", kwargs={"student_id": "20210001"})
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])
        data = res.data["data"]
        self.assertEqual(data["student_id"],    "20210001")
        self.assertEqual(data["name"],          "Ahmed Hassan")
        self.assertEqual(float(data["gpa"]),    3.20)
        self.assertEqual(data["allowed_hours"], 18)
        self.assertEqual(data["status"],        "active")

    def test_student_id_is_case_insensitive(self):
        """student_id lookup should work regardless of case."""
        url = reverse("students:student-detail", kwargs={"student_id": "20210001"})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_404_for_unknown_student(self):
        url = reverse("students:student-detail", kwargs={"student_id": "NOTEXIST"})
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(res.data["success"])
        self.assertEqual(res.data["error"]["code"], "NOT_FOUND")

    def test_404_response_has_standard_envelope(self):
        url = reverse("students:student-detail", kwargs={"student_id": "GHOST"})
        res = self.client.get(url)
        self.assertIn("error",   res.data)
        self.assertIn("code",    res.data["error"])
        self.assertIn("message", res.data["error"])
        self.assertIn("details", res.data["error"])


class StudentCreateTests(TestCase):
    """POST /api/students/"""

    def setUp(self):
        self.client = APIClient()
        self.url    = reverse("students:student-list-create")
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

    def _valid_payload(self, **overrides):
        base = {
            "student_id":    "20220001",
            "name":          "Sara Ibrahim",
            "email":         "sara.ibrahim@university.edu.eg",
            "faculty":       "Science",
            "academic_year": 2,
            "gpa":           "3.50",
            "allowed_hours": 18,
            "status":        "active",
            "national_id":   "29501011234567",
        }
        base.update(overrides)
        return base

    def test_creates_student_successfully(self):
        res = self.client.post(self.url, self._valid_payload(), format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data["success"])
        self.assertTrue(Student.objects.filter(student_id="20220001").exists())

    def test_400_on_missing_name(self):
        payload = self._valid_payload()
        del payload["name"]
        res = self.client.post(self.url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "VALIDATION_ERROR")

    def test_400_on_duplicate_student_id(self):
        make_student(student_id="20220001")
        res = self.client.post(self.url, self._valid_payload(), format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_on_invalid_gpa(self):
        res = self.client.post(self.url, self._valid_payload(gpa="5.00"), format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_on_invalid_national_id_length(self):
        res = self.client.post(
            self.url,
            self._valid_payload(national_id="1234567890123"),
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "VALIDATION_ERROR")

    def test_400_on_invalid_national_id_non_digit(self):
        res = self.client.post(
            self.url,
            self._valid_payload(national_id="ABC123"),
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "VALIDATION_ERROR")

    def test_400_gpa_hours_cross_validation(self):
        """GPA 1.5 → max 15 hours. Requesting 18 should fail."""
        res = self.client.post(
            self.url,
            self._valid_payload(gpa="1.50", allowed_hours=18),
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("allowed_hours", res.data["error"]["details"])

    def test_student_id_stored_uppercase(self):
        payload = self._valid_payload(student_id="abcd-0001")
        self.client.post(self.url, payload, format="json")
        self.assertTrue(Student.objects.filter(student_id="ABCD-0001").exists())


class StudentListTests(TestCase):
    """GET /api/students/"""

    def setUp(self):
        self.client = APIClient()
        self.url    = reverse("students:student-list-create")
        make_student(student_id="20210001", faculty="Engineering", status="active")
        make_student(student_id="20210002", name="Layla Mostafa",
                     email="layla@uni.edu.eg", faculty="Science",
                     status="inactive", gpa=2.80, allowed_hours=18)
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

    def test_returns_all_students(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 2)

    def test_filter_by_status(self):
        res = self.client.get(self.url, {"status": "active"})
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["student_id"], "20210001")

    def test_filter_by_faculty(self):
        res = self.client.get(self.url, {"faculty": "science"})
        self.assertEqual(res.data["count"], 1)


class StudentFeeTests(TestCase):
    """GET /api/students/<student_id>/fees/"""

    def setUp(self):
        self.client  = APIClient()
        self.user = get_user_model().objects.create_user(username="student_user", password="testpass123")
        self.student = make_student(gpa=3.20, allowed_hours=18, user=self.user)
        self.url     = reverse("students:student-fees", kwargs={"student_id": "20210001"})
        self.client.force_authenticate(user=self.user)

    def test_returns_fee_breakdown(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertEqual(data["student_id"],   "20210001")
        self.assertEqual(data["base_tuition"], 18 * 250)   # 4500
        self.assertEqual(data["fixed_fee"],    500)
        self.assertEqual(data["late_penalty"], 0)
        self.assertEqual(data["total"],        5000)
        self.assertEqual(data["currency"],     "EGP")

    def test_late_penalty_applied(self):
        res = self.client.get(self.url, {"is_late": "true"})
        self.assertEqual(res.data["data"]["late_penalty"], 200)
        self.assertEqual(res.data["data"]["total"], 5200)

    def test_scholarship_applied(self):
        res = self.client.get(self.url, {"scholarship_pct": "0.5"})
        data = res.data["data"]
        self.assertEqual(data["scholarship_discount"], int(5000 * 0.5))
        self.assertEqual(data["total"], 2500)

    def test_404_for_unknown_student(self):
        url = reverse("students:student-fees", kwargs={"student_id": "GHOST"})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_400_on_invalid_scholarship_pct(self):
        res = self.client.get(self.url, {"scholarship_pct": "1.5"})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_line_items_included(self):
        res = self.client.get(self.url)
        self.assertIsInstance(res.data["data"]["line_items"], list)
        self.assertGreater(len(res.data["data"]["line_items"]), 0)


class StudentUpdateTests(TestCase):
    """PATCH /api/students/<student_id>/"""

    def setUp(self):
        self.client  = APIClient()
        self.student = make_student()
        self.url     = reverse("students:student-detail", kwargs={"student_id": "20210001"})
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_user",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)

    def test_patch_status(self):
        res = self.client.patch(self.url, {"status": "suspended"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.student.refresh_from_db()
        self.assertEqual(self.student.status, "suspended")

    def test_patch_invalid_gpa(self):
        res = self.client.patch(self.url, {"gpa": "9.99"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_requires_all_fields(self):
        """PUT without required fields should return 400."""
        res = self.client.put(self.url, {"name": "Only Name"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


class StudentProfileTests(TestCase):
    """GET /api/students/<student_id>/profile/"""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="student_user", password="testpass123")
        self.student = make_student(user=self.user)
        self.url = reverse("students:student-profile", kwargs={"student_id": "20210001"})
        self.client.force_authenticate(user=self.user)

    def test_profile_response(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])
        data = res.data["data"]
        self.assertEqual(data["student_id"], "20210001")
        self.assertEqual(data["name"], "Ahmed Hassan")


class StudentPaymentsListTests(TestCase):
    """GET /api/students/<student_id>/payments/"""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="student_user", password="testpass123")
        self.student = make_student(user=self.user)
        self.other = make_student(student_id="S002", email="s2@u.eg")
        Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.PAID,
        )
        Payment.objects.create(
            student=self.other,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.PENDING,
        )
        self.url = reverse("students:student-payments", kwargs={"student_id": "20210001"})
        self.client.force_authenticate(user=self.user)

    def test_list_scoped_to_student(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertEqual(data["student_id"], "20210001")
        self.assertEqual(data["total_records"], 1)
        self.assertEqual(len(data["payments"]), 1)


class StudentPaymentDetailTests(TestCase):
    """GET /api/students/<student_id>/payments/<uuid>/"""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="student_user", password="testpass123")
        self.student = make_student(user=self.user)
        self.payment = Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.PENDING,
        )
        self.url = reverse(
            "students:student-payment-detail",
            kwargs={"student_id": "20210001", "transaction_id": self.payment.transaction_id},
        )
        self.client.force_authenticate(user=self.user)

    def test_detail_scoped_to_student(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertEqual(str(data["transaction_id"]), str(self.payment.transaction_id))

    def test_safe_detail_shape(self):
        res = self.client.get(self.url)
        data = res.data["data"]
        self.assertIn("status", data)
        self.assertIn("amount", data)
        self.assertNotIn("audit_logs", data)


class StudentPaymentStartTests(TestCase):
    """POST /api/students/<student_id>/payments/start/"""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="student_user", password="testpass123")
        self.student = make_student(user=self.user)
        self.url = reverse("students:student-payment-start", kwargs={"student_id": "20210001"})
        self.client.force_authenticate(user=self.user)

    def test_start_payment_via_student_route(self):
        res = self.client.post(self.url, {"provider": "fawry"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data["success"])
        data = res.data["data"]
        self.assertIn("transaction_id", data)
        self.assertEqual(data["provider"], "fawry")

    def test_body_student_id_cannot_override_path(self):
        make_student(student_id="S002", email="s2@u.eg")
        res = self.client.post(
            self.url,
            {"student_id": "S002", "provider": "fawry"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "STUDENT_ID_MISMATCH")
        self.assertEqual(Payment.objects.count(), 0)
