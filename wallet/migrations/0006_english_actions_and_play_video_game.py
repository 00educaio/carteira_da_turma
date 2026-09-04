from django.db import migrations, models


ACTION_NAMES = {
    "good-behavior": "Good Behavior",
    "organized-classroom": "Organized the Classroom",
    "helped-classmate": "Helped a Classmate",
    "finished-activity": "Finished an Activity",
    "handwriting-practice": "Handwriting Practice",
    "bathroom": "Use the Bathroom",
    "drink-water": "Drink Water",
    "sheet-of-paper": "Sheet of Paper",
    "indiscipline": "Misbehavior",
    "lost-card-replacement": "Lost Card Replacement",
    "play-video-game": "Play Video Game",
}

HISTORICAL_REASON_TRANSLATIONS = {
    "Bom comportamento": "Good Behavior",
    "Organizou a sala": "Organized the Classroom",
    "Ajudou um colega": "Helped a Classmate",
    "Terminou a atividade": "Finished an Activity",
    "Fazer caligrafia": "Handwriting Practice",
    "Ir ao banheiro": "Use the Bathroom",
    "Beber água": "Drink Water",
    "Folha de papel": "Sheet of Paper",
    "Indisciplina": "Misbehavior",
    "Reposição de cartão perdido": "Lost Card Replacement",
    "Tempo de jogar": "Play Video Game",
    "Reset semanal automático": "Automatic weekly reset",
    "Reset manual": "Manual reset",
}


def translate_actions(apps, schema_editor):
    Classroom = apps.get_model("wallet", "Classroom")
    ClassroomAction = apps.get_model("wallet", "ClassroomAction")
    Movement = apps.get_model("wallet", "Movement")

    for classroom in Classroom.objects.all().iterator():
        play_action = ClassroomAction.objects.filter(
            classroom=classroom, default_key="play-video-game"
        ).first()
        legacy_play_action = ClassroomAction.objects.filter(
            classroom=classroom, default_key="play-time"
        ).first()
        if play_action is None and legacy_play_action is not None:
            legacy_play_action.default_key = "play-video-game"
            legacy_play_action.name = ACTION_NAMES["play-video-game"]
            legacy_play_action.position = 11
            legacy_play_action.save(update_fields=["default_key", "name", "position"])
        elif play_action is None:
            ClassroomAction.objects.create(
                classroom=classroom,
                default_key="play-video-game",
                name=ACTION_NAMES["play-video-game"],
                nature="debit",
                value=1,
                position=11,
            )

        ClassroomAction.objects.get_or_create(
            classroom=classroom,
            default_key="sheet-of-paper",
            defaults={
                "name": ACTION_NAMES["sheet-of-paper"],
                "nature": "debit",
                "value": 1,
                "position": 8,
            },
        )

    for default_key, name in ACTION_NAMES.items():
        ClassroomAction.objects.filter(default_key=default_key).update(name=name)

    for old_reason, new_reason in HISTORICAL_REASON_TRANSLATIONS.items():
        Movement.objects.filter(reason=old_reason).update(reason=new_reason)


class Migration(migrations.Migration):
    dependencies = [("wallet", "0005_populate_default_classroom_actions")]

    operations = [
        migrations.AlterField(
            model_name="classroomaction",
            name="nature",
            field=models.CharField(
                choices=[("credit", "Reward"), ("debit", "Expense")],
                max_length=6,
            ),
        ),
        migrations.AlterField(
            model_name="movement",
            name="movement_type",
            field=models.CharField(
                choices=[
                    ("credit", "Credit"),
                    ("debit", "Debit"),
                    ("reset", "Reset"),
                    ("reversal", "Reversal"),
                ],
                max_length=12,
            ),
        ),
        migrations.RunPython(translate_actions, migrations.RunPython.noop),
    ]
