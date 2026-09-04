from datetime import datetime

from django.db import transaction
from django.utils import timezone

from .models import AppSetting, Classroom, ClassroomAction, Movement, Student
from .services import ensure_classroom_actions


BACKUP_VERSION = 3
INTEGER_MIN = -(2**63)
INTEGER_MAX = 2**63 - 1


def _logical_id(value, label):
    if (
        isinstance(value, bool)
        or not isinstance(value, (str, int))
        or not str(value).strip()
    ):
        raise ValueError(f"{label} has an invalid identifier.")
    return str(value)


def _integer(value, label, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be greater than or equal to {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be less than or equal to {maximum}.")
    return value


def _boolean(value, label, *, default=None):
    if value is None and default is not None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be true or false.")
    return value


def _text(value, label, max_length, *, allow_blank=False, default=None):
    if value is None and default is not None:
        value = default
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    value = value.strip()
    if not allow_blank and not value:
        raise ValueError(f"{label} cannot be blank.")
    if len(value) > max_length:
        raise ValueError(f"{label} can be at most {max_length} characters long.")
    return value


def _items(data, key, *, required=False):
    if required and key not in data:
        raise ValueError(f"The backup does not contain the '{key}' section.")
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"The '{key}' section must be a list.")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError(f"Every item in the '{key}' section must be an object.")
    return value


def _created_at(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("A transaction date must use ISO format.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("A transaction date must use ISO format.") from None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def build_backup(owner):
    classrooms = list(Classroom.objects.filter(owner=owner).order_by("name", "id"))
    students = list(
        Student.objects.select_related("classroom")
        .filter(classroom__owner=owner)
        .order_by("classroom__name", "name", "id")
    )
    movements = list(
        Movement.objects.select_related("student", "student__classroom", "action")
        .filter(student__classroom__owner=owner)
        .order_by("created_at", "id")
    )
    return {
        "version": BACKUP_VERSION,
        "exported_at": timezone.now().isoformat(),
        "classrooms": [
            {"id": classroom.id, "name": classroom.name, "active": classroom.active}
            for classroom in classrooms
        ],
        "actions": [
            {
                "id": action.id,
                "classroom_id": action.classroom_id,
                "name": action.name,
                "nature": action.nature,
                "value": action.value,
                "position": action.position,
                "active": action.active,
                "default_key": action.default_key,
            }
            for action in ClassroomAction.objects.filter(classroom__owner=owner).order_by(
                "classroom__name", "position", "name", "id"
            )
        ],
        "students": [
            {
                "id": student.id,
                "name": student.name,
                "classroom_id": student.classroom_id,
                "class_name": student.classroom.name,
                "code": student.code,
                "balance": student.balance,
                "active": student.active,
            }
            for student in students
        ],
        "movements": [
            {
                "id": movement.id,
                "student_id": movement.student_id,
                "action_id": movement.action_id,
                "movement_type": movement.movement_type,
                "amount": movement.amount,
                "signed_amount": movement.signed_amount,
                "reason": movement.reason,
                "balance_before": movement.balance_before,
                "balance_after": movement.balance_after,
                "reversed": movement.reversed,
                "created_at": timezone.localtime(movement.created_at).isoformat(),
            }
            for movement in movements
        ],
        "settings": {
            setting.key: setting.value
            for setting in AppSetting.objects.filter(owner=owner).order_by("key")
        },
    }


def validate_backup(data, owner):
    if not isinstance(data, dict):
        raise ValueError("The backup contents must be a JSON object.")
    version = data.get("version", 2)
    if isinstance(version, bool) or not isinstance(version, int) or version not in (2, 3):
        raise ValueError("Unsupported backup version. Use a v2 or v3 file.")

    classrooms_data = _items(data, "classrooms", required=version == 3)
    actions_data = _items(data, "actions", required=version == 3)
    students_data = _items(data, "students", required=True)
    movements_data = _items(data, "movements", required=True)
    settings_data = data.get("settings", {})
    if not isinstance(settings_data, dict):
        raise ValueError("The 'settings' section must be an object.")

    classrooms = []
    classroom_keys = set()
    classroom_names = set()
    for index, item in enumerate(classrooms_data, start=1):
        name = _text(
            item.get("name"), f"Classroom name {index}", 60, allow_blank=True, default=""
        )
        if name in classroom_names:
            raise ValueError(f"Classroom '{name or 'No classroom'}' is duplicated in the backup.")
        key = (
            _logical_id(item.get("id"), f"Classroom {index}")
            if version == 3
            else name
        )
        if key in classroom_keys:
            raise ValueError("The backup contains duplicate classroom identifiers.")
        classroom_names.add(name)
        classroom_keys.add(key)
        classrooms.append(
            {
                "key": key,
                "name": name,
                "active": _boolean(
                    item.get("active"), f"Classroom status {name or index}", default=True
                ),
            }
        )

    actions = []
    action_keys = set()
    action_default_keys = set()
    if version == 3:
        for index, item in enumerate(actions_data, start=1):
            key = _logical_id(item.get("id"), f"Action {index}")
            classroom_key = _logical_id(
                item.get("classroom_id"), f"Classroom for action {index}"
            )
            if key in action_keys:
                raise ValueError("The backup contains duplicate action identifiers.")
            if classroom_key not in classroom_keys:
                raise ValueError(f"Action {index} references a classroom that does not exist.")
            default_key = _text(
                item.get("default_key"), f"Stable identifier for action {index}", 80
            )
            unique_default = (classroom_key, default_key)
            if unique_default in action_default_keys:
                raise ValueError("Actions in the same classroom have duplicate stable identifiers.")
            nature = item.get("nature")
            if nature not in {ClassroomAction.CREDIT, ClassroomAction.DEBIT}:
                raise ValueError(f"Action {index} has an invalid type.")
            action_keys.add(key)
            action_default_keys.add(unique_default)
            actions.append(
                {
                    "key": key,
                    "classroom_key": classroom_key,
                    "name": _text(item.get("name"), f"Action name {index}", 120),
                    "nature": nature,
                    "value": _integer(
                        item.get("value"),
                        f"Value for action {index}",
                        minimum=1,
                        maximum=INTEGER_MAX,
                    ),
                    "position": _integer(
                        item.get("position", 0),
                        f"Position for action {index}",
                        minimum=0,
                        maximum=32767,
                    ),
                    "active": _boolean(
                        item.get("active"), f"Status for action {index}", default=True
                    ),
                    "default_key": default_key,
                }
            )

    students = []
    student_keys = set()
    student_codes = set()
    for index, item in enumerate(students_data, start=1):
        key = _logical_id(item.get("id"), f"Student {index}")
        if key in student_keys:
            raise ValueError("The backup contains duplicate student identifiers.")
        if version == 3:
            classroom_key = _logical_id(
                item.get("classroom_id"), f"Classroom for student {index}"
            )
            if classroom_key not in classroom_keys:
                raise ValueError(f"Student {index} references a classroom that does not exist.")
        else:
            classroom_key = _text(
                item.get("class_name"),
                f"Classroom for student {index}",
                60,
                allow_blank=True,
                default="",
            )
            if classroom_key not in classroom_keys:
                classroom_keys.add(classroom_key)
                classroom_names.add(classroom_key)
                classrooms.append(
                    {"key": classroom_key, "name": classroom_key, "active": True}
                )
        code = _text(item.get("code"), f"Student code {index}", 30)
        if code in student_codes:
            raise ValueError(f"Student code '{code}' is duplicated in the backup.")
        student_keys.add(key)
        student_codes.add(code)
        students.append(
            {
                "key": key,
                "classroom_key": classroom_key,
                "name": _text(item.get("name"), f"Student name {index}", 120),
                "code": code,
                "balance": _integer(
                    item.get("balance", 0),
                    f"Balance for student {index}",
                    minimum=INTEGER_MIN,
                    maximum=INTEGER_MAX,
                ),
                "active": _boolean(
                    item.get("active"), f"Status for student {index}", default=True
                ),
            }
        )

    conflicting_codes = set(
        Student.objects.filter(code__in=student_codes)
        .exclude(classroom__owner=owner)
        .values_list("code", flat=True)
    )
    if conflicting_codes:
        code = sorted(conflicting_codes)[0]
        raise ValueError(f"Student code '{code}' already belongs to another user.")

    action_classrooms = {item["key"]: item["classroom_key"] for item in actions}
    student_classrooms = {item["key"]: item["classroom_key"] for item in students}
    movements = []
    movement_keys = set()
    valid_movement_types = {choice[0] for choice in Movement.TYPES}
    for index, item in enumerate(movements_data, start=1):
        raw_key = item.get("id", f"movement-{index}")
        key = _logical_id(raw_key, f"Transaction {index}")
        if key in movement_keys:
            raise ValueError("The backup contains duplicate transaction identifiers.")
        student_key = _logical_id(
            item.get("student_id"), f"Student for transaction {index}"
        )
        if student_key not in student_keys:
            raise ValueError(f"Transaction {index} references a student that does not exist.")
        movement_type = item.get("movement_type", Movement.CREDIT)
        if movement_type not in valid_movement_types:
            raise ValueError(f"Transaction {index} has an invalid type.")
        action_key = None
        if version == 3 and item.get("action_id") is not None:
            action_key = _logical_id(
                item.get("action_id"), f"Action for transaction {index}"
            )
            if action_key not in action_keys:
                raise ValueError(f"Transaction {index} references an action that does not exist.")
            if action_classrooms[action_key] != student_classrooms[student_key]:
                raise ValueError(
                    f"The action for transaction {index} belongs to another classroom."
                )
        movement_keys.add(key)
        movements.append(
            {
                "student_key": student_key,
                "action_key": action_key,
                "movement_type": movement_type,
                "amount": _integer(
                    item.get("amount", 0),
                    f"Value for transaction {index}",
                    minimum=0,
                    maximum=INTEGER_MAX,
                ),
                "signed_amount": _integer(
                    item.get("signed_amount", 0),
                    f"Signed value for transaction {index}",
                    minimum=INTEGER_MIN,
                    maximum=INTEGER_MAX,
                ),
                "reason": _text(
                    item.get("reason"),
                    f"Reason for transaction {index}",
                    160,
                    default="Restored transaction",
                ),
                "balance_before": _integer(
                    item.get("balance_before", 0),
                    f"Previous balance for transaction {index}",
                    minimum=INTEGER_MIN,
                    maximum=INTEGER_MAX,
                ),
                "balance_after": _integer(
                    item.get("balance_after", 0),
                    f"New balance for transaction {index}",
                    minimum=INTEGER_MIN,
                    maximum=INTEGER_MAX,
                ),
                "reversed": _boolean(
                    item.get("reversed"),
                    f"Status for transaction {index}",
                    default=False,
                ),
                "created_at": _created_at(item.get("created_at")),
            }
        )

    settings = []
    setting_keys = set()
    for key, value in settings_data.items():
        normalized_key = _text(key, "Settings key", 80)
        if normalized_key in setting_keys:
            raise ValueError("The backup contains duplicate settings keys.")
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            raise ValueError(f"Setting '{normalized_key}' has an invalid value.")
        setting_keys.add(normalized_key)
        settings.append((normalized_key, str(value if value is not None else "")))

    return {
        "version": version,
        "classrooms": classrooms,
        "actions": actions,
        "students": students,
        "movements": movements,
        "settings": settings,
    }


@transaction.atomic
def restore_backup(owner, backup):
    Movement.objects.filter(student__classroom__owner=owner).delete()
    Student.objects.filter(classroom__owner=owner).delete()
    Classroom.objects.filter(owner=owner).delete()
    AppSetting.objects.filter(owner=owner).delete()

    classroom_map = {}
    for item in backup["classrooms"]:
        classroom = Classroom.objects.create(
            owner=owner, name=item["name"], active=item["active"]
        )
        classroom_map[item["key"]] = classroom
        if backup["version"] == 2:
            ensure_classroom_actions(classroom)

    action_map = {}
    for item in backup["actions"]:
        action_map[item["key"]] = ClassroomAction.objects.create(
            classroom=classroom_map[item["classroom_key"]],
            name=item["name"],
            nature=item["nature"],
            value=item["value"],
            position=item["position"],
            active=item["active"],
            default_key=item["default_key"],
        )

    student_map = {}
    for item in backup["students"]:
        student_map[item["key"]] = Student.objects.create(
            name=item["name"],
            classroom=classroom_map[item["classroom_key"]],
            code=item["code"],
            balance=item["balance"],
            active=item["active"],
        )

    for item in backup["movements"]:
        movement = Movement.objects.create(
            student=student_map[item["student_key"]],
            action=action_map.get(item["action_key"]),
            movement_type=item["movement_type"],
            amount=item["amount"],
            signed_amount=item["signed_amount"],
            reason=item["reason"],
            balance_before=item["balance_before"],
            balance_after=item["balance_after"],
            reversed=item["reversed"],
        )
        if item["created_at"] is not None:
            Movement.objects.filter(pk=movement.pk).update(
                created_at=item["created_at"]
            )

    AppSetting.objects.bulk_create(
        [AppSetting(owner=owner, key=key, value=value) for key, value in backup["settings"]]
    )
    return len(backup["students"])
