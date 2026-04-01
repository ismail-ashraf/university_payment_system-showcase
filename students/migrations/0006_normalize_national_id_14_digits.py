import re

from django.core.validators import RegexValidator
from django.db import migrations, models


def _is_valid(national_id: str | None) -> bool:
    if not national_id:
        return False
    return re.fullmatch(r"\d{14}", national_id) is not None


def _build_14_digit_id(student) -> str:
    student_digits = re.sub(r"\D", "", student.student_id or "")
    prefix = (student_digits + "0" * 8)[:8]
    suffix = f"{student.pk:06d}"[-6:]
    return f"{prefix}{suffix}"


def normalize_national_ids(apps, schema_editor):
    Student = apps.get_model("students", "Student")
    to_update = []
    for student in Student.objects.all():
        if _is_valid(student.national_id):
            continue
        student.national_id = _build_14_digit_id(student)
        to_update.append(student)
    if to_update:
        Student.objects.bulk_update(to_update, ["national_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("students", "0005_populate_missing_national_id"),
    ]

    operations = [
        migrations.RunPython(normalize_national_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="student",
            name="national_id",
            field=models.CharField(
                max_length=14,
                help_text="National ID (14 digits).",
                validators=[
                    RegexValidator(regex=r"^\d{14}$", message="National ID must be exactly 14 digits."),
                ],
            ),
        ),
    ]
