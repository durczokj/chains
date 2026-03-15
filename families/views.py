import datetime

from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from events.models import CodeType, Country
from families.engine import recompute_families
from families.models import Generation, ProductFamily
from families.serializers import (
    BulkResolveSerializer,
    CodeResolveSerializer,
    ProductFamilyListSerializer,
    ProductFamilySerializer,
)


class ProductFamilyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductFamily.objects.all()

    def get_serializer_class(self):
        if self.action == "list":
            return ProductFamilyListSerializer
        return ProductFamilySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        country = self.request.query_params.get("country")
        code_type = self.request.query_params.get("code_type")
        if country:
            qs = qs.filter(iso_country_code=country)
        if code_type:
            qs = qs.filter(code_type_id=code_type)
        return qs

    @action(detail=False, methods=["post"])
    def recompute(self, request):
        from events.models import Country as CountryModel

        country = request.query_params.get("country")
        dirty_only = request.query_params.get("dirty_only", "").lower() in ("1", "true", "yes")

        if dirty_only and not country:
            # Recompute only countries marked as dirty
            dirty_countries = list(
                CountryModel.objects.filter(families_dirty=True).values_list("code", flat=True)
            )
            for c in dirty_countries:
                recompute_families(iso_country_code=c)
            CountryModel.objects.filter(code__in=dirty_countries).update(families_dirty=False)
            return Response({"status": "ok", "recomputed_countries": dirty_countries})

        recompute_families(iso_country_code=country)
        if country:
            CountryModel.objects.filter(code=country).update(families_dirty=False)
        else:
            CountryModel.objects.all().update(families_dirty=False)
        return Response({"status": "ok"})


def _resolve_code(code, code_type, country, date):
    """Resolve a single code to its product family identifier."""
    date = datetime.date.fromisoformat(str(date)) if not isinstance(date, datetime.date) else date

    gens = (
        Generation.objects.filter(
            code=code,
            product_family__code_type_id=code_type,
            iso_country_code=country,
            introduction__date__lte=date,
        )
        .filter(Q(discontinuation__isnull=True) | Q(discontinuation__date__gte=date))
        .select_related("product_family", "introduction", "discontinuation")
    )

    results = []
    for gen in gens:
        results.append(
            {
                "code": code,
                "code_type": code_type,
                "iso_country_code": country,
                "date": str(date),
                "product_family_identifier": gen.product_family.identifier,
                "product_family_id": gen.product_family.pk,
                "generation_id": gen.pk,
                "start_date": str(gen.start_date),
                "end_date": str(gen.end_date),
            }
        )
    return results


@api_view(["GET"])
def resolve_code(request):
    serializer = CodeResolveSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data
    results = _resolve_code(d["code"], d["code_type"], d["country"], d["date"])
    if not results:
        return Response(
            {"detail": "No matching product family found."}, status=status.HTTP_404_NOT_FOUND
        )
    return Response(results[0] if len(results) == 1 else results)


@api_view(["GET"])
def resolve_reverse(request):
    identifier = request.query_params.get("identifier")
    date_str = request.query_params.get("date")
    if not identifier or not date_str:
        return Response(
            {"detail": "identifier and date are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    date = datetime.date.fromisoformat(date_str)
    try:
        pf = ProductFamily.objects.get(identifier=identifier)
    except ProductFamily.DoesNotExist:
        return Response({"detail": "Product family not found."}, status=status.HTTP_404_NOT_FOUND)

    gens = (
        pf.generations.filter(
            introduction__date__lte=date,
        )
        .filter(Q(discontinuation__isnull=True) | Q(discontinuation__date__gte=date))
        .select_related("introduction", "discontinuation")
    )
    results = []
    for gen in gens:
        results.append(
            {
                "generation_id": gen.pk,
                "start_date": str(gen.start_date),
                "end_date": str(gen.end_date),
                "code": gen.code,
            }
        )
    return Response({"identifier": identifier, "date": date_str, "generations": results})


@api_view(["POST"])
def resolve_bulk(request):
    serializer = BulkResolveSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    results = []
    for q in serializer.validated_data["queries"]:
        matches = _resolve_code(q["code"], q["code_type"], q["country"], q["date"])
        if matches:
            results.append(matches[0])
        else:
            results.append(
                {
                    "code": q["code"],
                    "code_type": q["code_type"],
                    "iso_country_code": q["country"],
                    "date": str(q["date"]),
                    "product_family_identifier": None,
                    "generation_id": None,
                    "start_date": None,
                    "end_date": None,
                }
            )
    return Response({"results": results})


# --- Frontend views ---


def family_recompute_view(request):
    """Recompute all families and redirect back to the list."""
    from django.shortcuts import redirect

    from events.models import Country as CountryModel

    recompute_families()
    CountryModel.objects.all().update(families_dirty=False)
    return redirect("family-list")


def family_list_view(request):
    country = request.GET.get("country", "")
    code_type = request.GET.get("code_type", "")
    qs = ProductFamily.objects.select_related("code_type")
    if country:
        qs = qs.filter(iso_country_code=country)
    if code_type:
        qs = qs.filter(code_type_id=code_type)
    countries = (
        ProductFamily.objects.values_list("iso_country_code", flat=True)
        .distinct()
        .order_by("iso_country_code")
    )
    from events.models import CodeType

    code_types = CodeType.objects.all()
    return render(
        request,
        "families/list.html",
        {
            "product_families": qs,
            "countries": countries,
            "code_types": code_types,
            "selected_country": country,
            "selected_code_type": code_type,
        },
    )


def generation_list_view(request):
    country = request.GET.get("country", "")
    code_type = request.GET.get("code_type", "")
    code = request.GET.get("code", "")
    status_filter = request.GET.get("status", "")

    qs = Generation.objects.select_related(
        "product_family__code_type",
        "introduction",
        "discontinuation",
    ).order_by("iso_country_code", "code", "introduction__date")

    if country:
        qs = qs.filter(iso_country_code=country)
    if code_type:
        qs = qs.filter(product_family__code_type_id=code_type)
    if code:
        qs = qs.filter(code=code)
    if status_filter == "active":
        qs = qs.filter(discontinuation__isnull=True)
    elif status_filter == "discontinued":
        qs = qs.filter(discontinuation__isnull=False)

    countries = (
        Generation.objects.values_list("iso_country_code", flat=True)
        .distinct()
        .order_by("iso_country_code")
    )
    code_types = CodeType.objects.all()

    return render(
        request,
        "families/generations.html",
        {
            "generations": qs,
            "countries": countries,
            "code_types": code_types,
            "selected_country": country,
            "selected_code_type": code_type,
            "selected_code": code,
            "selected_status": status_filter,
        },
    )


def family_detail_view(request, pk):
    from families.engine import get_product_family_mermaid

    pf = get_object_or_404(ProductFamily, pk=pk)
    mermaid = get_product_family_mermaid(pk)
    return render(
        request,
        "families/detail.html",
        {
            "product_family": pf,
            "mermaid": mermaid,
        },
    )


def converter_view(request):
    code_types = CodeType.objects.all()
    countries = Country.objects.all()
    mode = request.GET.get("mode", "")

    ctx = {
        "code_types": code_types,
        "countries": countries,
        "mode": mode,
    }

    if mode == "code_to_family":
        code = request.GET.get("code", "")
        code_type = request.GET.get("code_type", "")
        country = request.GET.get("country", "")
        date_str = request.GET.get("date", "")
        ctx.update(
            {
                "code_val": code,
                "code_type_val": code_type,
                "country_val": country,
                "date_val": date_str,
                "ctl_searched": True,
            }
        )
        if code and code_type and country and date_str:
            results = _resolve_code(int(code), code_type, country, date_str)
            ctx["ctl_results"] = results

    elif mode == "family_to_code":
        identifier = request.GET.get("identifier", "")
        rev_country = request.GET.get("rev_country", "")
        rev_date = request.GET.get("rev_date", "")
        ctx.update(
            {
                "identifier_val": identifier,
                "rev_country_val": rev_country,
                "rev_date_val": rev_date,
                "ltc_searched": True,
            }
        )
        if identifier and rev_date:
            try:
                date = datetime.date.fromisoformat(rev_date)
            except ValueError:
                date = None
            if date:
                qs = ProductFamily.objects.filter(identifier=identifier)
                if rev_country:
                    qs = qs.filter(iso_country_code=rev_country)
                pfs = list(qs)
                results = []
                for pf in pfs:
                    gens = (
                        pf.generations.filter(
                            introduction__date__lte=date,
                        )
                        .filter(
                            Q(discontinuation__isnull=True) | Q(discontinuation__date__gte=date)
                        )
                        .select_related("introduction", "discontinuation")
                    )
                    if rev_country:
                        gens = gens.filter(iso_country_code=rev_country)
                    for gen in gens:
                        results.append(
                            {
                                "code": gen.code,
                                "start_date": str(gen.start_date),
                                "end_date": str(gen.end_date),
                            }
                        )
                ctx["ltc_results"] = results

    return render(request, "families/converter.html", ctx)
