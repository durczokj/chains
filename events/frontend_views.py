from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from events.forms import EventForm, TransitionForm
from events.models import CodeTransition, Event
from lifecycles.engine import recompute_lifecycles
from lifecycles.models import Generation


def event_list_view(request):
    country = request.GET.get("country", "")
    qs = Event.objects.prefetch_related(
        "transitions__code_type",
        "transitions__introduction",
        "transitions__discontinuation",
        "transitions__pipo",
    )
    if country:
        qs = qs.filter(iso_country_code=country)
    countries = (
        Event.objects.values_list("iso_country_code", flat=True)
        .distinct()
        .order_by("iso_country_code")
    )
    return render(request, "events/list.html", {
        "events": qs,
        "countries": countries,
        "selected_country": country,
    })


def event_create_view(request):
    """Create the event (date, country, comment) then redirect to edit page to add transitions."""
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
    return render(request, "events/event_form.html", {
        "form": form,
        "title": "Create Event",
    })


def event_edit_view(request, pk):
    """Edit event details and manage transitions (add/delete)."""
    event = get_object_or_404(Event, pk=pk)
    transitions = event.transitions.select_related(
        "code_type", "introduction", "discontinuation", "pipo"
    ).order_by("pk")

    tform_errors = []

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "update_event":
            form = EventForm(request.POST, instance=event)
            if form.is_valid():
                form.save()
                recompute_lifecycles(iso_country_code=event.iso_country_code)
                return redirect("event-edit", pk=event.pk)
        else:
            form = EventForm(instance=event)

        if action == "add_transition":
            tform = TransitionForm(request.POST)
            if tform.is_valid():
                try:
                    tform.save(event)
                except ValidationError as e:
                    tform_errors = e.messages
                else:
                    return redirect("event-edit", pk=event.pk)
            else:
                tform_errors = [
                    msg
                    for errors in tform.errors.values()
                    for msg in errors
                ]
                tform = TransitionForm()
        else:
            tform = TransitionForm()
    else:
        form = EventForm(instance=event)
        tform = TransitionForm()

    return render(request, "events/edit.html", {
        "event": event,
        "form": form,
        "tform": tform,
        "transitions": transitions,
        "tform_errors": tform_errors,
        "title": "Edit Event",
    })


def transition_delete_view(request, pk):
    """Delete a single transition and recompute."""
    ct = get_object_or_404(CodeTransition, pk=pk)
    event = ct.event
    if request.method == "POST":
        ct.delete()
        # If event has no more transitions, keep it — user may add more
        recompute_lifecycles(iso_country_code=event.iso_country_code)
    return redirect("event-edit", pk=event.pk)


def event_delete_view(request, pk):
    event = get_object_or_404(Event, pk=pk)
    country = event.iso_country_code
    if request.method == "POST":
        event.delete()
        recompute_lifecycles(iso_country_code=country)
        return redirect("event-list")
    return render(request, "events/confirm_delete.html", {"event": event})


def active_codes_json_view(request):
    """Return active generation codes as JSON, optionally filtered by code_type."""
    code_type = request.GET.get("code_type", "")
    qs = Generation.objects.filter(end_date__year=9999)
    if code_type:
        qs = qs.filter(product_family__code_type=code_type)
    codes = sorted(qs.values_list("code", flat=True).distinct())
    return JsonResponse({"codes": codes})
