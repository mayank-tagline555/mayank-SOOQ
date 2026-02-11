from decimal import ROUND_HALF_UP
from decimal import Decimal

from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models import Sum
from django_softdelete.models import SoftDeleteModel
from rest_framework.serializers import ValidationError

from account.models import BusinessAccount
from account.models import User
from investor.message import MESSAGES
from seller.models import PreciousItem
from sooq_althahab.base_models import OwnershipMixin
from sooq_althahab.base_models import TimeStampedModelMixin
from sooq_althahab.base_models import UserTimeStampedModelMixin
from sooq_althahab.enums.investor import ContributionType
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.enums.investor import RequestType
from sooq_althahab.enums.jeweler import AssetContributionStatus
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.enums.sooq_althahab_admin import SubscriptionPaymentTypeChoices
from sooq_althahab.mixins import CustomIDMixin
from sooq_althahab_admin.models import Pool
from sooq_althahab_admin.models import PoolContribution


class PurchaseRequest(
    SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin, OwnershipMixin
):
    """
    Represents an purchase request made by an investor for a precious item.

    This model handles both purchase and sales requests. Investors can either
    request to buy a precious item or sell from their existing stock.

    Attributes:
        business (ForeignKey): The business entity associated with the purchase request.
        precious_item (ForeignKey): The precious item being transacted.
        total_cost (Decimal): The total cost of the requested asset.
        requested_quantity (Decimal): The quantity of the precious item requested.
        status (str): The current status of the request (e.g., Pending, Confirmed, Completed, Assigned).
        action_by (ForeignKey): The user who approved/rejected the request.
        request_type (str): Defines whether the request is a 'Purchase' or 'Sale'.
        related_purchase_request (ForeignKey): Links a sale request to its original purchase request.
    """

    business = models.ForeignKey(
        BusinessAccount,
        on_delete=models.CASCADE,
        related_name="purchase_requests",
        help_text="The business entity associated with this purchase request.",
    )
    request_type = models.CharField(
        max_length=15,
        choices=RequestType.choices,
        default=RequestType.PURCHASE,
        help_text="Select whether this is a Purchase Request or Sale Request.",
    )
    price_locked = models.DecimalField(
        max_digits=16, decimal_places=4, null=True, blank=True
    )
    premium = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    total_cost = models.DecimalField(max_digits=16, decimal_places=4)
    requested_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=30,
        choices=PurchaseRequestStatus.choices,
        default=PurchaseRequestStatus.PENDING,
    )
    # NOTE: The user by whom the purchase requests is created will be stored in the `created_by`
    action_by = models.ForeignKey(
        User,
        related_name="purchase_requests",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="User who approved/rejected the request.",
    )
    precious_item = models.ForeignKey(
        PreciousItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="purchase_requests",
        help_text="Reference to the precious item for this purchase request.",
    )
    jewelry_product = models.ForeignKey(
        "jeweler.JewelryProduct",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="purchase_requests",
        help_text="Jewelry product after musharakah contract terminates.",
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the purchase request was approved.",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="The date and time when the purchase request was completed.",
    )
    invoice_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        unique=True,
        help_text="Custom invoice number generated when request is approved.",
    )
    vat = models.DecimalField(max_digits=12, decimal_places=4, default=0.00)
    taxes = models.DecimalField(max_digits=12, decimal_places=4, default=0.00)
    platform_fee = models.DecimalField(max_digits=12, decimal_places=4, default=0.00)

    # One purchase can only have one sale
    related_purchase_request = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sale_requests",
        help_text="The original purchase request this sale is derived from.",
        db_index=True,
    )

    # this indicates requested qty multiply to price locked
    order_cost = models.DecimalField(
        max_digits=16, decimal_places=4, blank=True, null=True
    )

    # Initial order cost for sale requests (before deduction)
    # Stores the original calculated order cost (live price x qty x weight)
    # This is useful for showing the original price to seller and for backend calculations
    initial_order_cost = models.DecimalField(
        max_digits=16,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Initial order cost for sale requests (live price calculation before deduction).",
    )

    # Deduction amount set by seller for sale requests
    # This amount is deducted from the live price calculation
    deduction_amount = models.DecimalField(
        max_digits=16,
        decimal_places=4,
        null=True,
        blank=True,
        default=0.00,
        help_text="Deduction amount set by seller for sale requests. Deducted from live price calculation.",
    )

    pro_rata_mode = models.CharField(
        max_length=10,
        choices=SubscriptionPaymentTypeChoices.choices,
        default=SubscriptionPaymentTypeChoices.POSTPAID,
        help_text="Defines if pro rata is charged per purchase (prepaid) or consolidated annually (postpaid).",
    )
    pro_rata_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0.00,
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
        help_text="Pro rata rate as a decimal (e.g., 0.05 for 5%).",
    )
    pro_rata_fee = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=0,
        help_text="Calculated pro rata fee for this purchase request.",
    )
    annual_pro_rata_fee = models.DecimalField(
        max_digits=16,
        decimal_places=4,
        default=0,
        help_text="Calculated annual pro rata fee for this purchase request.",
    )

    # For the adding box number for the availibility of the item by taqabeth admin
    storage_box_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="The storage box number in the admin locker where this item is stored.",
    )

    @property
    def remaining_quantity(self):
        """
        Calculate the remaining quantity of units available for sale/contribution.

        This property correctly handles:
        - Sold units (excluded - all sale request statuses)
        - Units in active musharakah contracts (excluded - they're allocated)
        - Units in pools (excluded - they're allocated)
        - Pending/Approved asset contributions (excluded - treated as allocated)
        - Rejected asset contributions (included - available again)
        - Units returned from terminated musharakah (included - with remaining weight)
        - Production usage (already accounted in unit.remaining_weight)

        For METAL: Uses weight-based calculation (sum of remaining weights)
        For STONE: Uses count-based calculation (count of available units)
        """
        from decimal import Decimal as D

        from sooq_althahab.enums.jeweler import AssetContributionStatus
        from sooq_althahab.enums.jeweler import MusharakahContractStatus
        from sooq_althahab.enums.jeweler import RequestStatus

        if self.request_type == RequestType.JEWELRY_DESIGN:
            return self.requested_quantity

        if self.request_type == RequestType.SALE:
            return None  # Only makes sense for PURCHASE type

        # ==========================================================
        #   PENDING Status: Return requested_quantity (nothing sold/allocated yet)
        # ==========================================================
        if self.status == PurchaseRequestStatus.PENDING:
            # For PENDING purchase requests, no units have been created yet
            # and nothing has been sold or allocated, so remaining = requested
            return self.requested_quantity

        # ==========================================================
        #   1. Calculate total sold quantity from sale requests
        # ==========================================================
        # Deduct all sale requests regardless of status (they're allocated)
        total_sold = self.sale_requests.filter(
            status__in=[
                PurchaseRequestStatus.PENDING,
                PurchaseRequestStatus.APPROVED,
                PurchaseRequestStatus.COMPLETED,
                PurchaseRequestStatus.PENDING_SELLER_PRICE,
                PurchaseRequestStatus.PENDING_INVESTOR_CONFIRMATION,
            ]
        ).aggregate(total=Sum("requested_quantity"))["total"] or Decimal("0.00")

        # ==========================================================
        #   2. Calculate total contributed quantity (allocated)
        # ==========================================================
        # Count contributions that are PENDING, ADMIN_APPROVED, APPROVED, or TERMINATED
        # For TERMINATED: Only deduct the used portion (unused portion is returned and available)
        # REJECTED contributions are NOT deducted (available again)
        all_contributions_qs = self.asset_contributions.filter(
            status__in=[
                AssetContributionStatus.PENDING,
                AssetContributionStatus.ADMIN_APPROVED,
                AssetContributionStatus.APPROVED,
                AssetContributionStatus.TERMINATED,
            ]
        )

        total_contribution = Decimal("0.00")

        for contribution in all_contributions_qs:
            if contribution.status == AssetContributionStatus.TERMINATED:
                # For TERMINATED contributions, only count the used portion
                # The unused portion is returned and available again
                used_unused = contribution.used_unused_weight
                if used_unused and "used_weight" in used_unused:
                    used_weight = Decimal(str(used_unused["used_weight"]))
                    # Get full unit weight to convert weight to quantity
                    try:
                        if self.precious_item.material_type == MaterialType.METAL:
                            full_unit_weight = self.precious_item.precious_metal.weight
                            if full_unit_weight and full_unit_weight > Decimal("0.00"):
                                used_quantity = used_weight / full_unit_weight
                            else:
                                used_quantity = Decimal("0.00")
                        else:
                            # For stones, use quantity directly (stones are count-based)
                            # But we need to check how much was actually used
                            # For now, assume full quantity was used for TERMINATED stone contributions
                            used_quantity = contribution.quantity
                    except (AttributeError, ZeroDivisionError):
                        used_quantity = Decimal("0.00")

                    total_contribution += used_quantity
                else:
                    # If used_unused_weight is None or missing, assume full quantity was used
                    total_contribution += contribution.quantity
            else:
                # For PENDING, ADMIN_APPROVED, APPROVED: deduct full quantity
                total_contribution += contribution.quantity

        # ==========================================================
        #   3. Get available units (NOT sold, NOT in pool)
        # ==========================================================
        # Get units that are NOT sold, NOT in pool
        available_units = self.precious_item_units.filter(
            sale_request__isnull=True,  # Not sold
            pool__isnull=True,  # Not in pool
        )

        # Exclude units that are in ACTIVE musharakah contracts
        # These units are allocated and not available
        from investor.models import PreciousItemUnitMusharakahHistory

        # Get unit IDs that are in active musharakah contracts (via history)
        active_musharakah_unit_ids = PreciousItemUnitMusharakahHistory.objects.filter(
            precious_item_unit__purchase_request=self,
            musharakah_contract__musharakah_contract_status__in=[
                MusharakahContractStatus.ACTIVE,
                MusharakahContractStatus.RENEW,
                MusharakahContractStatus.UNDER_TERMINATION,
            ],
        ).values_list("precious_item_unit_id", flat=True)

        # Also exclude units in active musharakah via old FK (backward compatibility)
        active_musharakah_old_fk_units = self.precious_item_units.filter(
            musharakah_contract__isnull=False,
            musharakah_contract__musharakah_contract_status__in=[
                MusharakahContractStatus.ACTIVE,
                MusharakahContractStatus.RENEW,
                MusharakahContractStatus.UNDER_TERMINATION,
            ],
        ).values_list("id", flat=True)

        # Combine both sets of excluded unit IDs
        excluded_unit_ids = set(active_musharakah_unit_ids) | set(
            active_musharakah_old_fk_units
        )

        # Filter out units in active musharakah
        truly_available_units = available_units.exclude(id__in=excluded_unit_ids)

        # ==========================================================
        #   🔷 CASE 1: METAL → Weight Based
        # ==========================================================
        if self.precious_item.material_type == MaterialType.METAL:
            # Sum remaining weight from truly available units
            # unit.remaining_weight already accounts for production usage
            total_remaining_weight = Decimal("0.00")
            for unit in truly_available_units:
                total_remaining_weight += unit.remaining_weight or Decimal("0.00")

            # Get weight of 1 full unit
            try:
                full_unit_weight = self.precious_item.precious_metal.weight
            except AttributeError:
                return Decimal("0.00")

            if full_unit_weight <= Decimal("0.00"):
                return Decimal("0.00")

            # Convert weight to quantity
            qty_from_weight = total_remaining_weight / full_unit_weight

            # Base remaining quantity after deducting sold and contributions
            base_remaining = self.requested_quantity - total_sold - total_contribution

            # Take the minimum of weight-based calculation and quantity-based calculation
            # This ensures we don't show more than what's actually available
            remaining_qty = min(qty_from_weight, base_remaining)

            return max(remaining_qty.quantize(Decimal("0.01")), Decimal("0.00"))

        # ==========================================================
        #   🔶 CASE 2: STONE → Count Based
        # ==========================================================
        # For STONE, count available units
        # Units used in production are still counted (stones are not weight-deducted)
        # But we exclude units that are in active musharakah or pools

        available_stone_count = truly_available_units.count()

        # Base remaining quantity after deducting sold and contributions
        base_remaining = self.requested_quantity - total_sold - total_contribution

        # Take the minimum of count-based calculation and quantity-based calculation
        remaining_qty = min(Decimal(available_stone_count), base_remaining)

        return Decimal(max(remaining_qty, 0))

    @property
    def remaining_weight(self):
        """
        Total remaining weight across all available units.

        Excludes:
        - Units that are sold (all sale request statuses)
        - Units in pools
        - Units in active musharakah contracts (they're allocated)
        - Units allocated via pending/approved asset contributions

        Includes:
        - Units returned from terminated musharakah (with remaining weight)
        - Production usage is already accounted in unit.remaining_weight
        """

        if self.request_type == RequestType.SALE:
            return None

        # Get units that are NOT sold, NOT in pool
        available_units = self.precious_item_units.filter(
            sale_request__isnull=True,  # Not sold
            pool__isnull=True,  # Not in pool
        )

        # Exclude units that are in ACTIVE musharakah contracts
        from investor.models import PreciousItemUnitMusharakahHistory
        from sooq_althahab.enums.jeweler import MusharakahContractStatus

        # Get unit IDs that are in active musharakah contracts (via history)
        active_musharakah_unit_ids = PreciousItemUnitMusharakahHistory.objects.filter(
            precious_item_unit__purchase_request=self,
            musharakah_contract__musharakah_contract_status__in=[
                MusharakahContractStatus.ACTIVE,
                MusharakahContractStatus.RENEW,
                MusharakahContractStatus.UNDER_TERMINATION,
            ],
        ).values_list("precious_item_unit_id", flat=True)

        # Also exclude units in active musharakah via old FK (backward compatibility)
        active_musharakah_old_fk_units = self.precious_item_units.filter(
            musharakah_contract__isnull=False,
            musharakah_contract__musharakah_contract_status__in=[
                MusharakahContractStatus.ACTIVE,
                MusharakahContractStatus.RENEW,
                MusharakahContractStatus.UNDER_TERMINATION,
            ],
        ).values_list("id", flat=True)

        # Combine both sets of excluded unit IDs
        excluded_unit_ids = set(active_musharakah_unit_ids) | set(
            active_musharakah_old_fk_units
        )

        # Filter out units in active musharakah
        truly_available_units = available_units.exclude(id__in=excluded_unit_ids)

        total_remaining_weight = Decimal("0.00")

        # Sum remaining weight from truly available units
        for unit in truly_available_units.distinct():
            remaining = unit.remaining_weight or Decimal("0.00")

            # If remaining goes negative, clamp to zero
            if remaining < 0:
                remaining = Decimal("0.00")

            total_remaining_weight += remaining

        return total_remaining_weight

    def save(self, *args, **kwargs):
        self.clean()  # Ensure validation before saving
        super().save(*args, **kwargs)

    class Meta:
        db_table = "purchase_requests"
        verbose_name = "Purchase Request"
        verbose_name_plural = "Purchase Requests"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.id}"


class PreciousItemUnit(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    purchase_request = models.ForeignKey(
        PurchaseRequest,
        on_delete=models.CASCADE,
        related_name="precious_item_units",
        help_text="The purchase request where this unit was allocated.",
    )
    precious_item = models.ForeignKey(
        PreciousItem,
        on_delete=models.CASCADE,
        related_name="precious_item_units",
        help_text="The type of precious item (e.g., Gold 24k 20g).",
    )
    serial_number = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Unique serial number assigned when approving the purchase request.",
    )
    system_serial_number = models.CharField(
        max_length=50,
        db_index=True,
        help_text="System serial number assigned by admin when complete's the purchase request.",
        blank=True,
        null=True,
    )
    sale_request = models.ForeignKey(
        PurchaseRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sold_units",
        help_text="The sale request where this unit was sold (if applicable).",
    )
    musharakah_contract = models.ForeignKey(
        "jeweler.MusharakahContractRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="precious_item_units",
        help_text="The Musharakah contract where this unit is allocated (if applicable).",
    )
    pool = models.ForeignKey(
        Pool,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="precious_item_units",
        help_text="The Pool where this unit is allocated (if applicable).",
    )

    @property
    def remaining_weight(self):
        """
        Remaining weight logic:

        - STONE:
            Always return 1 (each unit = one stone).

        - METAL:
            Remaining weight = original_weight
                            - (weight used in direct allocations)
                            - (weight used in allocations through musharakah history)
        """

        from jeweler.models import ProductionPaymentAssetAllocation

        if self.precious_item.material_type == MaterialType.STONE:
            return Decimal("1")

        try:
            original_weight = self.precious_item.precious_metal.weight
        except:
            return Decimal("0.00")

        direct_used = ProductionPaymentAssetAllocation.objects.filter(
            precious_item_unit_asset=self
        ).aggregate(total=Sum("weight"))["total"] or Decimal("0.00")

        history_ids = PreciousItemUnitMusharakahHistory.objects.filter(
            precious_item_unit=self
        ).values_list("id", flat=True)

        musharakah_used = ProductionPaymentAssetAllocation.objects.filter(
            precious_item_unit_musharakah_id__in=history_ids
        ).aggregate(total=Sum("weight"))["total"] or Decimal("0.00")

        # Total used
        total_used = direct_used + musharakah_used

        # Remaining weight
        remaining = original_weight - total_used
        return max(remaining, Decimal("0.00"))

    def __str__(self):
        return f"{self.pk}"

    class Meta:
        db_table = "precious_item_units"
        verbose_name = "Precious Item Unit"
        verbose_name_plural = "Precious Item Units"
        unique_together = ("purchase_request", "serial_number")


class PreciousItemUnitMusharakahHistory(
    SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin
):
    precious_item_unit = models.ForeignKey(
        PreciousItemUnit, on_delete=models.CASCADE, related_name="musharakah_histories"
    )
    musharakah_contract = models.ForeignKey(
        "jeweler.MusharakahContractRequest",
        on_delete=models.CASCADE,
        related_name="musharakah_histories",
    )
    contributed_weight = models.DecimalField(max_digits=10, decimal_places=3)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.pk}"

    class Meta:
        db_table = "precious_item_unit_musharakah_history"
        verbose_name = "Precious Item Unit Musharakah History"
        verbose_name_plural = "Precious Item Unit Musharakah Histories"


class AssetContribution(SoftDeleteModel, CustomIDMixin, UserTimeStampedModelMixin):
    """
    Represents a contribution of precious material assets by a business entity
    toward a Musharakah contract or a Pool agreement.

    Links a specific purchase request and business account to a contribution,
    optionally tied to either a MusharakahContractRequest or Pool. It records the quantity
    of material contributed and includes a digital signature for verification.

    Ensures contributions are linked back to original purchase requests with appropriate context.
    """

    purchase_request = models.ForeignKey(
        PurchaseRequest,
        on_delete=models.CASCADE,
        related_name="asset_contributions",
        help_text="Reference to the purchase request for this asset contribution.",
    )
    business = models.ForeignKey(
        BusinessAccount,
        on_delete=models.CASCADE,
        related_name="asset_contributions",
        help_text="The business entity associated with this asset contribution.",
    )
    fullname = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Full name of the person making the asset contribution.",
    )
    # This field is used to store the quantity of precious item contributed in the pool or musharakah.
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    contribution_type = models.CharField(
        max_length=20,
        choices=ContributionType.choices,
        help_text="Type of contribution (e.g., Pool, Musharakah).",
    )
    musharakah_contract_request = models.ForeignKey(
        "jeweler.MusharakahContractRequest",
        on_delete=models.CASCADE,
        related_name="asset_contributions",
        null=True,
        blank=True,
        help_text="Reference to the Musharakah contract request for this asset contribution.",
    )
    pool = models.ForeignKey(
        Pool,
        on_delete=models.CASCADE,
        related_name="asset_contributions",
        null=True,
        blank=True,
        help_text="Reference to the pool for this asset contribution.",
    )
    pool_contributor = models.ForeignKey(
        PoolContribution,
        on_delete=models.CASCADE,
        related_name="asset_contributions",
        null=True,
        blank=True,
        help_text="Reference to the pool for this asset contribution.",
    )
    production_payment = models.ForeignKey(
        "jeweler.ProductionPayment",
        on_delete=models.CASCADE,
        related_name="asset_contributions",
        null=True,
        blank=True,
        help_text="Reference to the Production Payment for this asset contribution.",
    )
    status = models.CharField(
        max_length=20,
        choices=AssetContributionStatus.choices,
        default=AssetContributionStatus.PENDING,
        help_text="Current status of the asset contribution.",
    )
    price_locked = models.DecimalField(
        max_digits=16, decimal_places=4, null=True, blank=True
    )

    @property
    def used_unused_weight(self):
        """
        Calculate the remaining weight of the precious item unit.

        For metals: Returns the original weight minus the weight used in production payments.
        For stones: Returns the original weight (stones are quantity-based, not weight-deducted).
        """

        # Get the original weight based on material type

        from jeweler.models import ProductionPaymentAssetAllocation

        precious_item = self.purchase_request.precious_item

        if precious_item.material_type == MaterialType.METAL:
            try:
                precious_metal = precious_item.precious_metal
                original_weight = precious_metal.weight
            except AttributeError:
                return None

            precious_item_units = (
                PreciousItemUnit.objects.filter(
                    purchase_request=self.purchase_request,
                    precious_item__material_type=MaterialType.METAL,
                )
                .filter(
                    Q(payment_allocations__isnull=False)
                    | Q(
                        musharakah_histories__musharakah_contract=self.musharakah_contract_request
                    )
                )
                .distinct()
            )
            used_weight = Decimal("0.00")
            for unit in precious_item_units:
                unit_remaining = unit.remaining_weight or Decimal("0.00")
                unit_used = precious_metal.weight - unit_remaining
                used_weight += unit_used
            total_weight = self.quantity * original_weight
            # Quantize for consistent decimal formatting
            total_weight = total_weight.quantize(
                Decimal("0.000"), rounding=ROUND_HALF_UP
            )
            used_weight = used_weight.quantize(Decimal("0.000"), rounding=ROUND_HALF_UP)
            unused_weight = (total_weight - used_weight).quantize(
                Decimal("0.000"), rounding=ROUND_HALF_UP
            )

            return {
                "used_weight": used_weight,
                "total_weight": total_weight,
                "unused_weight": unused_weight,
            }

        elif precious_item.material_type == MaterialType.STONE:
            # For stones, return the original weight (no deduction)
            try:
                # 1. Collect allocated unit IDs for this purchase request only
                asset_unit_id = ProductionPaymentAssetAllocation.objects.filter(
                    precious_item_unit_asset__purchase_request=self.purchase_request,
                    precious_item_unit_asset__isnull=False,
                ).values_list("precious_item_unit_asset_id", flat=True)

                musharakah_asset_unit_ids = ProductionPaymentAssetAllocation.objects.filter(
                    precious_item_unit_musharakah__precious_item_unit__purchase_request=self.purchase_request,
                    precious_item_unit_musharakah__isnull=False,
                ).values_list(
                    "precious_item_unit_musharakah__precious_item_unit_id",
                    flat=True,
                )

                allocated_unit_ids = set(asset_unit_id) | set(musharakah_asset_unit_ids)

                # 2. Fetch all STONE units for this Purchase Request
                all_units = PreciousItemUnit.objects.filter(
                    purchase_request=self.purchase_request,
                    precious_item__material_type=MaterialType.STONE,
                )

                # 3. Units that are NOT allocated anywhere
                unused_units = all_units.exclude(id__in=allocated_unit_ids)

                # 4. Units that ARE allocated
                used_units = all_units.filter(id__in=allocated_unit_ids)

                # 5. Count (each stone = quantity 1)
                used_quantity = Decimal(used_units.count())
                unused_quantity = Decimal(unused_units.count())

                return {
                    "used_quantity": used_quantity,
                    "unused_quantity": unused_quantity,
                }

            except Exception as e:
                return {
                    "used_quantity": Decimal("0.00"),
                    "unused_quantity": Decimal("0.00"),
                }

        return None

    def clean(self):
        super().clean()
        if (
            self.contribution_type == ContributionType.POOL
            and not self.pool
            and self.pool_contributor
        ):
            raise ValidationError(MESSAGES["pool_required"])
        if (
            self.contribution_type == ContributionType.MUSHARAKAH
            and not self.musharakah_contract_request
        ):
            raise ValidationError(MESSAGES["musharakah_contract_request_required"])
        if (
            self.contribution_type == ContributionType.PRODUCTION_PAYMENT
            and not self.production_payment
        ):
            raise ValidationError(MESSAGES["production_payment_required"])

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    Q(
                        contribution_type=ContributionType.MUSHARAKAH,
                        musharakah_contract_request__isnull=False,
                    )
                    | Q(contribution_type=ContributionType.POOL, pool__isnull=False)
                    | Q(
                        contribution_type=ContributionType.PRODUCTION_PAYMENT,
                        production_payment__isnull=False,
                    )
                ),
                name="check_contribution_type_requires_related_field",
            ),
        ]
        db_table = "asset_contributions"
        verbose_name = "Asset Contribution"
        verbose_name_plural = "Asset Contributions"
        ordering = ["-created_at"]
