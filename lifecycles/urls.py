from django.urls import include, path
from rest_framework.routers import DefaultRouter

from lifecycles.views import (
    ProductFamilyViewSet,
    converter_view,
    lifecycle_detail_view,
    lifecycle_list_view,
    resolve_bulk,
    resolve_code,
    resolve_reverse,
)

router = DefaultRouter()
router.register(r"product-families", ProductFamilyViewSet, basename="api-product-family")

urlpatterns = [
    # Frontend
    path("lifecycles/", lifecycle_list_view, name="lifecycle-list"),
    path("lifecycles/<int:pk>/", lifecycle_detail_view, name="lifecycle-detail"),
    path("converter/", converter_view, name="converter"),
    # API
    path("api/", include(router.urls)),
    path("api/resolve/", resolve_code, name="resolve-code"),
    path("api/resolve/reverse/", resolve_reverse, name="resolve-reverse"),
    path("api/resolve/bulk/", resolve_bulk, name="resolve-bulk"),
]
