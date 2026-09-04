import json
import random
from functools import wraps
from urllib.parse import urlencode

import qrcode
import qrcode.image.svg
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .backups import build_backup, restore_backup, validate_backup
from .models import Classroom, ClassroomAction, Movement, Student
from .services import (
    apply_movement,
    build_analytics,
    ensure_classroom_actions,
    ensure_weekly_coins,
    undo_movement,
)

User = get_user_model()


def api_login_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Your session has expired. Please sign in again."}, status=401)
        if not request.user.is_superuser:
            return JsonResponse(
                {"error": "Class Wallet requires a superuser account."}, status=403
            )
        return view_func(request, *args, **kwargs)

    return wrapped


def json_body(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON.") from exc


def serialize_student(student):
    return {
        "id": student.id,
        "name": student.name,
        "classroom_id": student.classroom_id,
        "class_name": student.class_name,
        "code": student.code,
        "balance": student.balance,
    }


def classroom_for(owner, name, *, allow_inactive=False):
    name = str(name).strip()
    if len(name) > 60:
        raise ValueError("The classroom name can be at most 60 characters long.")
    classroom, _ = Classroom.objects.get_or_create(owner=owner, name=name)
    if not allow_inactive and not classroom.active:
        raise ValueError("This classroom is archived. Reactivate it before adding students.")
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
        raise ValueError("Each action value must be a positive integer.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ValueError("Each action value must be a positive integer.")
    if parsed <= 0:
        raise ValueError("Each action value must be greater than zero.")
    return parsed


def serialize_movement(movement):
    return {
        "id": movement.id,
        "action_id": movement.action_id,
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
    raise ValueError("Could not generate an available code.")


@ensure_csrf_cookie
@login_required
def index(request):
    if not request.user.is_superuser:
        return HttpResponse("Access is restricted to superusers.", status=403)
    ensure_weekly_coins(request.user)
    initial_student_id = None
    raw_student_id = request.GET.get("student", "").strip()
    if raw_student_id.isdigit():
        initial_student_id = (
            Student.objects.filter(
                pk=int(raw_student_id),
                classroom__owner=request.user,
                classroom__active=True,
                active=True,
            )
            .values_list("id", flat=True)
            .first()
        )
    return render(
        request,
        "wallet/index.html",
        {"initial_student_id": initial_student_id or ""},
    )


@require_http_methods(["GET", "POST"])
@api_login_required
def classrooms_api(request):
    if request.method == "POST":
        try:
            data = json_body(request)
            name = str(data.get("name", "")).strip()
            if not name:
                raise ValueError("Enter a classroom name.")
            if len(name) > 60:
                raise ValueError("The classroom name can be at most 60 characters long.")
            with transaction.atomic():
                classroom = Classroom.objects.create(owner=request.user, name=name)
                ensure_classroom_actions(classroom)
            return JsonResponse({"classroom": serialize_classroom(classroom)}, status=201)
        except (ValueError, IntegrityError) as exc:
            message = "You already have a classroom with this name." if isinstance(exc, IntegrityError) else str(exc)
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
        return JsonResponse({"error": "Classroom not found."}, status=404)

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
            raise ValueError("Send a list of actions to update.")
        items = data["actions"]
        if not items:
            raise ValueError("Send at least one action to update.")

        prepared = []
        received_ids = set()
        valid_natures = {choice[0] for choice in ClassroomAction.NATURES}
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Each submitted action must be a valid object.")
            raw_action_id = item.get("id")
            if isinstance(raw_action_id, bool) or not (
                isinstance(raw_action_id, int)
                or (isinstance(raw_action_id, str) and raw_action_id.strip().isdigit())
            ):
                raise ValueError("Invalid action identifier.")
            action_id = int(raw_action_id)
            if action_id <= 0:
                raise ValueError("Invalid action identifier.")
            if action_id in received_ids:
                raise ValueError("An action cannot be submitted more than once.")
            received_ids.add(action_id)

            if "value" not in item:
                raise ValueError("Enter a value for every submitted action.")
            value = positive_integer(item["value"])
            active = item.get("active")
            if not isinstance(active, bool):
                raise ValueError("Each action status must be active or inactive.")
            nature = item.get("nature")
            if nature is not None and nature not in valid_natures:
                raise ValueError("Invalid action type.")
            prepared.append((action_id, value, active, nature))

        with transaction.atomic():
            if not Classroom.objects.select_for_update().filter(
                pk=classroom.id, owner=request.user, active=True
            ).exists():
                raise ValueError("This classroom is archived and cannot be configured.")
            actions = {
                action.id: action
                for action in ClassroomAction.objects.select_for_update().filter(
                    classroom=classroom, id__in=received_ids
                )
            }
            if len(actions) != len(received_ids):
                raise ValueError("One or more actions do not belong to this classroom.")

            changed = []
            for action_id, value, active, nature in prepared:
                action = actions[action_id]
                if nature is not None and nature != action.nature:
                    raise ValueError("An action's type cannot be changed.")
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
            raise ValueError("Enter the new classroom name.")
        if len(name) > 60:
            raise ValueError("The classroom name can be at most 60 characters long.")
        classroom = Classroom.objects.get(pk=classroom_id, owner=request.user)
        classroom.name = name
        classroom.save(update_fields=["name"])
        return JsonResponse({"classroom": serialize_classroom(classroom)})
    except Classroom.DoesNotExist:
        return JsonResponse({"error": "Classroom not found."}, status=404)
    except (ValueError, IntegrityError) as exc:
        message = "You already have a classroom with this name." if isinstance(exc, IntegrityError) else str(exc)
        return JsonResponse({"error": message}, status=400)


@require_POST
@api_login_required
def archive_classroom_api(request, classroom_id):
    try:
        data = json_body(request)
        classroom = Classroom.objects.get(pk=classroom_id, owner=request.user)
        active = data.get("active")
        if not isinstance(active, bool):
            raise ValueError("Invalid classroom status.")
        classroom.active = active
        classroom.save(update_fields=["active"])
        return JsonResponse({"classroom": serialize_classroom(classroom)})
    except Classroom.DoesNotExist:
        return JsonResponse({"error": "Classroom not found."}, status=404)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
@api_login_required
def transfer_classroom_api(request, classroom_id):
    try:
        data = json_body(request)
        target_id = int(data.get("target_user_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Select a valid superuser."}, status=400)

    try:
        target = User.objects.get(pk=target_id, is_superuser=True, is_active=True)
        if target.pk == request.user.pk:
            raise ValueError("Choose a different superuser.")
        with transaction.atomic():
            classroom = Classroom.objects.select_for_update().get(
                pk=classroom_id, owner=request.user
            )
            if Classroom.objects.filter(owner=target, name=classroom.name).exists():
                raise ValueError("The recipient already has a classroom with this name.")
            classroom.owner = target
            classroom.save(update_fields=["owner"])
        return JsonResponse({"transferred": True, "classroom_id": classroom_id})
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except User.DoesNotExist:
        return JsonResponse({"error": "Destination superuser not found."}, status=404)
    except Classroom.DoesNotExist:
        return JsonResponse({"error": "Classroom not found."}, status=404)
    except IntegrityError:
        return JsonResponse(
            {"error": "The recipient already has a classroom with this name."}, status=400
        )


@require_GET
@api_login_required
def students_api(request):
    weekly_coins_awarded = ensure_weekly_coins(request.user)
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
        "weekly_coins_awarded": weekly_coins_awarded,
    })


@require_GET
@api_login_required
def student_card_qr_api(request, student_id):
    try:
        student = Student.objects.get(
            pk=student_id,
            classroom__owner=request.user,
            classroom__active=True,
            active=True,
        )
    except Student.DoesNotExist:
        return JsonResponse({"error": "Student not found."}, status=404)

    query = urlencode({"student": student.id})
    operation_url = request.build_absolute_uri(
        f"{reverse('wallet:index')}?{query}"
    )
    image = qrcode.make(
        operation_url,
        image_factory=qrcode.image.svg.SvgPathFillImage,
        box_size=10,
        border=4,
    )
    response = HttpResponse(image.to_string(), content_type="image/svg+xml")
    response["Cache-Control"] = "private, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_POST
@api_login_required
def create_student_api(request):
    try:
        data = json_body(request)
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("Enter the student's name.")
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
                errors.append(f"Line {number}: missing name.")
                continue
            try:
                student = Student.objects.create(
                    name=name,
                    classroom=classroom_for(request.user, class_name),
                    code=code,
                )
                created.append(serialize_student(student))
            except IntegrityError:
                errors.append(f"Line {number}: code {code} already exists.")
        return JsonResponse({"created": created, "errors": errors})
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
@api_login_required
def movement_api(request, student_id):
    try:
        data = json_body(request)
        if not isinstance(data, dict):
            raise ValueError("Submit a valid action for the transaction.")
        student, movement = apply_movement(
            owner=request.user,
            student_id=student_id,
            action_id=data.get("action_id"),
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
        return JsonResponse({"error": "Student not found."}, status=404)


@require_GET
@api_login_required
def movements_api(request):
    ensure_weekly_coins(request.user)
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


@require_GET
@api_login_required
def analytics_api(request):
    try:
        ensure_weekly_coins(request.user)
        data = build_analytics(
            owner=request.user,
            period=request.GET.get("period", "week"),
            start=request.GET.get("start"),
            end=request.GET.get("end"),
            classroom_id=request.GET.get("classroom_id"),
        )
        return JsonResponse(data)
    except Classroom.DoesNotExist:
        return JsonResponse({"error": "Classroom not found."}, status=404)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


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
                reason="Manual reset",
                balance_before=before,
                balance_after=0,
            )
    return JsonResponse({"reset_count": len(students)})


@require_GET
@api_login_required
def backup_api(request):
    payload = build_backup(request.user)
    response = JsonResponse(payload, json_dumps_params={"ensure_ascii": False, "indent": 2})
    filename = f"class-wallet-backup-{timezone.localtime().strftime('%Y-%m-%d-%H%M')}.json"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@require_POST
@api_login_required
def restore_api(request):
    try:
        if request.FILES:
            uploaded = request.FILES.get("file")
            if not uploaded:
                raise ValueError("Upload a JSON file.")
            data = json.loads(uploaded.read().decode("utf-8"))
        else:
            data = json_body(request)

        validated = validate_backup(data, request.user)
        restored_students = restore_backup(request.user, validated)
        return JsonResponse({
            "version": validated["version"],
            "restored_students": restored_students,
        })
    except (ValueError, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except IntegrityError:
        return JsonResponse(
            {"error": "The backup violates a database constraint and was not restored."},
            status=400,
        )
