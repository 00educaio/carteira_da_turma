import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import AppSetting, Classroom, Movement, Student


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

    def test_health_endpoint_remains_public(self):
        self.assertEqual(self.client.get("/health/").status_code, 200)

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
