from decimal import Decimal

from django.db.models import Case
from django.db.models import DecimalField
from django.db.models import Exists
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import Sum
from django.db.models import Value
from django.db.models import When
from django.db.models.functions import Coalesce
from django.db.models.functions import NullIf
from django.shortcuts import get_object_or_404

from account.models import Transaction
from investor.models import AssetContribution
from investor.models import PreciousItemUnit
from investor.models import PurchaseRequest
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.enums.investor import RequestType
from sooq_althahab.enums.jeweler import AssetContributionStatus
from sooq_althahab.enums.sooq_althahab_admin import MaterialType


def get_transaction_object(pk):
    return get_object_or_404(
        Transaction.objects.select_related(
            "from_business", "to_business", "purchase_request"
        ),
        pk=pk,
    )


def get_total_hold_amount_for_investor(business):
    """Returns the total hold amount for pending purchase requests created by the given users."""

    hold_amount_for_purchase_request = (
        PurchaseRequest.global_objects.filter(
            business=business,
            status=PurchaseRequestStatus.PENDING,
            request_type=RequestType.PURCHASE,
        ).aggregate(total=Sum("total_cost"))["total"]
        or 0
    )
    return hold_amount_for_purchase_request


def get_investors_total_assets(purchase_request):
    """
    Returns a queryset of the investor's total available assets that can still be contributed or sold.

    This includes all purchase requests that are not fully sold or allocated.
    Excludes any purchase request where the combined sold and contributed quantity
    is equal to or exceeds the originally requested quantity.
    """

    # Subquery to calculate total sold quantity
    # Include all sale request statuses that indicate the unit is allocated/sold
    # This matches the remaining_quantity calculation logic
    sold_quantity_subquery = Subquery(
        PurchaseRequest.objects.filter(
            related_purchase_request=OuterRef("pk"),
            request_type=RequestType.SALE,
            status__in=[
                PurchaseRequestStatus.PENDING,
                PurchaseRequestStatus.APPROVED,
                PurchaseRequestStatus.COMPLETED,
                PurchaseRequestStatus.PENDING_SELLER_PRICE,
                PurchaseRequestStatus.PENDING_INVESTOR_CONFIRMATION,
            ],
        )
        .values("related_purchase_request")
        .annotate(total_sold=Sum("requested_quantity"))
        .values("total_sold")[:1],
        output_field=DecimalField(),
    )

    # Subquery to calculate total contributed quantity (allocated to pools or musharakah)
    precious_item_exists_subquery = Exists(
        PreciousItemUnit.objects.filter(
            purchase_request=OuterRef("purchase_request"),
            musharakah_contract=OuterRef("musharakah_contract_request"),
        )
    )

    # Subquery to calculate total contributed quantity
    contributed_quantity_subquery = Subquery(
        AssetContribution.objects.annotate(
            has_precious_units=precious_item_exists_subquery
        )
        .filter(
            purchase_request=OuterRef("pk"),
            production_payment__isnull=True,
        )
        .filter(
            Q(
                status__in=[
                    AssetContributionStatus.PENDING,
                    AssetContributionStatus.APPROVED,
                ]
            )
            | Q(status=AssetContributionStatus.TERMINATED, has_precious_units=True)
        )
        .values("purchase_request")
        .annotate(total_contributed=Sum("quantity"))
        .values("total_contributed")[:1],
        output_field=DecimalField(),
    )

    # --- Musharakah allocations already used in ProductionPayment ---
    # Sum of weights used from musharakah histories for this purchase_request
    from jeweler.models import ProductionPaymentAssetAllocation

    # total weight used from musharakah histories linked to this purchase_request
    musharakah_used_weight_subquery = Subquery(
        ProductionPaymentAssetAllocation.objects.filter(
            precious_item_unit_musharakah__precious_item_unit__purchase_request=OuterRef(
                "pk"
            )
        )
        .values("precious_item_unit_musharakah__precious_item_unit__purchase_request")
        .annotate(total_weight=Sum("weight"))
        .values("total_weight")[:1],
        output_field=DecimalField(),
    )

    # total units used (for STONE) via musharakah histories used in production payments
    musharakah_used_units_subquery = Subquery(
        ProductionPaymentAssetAllocation.objects.filter(
            precious_item_unit_musharakah__precious_item_unit__purchase_request=OuterRef(
                "pk"
            ),
            precious_item_unit_musharakah__precious_item_unit__precious_item__material_type=MaterialType.STONE,
        )
        .values("precious_item_unit_musharakah__precious_item_unit__purchase_request")
        .annotate(total_units=Sum(Value(1), output_field=DecimalField()))
        .values("total_units")[:1],
        output_field=DecimalField(),
    )

    return (
        purchase_request.filter(
            request_type__in=[RequestType.PURCHASE, RequestType.JEWELRY_DESIGN],
            status__in=[
                PurchaseRequestStatus.COMPLETED,
                PurchaseRequestStatus.APPROVED,
                PurchaseRequestStatus.PENDING,
            ],
        )
        .annotate(
            total_sold=Coalesce(
                sold_quantity_subquery, Value(0, output_field=DecimalField())
            ),
            total_contributed=Coalesce(
                contributed_quantity_subquery, Value(0, output_field=DecimalField())
            ),
            musharakah_used_weight=Coalesce(
                musharakah_used_weight_subquery, Value(0, output_field=DecimalField())
            ),
            musharakah_used_units=Coalesce(
                musharakah_used_units_subquery, Value(0, output_field=DecimalField())
            ),
            # Convert musharakah used weight to equivalent quantity for METAL items.
            # Use NullIf to avoid division by zero if precious_metal.weight is NULL/0.
            musharakah_used_equivalent_quantity=Coalesce(
                Case(
                    When(
                        precious_item__material_type=MaterialType.METAL,
                        then=F("musharakah_used_weight")
                        / NullIf(F("precious_item__precious_metal__weight"), Value(0)),
                    ),
                    default=F("musharakah_used_units"),
                    output_field=DecimalField(),
                ),
                Value(0, output_field=DecimalField()),
            ),
            total_allocated=ExpressionWrapper(
                F("total_sold")
                + F("total_contributed")
                + F("musharakah_used_equivalent_quantity"),
                output_field=DecimalField(),
            ),
        )
        .filter(total_allocated__lt=F("requested_quantity"))
    )


def get_investors_unsold_assets(purchase_request):
    """
    Returns a queryset of the investor's unsold assets.

    This includes all purchase requests that are not yet fully sold or allocated.
    Excludes any purchase request where the combined sold and contributed quantity
    is equal to or exceeds the originally requested quantity.
    """

    # Subquery to calculate total sold quantity
    # Include all sale request statuses that indicate the unit is allocated/sold
    # This matches the remaining_quantity calculation logic
    sold_quantity_subquery = Subquery(
        PurchaseRequest.objects.filter(
            related_purchase_request=OuterRef("pk"),
            request_type=RequestType.SALE,
            status__in=[
                PurchaseRequestStatus.PENDING,
                PurchaseRequestStatus.APPROVED,
                PurchaseRequestStatus.COMPLETED,
                PurchaseRequestStatus.PENDING_SELLER_PRICE,
                PurchaseRequestStatus.PENDING_INVESTOR_CONFIRMATION,
            ],
        )
        .values("related_purchase_request")
        .annotate(total_sold=Sum("requested_quantity"))
        .values("total_sold")[:1],
        output_field=DecimalField(),
    )

    # Subquery to calculate total contributed quantity (allocated to pools or musharakah)
    precious_item_exists_subquery = Exists(
        PreciousItemUnit.objects.filter(
            purchase_request=OuterRef("purchase_request"),
            musharakah_contract=OuterRef("musharakah_contract_request"),
        )
    )

    # Subquery to calculate total contributed quantity
    contributed_quantity_subquery = Subquery(
        AssetContribution.objects.annotate(
            has_precious_units=precious_item_exists_subquery
        )
        .filter(
            purchase_request=OuterRef("pk"),
            production_payment__isnull=True,
        )
        .filter(
            Q(
                status__in=[
                    AssetContributionStatus.PENDING,
                    AssetContributionStatus.APPROVED,
                ]
            )
            | Q(status=AssetContributionStatus.TERMINATED, has_precious_units=True)
        )
        .values("purchase_request")
        .annotate(total_contributed=Sum("quantity"))
        .values("total_contributed")[:1],
        output_field=DecimalField(),
    )

    # --- Musharakah allocations already used in ProductionPayment ---
    # Sum of weights used from musharakah histories for this purchase_request
    from jeweler.models import ProductionPaymentAssetAllocation

    # total weight used from musharakah histories linked to this purchase_request
    musharakah_used_weight_subquery = Subquery(
        ProductionPaymentAssetAllocation.objects.filter(
            precious_item_unit_musharakah__precious_item_unit__purchase_request=OuterRef(
                "pk"
            )
        )
        .values("precious_item_unit_musharakah__precious_item_unit__purchase_request")
        .annotate(total_weight=Sum("weight"))
        .values("total_weight")[:1],
        output_field=DecimalField(),
    )

    # total units used (for STONE) via musharakah histories used in production payments
    musharakah_used_units_subquery = Subquery(
        ProductionPaymentAssetAllocation.objects.filter(
            precious_item_unit_musharakah__precious_item_unit__purchase_request=OuterRef(
                "pk"
            ),
            precious_item_unit_musharakah__precious_item_unit__precious_item__material_type=MaterialType.STONE,
        )
        .values("precious_item_unit_musharakah__precious_item_unit__purchase_request")
        .annotate(total_units=Sum(Value(1), output_field=DecimalField()))
        .values("total_units")[:1],
        output_field=DecimalField(),
    )

    return (
        purchase_request.filter(
            request_type__in=[RequestType.PURCHASE, RequestType.JEWELRY_DESIGN],
            status__in=[
                PurchaseRequestStatus.COMPLETED,
                PurchaseRequestStatus.APPROVED,
                PurchaseRequestStatus.PENDING,
            ],
        )
        .annotate(
            total_sold=Coalesce(
                sold_quantity_subquery, Value(0, output_field=DecimalField())
            ),
            total_contributed=Coalesce(
                contributed_quantity_subquery, Value(0, output_field=DecimalField())
            ),
            musharakah_used_weight=Coalesce(
                musharakah_used_weight_subquery, Value(0, output_field=DecimalField())
            ),
            musharakah_used_units=Coalesce(
                musharakah_used_units_subquery, Value(0, output_field=DecimalField())
            ),
            # Convert musharakah used weight to equivalent quantity for METAL items.
            # Use NullIf to avoid division by zero if precious_metal.weight is NULL/0.
            musharakah_used_equivalent_quantity=Coalesce(
                Case(
                    When(
                        precious_item__material_type=MaterialType.METAL,
                        then=F("musharakah_used_weight")
                        / NullIf(F("precious_item__precious_metal__weight"), Value(0)),
                    ),
                    default=F("musharakah_used_units"),
                    output_field=DecimalField(),
                ),
                Value(0, output_field=DecimalField()),
            ),
            total_allocated=ExpressionWrapper(
                F("total_sold")
                + F("total_contributed")
                + F("musharakah_used_equivalent_quantity"),
                output_field=DecimalField(),
            ),
        )
        .filter(total_allocated__lt=F("requested_quantity"))
    )


def get_total_withdrawal_pending_amount(business):
    """Returns the total withdrawal amount for pending withdrawal request for the business."""

    withdrawal_pending_amount = (
        Transaction.objects.filter(
            Q(from_business=business) | Q(to_business=business),
            status=TransactionStatus.PENDING,
            transaction_type=TransactionType.WITHDRAWAL,
        ).aggregate(total=Sum("amount"))["total"]
        or 0
    )
    return withdrawal_pending_amount


def get_total_weight_of_all_asset_contributed(contributed_assets):
    """Calculates the total precious material weight contributed based on asset quantity and item weight."""
    total_weight_invested = Decimal("0.00")
    for asset in contributed_assets:
        precious_item = asset.purchase_request.precious_item
        item_weight = 0

        if precious_item.material_type == MaterialType.METAL:
            item_weight = precious_item.precious_metal.weight
        elif precious_item.material_type == MaterialType.STONE:
            item_weight = precious_item.precious_stone.weight

        if item_weight:
            total_weight_invested += asset.quantity * item_weight
    return total_weight_invested


def create_manual_contributions(
    asset_contributions,
    user,
    business,
    pool=None,
    pool_contribution=None,
    musharakah_contract_request=None,
):
    """
    Create asset contributions from manually provided input data.

    - If `pool` is provided, each contribution will be associated with the pool.
    - If `musharakah_contract_request` is provided, each contribution will be associated with it.
    - Only one of `pool` or `musharakah_contract_request` should be set to avoid violating the database constraint.
    """

    contributed_assets = []

    for asset in asset_contributions:
        contribution = AssetContribution(
            created_by=user,
            business=business,
            pool_contributor=pool_contribution,
            **asset
        )
        if pool:
            contribution.pool = pool
        elif musharakah_contract_request:
            contribution.musharakah_contract_request = musharakah_contract_request
        contributed_assets.append(contribution)

    AssetContribution.objects.bulk_create(contributed_assets)

    if pool:
        return get_total_weight_of_all_asset_contributed(contributed_assets)
