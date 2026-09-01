from django.db import migrations


DEFAULT_ACTIONS = (
    ("good-behavior", "Bom comportamento", "credit"),
    ("organized-classroom", "Organizou a sala", "credit"),
    ("helped-classmate", "Ajudou um colega", "credit"),
    ("finished-activity", "Terminou a atividade", "credit"),
    ("handwriting-practice", "Fazer caligrafia", "credit"),
    ("bathroom", "Ir ao banheiro", "debit"),
    ("drink-water", "Beber água", "debit"),
    ("indiscipline", "Indisciplina", "debit"),
    ("lost-card-replacement", "Reposição de cartão perdido", "debit"),
    ("play-time", "Tempo de jogar", "debit"),

)


def populate_default_actions(apps, schema_editor):
    Classroom = apps.get_model("wallet", "Classroom")
    ClassroomAction = apps.get_model("wallet", "ClassroomAction")

    actions = []
    for classroom_id in Classroom.objects.values_list("id", flat=True).iterator():
        for position, (default_key, name, nature) in enumerate(DEFAULT_ACTIONS, start=1):
            actions.append(
                ClassroomAction(
                    classroom_id=classroom_id,
                    default_key=default_key,
                    name=name,
                    nature=nature,
                    value=1,
                    position=position,
                )
            )
    ClassroomAction.objects.bulk_create(actions, ignore_conflicts=True)


def remove_default_actions(apps, schema_editor):
    ClassroomAction = apps.get_model("wallet", "ClassroomAction")
    ClassroomAction.objects.filter(
        default_key__in=[item[0] for item in DEFAULT_ACTIONS]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("wallet", "0004_classroomaction_movement_action_and_more")]

    operations = [
        migrations.RunPython(populate_default_actions, remove_default_actions),
    ]
