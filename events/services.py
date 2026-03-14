"""
Shared transition-creation logic used by both the Django form and the DRF serializer.
"""
import datetime

from django.db import transaction

from events.models import (
    CodeTransition,
    Discontinuation,
    Event,
    Introduction,
    Pipo,
    TransitionType,
)
from lifecycles.engine import recompute_lifecycles


def create_transition(event, *, type, code_type_id, pi_code=None, po_code=None,
                      proxy_introduction=False, proxy_po=False,
                      discontinue_po=False):
    """
    Create a full transition (with proxies, recomputes, and optional
    discontinuation) on the given event.  Returns the main CodeTransition.

    ``code_type_id`` is the raw FK value (CodeType PK).
    """
    country = event.iso_country_code

    with transaction.atomic():
        if type == TransitionType.INTRODUCTION:
            ct = CodeTransition.objects.create(
                event=event, code_type_id=code_type_id, type=type,
            )
            intro = Introduction(code_transition=ct, pi_code=pi_code)
            intro.full_clean()
            intro.save()
            recompute_lifecycles(iso_country_code=country)
            return ct

        if type == TransitionType.DISCONTINUATION:
            ct = CodeTransition.objects.create(
                event=event, code_type_id=code_type_id, type=type,
            )
            disco = Discontinuation(code_transition=ct, po_code=po_code)
            disco.full_clean()
            disco.save()
            recompute_lifecycles(iso_country_code=country)
            return ct

        # ── PIPO ──────────────────────────────────────────────────────
        # 1. Proxy introductions first so the codes become active
        if proxy_introduction:
            intro_ct = CodeTransition.objects.create(
                event=event, code_type_id=code_type_id,
                type=TransitionType.INTRODUCTION,
            )
            Introduction.objects.create(code_transition=intro_ct, pi_code=pi_code)
            recompute_lifecycles(iso_country_code=country)

        if proxy_po:
            proxy_event = Event.objects.create(
                date=datetime.date(1970, 12, 31),
                iso_country_code=country,
                comment="Proxy introduction for PO code",
            )
            proxy_ct = CodeTransition.objects.create(
                event=proxy_event, code_type_id=code_type_id,
                type=TransitionType.INTRODUCTION,
            )
            Introduction.objects.create(code_transition=proxy_ct, pi_code=po_code)
            recompute_lifecycles(iso_country_code=country)

        # 2. Create the PIPO CodeTransition + Pipo record
        ct = CodeTransition.objects.create(
            event=event, code_type_id=code_type_id, type=type,
        )
        pipo = Pipo(code_transition=ct, pi_code=pi_code, po_code=po_code)
        pipo.full_clean()
        pipo.save()
        recompute_lifecycles(iso_country_code=country)

        # 3. Optionally discontinue PO
        if discontinue_po:
            disco_ct = CodeTransition.objects.create(
                event=event, code_type_id=code_type_id,
                type=TransitionType.DISCONTINUATION,
            )
            disco = Discontinuation(code_transition=disco_ct, po_code=po_code)
            disco.full_clean()
            disco.save()
            recompute_lifecycles(iso_country_code=country)

        return ct
