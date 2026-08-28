from django.db import transaction
from django.utils import timezone

from .models import AppSetting, Movement, Student


def current_week_key():
    today = timezone.localdate()
    iso_year, iso_week, _ = today.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


@transaction.atomic
def ensure_weekly_reset(owner):
    week_key = current_week_key()
    setting, _ = AppSetting.objects.select_for_update().get_or_create(
        owner=owner, key="last_reset_week", defaults={"value": week_key}
    )
    if setting.value == week_key:
        return False

    students = list(
        Student.objects.select_for_update()
        .filter(classroom__owner=owner, classroom__active=True, active=True)
        .exclude(balance=0)
    )
    movements = []
    for student in students:
        before = student.balance
        student.balance = 0
        movements.append(
            Movement(
                student=student,
                movement_type=Movement.RESET,
                amount=abs(before),
                signed_amount=-before,
                reason="Reset semanal automático",
                balance_before=before,
                balance_after=0,
            )
        )

    if students:
        Student.objects.bulk_update(students, ["balance"])
        Movement.objects.bulk_create(movements)

    setting.value = week_key
    setting.save(update_fields=["value"])
    return True


@transaction.atomic
def apply_movement(owner, student_id, movement_type, amount, reason):
    student = Student.objects.select_for_update().get(
        pk=student_id, classroom__owner=owner, classroom__active=True, active=True
    )
    amount = int(amount)
    if amount <= 0:
        raise ValueError("O valor precisa ser maior que zero.")

    if movement_type == Movement.CREDIT:
        signed_amount = amount
    elif movement_type == Movement.DEBIT:
        signed_amount = -amount
    else:
        raise ValueError("Tipo de movimentação inválido.")

    before = student.balance
    after = before + signed_amount
    if after < 0:
        raise ValueError("Saldo insuficiente.")

    student.balance = after
    student.save(update_fields=["balance"])
    movement = Movement.objects.create(
        student=student,
        movement_type=movement_type,
        amount=amount,
        signed_amount=signed_amount,
        reason=reason.strip() or "Movimentação",
        balance_before=before,
        balance_after=after,
    )
    return student, movement


@transaction.atomic
def undo_movement(owner, movement_id):
    movement = (
        Movement.objects.select_for_update()
        .select_related("student")
        .get(
            pk=movement_id,
            student__classroom__owner=owner,
            student__classroom__active=True,
        )
    )
    if movement.reversed:
        raise ValueError("Esta movimentação já foi desfeita.")
    if movement.movement_type in {Movement.RESET, Movement.REVERSAL}:
        raise ValueError("Esta movimentação não pode ser desfeita.")

    student = Student.objects.select_for_update().get(pk=movement.student_id)
    reversal = -movement.signed_amount
    after = student.balance + reversal
    if after < 0:
        raise ValueError("Não é possível desfazer porque o saldo ficaria negativo.")

    before = student.balance
    student.balance = after
    student.save(update_fields=["balance"])
    movement.reversed = True
    movement.save(update_fields=["reversed"])

    Movement.objects.create(
        student=student,
        movement_type=Movement.REVERSAL,
        amount=abs(reversal),
        signed_amount=reversal,
        reason=f"Estorno: {movement.reason}",
        balance_before=before,
        balance_after=after,
    )
    return student
