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
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from investor.models import AssetContribution
from investor.models import PreciousItemUnit
from investor.models import PurchaseRequest
from jeweler.message import MESSAGES as JEWELER_MESSAGES
from jeweler.models import ProductionPaymentAssetAllocation
from jeweler.serializers import DashboardInsightSerializer
from seller.filters import PurchaseRequestFilter
from seller.serializers import PurchaseRequestResponseSerializer
from sooq_althahab.constants import PURCHASE_REQUEST_VIEW_PERMISSION
from sooq_althahab.enums.investor import ContributionType
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.enums.investor import RequestType
from sooq_althahab.enums.jeweler import AssetContributionStatus
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.helper import PermissionManager
from sooq_althahab.querysets.purchase_request import base_purchase_request_queryset
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response


class BasePurchaseRequestView:
    """Base class for common query and accessibility logic for purchase requests."""

    def get_queryset_for_role(self, queryset):
        """Filter purchase requests based on user role and assigned business."""
        business = get_business_from_user_token(self.request, "business")
        if not business:
            return queryset.none()
        return queryset.filter(business=business)


class PurchasedAssetListView(BasePurchaseRequestView, ListAPIView):
    """Listing all purchase requests created by jeweler or linked via Musharakah."""

    pagination_class = CommonPagination
    permission_classes = [IsAuthenticated]
    serializer_class = PurchaseRequestResponseSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = PurchaseRequestFilter

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return PurchaseRequest.objects.none()

        business = get_business_from_user_token(self.request, "business")
        if not business:
            return PurchaseRequest.objects.none()

        queryset = base_purchase_request_queryset()

        # Fetch purchase requests either directly owned or linked via MusharakahContractRequest
        filtered_queryset = queryset.filter(
            Q(business=business)
            # NOTE: Display only the user's own purchase requests, excluding contributed assets
            # | Q(asset_contributions__musharakah_contract_request__jeweler=business)
        ).distinct()

        # Custom queryset for jeweler: Only count APPROVED/COMPLETED sale requests as sold
        # This allows purchase requests to remain visible until sale request is finally approved
        # Subquery to calculate total sold quantity - only count APPROVED and COMPLETED sale requests
        sold_quantity_subquery = Subquery(
            PurchaseRequest.objects.filter(
                related_purchase_request=OuterRef("pk"),
                request_type=RequestType.SALE,
                status__in=[
                    PurchaseRequestStatus.APPROVED,
                    PurchaseRequestStatus.COMPLETED,
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

        # Musharakah allocations already used in ProductionPayment
        # total weight used from musharakah histories linked to this purchase_request
        musharakah_used_weight_subquery = Subquery(
            ProductionPaymentAssetAllocation.objects.filter(
                precious_item_unit_musharakah__precious_item_unit__purchase_request=OuterRef(
                    "pk"
                )
            )
            .values(
                "precious_item_unit_musharakah__precious_item_unit__purchase_request"
            )
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
            .values(
                "precious_item_unit_musharakah__precious_item_unit__purchase_request"
            )
            .annotate(total_units=Sum(Value(1), output_field=DecimalField()))
            .values("total_units")[:1],
            output_field=DecimalField(),
        )

        return (
            filtered_queryset.filter(
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
                    musharakah_used_weight_subquery,
                    Value(0, output_field=DecimalField()),
                ),
                musharakah_used_units=Coalesce(
                    musharakah_used_units_subquery,
                    Value(0, output_field=DecimalField()),
                ),
                # Convert musharakah used weight to equivalent quantity for METAL items.
                # Use NullIf to avoid division by zero if precious_metal.weight is NULL/0.
                musharakah_used_equivalent_quantity=Coalesce(
                    Case(
                        When(
                            precious_item__material_type=MaterialType.METAL,
                            then=F("musharakah_used_weight")
                            / NullIf(
                                F("precious_item__precious_metal__weight"), Value(0)
                            ),
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

    @PermissionManager(PURCHASE_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """List all purchase requests."""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=JEWELER_MESSAGES["jeweler_assets_fetched"],
            data=serializer.data,
        )


class DashboardGeneralInsightAPIView(APIView):
    """Get general insights about jeweler's assets including metal and stone counts."""

    permission_classes = [IsAuthenticated]
    serializer_class = DashboardInsightSerializer

    def get(self, request, *args, **kwargs):
        """Get all metal and stone count for jeweler's available assets."""

        business = get_business_from_user_token(self.request, "business")

        # Get all purchase request of jeweler
        purchase_request_qs = (
            PurchaseRequest.objects.filter(
                business=business,
                request_type=RequestType.PURCHASE,  # only purchase requests
            )
            .annotate(
                total_sold=Sum(
                    "sale_requests__requested_quantity",
                    filter=Q(
                        sale_requests__status__in=[
                            PurchaseRequestStatus.PENDING,
                            PurchaseRequestStatus.APPROVED,
                            PurchaseRequestStatus.COMPLETED,
                        ]
                    ),
                ),
                total_contribution=Sum(
                    "asset_contributions__quantity",
                    filter=Q(
                        asset_contributions__status__in=[
                            RequestStatus.PENDING,
                            RequestStatus.APPROVED,
                        ]
                    ),
                ),
            )
            .annotate(
                remaining_quantity=(
                    F("requested_quantity")
                    - Coalesce(
                        F("total_sold"),
                        Value(
                            Decimal("0"),
                            output_field=DecimalField(max_digits=20, decimal_places=4),
                        ),
                    )
                    - Coalesce(
                        F("total_contribution"),
                        Value(
                            Decimal("0"),
                            output_field=DecimalField(max_digits=20, decimal_places=4),
                        ),
                    )
                )
            )
        )

        # Aggregate remaining quantities by material type
        aggregated = purchase_request_qs.aggregate(
            total_remaining=Coalesce(
                Sum("remaining_quantity"),
                Value(
                    Decimal("0"),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
            ),
            metal_remaining=Coalesce(
                Sum(
                    "remaining_quantity",
                    filter=Q(precious_item__material_type=MaterialType.METAL),
                ),
                Value(
                    Decimal("0"),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
            ),
            stone_remaining=Coalesce(
                Sum(
                    "remaining_quantity",
                    filter=Q(precious_item__material_type=MaterialType.STONE),
                ),
                Value(
                    Decimal("0"),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
            ),
        )
        # NOTE: If you want to include the contributed assets via Musharakah, uncomment the code below
        # NOTE: Display only the user's own purchase requests, excluding contributed assets
        # # Asset contributions provided by investors via Musharakah (only approved MCR, not yet used in production)
        # contributions_qs = AssetContribution.objects.filter(
        #     contribution_type=ContributionType.MUSHARAKAH,
        #     musharakah_contract_request__jeweler=business,
        #     musharakah_contract_request__status=RequestStatus.APPROVED,
        #     production_payment__isnull=True,
        #     deleted_at__isnull=True,
        # )

        # contributions_aggregated = contributions_qs.aggregate(
        #     metal_contributed=Coalesce(
        #         Sum(
        #             "quantity",
        #             filter=Q(
        #                 purchase_request__precious_item__material_type=MaterialType.METAL
        #             ),
        #         ),
        #         Value(
        #             Decimal("0"),
        #             output_field=DecimalField(max_digits=20, decimal_places=4),
        #         ),
        #     ),
        #     stone_contributed=Coalesce(
        #         Sum(
        #             "quantity",
        #             filter=Q(
        #                 purchase_request__precious_item__material_type=MaterialType.STONE
        #             ),
        #         ),
        #         Value(
        #             Decimal("0"),
        #             output_field=DecimalField(max_digits=20, decimal_places=4),
        #         ),
        #     ),
        # )

        metal_remaining_qty = float(aggregated.get("metal_remaining") or 0)
        stone_remaining_qty = float(aggregated.get("stone_remaining") or 0)
        # metal_contributed_qty = float(
        #     contributions_aggregated.get("metal_contributed") or 0
        # )
        # stone_contributed_qty = float(
        #     contributions_aggregated.get("stone_contributed") or 0
        # )

        insight_data = {
            # Combined totals including purchase remaining
            "total_metal_quantity": metal_remaining_qty,
            "total_stone_quantity": stone_remaining_qty,
            "total_quantity": metal_remaining_qty + stone_remaining_qty,
        }
        serializer = self.serializer_class(instance=insight_data)
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=JEWELER_MESSAGES["dashboard_insights_fetched"],
            data=serializer.data,
        )
