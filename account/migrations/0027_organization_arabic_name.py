from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("account", "0026_user_password_reset"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="arabic_name",
            field=models.CharField(
                blank=True,
                help_text="Arabic name of the organization",
                max_length=255,
                null=True,
            ),
        ),
    ]
