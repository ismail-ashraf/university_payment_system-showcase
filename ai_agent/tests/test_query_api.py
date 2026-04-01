from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from students.models import Student
from payments.models import Payment, current_semester
from django.contrib.auth import get_user_model


def make_student(**kwargs) -> Student:
    defaults = {
        "student_id":    "20210001",
        "name":          "Ahmed Hassan",
        "email":         "ahmed@uni.edu.eg",
        "faculty":       "Engineering",
        "academic_year": 3,
        "gpa":           Decimal("3.20"),
        "allowed_hours": 18,
        "status":        "active",
    }
    defaults.update(kwargs)
    return Student.objects.create(**defaults)


class AgentQueryAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/ai-agent/query/"
        User = get_user_model()
        self.user = User.objects.create_user(username="user", password="pass")
        self.other_user = User.objects.create_user(username="other", password="pass")
        self.admin = User.objects.create_user(username="admin", password="pass", is_staff=True)
        self.client.force_authenticate(user=self.user)
        self.student = make_student(user=self.user)
        self.other_student = make_student(
            student_id="20210002",
            email="other@uni.edu.eg",
            user=self.other_user,
        )
        self.payment = Payment.objects.create(
            student=self.student,
            amount=Decimal("5000.00"),
            semester=current_semester(),
            status=Payment.PaymentStatus.PAID,
        )

    def _post(self, operation, params=None):
        body = {"operation": operation}
        if params is not None:
            body["params"] = params
        return self.client.post(self.url, body, format="json")

    def test_get_payment(self):
        res = self._post("get_payment", {"transaction_id": str(self.payment.transaction_id)})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data["data"]
        self.assertEqual(data["transaction_id"], str(self.payment.transaction_id))
        self.assertNotIn("audit_logs", data)
        self.assertNotIn("payload", data)

    def test_get_payment_denied_for_other_student(self):
        self.client.force_authenticate(user=self.other_user)
        res = self._post("get_payment", {"transaction_id": str(self.payment.transaction_id)})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_get_payment_allowed(self):
        self.client.force_authenticate(user=self.admin)
        res = self._post("get_payment", {"transaction_id": str(self.payment.transaction_id)})
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_get_student(self):
        res = self._post("get_student", {"student_id": "20210001"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["data"]["student_id"], "20210001")

    def test_admin_get_student_allowed(self):
        self.client.force_authenticate(user=self.admin)
        res = self._post("get_student", {"student_id": "20210001"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["data"]["student_id"], "20210001")

    def test_get_student_denied_for_other_student(self):
        self.client.force_authenticate(user=self.user)
        res = self._post("get_student", {"student_id": "20210002"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_student_payments(self):
        res = self._post("get_student_payments", {"student_id": "20210001"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["data"]["total_records"], 1)

    def test_admin_get_student_payments_allowed(self):
        self.client.force_authenticate(user=self.admin)
        res = self._post("get_student_payments", {"student_id": "20210001"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["data"]["total_records"], 1)

    def test_get_student_payments_denied_for_other_student(self):
        self.client.force_authenticate(user=self.user)
        res = self._post("get_student_payments", {"student_id": "20210002"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_fee_breakdown(self):
        res = self._post("get_fee_breakdown", {"student_id": "20210001"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("base_tuition", res.data["data"])
        self.assertIn("line_items", res.data["data"])

    def test_admin_get_fee_breakdown_allowed(self):
        self.client.force_authenticate(user=self.admin)
        res = self._post("get_fee_breakdown", {"student_id": "20210001"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("base_tuition", res.data["data"])

    def test_get_fee_breakdown_denied_for_other_student(self):
        self.client.force_authenticate(user=self.user)
        res = self._post("get_fee_breakdown", {"student_id": "20210002"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_admin_payment_summary(self):
        res = self._post("get_admin_payment_summary", {})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data["error"]["code"], "FORBIDDEN")

    def test_admin_get_admin_payment_summary(self):
        self.client.force_authenticate(user=self.admin)
        res = self._post("get_admin_payment_summary", {})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("total_count", res.data["data"])

    def test_blocked_operation(self):
        res = self._post("cancel_payment", {"transaction_id": str(self.payment.transaction_id)})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "READ_ONLY_BLOCKED")

    def test_invalid_operation(self):
        res = self._post("unknown_operation", {})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "READ_ONLY_BLOCKED")

    def test_validation_error_missing_operation(self):
        res = self.client.post(self.url, {"params": {}}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "VALIDATION_ERROR")

    def test_validation_error_missing_param(self):
        res = self._post("get_payment", {})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "VALIDATION_ERROR")

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        res = self.client.post(self.url, {"operation": "get_student", "params": {"student_id": "20210001"}}, format="json")
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
