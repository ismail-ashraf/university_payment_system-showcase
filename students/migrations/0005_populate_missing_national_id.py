import re

from django.db import migrations


def _build_fake_national_id(student) -> str:
    digits = re.sub(r"\D", "", student.student_id or "")
    base = f"{digits}{student.pk}"
    return f"9{base}"


def populate_missing_national_ids(apps, schema_editor):
    Student = apps.get_model("students", "Student")
    to_update = []
    for student in Student.objects.all():
        if student.national_id:
            continue
        student.national_id = _build_fake_national_id(student)
        to_update.append(student)
    if to_update:
        Student.objects.bulk_update(to_update, ["national_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("students", "0004_replace_national_id_hash"),
    ]

    operations = [
        migrations.RunPython(populate_missing_national_ids, migrations.RunPython.noop),
    ]
