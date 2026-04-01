from django.test import TestCase

from students.admin import StudentAdminForm
from students.utils import normalize_national_id


class StudentAdminNationalIdTests(TestCase):
    def test_national_id_accepts_14_digits(self):
        form = StudentAdminForm(
            data={
                "student_id": "20210001",
                "name": "Ahmed Hassan",
                "gpa": "3.20",
                "allowed_hours": 18,
                "registered_hours": 0,
                "status": "active",
                "national_id": "29501011234567",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        student = form.save()
        self.assertTrue(student.national_id)
        self.assertEqual(student.national_id, normalize_national_id("29501011234567"))

    def test_national_id_rejects_non_digits(self):
        form = StudentAdminForm(
            data={
                "student_id": "20210001",
                "name": "Ahmed Hassan",
                "gpa": "3.20",
                "allowed_hours": 18,
                "registered_hours": 0,
                "status": "active",
                "national_id": "ABC-123",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("national_id", form.errors)

    def test_national_id_rejects_wrong_length(self):
        form = StudentAdminForm(
            data={
                "student_id": "20210001",
                "name": "Ahmed Hassan",
                "gpa": "3.20",
                "allowed_hours": 18,
                "registered_hours": 0,
                "status": "active",
                "national_id": "1234567890123",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("national_id", form.errors)

    def test_academic_year_rejects_float(self):
        form = StudentAdminForm(
            data={
                "student_id": "20210001",
                "name": "Ahmed Hassan",
                "gpa": "3.20",
                "allowed_hours": 18,
                "registered_hours": 0,
                "status": "active",
                "academic_year": "2.0",
                "national_id": "29501011234567",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("academic_year", form.errors)
