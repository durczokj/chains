from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Country(models.Model):
    code = models.CharField(max_length=2, primary_key=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["code"]
        verbose_name_plural = "Countries"

    def __str__(self):
        return f"{self.code} – {self.name}"


class CodeType(models.Model):
    id = models.CharField(max_length=10, primary_key=True)
    type = models.CharField(max_length=50)

    def __str__(self):
        return self.type


class Event(models.Model):
    date = models.DateField()
    iso_country_code = models.ForeignKey(
        Country, on_delete=models.PROTECT, db_column="iso_country_code",
    )
    comment = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["iso_country_code"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self):
        return f"Event {self.pk} – {self.iso_country_code} – {self.date}"


class TransitionType(models.TextChoices):
    INTRODUCTION = "INTRO", "Introduction"
    DISCONTINUATION = "DISCONT", "Discontinuation"
    PIPO = "PIPO", "PIPO"


class CodeTransition(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="transitions")
    code_type = models.ForeignKey(CodeType, on_delete=models.PROTECT, related_name="transitions")
    type = models.CharField(max_length=7, choices=TransitionType.choices)

    class Meta:
        indexes = [
            models.Index(fields=["type"]),
        ]

    def __str__(self):
        return f"{self.get_type_display()} ({self.code_type}) – Event {self.event_id}"

    def clean(self):
        # Validate that exactly one subtype record exists
        if self.pk:
            has_intro = hasattr(self, "introduction")
            has_disco = hasattr(self, "discontinuation")
            has_pipo = hasattr(self, "pipo")
            if self.type == TransitionType.INTRODUCTION and not has_intro:
                raise ValidationError("Introduction transition requires an Introduction record.")
            elif self.type == TransitionType.DISCONTINUATION and not has_disco:
                raise ValidationError("Discontinuation transition requires a Discontinuation record.")
            elif self.type == TransitionType.PIPO and not has_pipo:
                raise ValidationError("PIPO transition requires a PIPO record.")


class Introduction(models.Model):
    code_transition = models.OneToOneField(
        CodeTransition, on_delete=models.CASCADE, related_name="introduction"
    )
    pi_code = models.BigIntegerField()

    def clean(self):
        from lifecycles.models import Generation

        if self.code_transition_id:
            ct = self.code_transition
            if Generation.objects.filter(
                code=self.pi_code,
                product_family__code_type=ct.code_type,
                end_date__year=9999,
            ).exists():
                raise ValidationError("PI code is already an active generation.")

    def __str__(self):
        return f"Introduction pi_code={self.pi_code}"


class Discontinuation(models.Model):
    code_transition = models.OneToOneField(
        CodeTransition, on_delete=models.CASCADE, related_name="discontinuation"
    )
    po_code = models.BigIntegerField()

    def clean(self):
        from lifecycles.models import Generation

        if self.code_transition_id:
            ct = self.code_transition
            if not Generation.objects.filter(
                code=self.po_code,
                product_family__code_type=ct.code_type,
                end_date__year=9999,
            ).exists():
                raise ValidationError("PO code is not an active generation.")

    def __str__(self):
        return f"Discontinuation po_code={self.po_code}"


class Pipo(models.Model):
    code_transition = models.OneToOneField(
        CodeTransition, on_delete=models.CASCADE, related_name="pipo"
    )
    pi_code = models.BigIntegerField()
    po_code = models.BigIntegerField()

    class Meta:
        verbose_name = "PIPO"
        verbose_name_plural = "PIPOs"

    def __str__(self):
        return f"PIPO pi={self.pi_code} po={self.po_code}"

    def clean(self):
        if self.pi_code == self.po_code:
            raise ValidationError("PI and PO codes must differ.")

        from lifecycles.models import Generation

        if self.code_transition_id:
            ct = self.code_transition
            if not Generation.objects.filter(
                code=self.po_code,
                product_family__code_type=ct.code_type,
                end_date__year=9999,
            ).exists():
                raise ValidationError("PO code is not an active generation.")
            if not Generation.objects.filter(
                code=self.pi_code,
                product_family__code_type=ct.code_type,
                end_date__year=9999,
            ).exists():
                raise ValidationError("PI code is not an active generation.")
