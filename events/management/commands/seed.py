"""Seed reference data (countries and code types) from the case study."""

from django.core.management.base import BaseCommand

from events.models import CodeType, Country

COUNTRIES = [
    ("PL", "Poland"),
    ("DE", "Germany"),
    ("US", "United States"),
    ("JP", "Japan"),
    ("CN", "China"),
]

CODE_TYPES = [
    ("IPC", "Internal Product Code"),
    ("GTIN", "Global Trade Item Number"),
]


class Command(BaseCommand):
    help = "Seed countries and code types required by the case study."

    def handle(self, *args: object, **kwargs: object) -> None:
        for code, name in COUNTRIES:
            Country.objects.get_or_create(code=code, defaults={"name": name})
        for ct_id, ct_type in CODE_TYPES:
            CodeType.objects.get_or_create(id=ct_id, defaults={"type": ct_type})
        self.stdout.write(self.style.SUCCESS("Reference data seeded."))
