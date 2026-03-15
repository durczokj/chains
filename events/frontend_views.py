import datetime
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from events.forms import EventForm
from events.models import CodeState, CodeType, Country, Event, TransitionType
from events.services import save_event_transitions
from families.models import Generation


def event_list_view(request: HttpRequest) -> HttpResponse:
    country = request.GET.get("country", "")
    qs = Event.objects.prefetch_related(
        "transitions__code_type",
        "transitions__introduction",
        "transitions__discontinuation",
        "transitions__chain",
    )
    if country:
        qs = qs.filter(iso_country_code=country)
    countries = (
        Event.objects.values_list("iso_country_code", flat=True)
        .distinct()
        .order_by("iso_country_code")
    )
    return render(
        request,
        "events/list.html",
        {
            "events": qs,
            "countries": countries,
            "selected_country": country,
        },
    )


def event_create_view(request: HttpRequest) -> HttpResponse:
    """Create the event (country, comment) then redirect to edit page to add transitions."""
    if request.method == "POST":
        form = EventForm(request.POST)
        if form.is_valid():
            event = form.save(commit=False)
            if request.user.is_authenticated:
                event.created_by = request.user
            event.save()
            return redirect("event-edit", pk=event.pk)
    else:
        form = EventForm()
    return render(
        request,
        "events/event_form.html",
        {
            "form": form,
            "title": "Create Event",
        },
    )


def event_edit_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Edit event details and transitions together.  All transitions are
    submitted as a batch and replaced atomically."""
    event = get_object_or_404(Event, pk=pk)
    code_types = CodeType.objects.all()
    errors: list[str] = []

    if request.method == "POST":
        form = EventForm(request.POST, instance=event)
        if form.is_valid():
            transitions_data = _parse_transitions(request.POST)
            try:
                with transaction.atomic():
                    form.save()
                    save_event_transitions(event, transitions_data)
            except (ValidationError, ValueError) as e:
                errors = [str(m) for m in e.messages] if hasattr(e, "messages") else [str(e)]
                event.refresh_from_db()
            else:
                return redirect("event-edit", pk=event.pk)
        else:
            errors = [str(msg) for errs in form.errors.values() for msg in errs]
    else:
        form = EventForm(instance=event)

    transitions = event.transitions.select_related(
        "code_type", "introduction", "discontinuation", "chain"
    ).order_by("pk")

    return render(
        request,
        "events/edit.html",
        {
            "event": event,
            "form": form,
            "transitions": transitions,
            "code_types": code_types,
            "errors": errors,
            "title": "Edit Event",
        },
    )


def _parse_transitions(
    post_data: dict[str, str],
) -> list[dict[str, Any]]:
    """Parse indexed transition fields from POST data."""
    count = int(post_data.get("transition_count", 0))
    result = []
    for i in range(count):
        p = f"t-{i}-"
        t = post_data.get(f"{p}type", "").strip()
        if not t:
            continue
        date_str = post_data.get(f"{p}date", "").strip()
        pi = post_data.get(f"{p}introduction_code", "").strip()
        po = post_data.get(f"{p}discontinuation_code", "").strip()
        result.append(
            {
                "date": datetime.date.fromisoformat(date_str) if date_str else None,
                "type": t,
                "code_type_id": post_data.get(f"{p}code_type", "").strip(),
                "introduction_code": int(pi) if pi else None,
                "discontinuation_code": int(po) if po else None,
            }
        )
    return result


def event_delete_view(request: HttpRequest, pk: int) -> HttpResponse:
    event = get_object_or_404(Event, pk=pk)
    country = event.iso_country_code
    country_code = country.pk if hasattr(country, "pk") else country
    if request.method == "POST":
        with transaction.atomic():
            # Rollback CodeState for this event's transitions
            for ct in event.transitions.select_related("introduction", "discontinuation", "chain"):
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
                        end_date=datetime.date(9999, 12, 31),
                    )
            event.delete()
            Country.objects.filter(pk=country_code).update(families_dirty=True)
        return redirect("event-list")
    return render(request, "events/confirm_delete.html", {"event": event})


def active_codes_json_view(request: HttpRequest) -> JsonResponse:
    """Return active generation codes as JSON, optionally filtered by code_type."""
    code_type = request.GET.get("code_type", "")
    qs = Generation.objects.filter(discontinuation__isnull=True)
    if code_type:
        qs = qs.filter(product_family__code_type=code_type)
    codes = sorted(qs.values_list("code", flat=True).distinct())
    return JsonResponse({"codes": codes})
