"""
Management command to rebuild CodeState from all existing transitions
and optionally recompute families for dirty countries.

Usage:
    python manage.py rebuild_state                   # rebuild CodeState only
    python manage.py rebuild_state --recompute       # also recompute families
    python manage.py rebuild_state --country PL      # scope to one country
"""

from django.core.management.base import BaseCommand

from events.models import Country
from events.services import rebuild_code_states
from families.engine import recompute_families


class Command(BaseCommand):
    help = "Rebuild CodeState index from transitions and optionally recompute families."

    def add_arguments(self, parser):
        parser.add_argument(
            "--country", type=str, default=None, help="Limit to a single ISO country code."
        )
        parser.add_argument(
            "--recompute", action="store_true", help="Also recompute families (product families)."
        )

    def handle(self, **options):
        country = options["country"]

        self.stdout.write("Rebuilding CodeState index ...")
        rebuild_code_states(iso_country_code=country)
        self.stdout.write(self.style.SUCCESS("CodeState rebuilt."))

        if options["recompute"]:
            self.stdout.write("Recomputing families ...")
            recompute_families(iso_country_code=country)
            if country:
                Country.objects.filter(code=country).update(families_dirty=False)
            else:
                Country.objects.all().update(families_dirty=False)
            self.stdout.write(self.style.SUCCESS("Families recomputed."))
        else:
            self.stdout.write("Skipping family recompute (use --recompute to include).")
