from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AppSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=80, unique=True)),
                ("value", models.TextField(blank=True)),
            ],
        ),
        migrations.CreateModel(
            name="Student",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("class_name", models.CharField(blank=True, max_length=60)),
                ("code", models.CharField(db_index=True, max_length=30, unique=True)),
                ("balance", models.IntegerField(default=0)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["class_name", "name"]},
        ),
        migrations.CreateModel(
            name="Movement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("movement_type", models.CharField(choices=[("credit", "Crédito"), ("debit", "Débito"), ("reset", "Reset"), ("reversal", "Estorno")], max_length=12)),
                ("amount", models.PositiveIntegerField(default=0)),
                ("signed_amount", models.IntegerField(default=0)),
                ("reason", models.CharField(max_length=160)),
                ("balance_before", models.IntegerField(default=0)),
                ("balance_after", models.IntegerField(default=0)),
                ("reversed", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="movements", to="wallet.student")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
    ]
