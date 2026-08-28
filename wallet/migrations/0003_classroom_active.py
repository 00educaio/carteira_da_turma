from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("wallet", "0002_classroom_ownership")]

    operations = [
        migrations.AddField(
            model_name="classroom",
            name="active",
            field=models.BooleanField(default=True),
        ),
    ]
