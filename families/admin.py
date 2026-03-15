from django.contrib import admin

from families.models import Generation, GenerationLink, ProductFamily


class GenerationInline(admin.TabularInline):
    model = Generation
    extra = 0
    show_change_link = True


@admin.register(ProductFamily)
class ProductFamilyAdmin(admin.ModelAdmin):
    list_display = ["identifier", "iso_country_code", "code_type"]
    list_filter = ["iso_country_code", "code_type"]
    inlines = [GenerationInline]


@admin.register(Generation)
class GenerationAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "product_family",
        "iso_country_code",
        "code",
        "introduction",
        "discontinuation",
    ]


@admin.register(GenerationLink)
class GenerationLinkAdmin(admin.ModelAdmin):
    list_display = ["predecessor", "successor"]
