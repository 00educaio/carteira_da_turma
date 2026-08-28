from django.db import transaction
from django.utils import timezone

from .models import AppSetting, ClassroomAction, Movement, Student


DEFAULT_CLASSROOM_ACTIONS = (
    ("good-behavior", "Bom comportamento", ClassroomAction.CREDIT),
    ("organized-classroom", "Organizou a sala", ClassroomAction.CREDIT),
    ("helped-classmate", "Ajudou um colega", ClassroomAction.CREDIT),
    ("finished-activity", "Terminou a atividade", ClassroomAction.CREDIT),
    ("handwriting-practice", "Fazer caligrafia", ClassroomAction.CREDIT),
    ("bathroom", "Ir ao banheiro", ClassroomAction.DEBIT),
    ("drink-water", "Beber água", ClassroomAction.DEBIT),
    ("sheet-of-paper", "Folha de papel", ClassroomAction.DEBIT),
    ("indiscipline", "Indisciplina", ClassroomAction.DEBIT),
    ("lost-card-replacement", "Reposição de cartão perdido", ClassroomAction.DEBIT),
)


@transaction.atomic
def ensure_classroom_actions(classroom):
    """Create only the missing default actions without changing existing settings."""
    existing_keys = set(classroom.actions.values_list("default_key", flat=True))
    missing = [
        ClassroomAction(
            classroom=classroom,
            default_key=default_key,
            name=name,
            nature=nature,
            value=1,
            position=position,
        )
        for position, (default_key, name, nature) in enumerate(
            DEFAULT_CLASSROOM_ACTIONS, start=1
        )
        if default_key not in existing_keys
    ]
    if missing:
        ClassroomAction.objects.bulk_create(missing, ignore_conflicts=True)
    return classroom.actions.all()


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
def apply_movement(owner, student_id, action_id):
    student = Student.objects.select_for_update().get(
        pk=student_id, classroom__owner=owner, classroom__active=True, active=True
    )
    if isinstance(action_id, bool) or not (
        isinstance(action_id, int)
        or (isinstance(action_id, str) and action_id.strip().isdigit())
    ):
        raise ValueError("Selecione uma ação válida.")
    action_id = int(action_id)
    if action_id <= 0:
        raise ValueError("Selecione uma ação válida.")
    try:
        action = ClassroomAction.objects.select_for_update().get(pk=action_id)
    except ClassroomAction.DoesNotExist:
        raise ValueError("Selecione uma ação válida.") from None
    if action.classroom_id != student.classroom_id or not action.active:
        raise ValueError("Esta ação não está disponível para este aluno.")

    amount = action.value
    if action.nature == ClassroomAction.CREDIT:
        signed_amount = amount
    elif action.nature == ClassroomAction.DEBIT:
        signed_amount = -amount
    else:
        raise ValueError("A natureza desta ação é inválida.")

    before = student.balance
    after = before + signed_amount

    student.balance = after
    student.save(update_fields=["balance"])
    movement = Movement.objects.create(
        student=student,
        action=action,
        movement_type=action.nature,
        amount=amount,
        signed_amount=signed_amount,
        reason=action.name,
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
