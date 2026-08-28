from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def assign_legacy_data(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Classroom = apps.get_model("wallet", "Classroom")
    Student = apps.get_model("wallet", "Student")
    AppSetting = apps.get_model("wallet", "AppSetting")

    owner = User.objects.filter(is_superuser=True).order_by("id").first()
    if owner is None:
        owner = User.objects.order_by("id").first()
    if owner is None:
        owner = User.objects.create(
            username="legacy-owner",
            password="!",
            is_active=False,
            is_staff=True,
            is_superuser=True,
        )

    classrooms = {}
    for student in Student.objects.all().order_by("id"):
        name = student.class_name.strip()
        classroom = classrooms.get(name)
        if classroom is None:
            classroom, _ = Classroom.objects.get_or_create(owner_id=owner.id, name=name)
            classrooms[name] = classroom
        student.classroom_id = classroom.id
        student.save(update_fields=["classroom"])

    AppSetting.objects.filter(owner__isnull=True).update(owner_id=owner.id)


def restore_class_names(apps, schema_editor):
    Student = apps.get_model("wallet", "Student")
    for student in Student.objects.select_related("classroom"):
        student.class_name = student.classroom.name if student.classroom_id else ""
        student.save(update_fields=["class_name"])


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("wallet", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Classroom",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=60)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "owner",
                    models.ForeignKey(
                        limit_choices_to={"is_superuser": True},
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="classrooms",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="classroom",
            constraint=models.UniqueConstraint(
                fields=("owner", "name"), name="unique_classroom_per_owner"
            ),
        ),
        migrations.AddField(
            model_name="student",
            name="classroom",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="students",
                to="wallet.classroom",
            ),
        ),
        migrations.AddField(
            model_name="appsetting",
            name="owner",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="wallet_settings",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="appsetting",
            name="key",
            field=models.CharField(max_length=80),
        ),
        migrations.RunPython(assign_legacy_data, restore_class_names),
        migrations.RemoveField(model_name="student", name="class_name"),
        migrations.AlterField(
            model_name="student",
            name="classroom",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="students",
                to="wallet.classroom",
            ),
        ),
        migrations.AlterField(
            model_name="appsetting",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="wallet_settings",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="appsetting",
            constraint=models.UniqueConstraint(
                fields=("owner", "key"), name="unique_setting_per_owner"
            ),
        ),
        migrations.AlterModelOptions(
            name="student", options={"ordering": ["classroom__name", "name"]}
        ),
    ]
