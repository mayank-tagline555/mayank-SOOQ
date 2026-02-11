import calendar
from datetime import datetime
from datetime import timedelta
from decimal import ROUND_HALF_UP
from decimal import Decimal

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import DecimalField
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import Sum
from django.utils import timezone
from django_softdelete.models import SoftDeleteModel

from account.abstract import RiskLevelMixin
from account.mixins import ReceiptNumberMixin
from account.models import BusinessAccount
from account.models import Organization
from account.models import User
from sooq_althahab.base_models import OwnershipMixin
from sooq_althahab.base_models import TimeStampedModelMixin
from sooq_althahab.base_models import UserTimeStampedModelMixin
from sooq_althahab.enums.account import PlatformChoices
from sooq_althahab.enums.account import SubscriptionBillingFrequencyChoices
from sooq_althahab.enums.account import SubscriptionStatusChoices
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.account import UserType
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.sooq_althahab_admin import FundStatus
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.enums.sooq_althahab_admin import PaymentStatus
from sooq_althahab.enums.sooq_althahab_admin import PoolStatus
from sooq_althahab.enums.sooq_althahab_admin import StoneOrigin
from sooq_althahab.enums.sooq_althahab_admin import (
    SubscriptionPaymentAmountVariabilityChoices,
)
from sooq_althahab.enums.sooq_althahab_admin import SubscriptionPaymentIntervalChoices
from sooq_althahab.enums.sooq_althahab_admin import SubscriptionPaymentTypeChoices
from sooq_althahab.mixins import CustomIDMixin


class MaterialItem(CustomIDMixin, UserTimeStampedModelMixin, OwnershipMixin):
    """
    A generic model representing either a metal or a stone, associated with a material type.
    This model combines both MaterialItem and StoneType with a reference to MaterialType enum.

    Attributes:
        name (CharField): The name of the item (e.g., Gold, Diamond).
        material_type (EnumField): The material type (either metal or stone).
        image (CharField): URL of the image stored in S3.
    """

    name = models.CharField(max_length=100, db_index=True)
    material_type = models.CharField(
        max_length=10, choices=MaterialType.choices, db_index=True
    )
    image = models.CharField(max_length=500, blank=True, null=True)  # URL to S3 image
    global_metal = models.ForeignKey(
        "sooq_althahab_admin.GlobalMetal",
        on_delete=models.CASCADE,
        related_name="material_items",
        null=True,  # Allows null when material_type is 'stone', required for 'metal'
        blank=True,
    )
    is_enabled = models.BooleanField(default=True, db_index=True)
    stone_origin = models.CharField(
        max_length=10,
        choices=StoneOrigin.choices,
        db_index=True,
        default=StoneOrigin.NATURAL,
    )

    def __str__(self):
        return f"{self.name} - {self.material_type}"

    class Meta:
        db_table = "material_items"
        verbose_name = "Material Item"
        verbose_name_plural = "Material Items"
        ordering = ["-created_at"]


class Notification(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    """
    Django model class representing the notification details for a user.

    Attributes:
        user (ForeignKey): A foreign key to the `User` model, representing the user who will receive the notification.
        title (str): The title or subject of the notification.
        message (str): The body or content of the notification.
        type (str): The type of notification, chosen from the `NotificationTypes`
            enumeration.
        is_read (bool): A boolean flag indicating whether the notification has been
            read by the user.
        content_type (ForeignKey): A foreign key to the `ContentType` model, representing the type of the related object.
        object_id (PositiveIntegerField): The primary key of the related object.
        content_object (GenericForeignKey): A generic foreign key that dynamically links the notification to any model instance.

    Meta:
        verbose_name (str): A human-readable name for the model class in singular form.
        verbose_name_plural (str): A human-readable name for the model class in plural form.

    Methods:
        __str__(): Returns a string representation of the notification.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications"
    )
    title = models.CharField(max_length=255, blank=True, null=True)
    message = models.TextField(blank=True, null=True)
    notification_type = models.CharField(
        choices=NotificationTypes.choices,
        max_length=100,
        help_text="Select the notification type",
    )
    is_read = models.BooleanField(default=False)
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True
    )
    object_id = models.CharField(max_length=18, null=True, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        db_table = "notifications"
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ["-created_at"]

    def __str__(self):
        """
        Returns a string representation of the Notification Details.
        """
        return f"{self.user} - {self.title}"


class Pool(
    SoftDeleteModel,
    CustomIDMixin,
    RiskLevelMixin,
    UserTimeStampedModelMixin,
    OwnershipMixin,
):
    """
    Represents a pool of precious metals or stones contributed by investors.
    A pool allows investors to contribute precious materials (e.g., gold, silver) to a collective pool
    for the purpose of investment or trading. Each pool has a status indicating whether it is open or closed.
    """

    musharakah_contract_request = models.ForeignKey(
        "jeweler.MusharakahContractRequest",
        on_delete=models.CASCADE,
        related_name="pools",
        null=True,
        blank=True,
        help_text="Reference to the Musharakah contract request associated with this pool.",
    )
    name = models.CharField(max_length=100)
    material_type = models.CharField(
        max_length=10,
        choices=MaterialType.choices,
        db_index=True,
        null=True,
        blank=True,
    )
    material_item = models.ForeignKey(
        MaterialItem,
        on_delete=models.RESTRICT,
        related_name="pools",
        null=True,
        blank=True,
    )
    carat_type = models.ForeignKey(
        "sooq_althahab_admin.MetalCaratType",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
    )
    cut_shape = models.ForeignKey(
        "sooq_althahab_admin.StoneCutShape",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
    )
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    # Total required contribution for the pool (in grams or carats depending on material type)
    target = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    status = models.CharField(
        max_length=20, choices=PoolStatus.choices, default=PoolStatus.OPEN
    )
    expected_return_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Expected return percentage for the pool, e.g. 15.25%",
    )
    actual_return_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Actual return generated after closing",
    )
    return_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Return amount for this contribution after pool closure.",
    )
    is_active = models.BooleanField(default=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="approved_pools",
        null=True,
        blank=True,
    )
    minimum_investment_grams_per_participant = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Minimum investment amount in grams required per participant.",
    )
    logo = models.CharField(
        max_length=500, null=True, blank=True, help_text="URL or path to the pool logo."
    )
    authority_information = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Domicile or regulatory authority for the pool.",
    )
    fund_objective = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )
    fund_manager = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )
    participation_duration = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Total time (in months) allowed for participants to join the pool.",
    )
    pool_duration = models.PositiveIntegerField(
        null=True, blank=True, help_text="Total duration of the pool in Years."
    )
    terms_and_conditions = models.JSONField(null=True, blank=True)
    management_fee_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0.00,
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
        help_text="Management Fees rate as a decimal (e.g., 0.15 for 15%)",
    )
    performance_fee_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0.00,
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
        help_text="Performance Fees rate as a decimal (e.g., 0.15 for 15%)",
    )

    class Meta:
        db_table = "pools"
        verbose_name = "Pool"
        verbose_name_plural = "Pools"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.material_type})"

    @staticmethod
    def quantize(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.00"), rounding=ROUND_HALF_UP)

    @property
    def remaining_target(self):
        from investor.utils import get_total_weight_of_all_asset_contributed

        if not self.musharakah_contract_request:
            # Only count APPROVED contributions (not PENDING)
            total_contributions = self.asset_contributions.filter(
                pool_contributor__status__in=[
                    RequestStatus.ADMIN_APPROVED,
                    RequestStatus.APPROVED,
                ],
            ).distinct()

            total_weight = get_total_weight_of_all_asset_contributed(
                total_contributions
            )
            remaining = self.target - total_weight

            return {"total_remaining": remaining}

        # Fetch all required materials for the associated Musharakah contract request
        required_materials_qs = self.get_required_materials(
            self.musharakah_contract_request
        )

        material_requirements = {
            "metal": {},
            "stone": {},
        }

        for item in required_materials_qs:
            material_type = item["material_type"]
            item_name = item["material_item__name"]
            carat = item["carat_type__name"]
            shape = item["shape_cut__name"]
            weight = item["weight"]
            total_required_weight = item["total_required_weight"] or Decimal("0")

            if material_type == MaterialType.METAL:
                if item_name not in material_requirements["metal"]:
                    material_requirements["metal"][item_name] = {}
                material_requirements["metal"][item_name][carat] = self.quantize(
                    total_required_weight
                )

            elif material_type == MaterialType.STONE:
                if item_name not in material_requirements["stone"]:
                    material_requirements["stone"][item_name] = {}
                if shape not in material_requirements["stone"][item_name]:
                    material_requirements["stone"][item_name][shape] = {}
                weight_str = str(self.quantize(weight))
                quantity = (total_required_weight / weight).to_integral_value(
                    rounding=ROUND_HALF_UP
                )
                material_requirements["stone"][item_name][shape][weight_str] = int(
                    quantity
                )

        # Iterates through all contributions to subtract them from the required material quantities
        # Only count APPROVED contributions (not PENDING)
        contributions = self.asset_contributions.filter(
            pool_contributor__status__in=[
                RequestStatus.ADMIN_APPROVED,
                RequestStatus.APPROVED,
            ]
        ).select_related(
            "purchase_request__precious_item__precious_stone",
            "purchase_request__precious_item__precious_metal",
        )

        for contribution in contributions:
            pr = contribution.purchase_request
            item = pr.precious_item
            quantity = contribution.quantity or Decimal("0")

            material_type = item.material_type
            item_name = getattr(item.material_item, "name", None)
            carat = getattr(item.carat_type, "name", None)
            shape = (
                getattr(item.precious_stone.shape_cut, "name", None)
                if material_type == MaterialType.STONE
                else None
            )
            weight_per_unit = (
                item.precious_metal.weight
                if material_type == MaterialType.METAL
                else item.precious_stone.weight
            )

            if weight_per_unit is None or item_name is None:
                continue

            # Deducts metal contributions from the required weights
            if material_type == MaterialType.METAL:
                if (
                    item_name in material_requirements["metal"]
                    and carat in material_requirements["metal"][item_name]
                ):
                    contributed_weight = self.quantize(quantity * weight_per_unit)
                    material_requirements["metal"][item_name][
                        carat
                    ] -= contributed_weight
                    if material_requirements["metal"][item_name][carat] < 0:
                        material_requirements["metal"][item_name][carat] = Decimal(
                            "0.00"
                        )
            # Deducts stone contributions from the required quantities
            elif material_type == MaterialType.STONE:
                shape_dict = (
                    material_requirements["stone"].get(item_name, {}).get(shape)
                )
                if not shape_dict:
                    continue
                weight_str = str(self.quantize(weight_per_unit))
                if weight_str in shape_dict:
                    contributed_quantity = int(
                        quantity.to_integral_value(rounding=ROUND_HALF_UP)
                    )
                    shape_dict[weight_str] -= contributed_quantity
                    if shape_dict[weight_str] < 0:
                        shape_dict[weight_str] = 0

        # Returns the remaining required material quantities after subtracting for contributions
        return material_requirements

    def get_required_materials(self, musharakah_contract_request):
        from jeweler.models import JewelryProductMaterial

        required_materials_qs = (
            JewelryProductMaterial.objects.select_related(
                "material_type",
                "material_item",
                "carat_type",
                "shape_cut",
                "jewelry_product",
            )
            .prefetch_related("jewelry_product__musharakah_contract_request_quantities")
            .filter(
                jewelry_product__musharakah_contract_request_quantities__musharakah_contract_request=musharakah_contract_request
            )
            .annotate(
                required_weight=ExpressionWrapper(
                    F("weight")
                    * F(
                        "jewelry_product__musharakah_contract_request_quantities__quantity"
                    ),
                    output_field=DecimalField(max_digits=20, decimal_places=2),
                )
            )
            .values(
                "material_type",
                "material_item__name",
                "carat_type__name",
                "shape_cut__name",
                "weight",
            )
            .annotate(total_required_weight=Sum("required_weight"))
        )
        return required_materials_qs


class PoolContribution(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    """Represents a contribution made by an investor to a specific pool."""

    pool = models.ForeignKey(
        Pool, related_name="pool_contributions", on_delete=models.CASCADE
    )
    participant = models.ForeignKey(
        BusinessAccount, related_name="pool_contributions", on_delete=models.CASCADE
    )
    # # The profit amount returned to the contributor after the pool is closed.
    return_amount = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    # Total weight of all assets contributed by the investor
    weight = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    distributed_on = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=RequestStatus.choices, default=RequestStatus.PENDING
    )
    fund_status = models.CharField(
        max_length=20, choices=FundStatus.choices, default=FundStatus.OPEN
    )

    signature = models.CharField(
        max_length=500,
        help_text="Digital signature for the asset contribution in pool.",
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "pool_contributions"
        verbose_name = "Pool Contribution"
        verbose_name_plural = "Pool Contributions"

    def __str__(self):
        return f"{self.participant.name} - {self.pool.name} - {self.status}"


class GlobalMetal(CustomIDMixin, TimeStampedModelMixin):
    """
    Represents globally recognized metals with their name and symbol.
    """

    name = models.CharField(max_length=100, unique=True, db_index=True)
    # Symbole for fetch live price from Gold API. e.g., XAU, XAG, XPT
    symbol = models.CharField(max_length=10, unique=True, db_index=True)

    def __str__(self):
        return f"{self.name} ({self.symbol})"

    class Meta:
        db_table = "global_metals"
        verbose_name = "Global Metal"
        verbose_name_plural = "Global Metals"


class MetalPriceHistory(CustomIDMixin, TimeStampedModelMixin):
    """
    Stores live metal price history linked to global metals.
    """

    global_metal = models.ForeignKey(
        GlobalMetal, on_delete=models.CASCADE, related_name="price_histories"
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    price_on_date = models.DateTimeField()

    def __str__(self):
        return f"{self.global_metal.name} ({self.global_metal.symbol}) - {self.price} at {self.created_at}"

    class Meta:
        db_table = "metal_price_histories"
        verbose_name = "Metal Price History"
        verbose_name_plural = "Metal Price Histories"
        indexes = [
            models.Index(fields=["global_metal", "created_at"]),
        ]


class OrganizationBankAccount(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin
):
    """Represents a bank account associated with an organization."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="organization_bank_accounts",
    )
    bank_name = models.CharField(
        max_length=255,
        help_text="The name of the bank where the account is held.",
    )
    account_number = models.CharField(
        max_length=20,
        help_text="The bank account number",
    )
    account_name = models.CharField(
        max_length=255,
        help_text="The name associated with the bank account.",
    )
    iban_code = models.CharField(
        max_length=34,
        blank=True,
        null=True,
        help_text="The IBAN number for international and local transactions.",
    )
    swift_code = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        help_text="A unique code used to identify the bank for international transactions.",
    )

    def __str__(self):
        """
        Returns a string representation of the bank account.
        """
        return f"{self.account_name} - {self.account_number}"

    class Meta:
        db_table = "organization_bank_account"
        verbose_name = "Organization Bank Account"
        verbose_name_plural = "Organization Bank Accounts"


class BaseNamedModel(CustomIDMixin, TimeStampedModelMixin, OwnershipMixin):
    """Abstract base model for entities with a name and is_enabled flag."""

    name = models.CharField(max_length=100, unique=True)
    is_enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name}"

    class Meta:
        abstract = True


class StoneCutShape(BaseNamedModel):
    """Represents a cut shape of a precious stone."""

    class Meta:
        db_table = "stone_cut_shape"
        verbose_name = "Stone Cut Shape"
        verbose_name_plural = "Stone Cut Shapes"
        ordering = ["-created_at"]


class MetalCaratType(BaseNamedModel):
    """Represents a carat type of a precious metal."""

    purity_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Purity of gold in percentage (e.g., 99.9 for 24K)",
    )

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "metal_carat_type"
        verbose_name = "Metal Carat Type"
        verbose_name_plural = "Metal Carat Types"
        ordering = ["-created_at"]


class JewelryProductType(BaseNamedModel):
    """Represents a jewelry product type for jewelry design product."""

    class Meta:
        db_table = "jewelry_product_type"
        verbose_name = "Jewelry Product Type"
        verbose_name_plural = "Jewelry Product Types"
        ordering = ["-created_at"]


class JewelryProductColor(BaseNamedModel):
    """Represents a jewelry product color for jewelry design product."""

    class Meta:
        db_table = "jewelry_product_color"
        verbose_name = "Jewelry Product Color"
        verbose_name_plural = "Jewelry Product Colors"
        ordering = ["-created_at"]


class StoneClarity(BaseNamedModel):
    """Represents the clarity grade of a precious item."""

    class Meta:
        db_table = "stone_clarity"
        verbose_name = "Stone Clarity"
        verbose_name_plural = "Stone Clarities"
        ordering = ["-created_at"]


class BusinessSavedCardToken(SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin):
    business = models.ForeignKey(
        BusinessAccount,
        related_name="business_saved_card_tokens",
        on_delete=models.CASCADE,
    )
    token = models.CharField(max_length=16, unique=True)
    number = models.CharField(max_length=16)
    expiry_month = models.CharField(max_length=2)
    expiry_year = models.CharField(max_length=2)
    card_type = models.CharField(max_length=20)  # e.g., DEBIT, CREDIT
    card_brand = models.CharField(max_length=20)  # e.g., Visa, MasterCard
    is_used_for_subscription = models.BooleanField(default=False)

    class Meta:
        db_table = "business_saved_card_tokens"
        verbose_name = "Business Saved Card Token"
        verbose_name_plural = "Business Saved Card Tokens"

        constraints = [
            models.UniqueConstraint(
                fields=["business"],
                condition=models.Q(is_used_for_subscription=True),
                name="unique_active_subscription_token_per_business",
            )
        ]


class SubscriptionPlan(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin, OwnershipMixin
):
    name = models.CharField(max_length=100)
    translated_names = models.JSONField(
        blank=True,
        null=True,
        help_text="Stores subscription plan name in multiple languages, e.g., {'en': 'Seller Plan', 'ar': 'خطة البائع'}",
    )
    role = models.CharField(max_length=30, choices=UserRoleBusinessChoices)
    business_type = models.CharField(
        max_length=30, choices=UserType, default=UserType.BUSINESS
    )
    subscription_code = models.CharField(max_length=12, unique=True)
    duration = models.PositiveIntegerField(
        default=12,
        help_text="Duration of the subscription in months",
        validators=[MinValueValidator(1)],
    )
    # How often recurring billing cycles are generated (monthly or yearly). Used for subscription renewals and recurring charges. The INITIAL billing period follows the subscription duration field.
    billing_frequency = models.CharField(
        max_length=20,
        choices=SubscriptionBillingFrequencyChoices,
        default=SubscriptionBillingFrequencyChoices.MONTHLY,
        help_text="How the customer actually billed: monthly, or yearly",
    )
    # The payment interval for the subscription fee: monthly, quarterly, or yearly. This defines how often the customer pays. Should match or align with the subscription duration.
    payment_interval = models.CharField(
        max_length=20,
        choices=SubscriptionPaymentIntervalChoices.choices,
        default=SubscriptionPaymentIntervalChoices.MONTHLY,
        help_text="How the customer actually pays: monthly, or yearly",
    )
    payment_amount_variability = models.CharField(
        max_length=10,
        choices=SubscriptionPaymentAmountVariabilityChoices,
        default=SubscriptionPaymentAmountVariabilityChoices.FIXED,
        help_text="Specifies whether the subscription payment amount is fixed or varies over time.",
    )
    subscription_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    discounted_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    intro_grace_period_days = models.PositiveIntegerField(
        default=0,
        help_text="One-time free days added to the first billing cycle.",
    )
    commission_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=0.00,
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
        help_text="Commission rate as a decimal (e.g., 0.05 for 5%)",
    )
    pro_rata_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=0.00,
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
        help_text="Pro rata rate as a decimal (e.g., 0.05 for 5%)",
    )
    description = models.JSONField()
    is_active = models.BooleanField(default=True)
    payment_type = models.CharField(
        max_length=10,
        choices=SubscriptionPaymentTypeChoices.choices,
        default=SubscriptionPaymentTypeChoices.PREPAID,
        help_text="Defines whether the plan is prepaid or postpaid",
    )

    # Free Trial Limitation Fields (for JEWELER role only)
    musharakah_request_max_weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum metal weight in grams that the Jeweler can request when joining a Musharakah pool (Free Trial Only)",
    )
    metal_purchase_max_weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum metal weight in grams that the Jeweler can buy from the app (Free Trial Only)",
    )
    max_design_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum number of designs the Jeweler can upload (Free Trial Only)",
    )
    # Subscription Features - Controls which features are available in this plan
    features = models.JSONField(
        blank=True,
        null=True,
        default=list,
        help_text="List of enabled features for this subscription plan. Example: ['PURCHASE_ASSETS', 'JOIN_POOLS', 'JOIN_MUSHARAKAH']",
    )

    class Meta:
        db_table = "subscription_plans"
        verbose_name = "Subscription Plan"
        verbose_name_plural = "Subscription Plans"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.role})"


class BusinessSubscriptionPlan(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin
):
    """Represents a user's subscription to a service."""

    business = models.ForeignKey(
        BusinessAccount,
        related_name="business_subscription_plan",
        on_delete=models.CASCADE,
    )
    subscription_plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="business_subscription_plan",
    )
    start_date = models.DateField()
    expiry_date = models.DateField(null=True, blank=True)
    cancelled_date = models.DateField(null=True, blank=True)

    # NEW BILLING DATE FIELDS
    subscription_name = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Subscription plan name at the time of purchase",
    )
    billing_day = models.PositiveIntegerField(
        default=1,
        help_text="Day of the month when billing occurs (1-31). For end of month, use 31.",
    )
    next_billing_date = models.DateField(
        null=True, blank=True, help_text="Next scheduled billing date"
    )
    last_billing_date = models.DateField(
        null=True, blank=True, help_text="Last successful billing date"
    )
    billing_cycle_count = models.PositiveIntegerField(
        default=0, help_text="Number of billing cycles completed"
    )
    # How often billing cycles are generated. Used for RECURRING billing after initial subscription. Monthly bills every month, Yearly bills every year. The INITIAL billing period is based on subscription duration, not this field.
    billing_frequency = models.CharField(
        max_length=20,
        choices=SubscriptionBillingFrequencyChoices,
        default=SubscriptionBillingFrequencyChoices.MONTHLY,
    )
    # The payment interval for the subscription fee: monthly, quarterly, or yearly. This defines how often the customer pays. Should match or align with the subscription duration.
    payment_interval = models.CharField(
        max_length=20,
        choices=SubscriptionPaymentIntervalChoices.choices,
        default=SubscriptionPaymentIntervalChoices.MONTHLY,
        help_text="How the customer actually pays: monthly, or yearly",
    )
    subscription_fee = models.DecimalField(max_digits=10, decimal_places=2)
    intro_grace_period_days = models.PositiveIntegerField(
        default=0,
        help_text="Grace days applied to the first billing cycle (copied from plan).",
    )
    intro_grace_applied = models.BooleanField(
        default=False,
        help_text="Indicates whether the one-time grace days were granted.",
    )
    commission_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=0.00,
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
        help_text="Commission rate as a decimal (e.g., 0.05 for 5%)",
    )
    pro_rata_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=0.00,
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
        help_text="Pro rata rate as a decimal (e.g., 0.05 for 5%)",
    )
    payment_amount_variability = models.CharField(
        max_length=10,
        choices=SubscriptionPaymentAmountVariabilityChoices,
        default=SubscriptionPaymentAmountVariabilityChoices.FIXED,
        help_text="Specifies whether the subscription payment amount is fixed or varies over time.",
    )
    credimax_3ds_transaction_id = models.CharField(max_length=20, null=True, blank=True)
    business_saved_card_token = models.OneToOneField(
        BusinessSavedCardToken,
        related_name="business_subscription_plan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatusChoices,
        default=SubscriptionStatusChoices.PENDING,
    )
    is_auto_renew = models.BooleanField(default=True)

    # NEW BILLING CONFIGURATION FIELDS
    grace_period_days = models.PositiveIntegerField(
        default=3, help_text="Number of days to retry failed payments before suspending"
    )
    max_retry_attempts = models.PositiveIntegerField(
        default=3, help_text="Maximum number of payment retry attempts"
    )
    retry_count = models.PositiveIntegerField(
        default=0, help_text="Current number of retry attempts for failed payment"
    )
    payment_type = models.CharField(
        max_length=10,
        choices=SubscriptionPaymentTypeChoices.choices,
        default=SubscriptionPaymentTypeChoices.PREPAID,
        help_text="Defines whether the plan is prepaid or postpaid",
    )

    # PENDING PLAN CHANGE - Simple approach with only 2 fields
    # When admin updates the plan, we store the new plan ID and effective date
    # At the next billing cycle, we apply the changes by updating all fields from the new plan
    pending_subscription_plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pending_business_subscriptions",
        help_text="New subscription plan to be applied at next billing cycle",
    )
    pending_plan_effective_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date when the pending plan will take effect (next billing date)",
    )
    # Subscription Features - Stored at time of purchase/update
    # This ensures users keep their original features even if admin updates the subscription plan
    features = models.JSONField(
        blank=True,
        null=True,
        default=list,
        help_text="List of enabled features for this subscription. Copied from subscription plan at purchase time. Example: ['PURCHASE_ASSETS', 'JOIN_POOLS', 'JOIN_MUSHARAKAH']",
    )

    def save(self, *args, **kwargs):
        # CRITICAL: Set billing_day from start_date on creation
        # This ensures billing continues on the same day of month as activation
        # Example: Activated on Oct 13 → billing_day = 13 → bills on 13th each month
        is_new = not self.pk
        if is_new and self.start_date:
            # Extract day from start_date (e.g., 13 from Oct 13)
            self.billing_day = self.start_date.day

        # Set initial next_billing_date if not set
        # IMPORTANT: Don't override if intro_grace_applied is True (grace period sets next_billing_date)
        # For initial subscriptions, next_billing_date should equal expiry_date
        # This is set by _compute_initial_subscription_dates in the serializer
        # Only calculate if not already set and we have expiry_date
        if (
            not self.next_billing_date
            and self.start_date
            and not self.intro_grace_applied
        ):
            # Use expiry_date if available (for initial subscription)
            # Otherwise fall back to calculating from start_date
            if self.expiry_date:
                self.next_billing_date = self.expiry_date
            else:
                self.next_billing_date = self.calculate_next_billing_date(
                    self.start_date
                )
        super().save(*args, **kwargs)

    def calculate_next_billing_date(self, from_date=None):
        """
        Calculate the next billing date based on billing frequency and billing day.

        IMPORTANT: This method is used for RECURRING billing cycles after the initial subscription.
        For the initial subscription billing period, use expiry_date or the full subscription duration.

        Args:
            from_date: Date to calculate from. Defaults to last_billing_date or start_date.

        Returns:
            Date: The next billing date based on billing_frequency
        """
        if not from_date:
            from_date = self.last_billing_date or self.start_date

        if self.billing_frequency == SubscriptionBillingFrequencyChoices.MONTHLY:
            return self._calculate_next_monthly_billing_date(from_date)
        elif self.billing_frequency == SubscriptionBillingFrequencyChoices.YEARLY:
            return self._calculate_next_yearly_billing_date(from_date)

        return from_date

    def _calculate_next_monthly_billing_date(self, from_date):
        """
        Calculate next monthly billing date.

        CRITICAL: Uses the DAY from from_date, not self.billing_day
        This ensures if you activate on Oct 13, you bill on 13th each month
        """
        # Get next month
        if from_date.month == 12:
            next_month = 1
            next_year = from_date.year + 1
        else:
            next_month = from_date.month + 1
            next_year = from_date.year

        # Use the same day from from_date
        # Example: from_date = Oct 13 → use day 13 for next month
        target_day = from_date.day

        # Adjust if day doesn't exist in target month (e.g., Jan 31 → Feb 28)
        last_day_of_month = calendar.monthrange(next_year, next_month)[1]
        billing_day = min(target_day, last_day_of_month)

        return datetime(next_year, next_month, billing_day).date()

    def _calculate_next_yearly_billing_date(self, from_date):
        """Calculate next yearly billing date."""
        next_year = from_date.year + 1

        # Handle February 29th edge case for yearly billing
        if from_date.month == 2 and from_date.day == 29:
            if not calendar.isleap(next_year):
                return datetime(next_year, 2, 28).date()

        try:
            return datetime(next_year, from_date.month, from_date.day).date()
        except ValueError:
            # Handle edge cases like Feb 30/31
            last_day = calendar.monthrange(next_year, from_date.month)[1]
            return datetime(next_year, from_date.month, last_day).date()

    def is_due_for_billing(self):
        """Check if subscription is due for billing."""
        if not self.next_billing_date:
            return False

        today = timezone.now().date()
        return today >= self.next_billing_date

    def update_billing_after_success(self):
        """
        Update subscription after successful billing and payment.

        Steps:
        1. Update last_billing_date based on payment type:
           - PREPAID: Set to next_billing_date (end of future period we just paid for)
           - POSTPAID: Set to today (end of past period we just charged for)
        2. Apply pending plan changes if any (moves pending → active, clears pending fields)
        3. Calculate next_billing_date for the next cycle
        4. Increment billing_cycle_count
        5. Reset retry_count to 0
        6. Extend expiry_date if needed

        Example PREPAID: Billed period Jan 21 - Feb 21 (future period):
        - last_billing_date = Feb 21 (end of period we paid for)
        - next_billing_date = Mar 21 (calculated from Feb 21)
        - billing_cycle_count += 1

        Example POSTPAID: Billed period Dec 21 - Jan 21 (past period):
        - last_billing_date = Jan 21 (today, end of period we charged for)
        - next_billing_date = Feb 21 (calculated from Jan 21)
        - billing_cycle_count += 1
        """
        from django.utils import timezone

        from sooq_althahab.enums.sooq_althahab_admin import (
            SubscriptionPaymentTypeChoices,
        )

        # For PREPAID: The period we just billed ends at next_billing_date (future period)
        # For POSTPAID: The period we just billed ends at today (past period that just ended)
        today = timezone.now().date()

        if self.payment_type == SubscriptionPaymentTypeChoices.POSTPAID:
            # POSTPAID: Billing ran today for the period that ended yesterday.
            # Keep last_billing_date as today (the day we charged),
            # but use yesterday as the reference to compute the next billing date
            period_end_for_next_cycle = today - timedelta(days=1)
            self.last_billing_date = today
        else:
            # PREPAID: We paid for future period, so last_billing_date = next_billing_date
            period_end_for_next_cycle = self.next_billing_date
            self.last_billing_date = period_end_for_next_cycle

        # Apply pending plan changes if any
        # NOTE: Billing was done using pending plan fee (if it existed)
        # Now move pending → active and clear pending fields for next cycle
        if self.has_pending_plan_changes():
            import logging

            logger = logging.getLogger(__name__)

            old_fee = self.subscription_fee

            self.apply_pending_plan_changes()

            logger.info(
                f"[SUBSCRIPTION] Applied plan changes for {self.id}: "
                f"Fee {old_fee} → {self.subscription_fee}"
            )

        # Calculate next billing date from the end of the current period
        # This maintains the billing cycle pattern (e.g., 13th of each month)
        # If plan was changed, this will use the new billing frequency
        # For PREPAID: billed_period_end = next_billing_date (future period end)
        # For POSTPAID: billed_period_end = today (past period end)
        # Both should calculate next billing date from the period end
        calculated_next_billing_date = self.calculate_next_billing_date(
            period_end_for_next_cycle
        )

        # CRITICAL: For fixed-duration subscriptions (e.g., 12-month plan with monthly billing),
        # don't set next_billing_date beyond expiry_date. This ensures billing stops when
        # subscription period ends, rather than extending indefinitely.
        # If calculated date exceeds expiry_date, set it to expiry_date (final billing)
        if self.expiry_date and calculated_next_billing_date > self.expiry_date:
            self.next_billing_date = self.expiry_date
        else:
            self.next_billing_date = calculated_next_billing_date

        self.billing_cycle_count += 1
        self.retry_count = 0

        # IMPORTANT: For fixed-duration subscriptions (e.g., 12-month plan with monthly billing),
        # preserve the original expiry_date. Don't extend it.
        # The expiry_date represents the total subscription duration and should remain fixed.
        # Only extend expiry_date if it's None (shouldn't happen for proper subscriptions)
        # or if we need to handle edge cases for ongoing subscriptions without fixed end dates.
        # For most subscriptions, expiry_date is set at creation and should not be modified.
        if self.expiry_date is None:
            # No expiry_date set - calculate and set it (edge case)
            if self.billing_frequency == SubscriptionBillingFrequencyChoices.MONTHLY:
                self.expiry_date = self._calculate_next_monthly_billing_date(
                    self.next_billing_date
                )
            elif self.billing_frequency == SubscriptionBillingFrequencyChoices.YEARLY:
                self.expiry_date = self._calculate_next_yearly_billing_date(
                    self.next_billing_date
                )
        # For fixed-duration subscriptions, expiry_date is already set correctly at creation
        # and should not be extended. The subscription will naturally expire when expiry_date is reached.

        self.save()

    def update_billing_after_failure(self):
        """Update retry count after failed payment."""
        self.retry_count += 1
        if self.retry_count >= self.max_retry_attempts:
            # Move to next billing cycle but mark as failed
            self.next_billing_date = self.calculate_next_billing_date()
            self.retry_count = 0
        self.save()

    def apply_pending_plan_changes(self):
        """
        Move pending plan to active plan and clear pending fields.

        Updates all subscription fields from pending_subscription_plan:
        - subscription_plan, subscription_name
        - billing_frequency, payment_interval
        - subscription_fee, commission_rate, pro_rata_rate
        - payment_amount_variability, payment_type

        Then clears: pending_subscription_plan, pending_plan_effective_date

        Returns:
            bool: True if changes were applied, False if no pending plan
        """
        if not self.pending_subscription_plan:
            return False

        new_plan = self.pending_subscription_plan

        # Update all subscription fields from the new plan
        self.subscription_plan = new_plan
        self.subscription_name = new_plan.name
        self.billing_frequency = new_plan.billing_frequency
        self.payment_interval = new_plan.payment_interval
        self.payment_amount_variability = new_plan.payment_amount_variability
        self.payment_type = new_plan.payment_type

        # Use discounted fee if available, otherwise regular fee
        self.subscription_fee = (
            new_plan.discounted_fee or new_plan.subscription_fee or Decimal("0.00")
        )
        self.commission_rate = new_plan.commission_rate
        self.pro_rata_rate = new_plan.pro_rata_rate
        # Update features from the new plan
        self.features = new_plan.features or []

        # Clear pending fields
        self.pending_subscription_plan = None
        self.pending_plan_effective_date = None

        self.save()
        return True

    def has_pending_plan_changes(self):
        """Check if there are pending plan changes."""
        return bool(self.pending_subscription_plan)

    def should_apply_pending_changes(self, check_date=None):
        """
        Check if pending plan changes should be applied based on the effective date.

        Args:
            check_date: Date to check against (defaults to today)

        Returns:
            bool: True if pending changes should be applied
        """
        if not self.has_pending_plan_changes():
            return False

        if check_date is None:
            from django.utils import timezone

            check_date = timezone.now().date()

        return (
            self.pending_plan_effective_date
            and check_date >= self.pending_plan_effective_date
        )

    class Meta:
        db_table = "business_subscription_plans"
        verbose_name = "Business Subscription Plan"
        verbose_name_plural = "Business Subscription Plans"

    def __str__(self):
        return self.pk


class SubscriptionBillingHistory(CustomIDMixin, UserTimeStampedModelMixin):
    """Track billing history for subscriptions."""

    subscription = models.ForeignKey(
        BusinessSubscriptionPlan,
        related_name="billing_history",
        on_delete=models.CASCADE,
    )
    billing_date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=[
            ("SUCCESS", "Success"),
            ("FAILED", "Failed"),
            ("PENDING", "Pending"),
            ("CANCELLED", "Cancelled"),
        ],
        default="PENDING",
    )
    payment_method = models.CharField(max_length=50, null=True, blank=True)
    transaction_id = models.CharField(max_length=100, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    retry_attempt = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "subscription_billing_history"
        verbose_name = "Subscription Billing History"
        verbose_name_plural = "Subscription Billing Histories"
        ordering = ["-billing_date"]


class MusharakahDurationChoices(CustomIDMixin, TimeStampedModelMixin, OwnershipMixin):
    name = models.CharField(max_length=50, unique=True)  # e.g., "3 Months"
    days = models.PositiveIntegerField()  # e.g., 90
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "musharakah_duration_choices"
        verbose_name = "Musharakah Duration Choice"
        verbose_name_plural = "Musharakah Duration Choices"
        ordering = ["days"]

    def __str__(self):
        return self.pk


######################################################################################
############ Manufacturing and Products sending to marketplace and manage ############
######################################################################################


class MarketplaceProduct(SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin):
    """Tracks jewelry product to a marketplace platform."""

    product = models.OneToOneField(
        "jeweler.JewelryProduction",
        on_delete=models.CASCADE,
        related_name="marketplace",
    )
    magento_product_id = models.CharField(max_length=100, blank=True, null=True)
    # Please manage created at and created by for user tracking

    class Meta:
        db_table = "marketplace_product"
        verbose_name = "Marketplace Product"
        verbose_name_plural = "Marketplace Products"


class BillingDetails(
    SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin, ReceiptNumberMixin
):
    business = models.ForeignKey(
        BusinessAccount, related_name="billing_details", on_delete=models.RESTRICT
    )
    receipt_number = models.CharField(max_length=50, unique=True)
    # Custom invoice number generated when request is approved.
    invoice_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        unique=True,
        help_text="Custom invoice number generated when billing is completed.",
    )
    period_start_date = models.DateField()
    period_end_date = models.DateField()

    base_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    commission_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    service_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        null=True,
        blank=True,
    )
    vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,  # up to 0.9999 (i.e., 99.99%)
        null=True,
        blank=True,
        help_text="VAT rate as a decimal (e.g., 0.05 for 5%)",
    )
    vat_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,  # up to 0.9999 (i.e., 99.99%)
        null=True,
        blank=True,
        help_text="TAX rate as a decimal (e.g., 0.05 for 5%)",
    )
    tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        null=True,
        blank=True,
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Final total payable amount for this billing.",
    )
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "billing_details"
        verbose_name = "Billing Detail"
        verbose_name_plural = "Billing Details"
        ordering = ["-period_start_date"]

    def __str__(self):
        return f"Billing for {self.business.name} ({self.period_start_date} to {self.period_end_date})"

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            subscription_type = self.get_subscription_type_code()
            self.receipt_number = self.generate_receipt_number(
                users_business=self.business,
                model_cls=BillingDetails,
                subscription_code=subscription_type,
            )

        # Generate invoice number immediately when billing is created
        # This ensures invoice email sent before payment can show the invoice number
        if not self.invoice_number:
            self.invoice_number = self.generate_invoice_number_for_billing()

        super().save(*args, **kwargs)

    def get_subscription_type_code(self):
        """
        Retrieves the subscription type code from the latest subscription
        plan associated with the from_business (payer).
        """
        if self.business:
            latest_subscription = (
                self.business.business_subscription_plan.filter(
                    subscription_plan__is_active=True
                )
                .select_related("subscription_plan")
                .order_by("-start_date")
                .first()
            )

            if latest_subscription and latest_subscription.subscription_plan:
                subscription_code = (
                    latest_subscription.subscription_plan.subscription_code
                )
                return subscription_code[:3].upper() if subscription_code else "UNK"

        return "UNK"

    def generate_invoice_number_for_billing(self):
        """
        Generate a unique invoice number for billing details.
        Format: INV+USERINITIALS+MMYY+SEQUENCE (monthly basis)
        Example: INVJOH0625001
        """
        from django.db import transaction
        from django.utils.timezone import now

        from account.models import ReceiptSequence
        from account.models import UserAssignedBusiness

        current_time = now()
        mm_yy = current_time.strftime("%m%y")
        transaction_code = "INV"

        # Get user initials from the business owner or user (same logic as ReceiptNumberMixin)
        if self.business and self.business.name:
            business_initials = self.business.name[:3].upper()
        else:
            user_assigned_business = UserAssignedBusiness.objects.filter(
                business=self.business, is_owner=True
            ).first()

            if user_assigned_business and user_assigned_business.user:
                user = user_assigned_business.user
                fullname = user.fullname.strip()
                if fullname:
                    business_initials = "".join(
                        [part[0].upper() for part in fullname.split() if part]
                    )[:3]
                else:
                    business_initials = "USR"
            else:
                business_initials = "USR"

        # Use ReceiptSequence for atomic sequence tracking (same as PurchaseRequest)
        with transaction.atomic():
            sequence_obj, _ = ReceiptSequence.objects.select_for_update().get_or_create(
                mm_yy=mm_yy,
                transaction_code=transaction_code,
                defaults={"last_sequence": 0},
            )
            sequence_obj.last_sequence += 1
            sequence_obj.save()

        return f"{transaction_code}{business_initials}{mm_yy}{sequence_obj.last_sequence:03d}"


class AppVersion(CustomIDMixin, TimeStampedModelMixin):
    platform = models.CharField(max_length=10, choices=PlatformChoices)
    min_required_version = models.CharField(max_length=20)
    app_url = models.URLField()

    def __str__(self):
        return f"{self.platform} - {self.min_required_version}"
