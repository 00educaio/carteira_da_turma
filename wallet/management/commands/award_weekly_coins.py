from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from wallet.services import WEEKLY_COINS, ensure_weekly_coins


class Command(BaseCommand):
    help = "Award the weekly coins to every active student. Safe to run more than once."

    def handle(self, *args, **options):
        owners = (
            get_user_model()
            .objects.filter(
                is_superuser=True,
                classrooms__active=True,
                classrooms__students__active=True,
            )
            .distinct()
        )
        awarded_students = sum(
            ensure_weekly_coins(owner, award_if_uninitialized=True)
            for owner in owners.iterator()
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Awarded {WEEKLY_COINS} coins to {awarded_students} student(s)."
            )
        )
