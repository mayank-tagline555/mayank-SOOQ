import logging

from django.conf import settings
from django.db.models import Count
from django.db.models import Q
from django.db.models import Value
from django.db.models.functions import Coalesce
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.status import HTTP_200_OK
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.status import HTTP_403_FORBIDDEN

from investor.message import MESSAGES
from seller.filters import PreciousItemFilter
from seller.models import PreciousItem
from seller.serializers import PreciousItemResponseSerializer
from sooq_althahab.constants import PRODUCT_VIEW_PERMISSION
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.enums.investor import RequestType
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.helper import PermissionManager
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response

logger = logging.getLogger(__name__)

# Swagger parameters
PRODUCT_TYPE_PARAM = openapi.Parameter(
    name="product_type",
    in_=openapi.IN_QUERY,
    description="Specify the product type ('metal' or 'stone').",
    type=openapi.TYPE_STRING,
    required=False,
    enum=[choice[1] for choice in MaterialType.choices],
)


class BaseOrganizationView:
    """Base class for organization-related queryset filtering."""

    def get_queryset_by_organization(self, queryset, organization_id):
        """Filter queryset by organization users."""
        if not organization_id:
            return queryset.none()
        return queryset.filter(business__organization_id=organization_id).distinct()


class ProductListAPIView(BaseOrganizationView, ListAPIView):
    """Handles listing of Precious Items with filters."""

    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    serializer_class = PreciousItemResponseSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = PreciousItemFilter

    def get_queryset(self):
        """Override the get_queryset method to filter products by the organization of the current user."""
        organization_id = getattr(self.request.user, "organization_id", None)
        queryset = (
            PreciousItem.objects.filter(is_enabled=True)
            .select_related(
                "material_item",
                "precious_metal",
                "precious_stone",
                "created_by",
                "carat_type",
                "business",
                "material_item__global_metal",
            )
            .prefetch_related(
                "images",
                "business__user_assigned_businesses__user",
            )
            .exclude(created_by__in=settings.DEFAULT_SELLER_IDS)
            .annotate(
                completed_asset_purchase_request_count=Coalesce(
                    Count(
                        "purchase_requests",
                        filter=Q(
                            purchase_requests__status=PurchaseRequestStatus.COMPLETED,
                            purchase_requests__request_type=RequestType.PURCHASE,
                        ),
                        distinct=True,
                    ),
                    Value(0),
                )
            )
        )
        return self.get_queryset_by_organization(queryset, organization_id)

    @swagger_auto_schema(
        operation_description="Retrieve a list of Precious Metals with applied filters.",
        manual_parameters=[
            openapi.Parameter(
                "ordering",
                openapi.IN_QUERY,
                description="Order by `created_at, weight` field. Use `-` to sort in descending order.\n\n**Example**: `-created_at`.",
                type=openapi.TYPE_STRING,
            ),
            openapi.Parameter(
                "is_enabled",
                openapi.IN_QUERY,
                description="Filter by enabled status (true or false).\n\n**Example**: `true`",
                type=openapi.TYPE_BOOLEAN,
            ),
            openapi.Parameter(
                "material_type",
                openapi.IN_QUERY,
                description="Filter by material type (metal/stone).\n\n**Example**: `metal`",
                type=openapi.TYPE_STRING,
            ),
            openapi.Parameter(
                "material_item",
                openapi.IN_QUERY,
                description="Filter by material item.\n\n**Example**: `Gold, Silver, Ruby, etc.`",
                type=openapi.TYPE_STRING,
            ),
        ],
        responses={200: PreciousItemResponseSerializer(many=True)},
    )
    @PermissionManager(PRODUCT_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Retrieve a list of Precious Metals with applied filters."""
        queryset = self.filter_queryset(self.get_queryset())

        if not queryset.exists():
            return generic_response(
                status_code=HTTP_200_OK,
                message=MESSAGES["search_results_not_found"],
                data=[],
            )

        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(response_data)


class ProductRetrieveAPIView(BaseOrganizationView, RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PreciousItemResponseSerializer
    queryset = PreciousItem.objects.select_related(
        "material_item", "precious_metal", "precious_stone"
    ).prefetch_related("images")

    def get_queryset(self):
        """Filter products by the organization of the current user."""
        organization_id = getattr(self.request.user, "organization_id", None)
        queryset = (
            PreciousItem.objects.select_related(
                "material_item",
                "precious_metal",
                "precious_stone",
                "created_by",
                "carat_type",
                "business",
                "material_item__global_metal",
            )
            .prefetch_related(
                "images",
                "business__user_assigned_businesses__user",
            )
            .exclude(created_by__in=settings.DEFAULT_SELLER_IDS)
            .annotate(
                completed_asset_purchase_request_count=Coalesce(
                    Count(
                        "purchase_requests",
                        filter=Q(
                            purchase_requests__status=PurchaseRequestStatus.COMPLETED,
                            purchase_requests__request_type=RequestType.PURCHASE,
                        ),
                        distinct=True,
                    ),
                    Value(0),
                )
            )
        )
        return self.get_queryset_by_organization(queryset, organization_id)

    @swagger_auto_schema(manual_parameters=[PRODUCT_TYPE_PARAM])
    @PermissionManager(PRODUCT_VIEW_PERMISSION)
    def get(self, request, pk, *args, **kwargs):
        """Retrieve product details or show appropriate messages."""
        # First, check if the product belongs to admin/default sellers
        admin_product_exists = PreciousItem.objects.filter(
            pk=pk, created_by__in=settings.DEFAULT_SELLER_IDS
        ).exists()

        if admin_product_exists:
            return generic_response(
                status_code=HTTP_403_FORBIDDEN,
                error_message=MESSAGES["admin_asset_purchase_not_allowed"],
            )

        product = self.get_queryset().filter(pk=pk).first()

        if not product:
            return generic_response(
                status_code=HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["product_not_found"],
            )

        serializer = self.get_serializer(product)
        return generic_response(
            status_code=HTTP_200_OK,
            message=MESSAGES["product_retrieved"],
            data=serializer.data,
        )
