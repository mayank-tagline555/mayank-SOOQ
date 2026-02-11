from decimal import Decimal
from itertools import chain

from django.core.exceptions import ValidationError
from django.db.models import DecimalField
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import Sum
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.db.models.functions import Greatest
from django.http import Http404
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from investor.filters import OccupiedStockFilter
from investor.models import AssetContribution
from investor.models import PurchaseRequest
from investor.serializers import OccupiedAssetContributionDetailSerializer
from investor.serializers import OccupiedAssetContributionSerializer
from investor.serializers import PortfolioHistorySerializer
from jeweler.models import JewelryProduction
from jeweler.models import MusharakahContractRequest
from jeweler.serializers import MusharakahContractRequestResponseSerializer
from manufacturer.serializers import JewelryProductionDetailSerializer
from sooq_althahab.constants import OCCUPIED_STOCK_VIEW_PERMISSION
from sooq_althahab.constants import TAQABETH_REQUEST_VIEW_PERMISSION
from sooq_althahab.enums.investor import ContributionType
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.enums.investor import RequestType
from sooq_althahab.enums.jeweler import AssetContributionStatus
from sooq_althahab.enums.jeweler import DeliveryStatus
from sooq_althahab.enums.jeweler import MusharakahContractStatus
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.enums.sooq_althahab_admin import Status
from sooq_althahab.helper import PermissionManager
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response
from sooq_althahab_admin.message import MESSAGES as ADMIN_MESSAGES
from sooq_althahab_admin.models import Pool
from sooq_althahab_admin.serializers import PoolResponseSerializer


class TaqabethRequestListAPIView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(
                name="type",
                in_=openapi.IN_QUERY,
                description="Filter by type. One of: POOL, MUSHARAKAH_CONTRACT, JEWELRY_PRODUCTION",
                type=openapi.TYPE_STRING,
                enum=["POOL", "MUSHARAKAH_CONTRACT", "JEWELRY_PRODUCTION"],
                required=False,
            ),
            openapi.Parameter(
                name="ordering",
                in_=openapi.IN_QUERY,
                description="Order by field. Use - for descending. E.g., 'created_at' or '-created_at'",
                type=openapi.TYPE_STRING,
                required=False,
            ),
        ]
    )
    @PermissionManager(TAQABETH_REQUEST_VIEW_PERMISSION)
    def get(self, request):
        type_filter = request.query_params.get("type")
        ordering = request.query_params.get("ordering")

        # Fetch and serialize MusharakahContractRequests
        musharakah_qs = MusharakahContractRequest.objects.filter(
            status__in=[RequestStatus.ADMIN_APPROVED, RequestStatus.APPROVED],
            musharakah_contract_status=MusharakahContractStatus.ACTIVE,
        )
        musharakah_contract_request_serializer = (
            MusharakahContractRequestResponseSerializer(musharakah_qs, many=True).data
        )
        musharakah_list = [
            {
                "id": str(item["id"]),
                "type": "MUSHARAKAH_CONTRACT",
                "created_at": item["created_at"],
                "data": item,
            }
            for item in musharakah_contract_request_serializer
        ]

        # Fetch and serialize PoolContributions
        pool_qs = Pool.objects.all()
        pool_serializer = PoolResponseSerializer(
            pool_qs, many=True, context={"request": request}
        ).data
        pool_list = [
            {
                "id": str(item["id"]),
                "type": "POOL",
                "created_at": item["created_at"],
                "data": item,
            }
            for item in pool_serializer
        ]

        # Fetch and serialize JewelryProductionRequests
        jeweler_production = JewelryProduction.objects.filter(
            is_payment_completed=True, material_delivery_status=DeliveryStatus.PENDING
        )
        jeweler_production_serializer = JewelryProductionDetailSerializer(
            jeweler_production, many=True
        ).data
        jewelry_production_list = [
            {
                "id": str(item["id"]),
                "type": "JEWELRY_PRODUCTION",
                "created_at": item["created_at"],
                "data": item,
            }
            for item in jeweler_production_serializer
        ]

        # Combine all records
        all_data = list(chain(musharakah_list, pool_list, jewelry_production_list))

        # Apply type filter
        if type_filter:
            all_data = [item for item in all_data if item["type"] == type_filter]

        # Apply ordering
        if ordering:
            reverse = ordering.startswith("-")
            ordering_field = ordering.lstrip("-")
            if ordering_field in {"created_at", "type"}:
                all_data = sorted(
                    all_data, key=lambda x: x.get(ordering_field), reverse=reverse
                )
        else:
            # Default ordering by created_at descending
            all_data = sorted(all_data, key=lambda x: x["created_at"], reverse=True)

        # Paginate
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(all_data, request, view=self)
        serializer = PortfolioHistorySerializer(page, many=True)

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=ADMIN_MESSAGES["taqabeth_request_fetched"],
            data=paginator.get_paginated_response(serializer.data).data,
        )


class OccupiedStockListAPIView(ListAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    serializer_class = OccupiedAssetContributionSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = OccupiedStockFilter

    def get_queryset(self):
        return (
            AssetContribution.objects.filter(
                Q(
                    contribution_type=ContributionType.MUSHARAKAH,
                    musharakah_contract_request__status__in=[
                        RequestStatus.APPROVED,
                        RequestStatus.PENDING,
                    ],
                )
                | Q(
                    contribution_type=ContributionType.POOL,
                    pool_contributor__status__in=[Status.APPROVED, Status.PENDING],
                )
                | ~Q(
                    contribution_type__in=[
                        ContributionType.MUSHARAKAH,
                        ContributionType.POOL,
                    ]
                )
            )
            .select_related(
                "purchase_request",
                "purchase_request__precious_item",
                "purchase_request__precious_item__material_item",
                "purchase_request__business",
                "purchase_request__created_by",
                "musharakah_contract_request",
                "pool",
                "pool_contributor",
                "created_by",
                "updated_by",
            )
            .prefetch_related(
                "purchase_request__precious_item__images",
                "musharakah_contract_request__precious_item_units",
                "pool__precious_item_units",
            )
        )

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(
                "created_at_min",
                openapi.IN_QUERY,
                description="Filter contributions created from this date (YYYY-MM-DD HH:MM:SS)",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATETIME,
                required=False,
            ),
            openapi.Parameter(
                "created_at_max",
                openapi.IN_QUERY,
                description="Filter contributions created up to this date (YYYY-MM-DD HH:MM:SS)",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATETIME,
                required=False,
            ),
            openapi.Parameter(
                "contribution_type",
                openapi.IN_QUERY,
                description="Filter by contribution type (POOL, MUSHARAKAH, PRODUCTION_PAYMENT)",
                type=openapi.TYPE_STRING,
                enum=["POOL", "MUSHARAKAH", "PRODUCTION_PAYMENT"],
                required=False,
            ),
            openapi.Parameter(
                "musharakah_status",
                openapi.IN_QUERY,
                description="Filter by musharakah contract request status (PENDING, APPROVED, REJECTED)",
                type=openapi.TYPE_STRING,
                enum=["PENDING", "APPROVED", "REJECTED"],
                required=False,
            ),
            openapi.Parameter(
                "pool_status",
                openapi.IN_QUERY,
                description="Filter by pool contributor status (PENDING, APPROVED, REJECTED)",
                type=openapi.TYPE_STRING,
                enum=["PENDING", "APPROVED", "REJECTED"],
                required=False,
            ),
            openapi.Parameter(
                "business_name",
                openapi.IN_QUERY,
                description="Filter by business name (case-insensitive search)",
                type=openapi.TYPE_STRING,
                required=False,
            ),
            openapi.Parameter(
                "ordering",
                openapi.IN_QUERY,
                description="Order by field. Use - for descending. E.g., 'created_at' or '-created_at'",
                type=openapi.TYPE_STRING,
                required=False,
            ),
        ]
    )
    @PermissionManager(OCCUPIED_STOCK_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """List all occupied asset contributions with filtering and pagination."""

        try:
            queryset = self.filter_queryset(self.get_queryset())
            page = self.paginate_queryset(queryset)
            serializer = self.get_serializer(page, many=True)
            response_data = self.get_paginated_response(serializer.data).data
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=ADMIN_MESSAGES["occupied_stock_fetched"],
                data=response_data,
            )
        except ValidationError as e:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=str(e),
                data=None,
            )


class OccupiedStockRetrieveAPIView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OccupiedAssetContributionDetailSerializer

    def get_queryset(self):
        """
        Get all occupied (allocated) asset contributions.
        Includes contributions with any valid status to prevent 404 errors.
        """
        return (
            AssetContribution.objects.filter(
                Q(
                    contribution_type=ContributionType.MUSHARAKAH,
                    musharakah_contract_request__status__in=[
                        RequestStatus.APPROVED,
                        RequestStatus.PENDING,
                        RequestStatus.ADMIN_APPROVED,
                    ],
                )
                | Q(
                    contribution_type=ContributionType.POOL,
                    pool_contributor__status__in=[
                        RequestStatus.APPROVED,
                        RequestStatus.PENDING,
                        RequestStatus.ADMIN_APPROVED,
                    ],
                )
                | Q(
                    contribution_type=ContributionType.PRODUCTION_PAYMENT,
                    production_payment__isnull=False,
                )
            )
            .select_related(
                "purchase_request",
                "purchase_request__precious_item",
                "purchase_request__precious_item__material_item",
                "purchase_request__precious_item__precious_metal",
                "purchase_request__precious_item__precious_stone",
                "purchase_request__business",
                "purchase_request__created_by",
                "musharakah_contract_request",
                "pool",
                "pool_contributor",
                "production_payment",
                "created_by",
                "updated_by",
            )
            .prefetch_related(
                "purchase_request__precious_item__images",
                "purchase_request__precious_item_units",
            )
        )

    def get_serializer_context(self):
        """Add request context to serializer."""
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    @PermissionManager(OCCUPIED_STOCK_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            if not instance:
                return generic_response(
                    status_code=status.HTTP_404_NOT_FOUND,
                    error_message=ADMIN_MESSAGES["occupied_stock_not_found"],
                )

            serializer = self.get_serializer(instance)
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=ADMIN_MESSAGES["occupied_stock_fetched"],
                data=serializer.data,
            )
        except Exception as e:
            import traceback

            traceback.print_exc()
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=ADMIN_MESSAGES["occupied_stock_not_found"],
            )


class TaqabethEnfocerDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @PermissionManager(TAQABETH_REQUEST_VIEW_PERMISSION)
    def get(self, request):
        total_occupied_stock = AssetContribution.objects.filter(
            Q(
                contribution_type=ContributionType.MUSHARAKAH,
                musharakah_contract_request__status__in=[
                    RequestStatus.APPROVED,
                    RequestStatus.PENDING,
                ],
            )
            | Q(
                contribution_type=ContributionType.POOL,
                pool_contributor__status__in=[
                    Status.APPROVED,
                    Status.PENDING,
                ],
            )
            | ~Q(
                contribution_type__in=[
                    ContributionType.MUSHARAKAH,
                    ContributionType.POOL,
                ]
            )
        ).select_related("purchase_request__precious_item__precious_metal").annotate(
            occupied_weight=ExpressionWrapper(
                F("quantity")
                * F("purchase_request__precious_item__precious_metal__weight"),
                output_field=DecimalField(max_digits=18, decimal_places=10),
            )
        ).aggregate(
            total_weight=Sum("occupied_weight")
        ).get(
            "total_weight"
        ) or Decimal(
            "0.00"
        )

        sale_quantity_subquery = (
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
            .annotate(total=Sum("requested_quantity"))
            .values("total")
        )

        asset_quantity_subquery = (
            AssetContribution.objects.filter(
                purchase_request=OuterRef("pk"),
                status__in=[
                    AssetContributionStatus.PENDING,
                    AssetContributionStatus.ADMIN_APPROVED,
                    AssetContributionStatus.APPROVED,
                ],
            )
            .values("purchase_request")
            .annotate(total=Sum("quantity"))
            .values("total")
        )

        remaining_quantity_expr = Greatest(
            F("requested_quantity")
            - Coalesce(Subquery(sale_quantity_subquery), Value(Decimal("0.00")))
            - Coalesce(Subquery(asset_quantity_subquery), Value(Decimal("0.00"))),
            Value(Decimal("0.00")),
        )

        total_available_stock = PurchaseRequest.objects.filter(
            request_type=RequestType.PURCHASE,
            status__in=[
                PurchaseRequestStatus.APPROVED,
                PurchaseRequestStatus.COMPLETED,
            ],
            precious_item__material_type=MaterialType.METAL,
        ).annotate(
            remaining_quantity=remaining_quantity_expr,
            available_weight=ExpressionWrapper(
                F("remaining_quantity") * F("precious_item__precious_metal__weight"),
                output_field=DecimalField(max_digits=18, decimal_places=10),
            ),
        ).aggregate(
            total_weight=Sum("available_weight")
        ).get(
            "total_weight"
        ) or Decimal(
            "0.00"
        )

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=ADMIN_MESSAGES["taqabeth_dashboard_data_fetched"],
            data={
                "total_occupied_stock": total_occupied_stock,
                "available_metal_stock": total_available_stock,
            },
        )
