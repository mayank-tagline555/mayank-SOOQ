from django.db import models

from sooq_althahab.enums.account import RiskLevel


class RiskLevelMixin(models.Model):
    """Abstract model to keep risk level values in models like Musharakah or Pool."""

    risk_level = models.CharField(
        max_length=10,
        choices=RiskLevel.choices,
        help_text="Risk classification such as Low, Medium, or High.",
    )
    equity_min = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Minimum equity percentage for this risk level.",
    )
    equity_max = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Maximum equity percentage for this risk level.",
    )
    max_musharakah_weight = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        default=0,
        help_text="Maximum Musharakah weight for this risk level (in grams).",
    )
    penalty_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Penalty amount associated with this risk level.",
    )

    class Meta:
        abstract = True
