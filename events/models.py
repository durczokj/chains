import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Country(models.Model):
    code = models.CharField(max_length=2, primary_key=True)
    name = models.CharField(max_length=100)
    families_dirty = models.BooleanField(default=False)

    class Meta:
        ordering = ["code"]
        verbose_name_plural = "Countries"

    def __str__(self) -> str:
        return f"{self.code} – {self.name}"


class CodeType(models.Model):
    id = models.CharField(max_length=10, primary_key=True)
    type = models.CharField(max_length=50)

    def __str__(self) -> str:
        return self.type


class Event(models.Model):
    iso_country_code = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        db_column="iso_country_code",
    )
    comment = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["iso_country_code"]),
        ]

    def __str__(self) -> str:
        return f"Event {self.pk} – {self.iso_country_code}"


class TransitionType(models.TextChoices):
    INTRODUCTION = "INTRO", "Introduction"
    DISCONTINUATION = "DISCONT", "Discontinuation"
    chain = "chain", "chain"


class CodeTransition(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="transitions")
    code_type = models.ForeignKey(CodeType, on_delete=models.PROTECT, related_name="transitions")
    type = models.CharField(max_length=7, choices=TransitionType.choices)
    date = models.DateField()

    class Meta:
        ordering = ["date", "pk"]
        indexes = [
            models.Index(fields=["type"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_type_display()} ({self.code_type}) {self.date} – Event {self.event_id}"

    def clean(self) -> None:
        # Validate that exactly one subtype record exists
        if self.pk:
            has_intro = hasattr(self, "introduction")
            has_disco = hasattr(self, "discontinuation")
            has_chain = hasattr(self, "chain")
            if self.type == TransitionType.INTRODUCTION and not has_intro:
                raise ValidationError("Introduction transition requires an Introduction record.")
            elif self.type == TransitionType.DISCONTINUATION and not has_disco:
                raise ValidationError(
                    "Discontinuation transition requires a Discontinuation record."
                )
            elif self.type == TransitionType.chain and not has_chain:
                raise ValidationError("chain transition requires a chain record.")


class Introduction(models.Model):
    code_transition = models.OneToOneField(
        CodeTransition, on_delete=models.CASCADE, related_name="introduction"
    )
    introduction_code = models.BigIntegerField()

    def __str__(self) -> str:
        return f"Introduction introduction_code={self.introduction_code}"


class Discontinuation(models.Model):
    code_transition = models.OneToOneField(
        CodeTransition, on_delete=models.CASCADE, related_name="discontinuation"
    )
    discontinuation_code = models.BigIntegerField()

    def __str__(self) -> str:
        return f"Discontinuation discontinuation_code={self.discontinuation_code}"


class Chain(models.Model):
    code_transition = models.OneToOneField(
        CodeTransition, on_delete=models.CASCADE, related_name="chain"
    )
    introduction_code = models.BigIntegerField()
    discontinuation_code = models.BigIntegerField()

    class Meta:
        verbose_name = "chain"
        verbose_name_plural = "chains"

    def __str__(self) -> str:
        return (
            f"chain introduction={self.introduction_code}"
            f" discontinuation={self.discontinuation_code}"
        )

    def clean(self) -> None:
        if self.introduction_code == self.discontinuation_code:
            raise ValidationError("Introduction and discontinuation codes must differ.")


class CodeState(models.Model):
    """Denormalized per-code state for fast O(1) validation.

    Tracks whether a code is currently active or discontinued, scoped
    per (country, code_type, code).  Updated incrementally as events
    are saved — no full recompute needed.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        DISCONTINUED = "DISCONTINUED", "Discontinued"

    iso_country_code = models.ForeignKey(
        Country,
        on_delete=models.CASCADE,
        db_column="iso_country_code",
    )
    code_type = models.ForeignKey("CodeType", on_delete=models.CASCADE)
    code = models.BigIntegerField()
    status = models.CharField(max_length=13, choices=Status.choices)
    start_date = models.DateField()
    end_date = models.DateField(default=datetime.date(9999, 12, 31))

    class Meta:
        unique_together = [("iso_country_code", "code_type", "code", "start_date")]
        indexes = [
            models.Index(fields=["iso_country_code", "code_type", "code"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return (
            f"CodeState {self.code} ({self.code_type})"
            f" [{self.status}] {self.start_date}\u2013{self.end_date}"
        )
