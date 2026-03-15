from django.urls import include, path
from rest_framework.routers import DefaultRouter

from events.frontend_views import (
    active_codes_json_view,
    event_create_view,
    event_delete_view,
    event_edit_view,
    event_list_view,
)
from events.views import CodeTypeViewSet, CountryViewSet, EventViewSet

router = DefaultRouter()
router.register(r"events", EventViewSet, basename="api-event")
router.register(r"code-types", CodeTypeViewSet, basename="api-codetype")
router.register(r"countries", CountryViewSet, basename="api-country")

urlpatterns = [
    # Frontend
    path("", event_list_view, name="event-list"),
    path("events/new/", event_create_view, name="event-create"),
    path("events/<int:pk>/edit/", event_edit_view, name="event-edit"),
    path("events/<int:pk>/delete/", event_delete_view, name="event-delete"),
    path("api/active-codes/", active_codes_json_view, name="active-codes-api"),
    # API
    path("api/", include(router.urls)),
]
