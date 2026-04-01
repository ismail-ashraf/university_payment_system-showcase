"""
students/models.py
Student model — Phase 1 core entity.

Design decisions:
  • student_id is a CharField (university IDs are often alphanumeric like "20210001").
  • db_index=True on student_id ensures O(log n) lookups even at millions of rows.
  • allowed_hours is validated at the serializer layer AND at the DB level via a
    CheckConstraint so invalid data can never reach the table.
"""

from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator


class Student(models.Model):
    # ── Status choices ────────────────────────────────────────────────────────
    class Status(models.TextChoices):
        ACTIVE   = "active",   "Active"
        INACTIVE = "inactive", "Inactive"
        SUSPENDED = "suspended", "Suspended"
        GRADUATED = "graduated", "Graduated"

    # ── Fields ────────────────────────────────────────────────────────────────
    # Primary lookup key — indexed for fast API queries
    student_id = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        help_text="University-assigned student ID (e.g. 20210001).",
    )
    name = models.CharField(max_length=150)
    email = models.EmailField(unique=True, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    faculty = models.CharField(max_length=100, null=True, blank=True)
    academic_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(7)],
        help_text="Academic year (1–7 for faculties like Medicine).",
    )

    # Academic info
    gpa = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        validators=[MinValueValidator(0.00), MaxValueValidator(4.00)],
        help_text="Cumulative GPA on a 4.0 scale.",
    )
    allowed_hours = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(30)],
        help_text="Credit hours the student is allowed to register this semester.",
    )
    registered_hours = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(30)],
        help_text="Hours actually registered (filled after registration phase).",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.INACTIVE,
    )
    national_id = models.CharField(
        max_length=14,
        help_text="National ID (14 digits).",
        validators=[
            RegexValidator(regex=r"^\d{14}$", message="National ID must be exactly 14 digits."),
        ],
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="student_profile",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ── DB-level constraints ──────────────────────────────────────────────────
    class Meta:
        db_table = "students"
        ordering = ["student_id"]
        indexes = [
            # Composite index for common filter: faculty + status
            models.Index(fields=["faculty", "status"], name="idx_faculty_status"),
            # Index for GPA-based queries (e.g. scholarship checks)
            models.Index(fields=["gpa"], name="idx_gpa"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(allowed_hours__gte=1) & models.Q(allowed_hours__lte=30),
                name="chk_allowed_hours_range",
            ),
            models.CheckConstraint(
                condition=models.Q(gpa__gte=0) & models.Q(gpa__lte=4),
                name="chk_gpa_range",
            ),
        ]

    def __str__(self):
        return f"{self.student_id} — {self.name}"
