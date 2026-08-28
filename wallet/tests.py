import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import AppSetting, Classroom, ClassroomAction, Movement, Student
from .services import DEFAULT_CLASSROOM_ACTIONS, ensure_classroom_actions


class ClassAdministrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="professor", password="senha-teste"
        )
        self.client.force_login(self.user)
        self.class_a = Classroom.objects.create(owner=self.user, name="6º A")
        self.class_b = Classroom.objects.create(owner=self.user, name="6º B")
        self.student_a = Student.objects.create(
            name="Ana", classroom=self.class_a, code="1001", balance=10
        )
        self.student_b = Student.objects.create(
            name="Bruno", classroom=self.class_b, code="1002", balance=20
        )
        Movement.objects.create(
            student=self.student_a,
            movement_type=Movement.CREDIT,
            amount=10,
            signed_amount=10,
            reason="Atividade",
            balance_after=10,
        )
        Movement.objects.create(
            student=self.student_b,
            movement_type=Movement.CREDIT,
            amount=20,
            signed_amount=20,
            reason="Atividade",
            balance_after=20,
        )

    def test_students_and_movements_can_be_filtered_by_class(self):
        students = self.client.get("/api/students/", {"class_name": "6º A"}).json()
        movements = self.client.get("/api/movements/", {"class_name": "6º A"}).json()

        self.assertEqual([student["name"] for student in students["students"]], ["Ana"])
        self.assertEqual(students["classes"], ["6º A", "6º B"])
        self.assertEqual([movement["student_name"] for movement in movements["movements"]], ["Ana"])

    def test_reset_only_changes_selected_class(self):
        response = self.client.post(
            "/api/reset/",
            data=json.dumps({"class_name": "6º A"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reset_count"], 1)
        self.student_a.refresh_from_db()
        self.student_b.refresh_from_db()
        self.assertEqual(self.student_a.balance, 0)
        self.assertEqual(self.student_b.balance, 20)

    def test_bulk_creation_uses_selected_class_as_default(self):
        response = self.client.post(
            "/api/students/bulk/",
            data=json.dumps({"lines": ["Carla"], "default_class_name": "6º A"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        student = Student.objects.get(name="Carla")
        self.assertEqual(student.class_name, "6º A")
        self.assertEqual(student.classroom.owner, self.user)

    def test_student_can_be_safely_deleted(self):
        response = self.client.post(f"/api/students/{self.student_a.id}/delete/")

        self.assertEqual(response.status_code, 200)
        self.student_a.refresh_from_db()
        self.assertFalse(self.student_a.active)
        self.assertNotContains(self.client.get("/api/students/"), '"Ana"')
        self.assertNotContains(self.client.get("/api/movements/"), '"Ana"')

    def test_classroom_can_be_created_renamed_archived_and_reactivated(self):
        created = self.client.post(
            "/api/classrooms/",
            data=json.dumps({"name": "7º A"}),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201)
        classroom_id = created.json()["classroom"]["id"]

        renamed = self.client.post(
            f"/api/classrooms/{classroom_id}/rename/",
            data=json.dumps({"name": "7º B"}),
            content_type="application/json",
        )
        self.assertEqual(renamed.status_code, 200)

        archived = self.client.post(
            f"/api/classrooms/{classroom_id}/archive/",
            data=json.dumps({"active": False}),
            content_type="application/json",
        )
        self.assertFalse(archived.json()["classroom"]["active"])
        self.assertNotIn("7º B", self.client.get("/api/students/").json()["classes"])

        reactivated = self.client.post(
            f"/api/classrooms/{classroom_id}/archive/",
            data=json.dumps({"active": True}),
            content_type="application/json",
        )
        self.assertTrue(reactivated.json()["classroom"]["active"])
        self.assertIn("7º B", self.client.get("/api/students/").json()["classes"])

    def test_archived_classroom_is_hidden_but_preserved_in_backup(self):
        self.client.post(
            f"/api/classrooms/{self.class_a.id}/archive/",
            data=json.dumps({"active": False}),
            content_type="application/json",
        )

        self.assertNotContains(self.client.get("/api/students/"), '"Ana"')
        self.assertNotContains(self.client.get("/api/movements/"), '"Ana"')
        backup = self.client.get("/api/backup/").json()
        self.assertIn("Ana", str(backup["students"]))
        class_data = next(item for item in backup["classrooms"] if item["name"] == "6º A")
        self.assertFalse(class_data["active"])

        response = self.client.post(
            "/api/restore/", data=json.dumps(backup), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Classroom.objects.get(owner=self.user, name="6º A").active)
        self.assertTrue(Student.objects.filter(name="Ana").exists())

    def test_classroom_transfer_moves_all_data_to_target_superuser(self):
        target = get_user_model().objects.create_superuser(
            username="destino", password="senha-teste"
        )
        response = self.client.post(
            f"/api/classrooms/{self.class_a.id}/transfer/",
            data=json.dumps({"target_user_id": target.id}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.class_a.refresh_from_db()
        self.assertEqual(self.class_a.owner, target)
        self.assertNotContains(self.client.get("/api/students/"), '"Ana"')
        self.client.force_login(target)
        self.assertContains(self.client.get("/api/students/"), '"Ana"')

    def test_users_cannot_access_another_superusers_data(self):
        other = get_user_model().objects.create_superuser(
            username="outro", password="senha-teste"
        )
        other_class = Classroom.objects.create(owner=other, name="6º A")
        other_student = Student.objects.create(
            name="Aluno de outro usuário", classroom=other_class, code="9001", balance=50
        )
        other_movement = Movement.objects.create(
            student=other_student,
            movement_type=Movement.CREDIT,
            amount=50,
            signed_amount=50,
            reason="Privado",
            balance_after=50,
        )
        AppSetting.objects.create(owner=other, key="private", value="secret")

        self.assertNotContains(self.client.get("/api/students/"), other_student.name)
        self.assertNotContains(self.client.get("/api/movements/"), "Privado")
        self.assertEqual(
            self.client.post(f"/api/students/{other_student.id}/movement/").status_code,
            400,
        )
        self.assertEqual(
            self.client.post(f"/api/movements/{other_movement.id}/undo/").status_code,
            400,
        )

        backup = self.client.get("/api/backup/").json()
        self.assertNotIn(other_student.name, str(backup))
        self.assertNotIn("private", backup["settings"])

        self.client.post("/api/reset/", data="{}", content_type="application/json")
        other_student.refresh_from_db()
        self.assertEqual(other_student.balance, 50)

        response = self.client.post(
            "/api/restore/",
            data=json.dumps({"students": [], "movements": [], "settings": {}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Student.objects.filter(pk=other_student.id).exists())
        self.assertTrue(AppSetting.objects.filter(owner=other, key="private").exists())


class AuthenticationTests(TestCase):
    def test_main_page_redirects_to_login(self):
        response = self.client.get("/")

        self.assertRedirects(response, "/login/?next=/")

    def test_sensitive_apis_reject_anonymous_access(self):
        requests = [
            ("get", "/api/students/"),
            ("get", "/api/classrooms/"),
            ("post", "/api/classrooms/"),
            ("get", "/api/classrooms/1/actions/"),
            ("post", "/api/classrooms/1/actions/"),
            ("post", "/api/classrooms/1/rename/"),
            ("post", "/api/classrooms/1/archive/"),
            ("post", "/api/classrooms/1/transfer/"),
            ("post", "/api/students/create/"),
            ("post", "/api/students/bulk/"),
            ("post", "/api/students/1/movement/"),
            ("post", "/api/students/1/delete/"),
            ("get", "/api/movements/"),
            ("post", "/api/movements/1/undo/"),
            ("post", "/api/reset/"),
            ("get", "/api/backup/"),
            ("post", "/api/restore/"),
        ]

        for method, path in requests:
            with self.subTest(path=path):
                response = getattr(self.client, method)(path)
                self.assertEqual(response.status_code, 401)

    def test_valid_user_can_log_in(self):
        get_user_model().objects.create_superuser(
            username="professor", password="senha-segura"
        )

        response = self.client.post(
            "/login/", {"username": "professor", "password": "senha-segura"}
        )

        self.assertRedirects(response, "/")

    def test_regular_user_cannot_open_wallet(self):
        user = get_user_model().objects.create_user(username="auxiliar", password="senha-segura")
        self.client.force_login(user)

        self.assertEqual(self.client.get("/").status_code, 403)
        self.assertEqual(self.client.get("/api/students/").status_code, 403)


class ClassroomActionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="professor-acoes", password="senha-teste"
        )
        self.other_user = get_user_model().objects.create_superuser(
            username="outro-professor", password="senha-teste"
        )
        self.client.force_login(self.user)

    def create_classroom(self, name="6º A"):
        response = self.client.post(
            "/api/classrooms/",
            data=json.dumps({"name": name}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        return Classroom.objects.get(pk=response.json()["classroom"]["id"])

    def test_new_classroom_receives_the_complete_default_catalog(self):
        classroom = self.create_classroom()
        actions = list(classroom.actions.order_by("position"))

        self.assertEqual(len(actions), len(DEFAULT_CLASSROOM_ACTIONS))
        self.assertEqual(
            [action.default_key for action in actions],
            [item[0] for item in DEFAULT_CLASSROOM_ACTIONS],
        )
        self.assertTrue(all(action.value == 1 for action in actions))

    def test_catalog_service_is_idempotent_and_preserves_configuration(self):
        classroom = self.create_classroom()
        action = classroom.actions.get(default_key="good-behavior")
        action.value = 7
        action.active = False
        action.save(update_fields=["value", "active"])

        ensure_classroom_actions(classroom)
        ensure_classroom_actions(classroom)

        self.assertEqual(classroom.actions.count(), len(DEFAULT_CLASSROOM_ACTIONS))
        action.refresh_from_db()
        self.assertEqual(action.value, 7)
        self.assertFalse(action.active)

    def test_action_value_has_model_and_database_validation(self):
        classroom = Classroom.objects.create(owner=self.user, name="6º B")
        action = ClassroomAction(
            classroom=classroom,
            name="Teste",
            nature=ClassroomAction.CREDIT,
            value=0,
            default_key="test",
        )
        with self.assertRaises(ValidationError):
            action.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            action.save()

    def test_action_reference_is_optional_and_history_survives_deletion(self):
        classroom = self.create_classroom()
        student = Student.objects.create(name="Ana", classroom=classroom, code="7001")
        action = classroom.actions.get(default_key="good-behavior")
        movement = Movement.objects.create(
            student=student,
            action=action,
            movement_type=Movement.CREDIT,
            amount=action.value,
            signed_amount=action.value,
            reason=action.name,
        )

        action.delete()
        movement.refresh_from_db()

        self.assertIsNone(movement.action)
        self.assertEqual(movement.reason, "Bom comportamento")
        self.assertEqual(movement.amount, 1)

    def test_values_are_independent_between_classrooms(self):
        class_a = self.create_classroom("6º A")
        class_b = self.create_classroom("6º B")
        action_a = class_a.actions.get(default_key="bathroom")
        action_b = class_b.actions.get(default_key="bathroom")

        response = self.client.post(
            f"/api/classrooms/{class_a.id}/actions/",
            data=json.dumps({
                "actions": [{
                    "id": action_a.id,
                    "nature": action_a.nature,
                    "value": 4,
                    "active": False,
                }]
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        action_a.refresh_from_db()
        action_b.refresh_from_db()
        self.assertEqual(action_a.value, 4)
        self.assertFalse(action_a.active)
        self.assertEqual(action_b.value, 1)
        self.assertTrue(action_b.active)

    def test_invalid_batch_is_entirely_rejected(self):
        classroom = self.create_classroom()
        first, second = classroom.actions.order_by("position")[:2]

        response = self.client.post(
            f"/api/classrooms/{classroom.id}/actions/",
            data=json.dumps({
                "actions": [
                    {"id": first.id, "value": 9, "active": False},
                    {"id": second.id, "value": 0, "active": False},
                ]
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.value, first.active), (1, True))
        self.assertEqual((second.value, second.active), (1, True))

    def test_cross_owner_and_archived_classrooms_are_not_exposed(self):
        other_class = Classroom.objects.create(owner=self.other_user, name="Privada")
        ensure_classroom_actions(other_class)
        archived = self.create_classroom("Arquivada")
        archived.active = False
        archived.save(update_fields=["active"])

        for classroom in (other_class, archived):
            with self.subTest(classroom=classroom.name):
                self.assertEqual(
                    self.client.get(f"/api/classrooms/{classroom.id}/actions/").status_code,
                    404,
                )
                self.assertEqual(
                    self.client.post(
                        f"/api/classrooms/{classroom.id}/actions/",
                        data=json.dumps({"actions": []}),
                        content_type="application/json",
                    ).status_code,
                    404,
                )

    def test_restore_creates_catalog_and_transfer_keeps_same_actions(self):
        backup = {
            "classrooms": [{"name": "Restaurada", "active": True}],
            "students": [],
            "movements": [],
            "settings": {},
        }
        restored = self.client.post(
            "/api/restore/", data=json.dumps(backup), content_type="application/json"
        )
        self.assertEqual(restored.status_code, 200)
        classroom = Classroom.objects.get(owner=self.user, name="Restaurada")
        original_ids = set(classroom.actions.values_list("id", flat=True))

        transferred = self.client.post(
            f"/api/classrooms/{classroom.id}/transfer/",
            data=json.dumps({"target_user_id": self.other_user.id}),
            content_type="application/json",
        )

        self.assertEqual(transferred.status_code, 200)
        self.assertEqual(
            set(ClassroomAction.objects.filter(classroom=classroom).values_list("id", flat=True)),
            original_ids,
        )
        self.assertEqual(len(original_ids), len(DEFAULT_CLASSROOM_ACTIONS))
