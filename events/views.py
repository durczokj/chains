import datetime
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from rest_framework import viewsets
from rest_framework.serializers import BaseSerializer

from events.models import CodeState, CodeType, Country, Event, TransitionType
from events.serializers import CodeTypeSerializer, CountrySerializer, EventSerializer


class CountryViewSet(viewsets.ModelViewSet):
    queryset = Country.objects.all()
    serializer_class = CountrySerializer


class CodeTypeViewSet(viewsets.ModelViewSet):
    queryset = CodeType.objects.all()
    serializer_class = CodeTypeSerializer


class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.prefetch_related(
        "transitions__code_type",
        "transitions__introduction",
        "transitions__discontinuation",
        "transitions__chain",
    )
    serializer_class = EventSerializer

    def get_queryset(self) -> QuerySet[Event]:
        qs = super().get_queryset()
        country = self.request.query_params.get("country")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if country:
            qs = qs.filter(iso_country_code=country)
        if date_from:
            qs = qs.filter(transitions__date__gte=date_from)
        if date_to:
            qs = qs.filter(transitions__date__lte=date_to)
        return qs.distinct()

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        serializer.save(
            created_by=self.request.user if self.request.user.is_authenticated else None
        )

    def perform_update(self, serializer: BaseSerializer[Any]) -> None:
        serializer.save()

    def perform_destroy(self, instance: Event) -> None:
        country = instance.iso_country_code
        country_code = country.pk if hasattr(country, "pk") else country

        with transaction.atomic():
            # Rollback CodeState for this event's transitions
            for ct in instance.transitions.select_related(
                "introduction", "discontinuation", "chain"
            ):
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

            instance.delete()
            Country.objects.filter(pk=country_code).update(families_dirty=True)
