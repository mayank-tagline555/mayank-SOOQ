from datetime import timedelta
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models import Sum
from django_softdelete.models import SoftDeleteModel

from account.abstract import RiskLevelMixin
from account.models import BusinessAccount
from account.models import User
from investor.models import PreciousItemUnit
from investor.models import PreciousItemUnitMusharakahHistory
from sooq_althahab.base_models import OwnershipMixin
from sooq_althahab.base_models import TimeStampedModelMixin
from sooq_althahab.base_models import UserTimeStampedModelMixin
from sooq_althahab.enums.jeweler import ContractTerminator
from sooq_althahab.enums.jeweler import CostRetailPaymentOption
from sooq_althahab.enums.jeweler import DeliveryRequestStatus
from sooq_althahab.enums.jeweler import DeliveryStatus
from sooq_althahab.enums.jeweler import DesignType
from sooq_althahab.enums.jeweler import ImpactedParties
from sooq_althahab.enums.jeweler import InspectionRejectedByChoices
from sooq_althahab.enums.jeweler import InspectionStatus
from sooq_althahab.enums.jeweler import JewelryProductAttachmentUploadedByChoices
from sooq_althahab.enums.jeweler import LogisticCostPayableBy
from sooq_althahab.enums.jeweler import ManufactureType
from sooq_althahab.enums.jeweler import ManufacturingStatus
from sooq_althahab.enums.jeweler import MaterialSource
from sooq_althahab.enums.jeweler import MusharakahContractStatus
from sooq_althahab.enums.jeweler import Ownership
from sooq_althahab.enums.jeweler import ProductionStatus
from sooq_althahab.enums.jeweler import ProductProductionStatus
from sooq_althahab.enums.jeweler import RefineSellPaymentOption
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.jeweler import StockLocation
from sooq_althahab.enums.jeweler import StockStatus
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.mixins import CustomIDMixin
from sooq_althahab_admin.models import JewelryProductColor
from sooq_althahab_admin.models import JewelryProductType
from sooq_althahab_admin.models import MaterialItem
from sooq_althahab_admin.models import MetalCaratType
from sooq_althahab_admin.models import MusharakahDurationChoices
from sooq_althahab_admin.models import StoneClarity
from sooq_althahab_admin.models import StoneCutShape

#######################################################################################
############################### Jewelry Design Model's ################################
#######################################################################################


class JewelryDesign(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin, OwnershipMixin
):
    """Represents a jewelry designs."""

    business = models.ForeignKey(
        BusinessAccount, on_delete=models.CASCADE, related_name="jewelry_designs"
    )
    design_type = models.CharField(
        max_length=20, choices=DesignType.choices, default=DesignType.SINGLE
    )
    name = models.CharField(max_length=100, null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    duration = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Estimated duration (in days) to complete the collection.",
    )

    class Meta:
        db_table = "jewelry_designs"
        verbose_name = "Jewelry Design"
        verbose_name_plural = "Jewelry Designs"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "business"],
                condition=Q(design_type=DesignType.COLLECTION),
                name="unique_collection_name_per_business",
            )
        ]

    def __str__(self):
        return f"Design: {self.id}"

    @property
    def total_products(self):
        """Returns the total number of jewelry products in the design."""
        return self.jewelry_products.count()


class JewelryProduct(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin, OwnershipMixin
):
    """Represents a jewelry product derived from a jewelry design."""

    jewelry_design = models.ForeignKey(
        JewelryDesign,
        related_name="jewelry_products",
        on_delete=models.CASCADE,
    )
    product_name = models.CharField(max_length=100, blank=True, null=True)
    product_type = models.ForeignKey(
        JewelryProductType, related_name="jewelry_products", on_delete=models.RESTRICT
    )
    description = models.TextField(blank=True, null=True)
    premium_price = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    metal_price = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    weight = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "jewelry_products"
        verbose_name = "Jewelry Product"
        verbose_name_plural = "Jewelry Products"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.id}"


class JewelryProductMaterial(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    """Represents a material used in the creation of a jewelry product."""

    jewelry_product = models.ForeignKey(
        JewelryProduct,
        related_name="product_materials",
        on_delete=models.CASCADE,
    )
    material_type = models.CharField(max_length=10, choices=MaterialType.choices)
    material_item = models.ForeignKey(MaterialItem, on_delete=models.RESTRICT)
    weight = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Enter the quantity for stones only.",
    )
    carat_type = models.ForeignKey(
        MetalCaratType,
        on_delete=models.RESTRICT,
        related_name="jewelry_product_materials",
        blank=True,
        null=True,
    )
    color = models.ForeignKey(
        JewelryProductColor,
        related_name="jewelry_product_materials",
        on_delete=models.RESTRICT,
        blank=True,
        null=True,
    )
    shape_cut = models.ForeignKey(
        StoneCutShape,
        on_delete=models.RESTRICT,
        related_name="jewelry_product_materials",
        blank=True,
        null=True,
    )
    clarity = models.ForeignKey(
        StoneClarity,
        related_name="jewelry_product_materials",
        on_delete=models.RESTRICT,
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "jewelry_product_materials"
        verbose_name = "Jewelry Product Material"
        verbose_name_plural = "Jewelry Product Materials"

    def __str__(self):
        return f"{self.id}"


class JewelryProductAttachment(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    """Represents an attachment (image, document, etc.) for a jewelry product."""

    jewelry_product = models.ForeignKey(
        JewelryProduct,
        related_name="jewelry_product_attachments",
        on_delete=models.CASCADE,
    )
    file = models.CharField(max_length=500, blank=True, null=True)

    class Meta:
        db_table = "jewelry_product_attachments"
        verbose_name = "Jewelry Product Attachment"
        verbose_name_plural = "Jewelry Product Attachments"

    def __str__(self):
        return f"Attachment for {self.jewelry_product.product_name}"


#######################################################################################
############################ Musharakah Contract Request Model's ######################
#######################################################################################


class MusharakahContractRequest(
    SoftDeleteModel,
    CustomIDMixin,
    RiskLevelMixin,
    UserTimeStampedModelMixin,
    OwnershipMixin,
):
    """Represents a Musharakah contract request made by a jeweler for specific materials."""

    jeweler = models.ForeignKey(
        BusinessAccount,
        on_delete=models.CASCADE,
        related_name="jeweler_musharakah_contract_requests",
    )
    investor = models.ForeignKey(
        BusinessAccount,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="investor_musharakah_contract_requests",
    )
    design_type = models.CharField(
        max_length=20, choices=DesignType.choices, default=DesignType.SINGLE
    )
    # Total weight of the jewelry product
    target = models.DecimalField(max_digits=10, decimal_places=2)
    musharakah_equity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Equity percentage set during Musharakah creation, based on the jeweler/designer's risk level range (min to max).",
    )
    status = models.CharField(
        max_length=20, choices=RequestStatus.choices, default=RequestStatus.PENDING
    )
    musharakah_contract_status = models.CharField(
        max_length=20,
        choices=MusharakahContractStatus.choices,
        default=MusharakahContractStatus.NOT_ASSIGNED,
    )
    duration_in_days = models.ForeignKey(
        MusharakahDurationChoices,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        help_text="Select duration from dropdown. Admin-defined options.",
    )
    cash_contribution = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    description = models.TextField(blank=True, null=True)
    termination_reason = models.TextField(blank=True, null=True)
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the musharakah contract request was approved.",
    )
    # Which user terminated or renewed the musharakah contract
    action_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    # Which user has Terminated the musharakah contract request
    terminated_by = models.CharField(
        max_length=20,
        choices=ContractTerminator.choices,
        null=True,
        blank=True,
    )
    investor_signature = models.CharField(
        max_length=500,
        help_text="Digital signature for the asset contribution.",
        null=True,
        blank=True,
    )
    jeweler_signature = models.CharField(
        max_length=500,
        help_text="Digital signature of jeweler for the musharakah contract with investor.",
    )
    # For the adding box number for the availibility of the item by taqabeth admin
    storage_box_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="The storage box number in the admin locker where this musharakah contract asset is stored.",
    )
    impacted_party = models.CharField(
        max_length=20,
        choices=ImpactedParties.choices,
        null=True,
        blank=True,
        help_text="Select the party responsible for termination if the Musharakah Contract is teminated by the admin.",
    )
    terminated_musharakah_contract = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="terminated_contracts",
        help_text="Reference to the original musharakah contract that was terminated.",
    )

    class Meta:
        db_table = "musharakah_contract_requests"
        verbose_name = "Musharakah Contract Request"
        verbose_name_plural = "Musharakah Contract Requests"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.pk}"

    @property
    def expiry_date(self):
        """Return expiry date if approved_at is present, else return duration in days (e.g., "90 days")."""
        if self.musharakah_contract_status == MusharakahContractStatus.RENEW:
            latest_renewal = self.musharakah_contract_renewals.order_by(
                "-created_at"
            ).first()
            if latest_renewal:
                return latest_renewal.expiry_date

        if self.approved_at and self.duration_in_days:
            return self.approved_at + timedelta(days=self.duration_in_days.days)
        elif self.duration_in_days:
            return f"{self.duration_in_days.days} days"
        return None


class MusharakahContractDesign(
    SoftDeleteModel,
    TimeStampedModelMixin,
    CustomIDMixin,
):
    musharakah_contract_request = models.ForeignKey(
        MusharakahContractRequest,
        on_delete=models.CASCADE,
        related_name="musharakah_contract_designs",
    )
    design = models.ForeignKey(
        JewelryDesign,
        on_delete=models.CASCADE,
        related_name="musharakah_contract_designs",
    )

    class Meta:
        db_table = "musharakah_contract_designs"
        verbose_name = "Musharakah Contract Design"
        verbose_name_plural = "Musharakah Contract Designs"


class MusharakahContractRequestQuantity(
    SoftDeleteModel, TimeStampedModelMixin, CustomIDMixin
):
    """Represents a jewelry product request quantity for musharakah request."""

    musharakah_contract_request = models.ForeignKey(
        MusharakahContractRequest,
        related_name="musharakah_contract_request_quantities",
        on_delete=models.CASCADE,
    )
    jewelry_product = models.ForeignKey(
        JewelryProduct,
        related_name="musharakah_contract_request_quantities",
        on_delete=models.CASCADE,
    )
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )

    @property
    def remaining_quantity(self):
        """
        Returns the remaining quantity required for this jewelry product
        after deducting the allocated quantity from manufacturing requests.
        """

        allocated_product_quantity = (
            ManufacturingProductRequestedQuantity.objects.filter(
                jewelry_product=self.jewelry_product,
            ).aggregate(total=Sum("quantity"))["total"]
            or 0
        )

        return (self.quantity or 0) - allocated_product_quantity

    class Meta:
        db_table = "musharkah_contract_request_quantities"
        verbose_name = "Musharakah Contract Request Quantities"
        verbose_name_plural = "Musharakah Contract Request Quantities"

    def __str__(self):
        return f"{self.pk}"


class MusharakahContractRequestAttachment(
    SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin
):
    """File attachments (images, PDFs, etc.) related to a Musharakah request."""

    musharakah_contract_request = models.ForeignKey(
        MusharakahContractRequest,
        related_name="musharakah_contract_request_attachments",
        on_delete=models.CASCADE,
    )
    image = models.CharField(max_length=500, blank=True, null=True)

    class Meta:
        db_table = "musharakah_contract_request_attachments"
        verbose_name = "Musharakah Contract Request Attachment"
        verbose_name_plural = "Musharakah Contract Request Attachments"


class MusharakahContractTerminationRequest(
    SoftDeleteModel, UserTimeStampedModelMixin, OwnershipMixin, CustomIDMixin
):
    """File attachments (images, PDFs, etc.) related to a Musharakah request."""

    musharakah_contract_request = models.ForeignKey(
        MusharakahContractRequest,
        related_name="musharakah_contract_termination_requests",
        on_delete=models.CASCADE,
    )
    status = models.CharField(
        max_length=20, choices=RequestStatus.choices, default=RequestStatus.PENDING
    )
    termination_request_by = models.CharField(
        max_length=50, choices=ContractTerminator.choices
    )
    # Payment related fields
    cost_retail_payment_option = models.CharField(
        max_length=20,
        choices=CostRetailPaymentOption.choices,
        null=True,
        blank=True,
        help_text="Payment option for the musharakah contract termination: pay cost or pay retail.",
    )
    refine_sell_payment_option = models.CharField(
        max_length=20,
        choices=RefineSellPaymentOption.choices,
        null=True,
        blank=True,
        help_text="Payment option for the musharakah contract termination: pay refine or sell.",
    )
    logistics_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Logistics cost for pay's by the investor when jeweler terminate he musharakah contract.",
    )
    refining_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Refining cost for asset processing after termination.",
    )
    sell_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Selling cost for asset disposal after termination.",
    )
    manufacturing_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Manufacturing cost paid by jeweler.",
    )
    retail_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Retail price paid by investor.",
    )
    insurance_fee = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    # Payment tracking flags
    is_jeweler_settlement_payment = models.BooleanField(default=False)
    is_investor_logistic_fee_payment = models.BooleanField(default=False)
    is_investor_refining_cost_payment = models.BooleanField(default=False)
    is_investor_early_termination_payment = models.BooleanField(default=False)
    logistics_cost_payable_by = models.CharField(
        max_length=20,
        choices=LogisticCostPayableBy.choices,
        null=True,
        blank=True,
        help_text="Indicates who will bear the logistics cost: Jeweler or Investor.",
    )

    class Meta:
        db_table = "musharakah_contract_termination_requests"
        verbose_name = "Musharakah Contract Termination Request"
        verbose_name_plural = "Musharakah Contract Termination Requests"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Termination request of {self.musharakah_contract_request}"


class MusharakahContractRenewal(
    SoftDeleteModel, UserTimeStampedModelMixin, CustomIDMixin
):
    """
    Stores the history of renewals for a Musharakah Contract.
    Each time a contract is renewed, a new record is added here.
    """

    musharakah_contract_request = models.ForeignKey(
        MusharakahContractRequest,
        on_delete=models.CASCADE,
        related_name="musharakah_contract_renewals",
    )
    duration_in_days = models.ForeignKey(
        MusharakahDurationChoices,
        on_delete=models.RESTRICT,
        help_text="Select duration from dropdown. Admin-defined options.",
        blank=True,
        null=True,
    )
    reason = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "musharakah_contract_renewals"
        verbose_name = "Musharakah Contract Renewal"
        verbose_name_plural = "Musharakah Contract Renewals"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Renewal of {self.musharakah_contract_request}"

    @property
    def expiry_date(self):
        """Calculate the expiry date based on duration or use custom expiry date."""
        return self.created_at + timedelta(days=self.duration_in_days.days)


#######################################################################################
################################ Manufacturing Request ################################
#######################################################################################


class ManufacturingRequest(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin, OwnershipMixin
):
    """A manufacturing request created by a jeweler to acquire a manufacturer for jewelry design production."""

    business = models.ForeignKey(
        BusinessAccount,
        on_delete=models.CASCADE,
        related_name="jeweler_manufacturing_requests",
    )
    design = models.ForeignKey(
        JewelryDesign,
        on_delete=models.CASCADE,
        related_name="manufacturing_requests",
    )
    manufacturer_type = models.CharField(
        max_length=20,
        choices=ManufactureType.choices,
    )
    expected_completion = models.PositiveIntegerField(
        help_text="Preferred number of days to complete the manufacturing.",
    )
    description = models.TextField(blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=ManufacturingStatus.choices,
        default=ManufacturingStatus.PENDING,
    )
    direct_manufacturers = models.ManyToManyField(
        BusinessAccount,
        related_name="direct_manufacturing_requests",
        blank=True,
        help_text="Only these manufacturers can see the request if it's not a Tender.",
    )
    material_source = models.CharField(
        max_length=20,
        choices=MaterialSource.choices,
        default=MaterialSource.CASH,
    )

    class Meta:
        db_table = "manufacturing_requests"
        verbose_name = "Manufacturing Request"
        verbose_name_plural = "Manufacturing Requests"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.pk}"

    @property
    def correction_amount(self):
        """Returns the total correction amount for this manufacturing request."""
        total = self.correction_values.filter(deleted_at__isnull=True).aggregate(
            total=Sum("amount")
        )["total"]
        return total or 0


class ManufacturingTarget(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    """Manufacturing target related to the production process."""

    manufacturing_request = models.ForeignKey(
        ManufacturingRequest,
        on_delete=models.CASCADE,
        related_name="manufacturing_targets",
    )
    material_type = models.CharField(max_length=10, choices=MaterialType.choices)
    material_item = models.ForeignKey(MaterialItem, on_delete=models.RESTRICT)
    weight = models.DecimalField(max_digits=10, decimal_places=2)
    carat_type = models.ForeignKey(
        MetalCaratType, on_delete=models.RESTRICT, null=True, blank=True
    )
    shape_cut = models.ForeignKey(
        StoneCutShape, on_delete=models.RESTRICT, null=True, blank=True
    )
    quantity = models.IntegerField(
        null=True, blank=True, help_text="Applicable only for stone materials."
    )
    additional_material = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=(
            "Additional material allocated for production: "
            "if the material is metal, enter the extra weight in grams "
            "(supports decimals); if stone, enter the extra quantity "
            "as a number (can include fractional counts for precision)."
        ),
    )
    clarity = models.ForeignKey(
        StoneClarity,
        related_name="manufacturing_targets",
        on_delete=models.RESTRICT,
        blank=True,
        null=True,
    )
    color = models.ForeignKey(
        JewelryProductColor,
        related_name="manufacturing_targets",
        on_delete=models.RESTRICT,
        blank=True,
        null=True,
    )
    metal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    class Meta:
        db_table = "manufacturing_targets"
        verbose_name = "Manufacturing Target"
        verbose_name_plural = "Manufacturing Targets"
        ordering = ["-created_at"]


class ManufacturingProductRequestedQuantity(
    SoftDeleteModel, TimeStampedModelMixin, CustomIDMixin
):
    """Represents a jewelry product request quantity for manufacturing request."""

    manufacturing_request = models.ForeignKey(
        ManufacturingRequest,
        related_name="manufacturing_product_requested_quantities",
        on_delete=models.CASCADE,
    )
    jewelry_product = models.ForeignKey(
        JewelryProduct,
        related_name="manufacturing_product_requested_quantities",
        on_delete=models.CASCADE,
    )
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    production_status = models.CharField(
        max_length=20,
        choices=ProductProductionStatus.choices,
        default=ProductProductionStatus.PENDING,
        help_text="Indicates the current stage of product manufacturing as updated by the manufacturer (e.g., Pending, In Progress, or Completed).",
    )
    jeweler_inspection_status = models.CharField(
        max_length=20,
        choices=RequestStatus.choices,
        default=RequestStatus.PENDING,
        help_text="Status of jewelery inspection by the inspector (e.g., Pending, Approved, or Rejected).",
    )
    admin_inspection_status = models.CharField(
        max_length=20,
        choices=RequestStatus.choices,
        default=RequestStatus.PENDING,
        help_text="Status of admin inspection by the inspector (e.g., Pending, Approved, or Rejected).",
    )
    comment = models.TextField(blank=True, null=True)
    metal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    class Meta:
        db_table = "manufacturing_product_requested_quantities"
        verbose_name = "Manufacturing Product Requested Quantities"
        verbose_name_plural = "Manufacturing Product Requested Quantities"

    def __str__(self):
        return f"{self.pk}"


class InspectedRejectedJewelryProduct(
    SoftDeleteModel, TimeStampedModelMixin, CustomIDMixin
):
    """
    Represents a jewelry product that has been rejected during inspection by a jewelry inspector.
    """

    manufacturing_product = models.ForeignKey(
        ManufacturingProductRequestedQuantity,
        related_name="rejected_inspected_products",
        on_delete=models.CASCADE,
    )
    reason = models.TextField(
        blank=True, null=True, help_text="Reason for rejection during the inspection."
    )
    rejected_by = models.CharField(
        max_length=20,
        choices=InspectionRejectedByChoices.choices,
        help_text="User type who rejected the product (Jeweler or Jewelry Inspector).",
    )

    class Meta:
        db_table = "inspected_rejected_jewelry_products"
        verbose_name = "Inspected & Rejected Jewelry Product"
        verbose_name_plural = "Inspected & Rejected Jewelry Products"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.pk}"


class InspectionRejectionAttachment(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin
):
    """
    Represents an attachment (image, document, etc.) uploaded after a product is rejected during inspection.
    """

    inspected_rejected_product = models.ForeignKey(
        InspectedRejectedJewelryProduct,
        related_name="inspection_rejection_attachments",
        on_delete=models.CASCADE,
    )
    file = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Path or URL to the attachment file (image, document, etc.).",
    )

    class Meta:
        db_table = "inspection_rejection_attachments"
        verbose_name = "Inspection Rejection Attachment"
        verbose_name_plural = "Inspection Rejection Attachments"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.id}"


#######################################################################################
################################ Jewelry Production Model's ###########################
#######################################################################################


class JewelryProduction(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin, OwnershipMixin
):
    """Represents the production process for a specific manufacturing request."""

    manufacturing_request = models.OneToOneField(
        ManufacturingRequest,
        on_delete=models.CASCADE,
        related_name="jewelry_production",
    )
    design = models.ForeignKey(
        JewelryDesign,
        on_delete=models.CASCADE,
        related_name="productions",
    )
    manufacturer = models.ForeignKey(
        BusinessAccount,
        on_delete=models.CASCADE,
        related_name="jewelry_productions",
    )
    production_status = models.CharField(
        max_length=20,
        choices=ProductionStatus.choices,
        default=ProductionStatus.NOT_STARTED,
    )
    is_jeweler_approved = models.BooleanField(default=False)
    admin_inspection_status = models.CharField(
        max_length=20,
        choices=InspectionStatus.choices,
        default=InspectionStatus.PENDING,
    )
    delivery_status = models.CharField(
        max_length=20,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
        help_text="Indicates the delivery status of the completed jewelry products. (e.g., Pending, Out for delivery, or Delivered).",
    )
    material_delivery_status = models.CharField(
        max_length=20,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
        help_text="Indicates the delivery status of the materials that are used in the production (e.g., Pending, Out for delivery, or Delivered).",
    )
    is_payment_completed = models.BooleanField(default=False)
    comment = models.TextField(blank=True, null=True)
    delivery_date = models.DateField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    is_inspected = models.BooleanField(default=False)
    admin_inspected_at = models.DateTimeField(null=True, blank=True)
    inspected_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="inspected_productions",
        null=True,
        blank=True,
    )
    admin_approved_at = models.DateTimeField(null=True, blank=True)
    is_uploaded_to_marketplace = models.BooleanField(default=False)
    remark = models.TextField(blank=True, null=True)
    ownership = models.CharField(
        max_length=20,
        choices=Ownership.choices,
        default=Ownership.JEWELER,
        help_text="Transfer the ownership of jewelry for the designs.",
    )

    class Meta:
        db_table = "jewelry_productions"
        verbose_name = "Jewelry Production"
        verbose_name_plural = "Jewelry Productions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Production for Request {self.manufacturing_request.id}"

    @property
    def stone_price(self):
        """Returns the total stone price associated with this production."""
        total = self.stone_prices.filter(deleted_at__isnull=True).aggregate(
            total=Sum("stone_price")
        )["total"]
        return total or 0


class JewelryProductInspectionAttachment(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin
):
    """Represents an attachment (e.g., image or document) uploaded by the admin after the jewelry product is delivered."""

    jewelry_production = models.ForeignKey(
        JewelryProduction,
        related_name="inspection_attachments",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )

    manufacturing_jewelry_product = models.ForeignKey(
        ManufacturingProductRequestedQuantity,
        related_name="inspection_attachments",
        on_delete=models.CASCADE,
    )

    uploaded_by = models.CharField(
        max_length=20,
        choices=JewelryProductAttachmentUploadedByChoices.choices,
        help_text="User type who uploaded the attachment (Admin or Jewelry Inspector).",
    )

    file = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Path or URL to the attachment file (image, document, etc.).",
    )

    class Meta:
        db_table = "jewelry_product_inspection_attachments"
        verbose_name = "Jewelry Product Inspection Attachment"
        verbose_name_plural = "Jewelry Product Inspection Attachments"

    def __str__(self):
        return f"{self.id}"


class JewelryProductStonePrice(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin
):
    jewelry_production = models.ForeignKey(
        JewelryProduction,
        on_delete=models.CASCADE,
        related_name="stone_prices",
    )
    material_item = models.ForeignKey(MaterialItem, on_delete=models.RESTRICT)
    weight = models.DecimalField(max_digits=10, decimal_places=2)
    shape_cut = models.ForeignKey(
        StoneCutShape, on_delete=models.RESTRICT, null=True, blank=True
    )
    stone_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Stone price (in currency) to be entered by the manufacturer for final payment.",
    )

    class Meta:
        db_table = "jewelry_product_material_price"
        verbose_name = "Jewelry Product Stone Price"
        verbose_name_plural = "Jewelry Product Stone Prices"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Stone price {self.stone_price} for {self.material_item} in product {self.shape_cut}"


class ProductionPayment(SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin):
    """Tracks payments related to the production process."""

    jewelry_production = models.OneToOneField(
        JewelryProduction,
        on_delete=models.CASCADE,
        related_name="payment",
    )
    musharakah_contract = models.ForeignKey(
        MusharakahContractRequest, null=True, blank=True, on_delete=models.SET_NULL
    )
    payment_type = models.CharField(
        max_length=20,
        choices=MaterialSource.choices,
        default=MaterialSource.CASH,
    )
    metal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    stone_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    correction_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    vat = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    platform_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    class Meta:
        db_table = "jewelry_production_payments"
        verbose_name = "Jewelry Production Payment"
        verbose_name_plural = "Jewelry Production Payments"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment for Production {self.jewelry_production.id}"


class ProductionPaymentAssetAllocation(
    SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin
):
    """
    Maps specific PreciousItemUnits (serial-numbered assets) to a Production Payment.

    Ensures traceability of which exact units were used in fulfilling
    a production payment (whether direct asset contributions or via Musharakah Contract assets).
    """

    production_payment = models.ForeignKey(
        ProductionPayment,
        on_delete=models.CASCADE,
        related_name="payment_units",
        help_text="The serial-numbered precious item unit allocated for this payment.",
    )
    precious_item_unit_musharakah = models.ForeignKey(
        PreciousItemUnitMusharakahHistory,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="payment_allocations",
        help_text="The serial-numbered precious item unit of musharakah allocated for this payment.",
    )
    precious_item_unit_asset = models.ForeignKey(
        PreciousItemUnit,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="payment_allocations",
        help_text="The serial-numbered precious item unit of asset allocated for this payment.",
    )
    musharakah_contract = models.ForeignKey(
        MusharakahContractRequest,
        on_delete=models.SET_NULL,
        related_name="payment_units",
        null=True,
        blank=True,
        help_text="Optional Musharakah contract if this unit was linked via Musharakah.",
    )
    weight = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "production_payment_asset_allocations"
        verbose_name = "Production Payment Asset Allocation"
        verbose_name_plural = "Production Payment Asset Allocations"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.pk}"


#######################################################################################
############################### Jewelry Stock Management ############################
#######################################################################################


class JewelryStock(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin, OwnershipMixin
):
    """
    Represents stock management for jewelry products in showroom and marketplace.
    Tracks available quantities separately for showroom and marketplace.
    """

    business = models.ForeignKey(
        BusinessAccount,
        on_delete=models.CASCADE,
        related_name="jewelry_stocks",
        null=True,
        blank=True,
    )
    jewelry_product = models.ForeignKey(
        JewelryProduct,
        on_delete=models.CASCADE,
        related_name="jewelry_stocks",
        help_text="The jewelry product this stock entry belongs to.",
    )
    manufacturing_product = models.ForeignKey(
        ManufacturingProductRequestedQuantity,
        on_delete=models.CASCADE,
        related_name="jewelry_stocks",
        null=True,
        blank=True,
        help_text="The manufacturing product request that created this stock entry.",
    )
    showroom_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Quantity available in showroom.",
    )
    marketplace_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Quantity available in marketplace.",
    )
    showroom_status = models.CharField(
        max_length=20,
        choices=StockStatus.choices,
        default=StockStatus.OUT_OF_STOCK,
        help_text="Stock status for showroom (In Stock or Out of Stock).",
    )
    marketplace_status = models.CharField(
        max_length=20,
        choices=StockStatus.choices,
        default=StockStatus.OUT_OF_STOCK,
        help_text="Stock status for marketplace (In Stock or Out of Stock).",
    )
    location = models.CharField(
        max_length=20,
        choices=StockLocation.choices,
        default=StockLocation.SHOWROOM,
        help_text="Location where the stock is available (Showroom, Marketplace, or Both).",
    )
    is_published_to_marketplace = models.BooleanField(
        default=False,
        help_text="Indicates if the product has been published to marketplace.",
    )

    class Meta:
        db_table = "jewelry_stocks"
        verbose_name = "Jewelry Stock"
        verbose_name_plural = "Jewelry Stocks"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["jewelry_product", "manufacturing_product"],
                condition=Q(deleted_at__isnull=True),
                name="unique_jewelry_stock_per_product",
            )
        ]

    def __str__(self):
        return f"Stock for {self.jewelry_product.product_name} - {self.id}"

    @property
    def total_quantity(self):
        """Returns the total quantity across showroom and marketplace."""
        return self.showroom_quantity + self.marketplace_quantity

    def update_stock_status(self):
        """Automatically update stock status based on quantities."""
        self.showroom_status = (
            StockStatus.IN_STOCK
            if self.showroom_quantity > 0
            else StockStatus.OUT_OF_STOCK
        )
        self.marketplace_status = (
            StockStatus.IN_STOCK
            if self.marketplace_quantity > 0
            else StockStatus.OUT_OF_STOCK
        )
        # Update location based on availability
        if self.showroom_quantity > 0 and self.marketplace_quantity > 0:
            self.location = StockLocation.BOTH
        elif self.showroom_quantity > 0:
            self.location = StockLocation.SHOWROOM
        elif self.marketplace_quantity > 0:
            self.location = StockLocation.MARKETPLACE
        else:
            self.location = StockLocation.SHOWROOM  # Default


class JewelryProductMarketplace(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin, OwnershipMixin
):
    """
    Represents a jewelry product published to the marketplace.
    Tracks marketplace-specific information and published quantities.
    """

    jewelry_product = models.ForeignKey(
        JewelryProduct,
        on_delete=models.CASCADE,
        related_name="marketplace_entries",
        help_text="The jewelry product published to marketplace.",
    )
    jewelry_stock = models.ForeignKey(
        JewelryStock,
        on_delete=models.CASCADE,
        related_name="marketplace_entries",
        null=True,
        blank=True,
        help_text="The stock entry this marketplace publication is based on.",
    )
    published_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Quantity of pieces published to marketplace.",
    )
    description = models.TextField(
        blank=True,
        null=True,
        help_text="Product description for marketplace listing.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Indicates if the product is currently active on marketplace.",
    )
    published_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the product was published to marketplace.",
    )
    unpublished_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the product was unpublished from marketplace.",
    )

    class Meta:
        db_table = "jewelry_product_marketplace"
        verbose_name = "Jewelry Product Marketplace"
        verbose_name_plural = "Jewelry Product Marketplace"
        ordering = ["-published_at"]

    def __str__(self):
        return f"Marketplace: {self.jewelry_product.product_name} - {self.id}"

    def unpublish(self):
        """Unpublish the product from marketplace."""
        from django.utils import timezone

        self.is_active = False
        self.unpublished_at = timezone.now()
        self.save()


class JewelryProductMarketplaceImage(
    SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin
):
    """Represents an image attachment for a marketplace product listing."""

    marketplace = models.ForeignKey(
        JewelryProductMarketplace,
        on_delete=models.CASCADE,
        related_name="marketplace_images",
        help_text="The marketplace product this image belongs to.",
    )
    image = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Path or URL to the image file.",
    )

    class Meta:
        db_table = "jewelry_product_marketplace_images"
        verbose_name = "Jewelry Product Marketplace Image"
        verbose_name_plural = "Jewelry Product Marketplace Images"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Image for {self.marketplace.jewelry_product.product_name} - {self.id}"


class JewelryStockRestockRequest(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin, OwnershipMixin
):
    """
    Represents a restock request when stock is out in showroom or marketplace.
    """

    jewelry_stock = models.ForeignKey(
        JewelryStock,
        on_delete=models.CASCADE,
        related_name="restock_requests",
        help_text="The stock entry that needs restocking.",
    )
    requested_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Quantity requested for restocking.",
    )
    restock_location = models.CharField(
        max_length=20,
        choices=StockLocation.choices,
        help_text="Location where restocking is needed (Showroom or Marketplace).",
    )
    status = models.CharField(
        max_length=20,
        choices=RequestStatus.choices,
        default=RequestStatus.PENDING,
        help_text="Status of the restock request.",
    )
    requested_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date when the restock was requested.",
    )
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Additional notes for the restock request.",
    )

    class Meta:
        db_table = "jewelry_stock_restock_requests"
        verbose_name = "Jewelry Stock Restock Request"
        verbose_name_plural = "Jewelry Stock Restock Requests"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Restock Request {self.id} - {self.jewelry_stock.jewelry_product.product_name}"


#######################################################################################
############################### Jewelry Sales & Profit Distribution ###################
#######################################################################################


class JewelryStockSale(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin, OwnershipMixin
):
    """
    Represents a sale of jewelry product from showroom or marketplace.
    Tracks sales amount and location for profit distribution.
    """

    manufacturing_request = models.ForeignKey(
        ManufacturingRequest,
        on_delete=models.CASCADE,
        related_name="sales",
        help_text="The manufacturing request associated with this sale.",
    )
    jewelry_product = models.ForeignKey(
        JewelryProduct,
        on_delete=models.CASCADE,
        related_name="sales",
        help_text="The jewelry product that was sold.",
    )
    jewelry_stock = models.ForeignKey(
        JewelryStock,
        on_delete=models.CASCADE,
        related_name="sales",
        help_text="The stock entry this sale is associated with.",
    )
    sale_location = models.CharField(
        max_length=20,
        choices=StockLocation.choices,
        help_text="Location where the sale occurred (Showroom or Marketplace).",
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Quantity of pieces sold.",
    )
    sale_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Total sale price for the sold quantity.",
    )
    sale_date = models.DateField(
        help_text="Date when the sale occurred.",
    )
    customer_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Name of the customer who purchased.",
    )
    customer_email = models.EmailField(
        blank=True,
        null=True,
        help_text="Email of the customer.",
    )
    customer_phone = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Phone number of the customer.",
    )
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Additional notes about the sale.",
    )
    status = models.CharField(
        max_length=20,
        choices=DeliveryRequestStatus.choices,
        default=DeliveryRequestStatus.NEW,
        help_text="Current status of the delivery request.",
    )
    delivery_date = models.DateField(
        null=True,
        blank=True,
        help_text="Expected or actual delivery date.",
    )
    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the delivery was completed.",
    )
    delivery_address = models.TextField(
        blank=True,
        null=True,
        help_text="Delivery address of the customer.",
    )

    class Meta:
        db_table = "jewelry_stock_sales"
        verbose_name = "Jewelry Stock Sale"
        verbose_name_plural = "Jewelry Stock Sales"
        ordering = ["-sale_date", "-created_at"]

    def __str__(self):
        return f"Stock Sale {self.id} - {self.jewelry_product.product_name} - {self.quantity} pieces"

    @property
    def unit_price(self):
        """Returns the price per unit."""
        if self.quantity and self.quantity > 0:
            return self.sale_price / self.quantity
        return Decimal("0.00")


class JewelryProfitDistribution(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin, OwnershipMixin
):
    """
    Represents profit distribution for a jewelry sale to investor/jeweler
    who are part of the Musharakah contract for manufacturing this jewelry.
    """

    jewelry_sale = models.ForeignKey(
        JewelryStockSale,
        on_delete=models.CASCADE,
        related_name="profit_distributions",
        help_text="The jewelry sale this profit distribution is for.",
    )
    musharakah_contract = models.ForeignKey(
        MusharakahContractRequest,
        on_delete=models.CASCADE,
        related_name="profit_distributions",
        help_text="The Musharakah contract this profit is distributed from.",
        null=True,
        blank=True,
    )
    recipient_business = models.ForeignKey(
        BusinessAccount,
        on_delete=models.CASCADE,
        related_name="profit_distributions_received",
        help_text="The business (investor or jeweler) receiving the profit.",
    )
    recipient_type = models.CharField(
        max_length=20,
        choices=Ownership.choices,
        help_text="Type of recipient (Jeweler or Investor).",
    )
    cost_of_repurchasing_metal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Cost of repurchasing the metal/gold used in the jewelry.",
    )
    revenue = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total revenue generated from this jewelry sale.",
    )
    profit_share_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Profit share percentage for this recipient based on Musharakah equity.",
    )
    profit_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Profit amount for this recipient (revenue * profit_share_percentage / 100).",
    )
    distributed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the profit was distributed.",
    )

    class Meta:
        db_table = "jewelry_profit_distributions"
        verbose_name = "Jewelry Profit Distribution"
        verbose_name_plural = "Jewelry Profit Distributions"
        ordering = ["-created_at"]

    def __str__(self):
        business_name = (
            self.recipient_business.name if self.recipient_business else "Unknown"
        )
        return f"Profit Distribution {self.id} - {business_name} - {self.profit_amount}"

    def calculate_profit(self):
        """Calculate profit amount based on revenue and profit share percentage."""
        if self.revenue and self.profit_share_percentage:
            self.profit_amount = (
                self.revenue * self.profit_share_percentage / Decimal("100.00")
            )
        return self.profit_amount

    def mark_as_distributed(self):
        """Mark profit as distributed."""
        from django.utils import timezone

        self.distributed_at = timezone.now()
        self.save()
