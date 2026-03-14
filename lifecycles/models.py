import datetime

from django.db import models

from events.models import CodeTransition, CodeType


class ProductFamily(models.Model):
    code_type = models.ForeignKey(
        CodeType, on_delete=models.CASCADE, related_name="product_families"
    )
    identifier = models.CharField(max_length=255, unique=True)
    iso_country_code = models.CharField(max_length=2, db_index=True)

    class Meta:
        ordering = ["iso_country_code", "identifier"]
        verbose_name_plural = "Product families"

    def __str__(self):
        return self.identifier


class Generation(models.Model):
    product_family = models.ForeignKey(
        ProductFamily, on_delete=models.CASCADE, related_name="generations"
    )
    source_transition = models.ForeignKey(
        CodeTransition, on_delete=models.CASCADE, related_name="generations"
    )
    code = models.BigIntegerField()
    iso_country_code = models.CharField(max_length=2, db_index=True)
    start_date = models.DateField(default=datetime.date(1970, 1, 1))
    end_date = models.DateField(default=datetime.date(9999, 12, 31))

    class Meta:
        ordering = ["start_date"]

    def __str__(self):
        return f"Gen {self.pk} (code:{self.code} {self.start_date}–{self.end_date})"

    @property
    def is_root(self):
        return not GenerationLink.objects.filter(successor=self).exists()

    @property
    def is_leaf(self):
        return not GenerationLink.objects.filter(predecessor=self).exists()


class GenerationLink(models.Model):
    predecessor = models.ForeignKey(
        Generation, on_delete=models.CASCADE, related_name="successor_links"
    )
    successor = models.ForeignKey(
        Generation, on_delete=models.CASCADE, related_name="predecessor_links"
    )
    source_transition = models.ForeignKey(
        CodeTransition, on_delete=models.CASCADE, related_name="generation_links",
        null=True,
    )

    class Meta:
        unique_together = [("predecessor", "successor")]

    def __str__(self):
        return f"Gen {self.predecessor_id} → Gen {self.successor_id}"
