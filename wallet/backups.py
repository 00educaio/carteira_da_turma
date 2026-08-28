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
        raise ValueError(f"{label} possui identificador inválido.")
    return str(value)


def _integer(value, label, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} deve ser um número inteiro.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} deve ser maior ou igual a {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} deve ser menor ou igual a {maximum}.")
    return value


def _boolean(value, label, *, default=None):
    if value is None and default is not None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{label} deve ser verdadeiro ou falso.")
    return value


def _text(value, label, max_length, *, allow_blank=False, default=None):
    if value is None and default is not None:
        value = default
    if not isinstance(value, str):
        raise ValueError(f"{label} deve ser um texto.")
    value = value.strip()
    if not allow_blank and not value:
        raise ValueError(f"{label} não pode ficar vazio.")
    if len(value) > max_length:
        raise ValueError(f"{label} pode ter no máximo {max_length} caracteres.")
    return value


def _items(data, key, *, required=False):
    if required and key not in data:
        raise ValueError(f"O backup não contém a seção '{key}'.")
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"A seção '{key}' deve ser uma lista.")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError(f"Todos os itens da seção '{key}' devem ser objetos.")
    return value


def _created_at(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("A data de uma movimentação deve estar no formato ISO.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("A data de uma movimentação deve estar no formato ISO.") from None
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
        raise ValueError("O conteúdo do backup deve ser um objeto JSON.")
    version = data.get("version", 2)
    if isinstance(version, bool) or not isinstance(version, int) or version not in (2, 3):
        raise ValueError("Versão de backup não suportada. Use um arquivo v2 ou v3.")

    classrooms_data = _items(data, "classrooms", required=version == 3)
    actions_data = _items(data, "actions", required=version == 3)
    students_data = _items(data, "students", required=True)
    movements_data = _items(data, "movements", required=True)
    settings_data = data.get("settings", {})
    if not isinstance(settings_data, dict):
        raise ValueError("A seção 'settings' deve ser um objeto.")

    classrooms = []
    classroom_keys = set()
    classroom_names = set()
    for index, item in enumerate(classrooms_data, start=1):
        name = _text(
            item.get("name"), f"Nome da turma {index}", 60, allow_blank=True, default=""
        )
        if name in classroom_names:
            raise ValueError(f"A turma '{name or 'Sem turma'}' está duplicada no backup.")
        key = (
            _logical_id(item.get("id"), f"Turma {index}")
            if version == 3
            else name
        )
        if key in classroom_keys:
            raise ValueError("Há identificadores de turma duplicados no backup.")
        classroom_names.add(name)
        classroom_keys.add(key)
        classrooms.append(
            {
                "key": key,
                "name": name,
                "active": _boolean(
                    item.get("active"), f"Status da turma {name or index}", default=True
                ),
            }
        )

    actions = []
    action_keys = set()
    action_default_keys = set()
    if version == 3:
        for index, item in enumerate(actions_data, start=1):
            key = _logical_id(item.get("id"), f"Ação {index}")
            classroom_key = _logical_id(
                item.get("classroom_id"), f"Turma da ação {index}"
            )
            if key in action_keys:
                raise ValueError("Há identificadores de ação duplicados no backup.")
            if classroom_key not in classroom_keys:
                raise ValueError(f"A ação {index} referencia uma turma inexistente.")
            default_key = _text(
                item.get("default_key"), f"Identificador estável da ação {index}", 80
            )
            unique_default = (classroom_key, default_key)
            if unique_default in action_default_keys:
                raise ValueError("Há ações com identificador estável duplicado na mesma turma.")
            nature = item.get("nature")
            if nature not in {ClassroomAction.CREDIT, ClassroomAction.DEBIT}:
                raise ValueError(f"A ação {index} possui natureza inválida.")
            action_keys.add(key)
            action_default_keys.add(unique_default)
            actions.append(
                {
                    "key": key,
                    "classroom_key": classroom_key,
                    "name": _text(item.get("name"), f"Nome da ação {index}", 120),
                    "nature": nature,
                    "value": _integer(
                        item.get("value"),
                        f"Valor da ação {index}",
                        minimum=1,
                        maximum=INTEGER_MAX,
                    ),
                    "position": _integer(
                        item.get("position", 0),
                        f"Posição da ação {index}",
                        minimum=0,
                        maximum=32767,
                    ),
                    "active": _boolean(
                        item.get("active"), f"Status da ação {index}", default=True
                    ),
                    "default_key": default_key,
                }
            )

    students = []
    student_keys = set()
    student_codes = set()
    for index, item in enumerate(students_data, start=1):
        key = _logical_id(item.get("id"), f"Aluno {index}")
        if key in student_keys:
            raise ValueError("Há identificadores de aluno duplicados no backup.")
        if version == 3:
            classroom_key = _logical_id(
                item.get("classroom_id"), f"Turma do aluno {index}"
            )
            if classroom_key not in classroom_keys:
                raise ValueError(f"O aluno {index} referencia uma turma inexistente.")
        else:
            classroom_key = _text(
                item.get("class_name"),
                f"Turma do aluno {index}",
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
        code = _text(item.get("code"), f"Código do aluno {index}", 30)
        if code in student_codes:
            raise ValueError(f"O código de aluno '{code}' está duplicado no backup.")
        student_keys.add(key)
        student_codes.add(code)
        students.append(
            {
                "key": key,
                "classroom_key": classroom_key,
                "name": _text(item.get("name"), f"Nome do aluno {index}", 120),
                "code": code,
                "balance": _integer(
                    item.get("balance", 0),
                    f"Saldo do aluno {index}",
                    minimum=INTEGER_MIN,
                    maximum=INTEGER_MAX,
                ),
                "active": _boolean(
                    item.get("active"), f"Status do aluno {index}", default=True
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
        raise ValueError(f"O código de aluno '{code}' já pertence a outro usuário.")

    action_classrooms = {item["key"]: item["classroom_key"] for item in actions}
    student_classrooms = {item["key"]: item["classroom_key"] for item in students}
    movements = []
    movement_keys = set()
    valid_movement_types = {choice[0] for choice in Movement.TYPES}
    for index, item in enumerate(movements_data, start=1):
        raw_key = item.get("id", f"movement-{index}")
        key = _logical_id(raw_key, f"Movimentação {index}")
        if key in movement_keys:
            raise ValueError("Há identificadores de movimentação duplicados no backup.")
        student_key = _logical_id(
            item.get("student_id"), f"Aluno da movimentação {index}"
        )
        if student_key not in student_keys:
            raise ValueError(f"A movimentação {index} referencia um aluno inexistente.")
        movement_type = item.get("movement_type", Movement.CREDIT)
        if movement_type not in valid_movement_types:
            raise ValueError(f"A movimentação {index} possui tipo inválido.")
        action_key = None
        if version == 3 and item.get("action_id") is not None:
            action_key = _logical_id(
                item.get("action_id"), f"Ação da movimentação {index}"
            )
            if action_key not in action_keys:
                raise ValueError(f"A movimentação {index} referencia uma ação inexistente.")
            if action_classrooms[action_key] != student_classrooms[student_key]:
                raise ValueError(
                    f"A ação da movimentação {index} pertence a outra turma."
                )
        movement_keys.add(key)
        movements.append(
            {
                "student_key": student_key,
                "action_key": action_key,
                "movement_type": movement_type,
                "amount": _integer(
                    item.get("amount", 0),
                    f"Valor da movimentação {index}",
                    minimum=0,
                    maximum=INTEGER_MAX,
                ),
                "signed_amount": _integer(
                    item.get("signed_amount", 0),
                    f"Valor assinado da movimentação {index}",
                    minimum=INTEGER_MIN,
                    maximum=INTEGER_MAX,
                ),
                "reason": _text(
                    item.get("reason"),
                    f"Motivo da movimentação {index}",
                    160,
                    default="Movimentação restaurada",
                ),
                "balance_before": _integer(
                    item.get("balance_before", 0),
                    f"Saldo anterior da movimentação {index}",
                    minimum=INTEGER_MIN,
                    maximum=INTEGER_MAX,
                ),
                "balance_after": _integer(
                    item.get("balance_after", 0),
                    f"Saldo posterior da movimentação {index}",
                    minimum=INTEGER_MIN,
                    maximum=INTEGER_MAX,
                ),
                "reversed": _boolean(
                    item.get("reversed"),
                    f"Status da movimentação {index}",
                    default=False,
                ),
                "created_at": _created_at(item.get("created_at")),
            }
        )

    settings = []
    setting_keys = set()
    for key, value in settings_data.items():
        normalized_key = _text(key, "Chave de configuração", 80)
        if normalized_key in setting_keys:
            raise ValueError("Há chaves de configuração duplicadas no backup.")
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            raise ValueError(f"A configuração '{normalized_key}' possui valor inválido.")
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
