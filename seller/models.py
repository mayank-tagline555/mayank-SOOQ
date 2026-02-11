from decimal import Decimal

from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models
from django_softdelete.models import SoftDeleteModel

from account.models import BusinessAccount
from account.models import User
from sooq_althahab.base_models import OwnershipMixin
from sooq_althahab.base_models import TimeStampedModelMixin
from sooq_althahab.enums.seller import CertificateType
from sooq_althahab.enums.seller import CommonGradeType
from sooq_althahab.enums.seller import FluorescenceGradeType
from sooq_althahab.enums.seller import PremiumValueType
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.mixins import CustomIDMixin
from sooq_althahab_admin.models import JewelryProductColor
from sooq_althahab_admin.models import MaterialItem
from sooq_althahab_admin.models import MetalCaratType
from sooq_althahab_admin.models import StoneClarity
from sooq_althahab_admin.models import StoneCutShape


class PreciousItem(
    SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin, OwnershipMixin
):
    material_type = models.CharField(max_length=20, choices=MaterialType.choices)
    name = models.CharField(max_length=255, blank=True, db_index=True)
    material_item = models.ForeignKey(
        MaterialItem, on_delete=models.CASCADE, related_name="precious_items"
    )
    description = models.TextField(blank=True)
    premium_value_type = models.CharField(
        max_length=10,
        choices=PremiumValueType.choices,
        default=PremiumValueType.PERCENTAGE,
        help_text="Select whether the premium is entered as a percentage or a fixed amount.",
    )
    premium_price_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0.0000,
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
        help_text="Premium price rate as a decimal (e.g., 0.05 for 5%)",
    )
    premium_price_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    is_enabled = models.BooleanField(default=True, db_index=True)
    additional_features = models.CharField(max_length=255, blank=True, null=True)
    business = models.ForeignKey(
        BusinessAccount, on_delete=models.CASCADE, related_name="precious_items"
    )
    certificate_type = models.CharField(
        max_length=15,
        choices=CertificateType.choices,
        default=CertificateType.NOT_CERTIFIED,
        help_text="Select the certificate type.",
    )
    origin = models.CharField(max_length=100, blank=True, null=True)
    report_number = models.CharField(max_length=50, blank=True, null=True)
    date_of_issue = models.DateField(
        help_text="The date when the certificate was issued.", blank=True, null=True
    )
    width = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    length = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    depth = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    carat_type = models.ForeignKey(
        MetalCaratType,
        on_delete=models.RESTRICT,
        related_name="precious_items",
        blank=True,
        null=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_by_preciousitem",
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_by_preciousitem",
    )

    def __str__(self):
        return f"{self.material_type} - {self.name}"

    class Meta:
        db_table = "precious_items"
        verbose_name = "Precious Item"
        verbose_name_plural = "Precious Items"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["report_number", "organization_id"],
                name="unique_report_number_organization",
            ),
        ]


# TODO: As we decided to keep the file field for the image, it may change later.
class PreciousItemImage(SoftDeleteModel, CustomIDMixin, models.Model):
    precious_item = models.ForeignKey(
        PreciousItem, on_delete=models.CASCADE, related_name="images"
    )
    image = models.CharField(max_length=500, blank=True, null=True)

    def __str__(self):
        return f"Image for {self.precious_item}"

    class Meta:
        db_table = "precious_item_images"
        verbose_name = "Precious Item Image"
        verbose_name_plural = "Precious Item Images"


class PreciousMetal(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    precious_item = models.OneToOneField(
        PreciousItem, on_delete=models.CASCADE, related_name="precious_metal"
    )
    weight = models.DecimalField(max_digits=18, decimal_places=10)
    brand = models.CharField(max_length=100, blank=True, null=True)
    condition = models.CharField(max_length=50, blank=True)
    packaging = models.CharField(max_length=100, blank=True, null=True)
    manufacture_date = models.DateTimeField(blank=True, null=True)
    treatment = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"Metal: {self.precious_item.name}, Type: {self.precious_item.material_type}"

    class Meta:
        db_table = "precious_metals"
        verbose_name = "Precious Metal"
        verbose_name_plural = "Precious Metals"


class PreciousStone(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    precious_item = models.OneToOneField(
        PreciousItem, on_delete=models.CASCADE, related_name="precious_stone"
    )
    weight = models.DecimalField(max_digits=10, decimal_places=2)
    shape_cut = models.ForeignKey(
        StoneCutShape, on_delete=models.RESTRICT, related_name="precious_stones"
    )

    # Only for Round Brilliant diamonds.
    cut_grade = models.CharField(
        max_length=15,
        choices=CommonGradeType.choices,
        default=CommonGradeType.EXCELLENT,
        help_text="Select cut quality grade.",
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    polish = models.CharField(
        max_length=15,
        choices=CommonGradeType.choices,
        default=CommonGradeType.EXCELLENT,
        help_text="Select the polish quality grade.",
    )
    symmetry = models.CharField(
        max_length=15,
        choices=CommonGradeType.choices,
        default=CommonGradeType.EXCELLENT,
        help_text="Select the symmetry quality grade.",
    )
    fluorescence = models.CharField(
        max_length=15,
        choices=FluorescenceGradeType.choices,
        default=FluorescenceGradeType.NONE,
        help_text="Select the fluorescence quality grade.",
    )
    color = models.ForeignKey(
        JewelryProductColor,
        related_name="precious_stone",
        on_delete=models.RESTRICT,
        blank=True,
        null=True,
        help_text="Only for diamonds",
    )
    clarity = models.ForeignKey(
        StoneClarity,
        related_name="precious_stone",
        on_delete=models.RESTRICT,
        blank=True,
        null=True,
    )

    def __str__(self):
        return f"Stone: {self.precious_item.name}, Type: {self.precious_item.material_type}"

    class Meta:
        db_table = "precious_stones"
        verbose_name = "Precious Stone"
        verbose_name_plural = "Precious Stones"
