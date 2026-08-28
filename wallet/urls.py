from django.urls import path
from . import views

app_name = "wallet"

urlpatterns = [
    path("", views.index, name="index"),
    path("health/", views.health, name="health"),
    path("api/classrooms/", views.classrooms_api, name="classrooms_api"),
    path(
        "api/classrooms/<int:classroom_id>/rename/",
        views.rename_classroom_api,
        name="rename_classroom_api",
    ),
    path(
        "api/classrooms/<int:classroom_id>/archive/",
        views.archive_classroom_api,
        name="archive_classroom_api",
    ),
    path(
        "api/classrooms/<int:classroom_id>/transfer/",
        views.transfer_classroom_api,
        name="transfer_classroom_api",
    ),
    path("api/students/", views.students_api, name="students_api"),
    path("api/students/create/", views.create_student_api, name="create_student_api"),
    path("api/students/bulk/", views.bulk_students_api, name="bulk_students_api"),
    path("api/students/<int:student_id>/movement/", views.movement_api, name="movement_api"),
    path("api/students/<int:student_id>/delete/", views.delete_student_api, name="delete_student_api"),
    path("api/movements/", views.movements_api, name="movements_api"),
    path("api/movements/<int:movement_id>/undo/", views.undo_api, name="undo_api"),
    path("api/reset/", views.reset_api, name="reset_api"),
    path("api/backup/", views.backup_api, name="backup_api"),
    path("api/restore/", views.restore_api, name="restore_api"),
]
