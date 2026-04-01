from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("students", "0003_add_national_id_hash"),
    ]

    operations = [
        migrations.AddField(
            model_name="student",
            name="national_id",
            field=models.CharField(
                blank=True,
                help_text="National ID (normalized digits only).",
                max_length=32,
                null=True,
            ),
        ),
        migrations.RemoveField(
            model_name="student",
            name="national_id_hash",
        ),
    ]
