from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import AppSetting, Classroom, ClassroomAction, Movement, Student


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


def analytics_period(period, start=None, end=None):
    today = timezone.localdate()
    if period == "week":
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    elif period == "month":
        start_date = today.replace(day=1)
        next_month = (
            start_date.replace(year=start_date.year + 1, month=1)
            if start_date.month == 12
            else start_date.replace(month=start_date.month + 1)
        )
        end_date = next_month - timedelta(days=1)
    elif period == "all":
        return None, None
    elif period == "custom":
        if not start or not end:
            raise ValueError("Informe as datas inicial e final do intervalo.")
        try:
            start_date = date.fromisoformat(start)
            end_date = date.fromisoformat(end)
        except (TypeError, ValueError):
            raise ValueError("Informe datas válidas no formato AAAA-MM-DD.") from None
        if start_date > end_date:
            raise ValueError("A data inicial não pode ser posterior à data final.")
    else:
        raise ValueError("Período de análise inválido.")
    return start_date, end_date


def _leaders(items, field, *, highest=True, require_positive=False):
    if not items:
        return []
    target = (max if highest else min)(item[field] for item in items)
    if require_positive and target <= 0:
        return []
    return sorted(
        [item for item in items if item[field] == target],
        key=lambda item: (item["name"].casefold(), item["id"]),
    )


def build_analytics(owner, period="week", start=None, end=None, classroom_id=None):
    start_date, end_date = analytics_period(period, start, end)

    classrooms_query = Classroom.objects.filter(owner=owner, active=True)
    if classroom_id not in (None, ""):
        try:
            classroom_id = int(classroom_id)
        except (TypeError, ValueError):
            raise ValueError("Turma informada é inválida.") from None
        if classroom_id <= 0:
            raise ValueError("Turma informada é inválida.")
        classroom = classrooms_query.get(pk=classroom_id)
        classrooms_query = classrooms_query.filter(pk=classroom.pk)
    else:
        classroom_id = None

    classrooms = list(classrooms_query.order_by("name", "id"))
    classroom_ids = [classroom.id for classroom in classrooms]
    classroom_rows = [
        {"id": classroom.id, "name": classroom.name, "earned": 0, "spent": 0}
        for classroom in classrooms
    ]
    classroom_map = {item["id"]: item for item in classroom_rows}

    students = list(
        Student.objects.select_related("classroom")
        .filter(classroom_id__in=classroom_ids)
        .order_by("name", "classroom__name", "id")
    )
    student_rows = [
        {
            "id": student.id,
            "name": student.name,
            "classroom_id": student.classroom_id,
            "class_name": student.classroom.name,
            "active": student.active,
            "earned": 0,
            "spent": 0,
        }
        for student in students
    ]
    student_map = {item["id"]: item for item in student_rows}

    movements = Movement.objects.filter(
        student__classroom_id__in=classroom_ids,
        reversed=False,
        movement_type__in=[Movement.CREDIT, Movement.DEBIT],
    )
    if start_date is not None:
        current_timezone = timezone.get_current_timezone()
        start_at = timezone.make_aware(
            datetime.combine(start_date, time.min), current_timezone
        )
        end_at = timezone.make_aware(
            datetime.combine(end_date + timedelta(days=1), time.min),
            current_timezone,
        )
        movements = movements.filter(created_at__gte=start_at, created_at__lt=end_at)

    aggregates = movements.values(
        "student_id", "student__classroom_id"
    ).annotate(
        earned=Sum("amount", filter=Q(movement_type=Movement.CREDIT)),
        spent=Sum("amount", filter=Q(movement_type=Movement.DEBIT)),
    )
    for aggregate in aggregates:
        earned = aggregate["earned"] or 0
        spent = aggregate["spent"] or 0
        student_row = student_map[aggregate["student_id"]]
        classroom_row = classroom_map[aggregate["student__classroom_id"]]
        student_row["earned"] = earned
        student_row["spent"] = spent
        classroom_row["earned"] += earned
        classroom_row["spent"] += spent

    negative_students = [
        {
            "id": student.id,
            "name": student.name,
            "classroom_id": student.classroom_id,
            "class_name": student.classroom.name,
            "balance": student.balance,
        }
        for student in students
        if student.active and student.balance < 0
    ]
    negative_students.sort(
        key=lambda item: (item["name"].casefold(), item["class_name"].casefold(), item["id"])
    )

    return {
        "period": {
            "key": period,
            "start": start_date.isoformat() if start_date else None,
            "end": end_date.isoformat() if end_date else None,
        },
        "classroom_id": classroom_id,
        "totals": {
            "earned": sum(item["earned"] for item in classroom_rows),
            "spent": sum(item["spent"] for item in classroom_rows),
        },
        "classrooms": classroom_rows,
        "students": student_rows,
        "negative_students": negative_students,
        "leaders": {
            "most_spent_classrooms": _leaders(classroom_rows, "spent"),
            "least_spent_classrooms": _leaders(
                classroom_rows, "spent", highest=False
            ),
            "most_spent_students": _leaders(
                student_rows, "spent", require_positive=True
            ),
            "most_earned_students": _leaders(
                student_rows, "earned", require_positive=True
            ),
        },
    }


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
