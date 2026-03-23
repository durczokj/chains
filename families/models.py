import datetime

from django.db import models

from events.models import CodeTransition, CodeType, Country


class ProductFamily(models.Model):
    code_type = models.ForeignKey(
        CodeType, on_delete=models.CASCADE, related_name="product_families"
    )
    identifier = models.CharField(max_length=255, unique=True)
    iso_country_code = models.ForeignKey(
        Country,
        on_delete=models.CASCADE,
        db_column="iso_country_code",
    )

    class Meta:
        ordering = ["iso_country_code", "identifier"]
        verbose_name_plural = "Product families"

    def __str__(self) -> str:
        return self.identifier


class Generation(models.Model):
    product_family = models.ForeignKey(
        ProductFamily, on_delete=models.CASCADE, related_name="generations"
    )
    introduction = models.ForeignKey(
        CodeTransition, on_delete=models.CASCADE, related_name="introduced_generations"
    )
    discontinuation = models.ForeignKey(
        CodeTransition,
        on_delete=models.CASCADE,
        related_name="discontinued_generations",
        null=True,
        blank=True,
    )
    class Meta:
        ordering = ["introduction__date"]

    @property
    def code(self) -> int:
        return self.introduction.introduction.introduction_code

    @property
    def iso_country_code(self) -> str:
        return self.product_family.iso_country_code_id

    @property
    def start_date(self) -> datetime.date:
        return self.introduction.date

    @property
    def end_date(self) -> datetime.date:
        if self.discontinuation:
            return self.discontinuation.date
        return datetime.date(9999, 12, 31)

    def __str__(self) -> str:
        return f"Gen {self.pk} (code:{self.code} {self.start_date}–{self.end_date})"

    @property
    def is_root(self) -> bool:
        return not GenerationLink.objects.filter(successor=self).exists()

    @property
    def is_leaf(self) -> bool:
        return not GenerationLink.objects.filter(predecessor=self).exists()


class GenerationLink(models.Model):
    predecessor = models.ForeignKey(
        Generation, on_delete=models.CASCADE, related_name="successor_links"
    )
    successor = models.ForeignKey(
        Generation, on_delete=models.CASCADE, related_name="predecessor_links"
    )
    source_transition = models.ForeignKey(
        CodeTransition,
        on_delete=models.CASCADE,
        related_name="generation_links",
        null=True,
    )

    class Meta:
        unique_together = [("predecessor", "successor")]

    def __str__(self) -> str:
        return f"Gen {self.predecessor_id} → Gen {self.successor_id}"
