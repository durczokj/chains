from django.urls import include, path
from rest_framework.routers import DefaultRouter

from families.views import (
    ProductFamilyViewSet,
    converter_view,
    family_detail_view,
    family_list_view,
    family_recompute_view,
    generation_list_view,
    resolve_bulk,
    resolve_code,
    resolve_reverse,
)

router = DefaultRouter()
router.register(r"product-families", ProductFamilyViewSet, basename="api-product-family")

urlpatterns = [
    # Frontend
    path("families/", family_list_view, name="family-list"),
    path("families/recompute/", family_recompute_view, name="family-recompute"),
    path("families/<int:pk>/", family_detail_view, name="family-detail"),
    path("generations/", generation_list_view, name="generation-list"),
    path("converter/", converter_view, name="converter"),
    # API
    path("api/", include(router.urls)),
    path("api/resolve/", resolve_code, name="resolve-code"),
    path("api/resolve/reverse/", resolve_reverse, name="resolve-reverse"),
    path("api/resolve/bulk/", resolve_bulk, name="resolve-bulk"),
]
