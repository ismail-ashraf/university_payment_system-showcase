from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("students", "0002_add_student_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="student",
            name="national_id_hash",
            field=models.CharField(
                blank=True,
                help_text="Hashed national ID for verification (raw value not stored).",
                max_length=128,
                null=True,
            ),
        ),
    ]
