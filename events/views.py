from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from events.models import CodeType, Event
from events.serializers import CodeTypeSerializer, EventSerializer
from lifecycles.engine import recompute_lifecycles


class CodeTypeViewSet(viewsets.ModelViewSet):
    queryset = CodeType.objects.all()
    serializer_class = CodeTypeSerializer


class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.prefetch_related(
        "transitions__code_type",
        "transitions__introduction",
        "transitions__discontinuation",
        "transitions__pipo",
    )
    serializer_class = EventSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        country = self.request.query_params.get("country")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if country:
            qs = qs.filter(iso_country_code=country)
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return qs

    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user if self.request.user.is_authenticated else None
        )

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        country = instance.iso_country_code
        instance.delete()
        recompute_lifecycles(iso_country_code=country)
