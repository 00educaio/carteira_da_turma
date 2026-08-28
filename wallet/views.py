import json
import random
from datetime import datetime
from functools import wraps

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import AppSetting, Classroom, ClassroomAction, Movement, Student
from .services import (
    apply_movement,
    ensure_classroom_actions,
    ensure_weekly_reset,
    undo_movement,
)

User = get_user_model()


def api_login_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Sua sessão expirou. Entre novamente."}, status=401)
        if not request.user.is_superuser:
            return JsonResponse(
                {"error": "A Carteira da Turma exige uma conta de superusuário."}, status=403
            )
        return view_func(request, *args, **kwargs)

    return wrapped


def json_body(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("JSON inválido.") from exc


def serialize_student(student):
    return {
        "id": student.id,
        "name": student.name,
        "class_name": student.class_name,
        "code": student.code,
        "balance": student.balance,
    }


def classroom_for(owner, name, *, allow_inactive=False):
    name = str(name).strip()
    if len(name) > 60:
        raise ValueError("O nome da turma pode ter no máximo 60 caracteres.")
    classroom, _ = Classroom.objects.get_or_create(owner=owner, name=name)
    if not allow_inactive and not classroom.active:
        raise ValueError("Esta turma está arquivada. Reative-a antes de cadastrar alunos.")
    ensure_classroom_actions(classroom)
    return classroom


def serialize_classroom(classroom):
    student_count = (
        classroom.student_count
        if hasattr(classroom, "student_count")
        else classroom.students.count()
    )
    active_student_count = (
        classroom.active_student_count
        if hasattr(classroom, "active_student_count")
        else classroom.students.filter(active=True).count()
    )
    return {
        "id": classroom.id,
        "name": classroom.name,
        "active": classroom.active,
        "student_count": student_count,
        "active_student_count": active_student_count,
    }


def serialize_classroom_action(action):
    return {
        "id": action.id,
        "name": action.name,
        "nature": action.nature,
        "value": action.value,
        "position": action.position,
        "active": action.active,
        "default_key": action.default_key,
    }


def positive_integer(value):
    if isinstance(value, bool):
        raise ValueError("O valor de cada ação deve ser um número inteiro positivo.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ValueError("O valor de cada ação deve ser um número inteiro positivo.")
    if parsed <= 0:
        raise ValueError("O valor de cada ação deve ser maior que zero.")
    return parsed


def serialize_movement(movement):
    return {
        "id": movement.id,
        "student_id": movement.student_id,
        "student_name": movement.student.name,
        "class_name": movement.student.class_name,
        "movement_type": movement.movement_type,
        "amount": movement.amount,
        "signed_amount": movement.signed_amount,
        "reason": movement.reason,
        "balance_before": movement.balance_before,
        "balance_after": movement.balance_after,
        "reversed": movement.reversed,
        "created_at": timezone.localtime(movement.created_at).isoformat(),
    }


def generate_code():
    for _ in range(1000):
        code = str(random.randint(1000, 9999))
        if not Student.objects.filter(code=code).exists():
            return code
    raise ValueError("Não foi possível gerar um código disponível.")


@ensure_csrf_cookie
@login_required
def index(request):
    if not request.user.is_superuser:
        return HttpResponse("Acesso permitido apenas para superusuários.", status=403)
    ensure_weekly_reset(request.user)
    return render(request, "wallet/index.html")


@require_http_methods(["GET", "POST"])
@api_login_required
def classrooms_api(request):
    if request.method == "POST":
        try:
            data = json_body(request)
            name = str(data.get("name", "")).strip()
            if not name:
                raise ValueError("Informe o nome da turma.")
            if len(name) > 60:
                raise ValueError("O nome da turma pode ter no máximo 60 caracteres.")
            with transaction.atomic():
                classroom = Classroom.objects.create(owner=request.user, name=name)
                ensure_classroom_actions(classroom)
            return JsonResponse({"classroom": serialize_classroom(classroom)}, status=201)
        except (ValueError, IntegrityError) as exc:
            message = "Você já possui uma turma com esse nome." if isinstance(exc, IntegrityError) else str(exc)
            return JsonResponse({"error": message}, status=400)

    classrooms = (
        Classroom.objects.filter(owner=request.user)
        .annotate(
            student_count=Count("students"),
            active_student_count=Count("students", filter=Q(students__active=True)),
        )
        .order_by("name")
    )
    targets = list(
        User.objects.filter(is_superuser=True, is_active=True)
        .exclude(pk=request.user.pk)
        .order_by("username")
        .values("id", "username")
    )
    return JsonResponse({
        "classrooms": [serialize_classroom(item) for item in classrooms],
        "transfer_targets": targets,
    })


@require_http_methods(["GET", "POST"])
@api_login_required
def classroom_actions_api(request, classroom_id):
    try:
        classroom = Classroom.objects.get(
            pk=classroom_id, owner=request.user, active=True
        )
    except Classroom.DoesNotExist:
        return JsonResponse({"error": "Turma não encontrada."}, status=404)

    if request.method == "GET":
        return JsonResponse({
            "classroom": {"id": classroom.id, "name": classroom.name},
            "actions": [
                serialize_classroom_action(action)
                for action in classroom.actions.order_by("position", "name", "id")
            ],
        })

    try:
        data = json_body(request)
        if not isinstance(data, dict) or not isinstance(data.get("actions"), list):
            raise ValueError("Envie uma lista de ações para atualizar.")
        items = data["actions"]
        if not items:
            raise ValueError("Envie ao menos uma ação para atualizar.")

        prepared = []
        received_ids = set()
        valid_natures = {choice[0] for choice in ClassroomAction.NATURES}
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Cada ação enviada deve ser um objeto válido.")
            raw_action_id = item.get("id")
            if isinstance(raw_action_id, bool) or not (
                isinstance(raw_action_id, int)
                or (isinstance(raw_action_id, str) and raw_action_id.strip().isdigit())
            ):
                raise ValueError("Identificador de ação inválido.")
            action_id = int(raw_action_id)
            if action_id <= 0:
                raise ValueError("Identificador de ação inválido.")
            if action_id in received_ids:
                raise ValueError("Uma ação não pode ser enviada mais de uma vez.")
            received_ids.add(action_id)

            if "value" not in item:
                raise ValueError("Informe o valor de todas as ações enviadas.")
            value = positive_integer(item["value"])
            active = item.get("active")
            if not isinstance(active, bool):
                raise ValueError("O status de cada ação deve ser ativo ou inativo.")
            nature = item.get("nature")
            if nature is not None and nature not in valid_natures:
                raise ValueError("Natureza de ação inválida.")
            prepared.append((action_id, value, active, nature))

        with transaction.atomic():
            if not Classroom.objects.select_for_update().filter(
                pk=classroom.id, owner=request.user, active=True
            ).exists():
                raise ValueError("Esta turma está arquivada e não pode ser configurada.")
            actions = {
                action.id: action
                for action in ClassroomAction.objects.select_for_update().filter(
                    classroom=classroom, id__in=received_ids
                )
            }
            if len(actions) != len(received_ids):
                raise ValueError("Uma ou mais ações não pertencem a esta turma.")

            changed = []
            for action_id, value, active, nature in prepared:
                action = actions[action_id]
                if nature is not None and nature != action.nature:
                    raise ValueError("A natureza de uma ação não pode ser alterada.")
                action.value = value
                action.active = active
                changed.append(action)
            ClassroomAction.objects.bulk_update(changed, ["value", "active"])

        return JsonResponse({
            "classroom": {"id": classroom.id, "name": classroom.name},
            "actions": [
                serialize_classroom_action(action)
                for action in classroom.actions.order_by("position", "name", "id")
            ],
        })
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
@api_login_required
def rename_classroom_api(request, classroom_id):
    try:
        data = json_body(request)
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("Informe o novo nome da turma.")
        if len(name) > 60:
            raise ValueError("O nome da turma pode ter no máximo 60 caracteres.")
        classroom = Classroom.objects.get(pk=classroom_id, owner=request.user)
        classroom.name = name
        classroom.save(update_fields=["name"])
        return JsonResponse({"classroom": serialize_classroom(classroom)})
    except Classroom.DoesNotExist:
        return JsonResponse({"error": "Turma não encontrada."}, status=404)
    except (ValueError, IntegrityError) as exc:
        message = "Você já possui uma turma com esse nome." if isinstance(exc, IntegrityError) else str(exc)
        return JsonResponse({"error": message}, status=400)


@require_POST
@api_login_required
def archive_classroom_api(request, classroom_id):
    try:
        data = json_body(request)
        classroom = Classroom.objects.get(pk=classroom_id, owner=request.user)
        active = data.get("active")
        if not isinstance(active, bool):
            raise ValueError("Status de turma inválido.")
        classroom.active = active
        classroom.save(update_fields=["active"])
        return JsonResponse({"classroom": serialize_classroom(classroom)})
    except Classroom.DoesNotExist:
        return JsonResponse({"error": "Turma não encontrada."}, status=404)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
@api_login_required
def transfer_classroom_api(request, classroom_id):
    try:
        data = json_body(request)
        target_id = int(data.get("target_user_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Selecione um superusuário válido."}, status=400)

    try:
        target = User.objects.get(pk=target_id, is_superuser=True, is_active=True)
        if target.pk == request.user.pk:
            raise ValueError("Escolha outro superusuário.")
        with transaction.atomic():
            classroom = Classroom.objects.select_for_update().get(
                pk=classroom_id, owner=request.user
            )
            if Classroom.objects.filter(owner=target, name=classroom.name).exists():
                raise ValueError("O destinatário já possui uma turma com esse nome.")
            classroom.owner = target
            classroom.save(update_fields=["owner"])
        return JsonResponse({"transferred": True, "classroom_id": classroom_id})
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except User.DoesNotExist:
        return JsonResponse({"error": "Superusuário de destino não encontrado."}, status=404)
    except Classroom.DoesNotExist:
        return JsonResponse({"error": "Turma não encontrada."}, status=404)
    except IntegrityError:
        return JsonResponse(
            {"error": "O destinatário já possui uma turma com esse nome."}, status=400
        )


@require_GET
@api_login_required
def students_api(request):
    reset_performed = ensure_weekly_reset(request.user)
    query = request.GET.get("q", "").strip()
    class_filter_enabled = "class_name" in request.GET
    class_name = request.GET.get("class_name", "").strip()
    students = Student.objects.select_related("classroom").filter(
        classroom__owner=request.user, classroom__active=True, active=True
    )
    classes = list(
        Classroom.objects.filter(owner=request.user, active=True)
        .order_by("name")
        .values_list("name", flat=True)
    )
    if class_filter_enabled:
        students = students.filter(classroom__name=class_name)
    if query:
        students = students.filter(
            Q(code__icontains=query)
            | Q(name__icontains=query)
            | Q(classroom__name__icontains=query)
        )
    return JsonResponse({
        "students": [serialize_student(student) for student in students],
        "classes": classes,
        "reset_performed": reset_performed,
    })


@require_POST
@api_login_required
def create_student_api(request):
    try:
        data = json_body(request)
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("Informe o nome do aluno.")
        code = str(data.get("code", "")).strip() or generate_code()
        student = Student.objects.create(
            name=name,
            classroom=classroom_for(request.user, str(data.get("class_name", ""))),
            code=code,
            balance=int(data.get("balance", 0) or 0),
        )
        return JsonResponse({"student": serialize_student(student)}, status=201)
    except (ValueError, IntegrityError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
@api_login_required
def bulk_students_api(request):
    try:
        data = json_body(request)
        lines = data.get("lines", [])
        default_class_name = str(data.get("default_class_name", "")).strip()
        if isinstance(lines, str):
            lines = lines.splitlines()
        created = []
        errors = []
        for number, line in enumerate(lines, start=1):
            line = str(line).strip()
            if not line:
                continue
            parts = [part.strip() for part in line.split(";")]
            name = parts[0] if parts else ""
            class_name = parts[1] if len(parts) > 1 else default_class_name
            code = parts[2] if len(parts) > 2 and parts[2] else generate_code()
            if not name:
                errors.append(f"Linha {number}: nome vazio.")
                continue
            try:
                student = Student.objects.create(
                    name=name,
                    classroom=classroom_for(request.user, class_name),
                    code=code,
                )
                created.append(serialize_student(student))
            except IntegrityError:
                errors.append(f"Linha {number}: código {code} já existe.")
        return JsonResponse({"created": created, "errors": errors})
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
@api_login_required
def movement_api(request, student_id):
    try:
        data = json_body(request)
        student, movement = apply_movement(
            owner=request.user,
            student_id=student_id,
            movement_type=data.get("movement_type"),
            amount=data.get("amount"),
            reason=str(data.get("reason", "")),
        )
        return JsonResponse({
            "student": serialize_student(student),
            "movement": serialize_movement(movement),
        })
    except (Student.DoesNotExist, ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
@api_login_required
def delete_student_api(request, student_id):
    try:
        student = Student.objects.get(
            pk=student_id,
            classroom__owner=request.user,
            classroom__active=True,
            active=True,
        )
        student.active = False
        student.save(update_fields=["active"])
        return JsonResponse({"deleted": True, "student_id": student.id})
    except Student.DoesNotExist:
        return JsonResponse({"error": "Aluno não encontrado."}, status=404)


@require_GET
@api_login_required
def movements_api(request):
    ensure_weekly_reset(request.user)
    limit = min(max(int(request.GET.get("limit", 100)), 1), 500)
    movements = Movement.objects.select_related("student", "student__classroom").filter(
        student__classroom__owner=request.user,
        student__classroom__active=True,
        student__active=True,
    )
    if "class_name" in request.GET:
        movements = movements.filter(
            student__classroom__name=request.GET.get("class_name", "").strip()
        )
    movements = movements[:limit]
    return JsonResponse({"movements": [serialize_movement(item) for item in movements]})


@require_POST
@api_login_required
def undo_api(request, movement_id):
    try:
        student = undo_movement(request.user, movement_id)
        return JsonResponse({"student": serialize_student(student)})
    except (Movement.DoesNotExist, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
@api_login_required
def reset_api(request):
    try:
        data = json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    class_filter_enabled = "class_name" in data
    class_name = str(data.get("class_name", "")).strip()
    with transaction.atomic():
        students_query = Student.objects.select_for_update().filter(
            classroom__owner=request.user, classroom__active=True, active=True
        )
        if class_filter_enabled:
            students_query = students_query.filter(classroom__name=class_name)
        students = list(students_query.exclude(balance=0))
        for student in students:
            before = student.balance
            student.balance = 0
            student.save(update_fields=["balance"])
            Movement.objects.create(
                student=student,
                movement_type=Movement.RESET,
                amount=abs(before),
                signed_amount=-before,
                reason="Reset manual",
                balance_before=before,
                balance_after=0,
            )
        today = timezone.localdate()
        iso_year, iso_week, _ = today.isocalendar()
        AppSetting.objects.update_or_create(
            owner=request.user,
            key="last_reset_week",
            defaults={"value": f"{iso_year}-W{iso_week:02d}"},
        )
    return JsonResponse({"reset_count": len(students)})


@require_GET
@api_login_required
def backup_api(request):
    payload = {
        "version": 2,
        "exported_at": timezone.now().isoformat(),
        "classrooms": [
            {"name": classroom.name, "active": classroom.active}
            for classroom in Classroom.objects.filter(owner=request.user).order_by("name")
        ],
        "students": [
            serialize_student(student)
            for student in Student.objects.select_related("classroom").filter(
                classroom__owner=request.user, active=True
            )
        ],
        "movements": [
            serialize_movement(movement)
            for movement in Movement.objects.select_related("student", "student__classroom")
            .filter(student__classroom__owner=request.user, student__active=True)
            .order_by("created_at", "id")
        ],
        "settings": {
            setting.key: setting.value
            for setting in AppSetting.objects.filter(owner=request.user)
        },
    }
    response = JsonResponse(payload, json_dumps_params={"ensure_ascii": False, "indent": 2})
    filename = f"carteira-backup-{datetime.now().strftime('%Y-%m-%d-%H%M')}.json"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@require_POST
@api_login_required
def restore_api(request):
    try:
        if request.FILES:
            uploaded = request.FILES.get("file")
            if not uploaded:
                raise ValueError("Envie um arquivo JSON.")
            data = json.loads(uploaded.read().decode("utf-8"))
        else:
            data = json_body(request)

        students_data = data.get("students", [])
        movements_data = data.get("movements", [])
        settings_data = data.get("settings", {})
        classrooms_data = data.get("classrooms", [])

        with transaction.atomic():
            Movement.objects.filter(student__classroom__owner=request.user).delete()
            Student.objects.filter(classroom__owner=request.user).delete()
            Classroom.objects.filter(owner=request.user).delete()
            AppSetting.objects.filter(owner=request.user).delete()

            classrooms = {}
            for item in classrooms_data:
                name = str(item.get("name", "")).strip()
                if name in classrooms:
                    continue
                classrooms[name] = Classroom.objects.create(
                    owner=request.user,
                    name=name,
                    active=bool(item.get("active", True)),
                )
                ensure_classroom_actions(classrooms[name])

            student_map = {}
            for item in students_data:
                class_name = str(item.get("class_name", "")).strip()
                student = Student.objects.create(
                    name=item["name"],
                    classroom=classrooms.get(class_name)
                    or classroom_for(request.user, class_name, allow_inactive=True),
                    code=str(item["code"]),
                    balance=int(item.get("balance", 0)),
                )
                old_id = item.get("id")
                if old_id is not None:
                    student_map[str(old_id)] = student

            for item in movements_data:
                student = student_map.get(str(item.get("student_id")))
                if not student:
                    continue
                movement = Movement.objects.create(
                    student=student,
                    movement_type=item.get("movement_type", Movement.CREDIT),
                    amount=abs(int(item.get("amount", 0))),
                    signed_amount=int(item.get("signed_amount", 0)),
                    reason=item.get("reason", "Movimentação restaurada"),
                    balance_before=int(item.get("balance_before", 0)),
                    balance_after=int(item.get("balance_after", 0)),
                    reversed=bool(item.get("reversed", False)),
                )
                created_at = item.get("created_at")
                if created_at:
                    try:
                        parsed = datetime.fromisoformat(created_at)
                        Movement.objects.filter(pk=movement.pk).update(created_at=parsed)
                    except ValueError:
                        pass

            for key, value in settings_data.items():
                AppSetting.objects.create(
                    owner=request.user, key=str(key), value=str(value)
                )

        return JsonResponse({"restored_students": len(students_data)})
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
