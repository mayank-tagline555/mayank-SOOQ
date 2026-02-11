from decimal import Decimal

from django.db import models
from django.db.models import DecimalField
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import Sum
from django_softdelete.models import SoftDeleteModel

from account.models import BusinessAccount
from jeweler.models import ManufacturingProductRequestedQuantity
from jeweler.models import ManufacturingRequest
from sooq_althahab.base_models import OwnershipMixin
from sooq_althahab.base_models import UserTimeStampedModelMixin
from sooq_althahab.enums.manufacturer import ManufactureRequestStatus
from sooq_althahab.mixins import CustomIDMixin


class ManufacturingEstimationRequest(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin, OwnershipMixin
):
    """
    Represents an estimation/quote submitted by a manufacturer
    in response to a jeweler's manufacturing request.
    """

    business = models.ForeignKey(
        BusinessAccount,
        on_delete=models.CASCADE,
        related_name="estimation_requests",
    )
    manufacturing_request = models.ForeignKey(
        ManufacturingRequest,
        related_name="estimation_requests",
        on_delete=models.CASCADE,
    )
    status = models.CharField(
        max_length=20,
        choices=ManufactureRequestStatus.choices,
        default=ManufactureRequestStatus.PENDING,
    )
    duration = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Number of days required to produce the product.",
    )
    comment = models.TextField(
        blank=True,
        null=True,
    )
    approved_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    @property
    def total_estimated_cost(self):
        total = self.estimated_prices.annotate(
            total_amount=ExpressionWrapper(
                F("estimated_price") * F("requested_product__quantity"),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            )
        ).aggregate(total_cost=Sum("total_amount"))["total_cost"] or Decimal("0.00")
        return total

    class Meta:
        db_table = "estimation_requests"
        verbose_name = "Estimation Request"
        verbose_name_plural = "Estimation Requests"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Estimation for {self.manufacturing_request} by {self.business}"


class ProductManufacturingEstimatedPrice(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin, OwnershipMixin
):
    """Represents an estimated price for a product manufacturing request"""

    estimation_request = models.ForeignKey(
        ManufacturingEstimationRequest,
        related_name="estimated_prices",
        on_delete=models.CASCADE,
    )
    requested_product = models.ForeignKey(
        ManufacturingProductRequestedQuantity,
        related_name="estimated_prices",
        on_delete=models.CASCADE,
    )
    estimated_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    class Meta:
        db_table = "product_manufacturing_estimated_prices"
        verbose_name = "Product Manufacturing Estimated Price"
        verbose_name_plural = "Product Manufacturing Estimated Prices"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Estimation for {self.requested_product.jewelry_product.product_name}"


class CorrectionValue(SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin):
    """Represents a correction value for manufacturing request"""

    manufacturing_request = models.ForeignKey(
        ManufacturingRequest,
        related_name="correction_values",
        on_delete=models.CASCADE,
    )
    status = models.CharField(
        max_length=20,
        choices=ManufactureRequestStatus.choices,
        default=ManufactureRequestStatus.PENDING,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Correction Value {self.amount} for {self.manufacturing_request} - {self.status}"

    class Meta:
        db_table = "correction_values"
        verbose_name = "Correction Value"
        verbose_name_plural = "Correction Values"
