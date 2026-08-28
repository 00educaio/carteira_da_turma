from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Classroom(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="classrooms",
        limit_choices_to={"is_superuser": True},
    )
    name = models.CharField(max_length=60)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="unique_classroom_per_owner")
        ]

    def __str__(self):
        return f"{self.name or 'Sem turma'} — {self.owner}"


class Student(models.Model):
    name = models.CharField(max_length=120)
    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, related_name="students")
    code = models.CharField(max_length=30, unique=True, db_index=True)
    balance = models.IntegerField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["classroom__name", "name"]

    @property
    def class_name(self):
        return self.classroom.name

    def __str__(self):
        return f"{self.name} ({self.code})"


class ClassroomAction(models.Model):
    CREDIT = "credit"
    DEBIT = "debit"
    NATURES = [
        (CREDIT, "Recompensa"),
        (DEBIT, "Despesa"),
    ]

    classroom = models.ForeignKey(
        Classroom, on_delete=models.CASCADE, related_name="actions"
    )
    name = models.CharField(max_length=120)
    nature = models.CharField(max_length=6, choices=NATURES)
    value = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    position = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField(default=True)
    default_key = models.CharField(max_length=80)

    class Meta:
        ordering = ["position", "name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["classroom", "default_key"],
                name="unique_action_key_per_classroom",
            ),
            models.CheckConstraint(
                condition=models.Q(value__gt=0),
                name="classroom_action_value_positive",
            ),
        ]

    def __str__(self):
        return f"{self.name} — {self.classroom}"


class Movement(models.Model):
    CREDIT = "credit"
    DEBIT = "debit"
    RESET = "reset"
    REVERSAL = "reversal"
    TYPES = [
        (CREDIT, "Crédito"),
        (DEBIT, "Débito"),
        (RESET, "Reset"),
        (REVERSAL, "Estorno"),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="movements")
    action = models.ForeignKey(
        ClassroomAction,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="movements",
    )
    movement_type = models.CharField(max_length=12, choices=TYPES)
    amount = models.PositiveIntegerField(default=0)
    signed_amount = models.IntegerField(default=0)
    reason = models.CharField(max_length=160)
    balance_before = models.IntegerField(default=0)
    balance_after = models.IntegerField(default=0)
    reversed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class AppSetting(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet_settings"
    )
    key = models.CharField(max_length=80)
    value = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "key"], name="unique_setting_per_owner")
        ]

    def __str__(self):
        return self.key
