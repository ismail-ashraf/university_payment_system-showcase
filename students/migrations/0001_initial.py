"""
students/migrations/0001_initial.py
Initial migration for the Student model.
"""

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Student",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("student_id", models.CharField(
                    db_index=True, help_text="University-assigned student ID (e.g. 20210001).",
                    max_length=20, unique=True,
                )),
                ("name", models.CharField(max_length=150)),
                ("email", models.EmailField(blank=True, max_length=254, null=True, unique=True)),
                ("phone", models.CharField(blank=True, max_length=20, null=True)),
                ("faculty", models.CharField(blank=True, max_length=100, null=True)),
                ("academic_year", models.PositiveSmallIntegerField(
                    blank=True, null=True,
                    help_text="Academic year (1–7 for faculties like Medicine).",
                    validators=[
                        django.core.validators.MinValueValidator(1),
                        django.core.validators.MaxValueValidator(7),
                    ],
                )),
                ("gpa", models.DecimalField(
                    decimal_places=2, max_digits=4,
                    help_text="Cumulative GPA on a 4.0 scale.",
                    validators=[
                        django.core.validators.MinValueValidator(0.0),
                        django.core.validators.MaxValueValidator(4.0),
                    ],
                )),
                ("allowed_hours", models.PositiveSmallIntegerField(
                    help_text="Credit hours the student is allowed to register this semester.",
                    validators=[
                        django.core.validators.MinValueValidator(1),
                        django.core.validators.MaxValueValidator(30),
                    ],
                )),
                ("registered_hours", models.PositiveSmallIntegerField(
                    default=0,
                    help_text="Hours actually registered (filled after registration phase).",
                    validators=[
                        django.core.validators.MinValueValidator(0),
                        django.core.validators.MaxValueValidator(30),
                    ],
                )),
                ("status", models.CharField(
                    choices=[
                        ("active",    "Active"),
                        ("inactive",  "Inactive"),
                        ("suspended", "Suspended"),
                        ("graduated", "Graduated"),
                    ],
                    default="inactive",
                    max_length=20,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "students",
                "ordering": ["student_id"],
            },
        ),
        migrations.AddIndex(
            model_name="student",
            index=models.Index(fields=["faculty", "status"], name="idx_faculty_status"),
        ),
        migrations.AddIndex(
            model_name="student",
            index=models.Index(fields=["gpa"], name="idx_gpa"),
        ),
        migrations.AddConstraint(
            model_name="student",
            constraint=models.CheckConstraint(
                condition=models.Q(allowed_hours__gte=1) & models.Q(allowed_hours__lte=30),
                name="chk_allowed_hours_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="student",
            constraint=models.CheckConstraint(
                condition=models.Q(gpa__gte=0) & models.Q(gpa__lte=4),
                name="chk_gpa_range",
            ),
        ),
    ]