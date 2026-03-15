"""
Shared transition-creation logic used by both the Django form and the DRF serializer.

The only public entry point is ``save_event_transitions``.  It validates all
transitions against the CodeState index in O(1) per transition, persists them,
updates CodeState incrementally, and marks the country's families as dirty
for later batch recomputation.

Family recomputation is *not* triggered here — call
``recompute_dirty_families()`` or the /api/product-families/recompute/
endpoint when you need up-to-date product families.
"""

import datetime as _dt

from django.core.exceptions import ValidationError
from django.db import transaction

from events.models import (
    Chain,
    CodeState,
    CodeTransition,
    Country,
    Discontinuation,
    Introduction,
    TransitionType,
)


def save_event_transitions(event, transitions_data):
    """
    Replace **all** transitions on *event*, validate against CodeState,
    update CodeState incrementally, and mark the country dirty.

    ``transitions_data`` is a list of dicts, each with keys:
        date, type, code_type_id,
        introduction_code (opt), discontinuation_code (opt)

    Everything runs inside a single atomic block so that validation errors
    roll back the whole batch (including CodeState updates).
    """
    country_code = (
        event.iso_country_code_id
        if hasattr(event.iso_country_code, "pk")
        else event.iso_country_code
    )

    with transaction.atomic():
        # 1. Undo CodeState effects of any existing transitions on this event
        _rollback_code_states(event, country_code)

        # 2. Remove existing transitions
        event.transitions.all().delete()

        # 3. Sort transitions in canonical order: INTRO first, chain second, DISCONT last
        TYPE_ORDER: dict[str, int] = {
            TransitionType.INTRODUCTION: 0,
            TransitionType.chain: 1,
            TransitionType.DISCONTINUATION: 2,
        }
        sorted_data = sorted(
            transitions_data,
            key=lambda td: (td["date"], TYPE_ORDER.get(td["type"], 9)),
        )

        # 4. Pre-compute effective end dates for introductions that have
        #    a matching discontinuation within the same event batch.
        intro_end_dates: dict[int, _dt.date] = {}
        for td in sorted_data:
            if td["type"] == TransitionType.DISCONTINUATION:
                code = td.get("discontinuation_code")
                if code is not None:
                    intro_end_dates.setdefault(code, td["date"])

        # 5. Validate and create each transition, updating CodeState as we go
        for td in sorted_data:
            _validate_and_create(
                event,
                country_code=country_code,
                date=td["date"],
                type=td["type"],
                code_type_id=td["code_type_id"],
                introduction_code=td.get("introduction_code"),
                discontinuation_code=td.get("discontinuation_code"),
                intro_end_dates=intro_end_dates,
            )

        # 6. Mark country as dirty (families need batch recompute)
        Country.objects.filter(pk=country_code).update(families_dirty=True)


def rebuild_code_states(iso_country_code=None):
    """Rebuild CodeState from scratch by replaying all transitions.

    This is the authoritative rebuild — use it after a migration or if
    CodeState ever gets out of sync.
    """
    TYPE_ORDER: dict[str, int] = {
        TransitionType.INTRODUCTION: 0,
        TransitionType.chain: 1,
        TransitionType.DISCONTINUATION: 2,
    }

    qs = CodeTransition.objects.select_related("introduction", "discontinuation", "chain", "event")
    if iso_country_code:
        qs = qs.filter(event__iso_country_code=iso_country_code)
        CodeState.objects.filter(iso_country_code=iso_country_code).delete()
    else:
        CodeState.objects.all().delete()

    transitions = list(qs.order_by("date", "pk"))
    transitions.sort(key=lambda ct: (ct.date, TYPE_ORDER.get(ct.type, 9), ct.pk))

    for ct in transitions:
        country = ct.event.iso_country_code_id
        if ct.type == TransitionType.INTRODUCTION:
            CodeState.objects.create(
                iso_country_code_id=country,
                code_type_id=ct.code_type_id,
                code=ct.introduction.introduction_code,
                status=CodeState.Status.ACTIVE,
                start_date=ct.date,
            )
        elif ct.type == TransitionType.DISCONTINUATION:
            CodeState.objects.filter(
                iso_country_code=country,
                code_type_id=ct.code_type_id,
                code=ct.discontinuation.discontinuation_code,
                status=CodeState.Status.ACTIVE,
            ).update(
                status=CodeState.Status.DISCONTINUED,
                end_date=ct.date,
            )
        # chain doesn't change CodeState — INTRO/DISCONT transitions handle it


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _rollback_code_states(event, country_code):
    """Reverse the CodeState effects of all transitions on this event."""
    transitions = list(
        event.transitions.select_related("introduction", "discontinuation", "chain").order_by(
            "date", "pk"
        )
    )

    # Process in reverse order to undo correctly
    for ct in reversed(transitions):
        if ct.type == TransitionType.INTRODUCTION:
            CodeState.objects.filter(
                iso_country_code=country_code,
                code_type_id=ct.code_type_id,
                code=ct.introduction.introduction_code,
                start_date=ct.date,
            ).delete()
        elif ct.type == TransitionType.DISCONTINUATION:
            CodeState.objects.filter(
                iso_country_code=country_code,
                code_type_id=ct.code_type_id,
                code=ct.discontinuation.discontinuation_code,
                status=CodeState.Status.DISCONTINUED,
                end_date=ct.date,
            ).update(
                status=CodeState.Status.ACTIVE,
                end_date=_dt.date(9999, 12, 31),
            )


def _validate_and_create(
    event,
    *,
    country_code,
    date,
    type,
    code_type_id,
    introduction_code=None,
    discontinuation_code=None,
    intro_end_dates=None,
):
    """Validate one transition against CodeState, create DB records, update CodeState."""

    if type == TransitionType.INTRODUCTION:
        effective_end = (intro_end_dates or {}).get(introduction_code)
        _validate_introduction(country_code, code_type_id, introduction_code, date, effective_end)
        ct = CodeTransition.objects.create(
            event=event,
            code_type_id=code_type_id,
            type=type,
            date=date,
        )
        Introduction.objects.create(code_transition=ct, introduction_code=introduction_code)
        CodeState.objects.create(
            iso_country_code_id=country_code,
            code_type_id=code_type_id,
            code=introduction_code,
            status=CodeState.Status.ACTIVE,
            start_date=date,
        )

    elif type == TransitionType.DISCONTINUATION:
        _validate_discontinuation(country_code, code_type_id, discontinuation_code)
        ct = CodeTransition.objects.create(
            event=event,
            code_type_id=code_type_id,
            type=type,
            date=date,
        )
        Discontinuation.objects.create(
            code_transition=ct, discontinuation_code=discontinuation_code
        )
        # Only discontinue the generation that started on or before this date
        # (avoids accidentally closing a future generation for the same code).
        CodeState.objects.filter(
            iso_country_code=country_code,
            code_type_id=code_type_id,
            code=discontinuation_code,
            status=CodeState.Status.ACTIVE,
            start_date__lte=date,
        ).update(
            status=CodeState.Status.DISCONTINUED,
            end_date=date,
        )

    elif type == TransitionType.chain:
        _validate_chain(country_code, code_type_id, introduction_code, discontinuation_code)
        ct = CodeTransition.objects.create(
            event=event,
            code_type_id=code_type_id,
            type=type,
            date=date,
        )
        ch = Chain(
            code_transition=ct,
            introduction_code=introduction_code,
            discontinuation_code=discontinuation_code,
        )
        ch.full_clean()
        ch.save()

    return ct


def _validate_introduction(country_code, code_type_id, code, date, effective_end=None):
    """Ensure introducing this code doesn't create overlapping generations.

    Uses proper interval overlap: two intervals [s1,e1) and [s2,e2) overlap
    iff s1 < e2 AND s2 < e1.  ``effective_end`` is the known discontinuation
    date within the same event batch (if any); otherwise the new generation
    is treated as open-ended (9999-12-31).
    """
    new_end = effective_end or _dt.date(9999, 12, 31)

    # Check for interval overlap with any existing generation for this code:
    #   existing.start_date < new_end  AND  existing.end_date > date
    overlapping = CodeState.objects.filter(
        iso_country_code=country_code,
        code_type_id=code_type_id,
        code=code,
        start_date__lt=new_end,
        end_date__gt=date,
    ).exists()

    if overlapping:
        raise ValidationError(
            f"Cannot introduce code {code}: would create overlapping generations "
            f"(code type {code_type_id}, country {country_code})."
        )


def _validate_discontinuation(country_code, code_type_id, code):
    """Ensure the code has an active generation to discontinue."""
    active = CodeState.objects.filter(
        iso_country_code=country_code,
        code_type_id=code_type_id,
        code=code,
        status=CodeState.Status.ACTIVE,
    ).exists()

    if not active:
        raise ValidationError(
            f"Discontinuation of code {code} which has no active generation "
            f"(code type {code_type_id}, country {country_code})."
        )


def _validate_chain(country_code, code_type_id, introduction_code, discontinuation_code):
    """Ensure chain references valid codes."""
    # PO (discontinuation_code) must have a generation (active or discontinued)
    po_exists = CodeState.objects.filter(
        iso_country_code=country_code,
        code_type_id=code_type_id,
        code=discontinuation_code,
    ).exists()

    if not po_exists:
        raise ValidationError(
            f"Chain references discontinuation code {discontinuation_code} "
            f"which has no generation "
            f"(code type {code_type_id}, country {country_code})."
        )

    # PI (introduction_code) must have an active generation
    pi_active = CodeState.objects.filter(
        iso_country_code=country_code,
        code_type_id=code_type_id,
        code=introduction_code,
        status=CodeState.Status.ACTIVE,
    ).exists()

    if not pi_active:
        raise ValidationError(
            f"Chain references introduction code {introduction_code} "
            f"which has no active generation "
            f"(code type {code_type_id}, country {country_code})."
        )
