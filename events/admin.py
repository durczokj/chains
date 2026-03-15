from django.contrib import admin

from events.models import (
    Chain,
    CodeTransition,
    CodeType,
    Country,
    Discontinuation,
    Event,
    Introduction,
)


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ["code", "name"]
    search_fields = ["code", "name"]
    ordering = ["code"]


@admin.register(CodeType)
class CodeTypeAdmin(admin.ModelAdmin):
    list_display = ["id", "type"]


class IntroductionInline(admin.StackedInline):
    model = Introduction
    extra = 0


class DiscontinuationInline(admin.StackedInline):
    model = Discontinuation
    extra = 0


class ChainInline(admin.StackedInline):
    model = Chain
    extra = 0


class CodeTransitionInline(admin.TabularInline):
    model = CodeTransition
    extra = 0
    show_change_link = True


@admin.register(CodeTransition)
class CodeTransitionAdmin(admin.ModelAdmin):
    list_display = ["id", "event", "code_type", "type", "date"]
    list_filter = ["type", "code_type"]
    inlines = [IntroductionInline, DiscontinuationInline, ChainInline]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["id", "iso_country_code", "comment"]
    list_filter = ["iso_country_code"]
    inlines = [CodeTransitionInline]
