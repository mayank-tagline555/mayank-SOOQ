import logging
from datetime import date
from datetime import datetime
from decimal import Decimal
from itertools import chain

from django.contrib.contenttypes.models import ContentType
from django.db import close_old_connections
from django.db.models import Case
from django.db.models import DecimalField
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import FloatField
from django.db.models import Max
from django.db.models import OuterRef
from django.db.models import Prefetch
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import Sum
from django.db.models import Value
from django.db.models import When
from django.db.models.functions import Coalesce
from django.http import Http404
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveDestroyAPIView
from rest_framework.generics import UpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.validators import ValidationError
from rest_framework.views import APIView

from account.models import User
from account.utils import get_user_or_business_name
from investor.message import MESSAGES
from investor.models import AssetContribution
from investor.models import PreciousItemUnit
from investor.models import PurchaseRequest
from investor.serializers import AdminPurchaseRequestSerializer
from investor.serializers import PoolContributionResponseSerializer
from investor.serializers import PortfolioHistorySerializer
from investor.serializers import PurchaseRequestContributionSerializer
from investor.serializers import PurchaseRequestSerializer
from investor.serializers import PurchaseRequestSerializerV2
from investor.serializers import SaleRequestConfirmationSerializer
from investor.serializers import SaleRequestSerializer
from investor.serializers import SerialNumberValidationSerializer
from investor.utils import get_investors_total_assets
from investor.utils import get_investors_unsold_assets
from jeweler.models import MusharakahContractRequest
from jeweler.serializers import MusharakahContractRequestResponseSerializer
from seller.filters import PurchaseRequestFilter
from seller.serializers import BasePurchaseRequestSerializer
from seller.serializers import PurchaseRequestDetailsSerializer
from seller.serializers import PurchaseRequestResponseSerializer
from seller.utils import get_custom_time_range
from seller.utils import get_fcm_tokens_for_users
from sooq_althahab.billing.subscription.helpers import check_subscription_feature_access
from sooq_althahab.constants import ADMIN_PURCHASE_REQUEST_CREATE_PERMISSION
from sooq_althahab.constants import PURCHASE_REQUEST_CREATE_PERMISSION
from sooq_althahab.constants import PURCHASE_REQUEST_DELETE_PERMISSION
from sooq_althahab.constants import PURCHASE_REQUEST_VIEW_PERMISSION
from sooq_althahab.enums.account import SubscriptionFeatureChoices
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.account import UserType
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.enums.investor import RequestType
from sooq_althahab.enums.jeweler import MusharakahContractStatus
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.enums.sooq_althahab_admin import Status
from sooq_althahab.helper import PermissionManager
from sooq_althahab.querysets.purchase_request import base_purchase_request_queryset
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.tasks import send_mail
from sooq_althahab.tasks import send_notification
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab.utils import send_notification_count_to_users
from sooq_althahab.utils import send_notifications_to_organization_admins
from sooq_althahab_admin.models import Notification
from sooq_althahab_admin.models import PoolContribution

logger = logging.getLogger(__name__)


class BasePurchaseRequestView:
    """Base class for common query and accessibility logic for purchase requests."""

    def get_queryset_for_role(self, queryset):
        """Filter purchase requests based on user role and assigned business."""

        business = get_business_from_user_token(self.request, "business")
        if not business:
            return queryset.none()
        return queryset.filter(
            Q(business=business)
            # NOTE: Display only the user's own purchase requests, excluding contributed assets
            # | Q(asset_contributions__musharakah_contract_request__jeweler=business)
        ).distinct()


class PurchaseRequestListView(BasePurchaseRequestView, ListAPIView):
    """Handles listing all purchase requests."""

    pagination_class = CommonPagination
    permission_classes = [IsAuthenticated]
    serializer_class = PurchaseRequestDetailsSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = PurchaseRequestFilter

    def get_queryset(self):
        """Retrieve purchase requests based on the user's role and assigned business."""
        if self.request.user.is_anonymous:
            return PurchaseRequest.objects.none()

        base_queryset = base_purchase_request_queryset()

        business_purchase_requests = self.get_queryset_for_role(base_queryset)

        return get_investors_unsold_assets(business_purchase_requests)

    @PermissionManager(PURCHASE_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """List all purchase requests."""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["purchase_request_fetched"],
            data=response_data,
        )


class PendingPurchaseRequestListView(BasePurchaseRequestView, ListAPIView):
    """
    Handles listing all pending purchase and sale requests.

    This endpoint returns all requests (both Purchase and Sale) that are in pending states:
    - PENDING
    - PENDING_SELLER_PRICE
    - PENDING_INVESTOR_CONFIRMATION

    Designed for the investor app's "Pending" tab to show all pending requests.
    """

    pagination_class = CommonPagination
    permission_classes = [IsAuthenticated]
    serializer_class = PurchaseRequestDetailsSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = PurchaseRequestFilter

    def get_queryset(self):
        """Retrieve pending purchase and sale requests based on the user's role and assigned business."""
        if self.request.user.is_anonymous:
            return PurchaseRequest.objects.none()

        base_queryset = base_purchase_request_queryset()

        business_purchase_requests = self.get_queryset_for_role(base_queryset)

        # Filter for all pending statuses (both Purchase and Sale requests)
        pending_statuses = [
            PurchaseRequestStatus.PENDING,
            PurchaseRequestStatus.PENDING_SELLER_PRICE,
            PurchaseRequestStatus.PENDING_INVESTOR_CONFIRMATION,
        ]

        return business_purchase_requests.filter(
            status__in=pending_statuses,
            request_type__in=[RequestType.PURCHASE, RequestType.SALE],
        )

    @PermissionManager(PURCHASE_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """List all pending purchase and sale requests."""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["purchase_request_fetched"],
            data=response_data,
        )


class AvailableAssetPurchaseRequestAPIView(CreateAPIView):
    """
    API to fetch purchase requests (materials) eligible for Musharakah contracts.

    This endpoint returns a filtered list of approved or completed purchase requests
    that are compatible with an investor's available (unsold and unallocated) assets.

    Note: carat_type filtering is not applied - all available assets are shown regardless
    of carat_type, allowing users to allocate materials with different carat_types to contracts.
    "carat_type": "24k"

    ### Example Payload:

    ```json
    [
        {
            "material_type": "metal",
            "material_item": "Gold"
        },
        {
            "material_type": "metal",
            "material_item": "Silver"
        },
        {
            "material_type": "stone",
            "material_item": "Ruby",
            "shape_cut": "sct_210425d84b24",
            "weight": "895689.00",
            "cut_grade": "EXCELLENT"
            "stone_origin": "NATURAL"
        }
    ]
    ```

    Each object in the array represents a filter. You can combine different material and stone attributes.
    Note: carat_type filter is ignored for metals - all carat_types will be shown.
    """

    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    serializer_class = PurchaseRequestResponseSerializer

    @swagger_auto_schema(
        operation_description="Filter and retrieve purchase requests eligible for Musharakah contracts.\n\n"
        "Send an array of filter objects in the request body. Each object may contain:\n"
        "- `material_type` (e.g., 'metal' or 'stone')\n"
        "- `material_item` (e.g., 'Gold', 'Silver', 'Ruby')\n"
        "Note: `carat_type` filter is not applied - all available assets are shown regardless of carat_type.\n"
        "- `shape_cut`, `weight`, `cut_grade` for stones\n\n",
        request_body=openapi.Schema(
            type=openapi.TYPE_ARRAY,
            items=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "material_type": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        example="metal",
                        description="Type of material",
                    ),
                    "material_item": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        example="Gold",
                        description="Name of the material item",
                    ),
                    "carat_type": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        example="24k",
                        description="Carat type (for metals)",
                    ),
                    "shape_cut": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        example="sct_210425d84b24",
                        description="Shape cut ID (for stones)",
                    ),
                    "weight": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        example="895689.00",
                        description="Weight (for stones)",
                    ),
                    "cut_grade": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        example="EXCELLENT",
                        description="Cut grade (for stones)",
                    ),
                    "stone_origin": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        example="NATURAL",
                        description="Stone origin (for Diamonds)",
                    ),
                },
                required=[],
            ),
            description="Array of filter objects. Each object can include one or more filter fields.",
        ),
        responses={200: PurchaseRequestResponseSerializer(many=True)},
        manual_parameters=[
            openapi.Parameter(
                name="page",
                in_=openapi.IN_QUERY,
                description="Page number",
                type=openapi.TYPE_INTEGER,
            ),
            openapi.Parameter(
                name="page_size",
                in_=openapi.IN_QUERY,
                description="Number of items per page",
                type=openapi.TYPE_INTEGER,
            ),
        ],
    )
    @PermissionManager(PURCHASE_REQUEST_VIEW_PERMISSION)
    def post(self, request, *args, **kwargs):
        business = get_business_from_user_token(request, "business")
        filters = request.data

        if not isinstance(filters, list):
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=MESSAGES["filter_value_validation"],
                data=[],
            )

        query = Q()

        for filter_item in filters:
            condition = Q()
            stone_origin = filter_item.get("stone_origin", None)
            for key, value in filter_item.items():
                # Filter by material type (metal / stone)
                if key == "material_type":
                    condition &= Q(precious_item__material_type=value)

                # Metal-related fields (precious_item) - carat_type removed to show all available assets
                elif key == "material_item":
                    condition &= Q(**{f"precious_item__{key}__name": value})

                # Stone-related fields (precious_stone)
                elif key in ["shape_cut", "weight", "cut_grade"]:
                    condition &= Q(
                        **{
                            f"precious_item__precious_stone__{key}": value,
                            f"precious_item__material_item__stone_origin": stone_origin,
                        }
                    )

            query |= condition

        base_queryset = base_purchase_request_queryset().filter(
            business=business,
            request_type=RequestType.PURCHASE,
            status__in=[
                PurchaseRequestStatus.APPROVED,
                PurchaseRequestStatus.COMPLETED,
            ],
        )

        # Apply dynamic filters to the base queryset
        filtered_queryset = base_queryset.filter(query)

        # Include only investor assets that are not fully sold or allocated
        final_queryset = get_investors_total_assets(filtered_queryset).select_related(
            "precious_item__precious_metal",
            "precious_item__precious_stone",
        )

        # remaining_quantity is computed property (not DB annotation). Some rows can still
        # have 0 after DB filtering, so exclude them explicitly.
        available_purchase_requests = []
        unallocated_total_quantity = Decimal("0.0")
        unallocated_total_weight = Decimal("0.0")
        unallocated_total_metal_weight = Decimal("0.0")
        unallocated_total_stone_pieces = Decimal("0.0")

        for pr in final_queryset:
            remaining_qty = pr.remaining_quantity or Decimal("0.0")

            # Only keep assets that still have available quantity
            if remaining_qty > Decimal("0.0"):
                available_purchase_requests.append(pr)
                unallocated_total_quantity += remaining_qty

                # Material Wise Purchase request fetch (pr = Purchase request)
                metal_pr = getattr(pr.precious_item, "precious_metal", None)
                stone_pr = getattr(pr.precious_item, "precious_stone", None)

                # Get the weight per unit from metal or stone
                weight_per_unit = Decimal("0.0")
                if metal_pr:
                    weight_per_unit = Decimal(metal_pr.weight or 0)
                    unallocated_total_metal_weight += remaining_qty * weight_per_unit
                elif stone_pr:
                    unallocated_total_stone_pieces += remaining_qty

                unallocated_total_weight += remaining_qty * weight_per_unit

        # Paginate the filtered list
        page = self.paginate_queryset(available_purchase_requests)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        response_data["unallocated_assets"] = unallocated_total_quantity
        response_data["unallocated_total_weight"] = unallocated_total_weight
        response_data["unallocated_total_metal_weight"] = unallocated_total_metal_weight
        response_data["unallocated_total_stone_pieces"] = unallocated_total_stone_pieces

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["purchase_request_fetched"],
            data=response_data,
        )


class PortfolioHistoryAPIView(BasePurchaseRequestView, APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(
                name="type",
                in_=openapi.IN_QUERY,
                description="Filter by type. One of: PURCHASE_REQUEST, POOL_CONTRIBUTOR, MUSHARAKAH_CONTRACT",
                type=openapi.TYPE_STRING,
                enum=["PURCHASE_REQUEST", "POOL_CONTRIBUTOR", "MUSHARAKAH_CONTRACT"],
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
    @PermissionManager(PURCHASE_REQUEST_VIEW_PERMISSION)
    def get(self, request):
        business = get_business_from_user_token(request, "business")
        # Handle both single value and array of values
        type_filters = request.query_params.getlist("type")
        ordering = request.query_params.get("ordering")

        all_data = []

        # Determine which types to fetch
        # Case 1: No type filter → show all types
        # Case 2: Empty string in type filter → show all types
        # Case 3: Array with all three types → show all types
        # Case 4: Single or multiple specific types → show only requested types

        # Remove empty strings from the list
        type_filters = [t for t in type_filters if t and t.strip()]

        if not type_filters:
            # No type filter or only empty strings → show all types (default behavior)
            fetch_musharakah = True
            fetch_pool = True
            fetch_purchase = True
        elif len(type_filters) == 1:
            # Single type filter provided
            single_type = type_filters[0]
            fetch_musharakah = single_type == "MUSHARAKAH_CONTRACT"
            fetch_pool = single_type == "POOL_CONTRIBUTOR"
            fetch_purchase = single_type == "PURCHASE_REQUEST"
        else:
            # Multiple type filters provided - check if all three types are present
            all_types = {"MUSHARAKAH_CONTRACT", "POOL_CONTRIBUTOR", "PURCHASE_REQUEST"}
            type_set = set(type_filters)

            if all_types.issubset(type_set):
                # All three types present → show all
                fetch_musharakah = True
                fetch_pool = True
                fetch_purchase = True
            else:
                # Only some types → show only requested ones
                fetch_musharakah = "MUSHARAKAH_CONTRACT" in type_filters
                fetch_pool = "POOL_CONTRIBUTOR" in type_filters
                fetch_purchase = "PURCHASE_REQUEST" in type_filters

        # Fetch and serialize MusharakahContractRequests with optimized queries
        if fetch_musharakah:
            musharakah_qs = (
                MusharakahContractRequest.objects.select_related(
                    "jeweler",
                    "investor",
                )
                .prefetch_related(
                    "musharakah_contract_request_attachments",
                    "musharakah_contract_request_quantities",
                    Prefetch(
                        "asset_contributions",
                        queryset=AssetContribution.objects.select_related(
                            "purchase_request__precious_item__material_item",
                            "purchase_request__precious_item__precious_metal",
                            "purchase_request__precious_item__precious_stone",
                        ).prefetch_related("purchase_request__precious_item__images"),
                    ),
                )
                .filter(
                    Q(status=RequestStatus.REJECTED)
                    | (
                        Q(status=RequestStatus.APPROVED)
                        & Q(
                            musharakah_contract_status__in=[
                                MusharakahContractStatus.UNDER_TERMINATION,
                                MusharakahContractStatus.TERMINATED,
                            ]
                        )
                    ),
                    investor=business,
                )
            )
            musharakah_contract_request_serializer = (
                MusharakahContractRequestResponseSerializer(
                    musharakah_qs, many=True
                ).data
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
            all_data.extend(musharakah_list)

        # Fetch and serialize PoolContributions with optimized queries
        if fetch_pool:
            pool_qs = (
                PoolContribution.objects.select_related("pool", "participant")
                .prefetch_related(
                    Prefetch(
                        "asset_contributions",
                        queryset=AssetContribution.objects.select_related(
                            "purchase_request__precious_item__material_item",
                            "purchase_request__precious_item__precious_metal",
                            "purchase_request__precious_item__precious_stone",
                        ).prefetch_related("purchase_request__precious_item__images"),
                    )
                )
                .filter(participant=business, status=Status.REJECTED)
            )
            pool_serializer = PoolContributionResponseSerializer(
                pool_qs, many=True, context={"request": request}
            ).data
            pool_list = [
                {
                    "id": str(item["id"]),
                    "type": "POOL_CONTRIBUTOR",
                    "created_at": item["created_at"],
                    "data": item,
                }
                for item in pool_serializer
            ]
            all_data.extend(pool_list)

        # Fetch and serialize PurchaseRequests with optimized queries
        # Exclude purchase requests with jewelry_product (jewelry designs from musharakah termination)
        # These are already shown in the assets list, so they shouldn't appear in history
        if fetch_purchase:
            purchase_request_qs = base_purchase_request_queryset()
            purchase_requests = self.get_queryset_for_role(purchase_request_qs).filter(
                jewelry_product__isnull=True
            )
            purchase_request_serializer = PurchaseRequestResponseSerializer(
                purchase_requests, many=True
            ).data
            purchase_requests_list = [
                {
                    "id": str(item["id"]),
                    "type": "PURCHASE_REQUEST",
                    "created_at": item["created_at"],
                    "data": item,
                }
                for item in purchase_request_serializer
            ]
            all_data.extend(purchase_requests_list)

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
            message=MESSAGES["portfolio_history_fetched"],
            data=paginator.get_paginated_response(serializer.data).data,
        )


class PurchaseRequestCreateView(BasePurchaseRequestView, CreateAPIView):
    """Handles creating asset purchase requests for version 1."""

    permission_classes = [IsAuthenticated]
    serializer_class = PurchaseRequestSerializer

    @PermissionManager(PURCHASE_REQUEST_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        """Create a new asset purchase request."""
        user = request.user
        organization_code = request.auth.get("organization_code")

        # If investor is individual then pass full name or else pass business name
        investor_name = get_user_or_business_name(request)
        if not investor_name:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["business_account_not_found"],
            )

        # Check subscription feature access (only for INVESTOR role)
        business = get_business_from_user_token(request, "business")
        if (
            business
            and business.business_account_type == UserRoleBusinessChoices.INVESTOR
        ):
            try:
                check_subscription_feature_access(
                    business, SubscriptionFeatureChoices.PURCHASE_ASSETS
                )
            except ValidationError as ve:
                error_msg = (
                    ve.detail[0] if isinstance(ve.detail, list) else str(ve.detail)
                )
                return generic_response(
                    status_code=status.HTTP_403_FORBIDDEN,
                    error_message=error_msg,
                )

        asset_purchase_request_serializer = self.get_serializer(data=request.data)

        if not asset_purchase_request_serializer.is_valid():
            return handle_serializer_errors(asset_purchase_request_serializer)

        try:
            organization = user.organization_id
            purchase_request_instance = asset_purchase_request_serializer.save(
                created_by=user, organization_id=organization
            )
        except ValidationError as ve:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=ve.detail[0],
            )

        # Get users associated with the seller's business of the precious item
        users_in_seller_business = User.objects.filter(
            user_assigned_businesses__business=purchase_request_instance.precious_item.business,
            user_preference__notifications_enabled=True,
        )

        tokens = get_fcm_tokens_for_users(users_in_seller_business)
        title = "Purchase request created."
        notification_type = NotificationTypes.PURCHASE_REQUEST_CREATED
        content_type = ContentType.objects.get_for_model(PurchaseRequest)
        if tokens:
            body = f"Purchase request for your precious item {purchase_request_instance.precious_item.name}."

            # Create a notification for each seller's business user
            notifications = [
                Notification(
                    user=user,
                    title=title,
                    message=body,
                    notification_type=notification_type,
                    content_type=content_type,
                    object_id=purchase_request_instance.id,
                )
                for user in users_in_seller_business
            ]
            # Bulk insert notifications, ignoring conflicts from concurrent operations
            Notification.objects.bulk_create(notifications, ignore_conflicts=True)

            # Serialize just **one** notification (since all are identical)
            notification_data = {
                "notification_type": notification_type,
                "id": str(purchase_request_instance.id),
            }

            # Send notifications to seller's business users asynchronously

            send_notification_count_to_users(users_in_seller_business)
            send_notification.delay(tokens, title, body, notification_data)

        # Send notification to organization admin's
        user_type = (
            "(Business)" if user.user_type == UserType.BUSINESS else "(Individual)"
        )
        message = f"'{investor_name}' {user_type} has created an asset purchase request for '{purchase_request_instance.precious_item}' from the business '{purchase_request_instance.precious_item.business.name}'."
        send_notifications_to_organization_admins(
            organization_code,
            title,
            message,
            notification_type,
            content_type,
            purchase_request_instance.id,
            UserRoleChoices.TAQABETH_ENFORCER,
        )

        return generic_response(
            status_code=status.HTTP_201_CREATED,
            message=MESSAGES["purchase_request_created"],
            data=asset_purchase_request_serializer.data,
        )


class PurchaseRequestCreateViewV2(BasePurchaseRequestView, CreateAPIView):
    """Handles creating asset purchase requests for version 2. it include vat and pro rata changes."""

    permission_classes = [IsAuthenticated]
    serializer_class = PurchaseRequestSerializerV2

    @PermissionManager(PURCHASE_REQUEST_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        """Create a new asset purchase request."""
        user = request.user
        organization_code = request.auth.get("organization_code")

        # If investor is individual then pass full name or else pass business name
        investor_name = get_user_or_business_name(request)
        if not investor_name:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["business_account_not_found"],
            )

        # Check subscription feature access (only for INVESTOR role)
        business = get_business_from_user_token(request, "business")
        if (
            business
            and business.business_account_type == UserRoleBusinessChoices.INVESTOR
        ):
            try:
                check_subscription_feature_access(
                    business, SubscriptionFeatureChoices.PURCHASE_ASSETS
                )
            except ValidationError as ve:
                error_msg = (
                    ve.detail[0] if isinstance(ve.detail, list) else str(ve.detail)
                )
                return generic_response(
                    status_code=status.HTTP_403_FORBIDDEN,
                    error_message=error_msg,
                )

        asset_purchase_request_serializer = self.get_serializer(data=request.data)

        if not asset_purchase_request_serializer.is_valid():
            return handle_serializer_errors(asset_purchase_request_serializer)

        try:
            organization = user.organization_id
            purchase_request_instance = asset_purchase_request_serializer.save(
                created_by=user, organization_id=organization
            )
        except ValidationError as ve:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=ve.detail[0],
            )

        # Get users associated with the seller's business of the precious item
        users_in_seller_business = User.objects.filter(
            user_assigned_businesses__business=purchase_request_instance.precious_item.business,
            user_preference__notifications_enabled=True,
        )

        tokens = get_fcm_tokens_for_users(users_in_seller_business)
        title = "Purchase request created."
        notification_type = NotificationTypes.PURCHASE_REQUEST_CREATED
        content_type = ContentType.objects.get_for_model(PurchaseRequest)
        body = f"Purchase request for your precious item {purchase_request_instance.precious_item.name}."
        if tokens:
            # Create a notification for each seller's business user
            notifications = [
                Notification(
                    user=user,
                    title=title,
                    message=body,
                    notification_type=notification_type,
                    content_type=content_type,
                    object_id=purchase_request_instance.id,
                )
                for user in users_in_seller_business
            ]
            # Bulk insert notifications, ignoring conflicts from concurrent operations
            Notification.objects.bulk_create(notifications, ignore_conflicts=True)

            # Serialize just **one** notification (since all are identical)
            notification_data = {
                "notification_type": notification_type,
                "id": str(purchase_request_instance.id),
            }

            # Send notifications to seller's business users asynchronously

            send_notification_count_to_users(users_in_seller_business)
            send_notification.delay(tokens, title, body, notification_data)

        # Send notification to organization admin's
        user_type = (
            "(Business)" if user.user_type == UserType.BUSINESS else "(Individual)"
        )
        message = f"'{investor_name}' {user_type} has created an asset purchase request for '{purchase_request_instance.precious_item}' from the business '{purchase_request_instance.precious_item.business.name}'."
        send_notifications_to_organization_admins(
            organization_code,
            title,
            message,
            notification_type,
            content_type,
            purchase_request_instance.id,
            UserRoleChoices.TAQABETH_ENFORCER,
        )
        response_purchase_request_serializer = BasePurchaseRequestSerializer(
            purchase_request_instance
        )
        recipient_email = users_in_seller_business.values_list("email", flat=True)
        email_context = {
            "precious_item_name": purchase_request_instance.precious_item.name,
            "order_cost": purchase_request_instance.order_cost,
            "purchase_request": response_purchase_request_serializer.data,
            "message": body,
            "business_name": purchase_request_instance.precious_item.business.name,
            "total_amount": purchase_request_instance.total_cost,
            "date": purchase_request_instance.created_at.date(),
            "requested_quantity": purchase_request_instance.requested_quantity,
        }  # Debug: print context dictionary

        send_mail.delay(
            subject="Purchase Request Created",
            template_name="templates/purchase-request.html",
            context=email_context,
            to_emails=list(recipient_email),
        )

        return generic_response(
            status_code=status.HTTP_201_CREATED,
            message=MESSAGES["purchase_request_created"],
            data=asset_purchase_request_serializer.data,
        )


class AdminPurchaseRequestCreateView(BasePurchaseRequestView, CreateAPIView):
    """Handles assign precious metal to the investors assets."""

    permission_classes = [IsAuthenticated]
    serializer_class = AdminPurchaseRequestSerializer

    @PermissionManager(ADMIN_PURCHASE_REQUEST_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        """Assign precious item to selected investor"""

        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        try:
            serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["purchase_request_created_and_assigned_precious_item"],
                data=serializer.data,
            )
        except ValidationError as ve:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=ve.detail[0],
            )


class PurchaseRequestRetrieveDeleteView(
    BasePurchaseRequestView, RetrieveDestroyAPIView
):
    """Handles retrieving and deleting specific purchase requests."""

    serializer_class = PurchaseRequestDetailsSerializer
    permission_classes = [IsAuthenticated]
    queryset = base_purchase_request_queryset()

    def get_queryset(self):
        """Retrieve purchase requests based on the user's role and assigned business."""
        if self.request.user.is_anonymous:
            return PurchaseRequest.objects.none()

        return self.get_queryset_for_role(self.queryset)

    @PermissionManager(PURCHASE_REQUEST_VIEW_PERMISSION)
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a specific purchase request."""

        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data,
                message=MESSAGES["purchase_request_retrieved"],
                status_code=status.HTTP_200_OK,
            )
        except Http404:
            return generic_response(
                error_message=MESSAGES["purchase_request_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

    @PermissionManager(PURCHASE_REQUEST_DELETE_PERMISSION)
    def destroy(self, request, *args, **kwargs):
        """Delete a specific purchase request."""

        try:
            instance = self.get_object()
            instance.hard_delete()
            return generic_response(
                message=MESSAGES["purchase_request_deleted"],
                status_code=status.HTTP_200_OK,
            )
        except Http404:
            return generic_response(
                error_message=MESSAGES["purchase_request_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )


class PurchaseRequestDeleteRetrieveAPIView(PurchaseRequestRetrieveDeleteView):
    """API view to retrieve and delete purchase requests only for jeweler."""

    @PermissionManager(PURCHASE_REQUEST_VIEW_PERMISSION)
    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            business = get_business_from_user_token(request, "business")

            if instance.business == business:
                serializer = self.get_serializer(instance)
            else:
                serializer = PurchaseRequestContributionSerializer(
                    instance, context={"request": request}
                )
            return generic_response(
                data=serializer.data,
                message=MESSAGES["purchase_request_retrieved"],
                status_code=status.HTTP_200_OK,
            )
        except Http404:
            return generic_response(
                error_message=MESSAGES["purchase_request_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )


class RealizedProfitView(APIView, BasePurchaseRequestView):
    """Retrieve realized profit grouped by time ranges from investor's sold purchased assets."""

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return PurchaseRequest.objects.none()
        return self.get_queryset_for_role(base_purchase_request_queryset())

    def get(self, request):
        # Prefetch related sales only where they are approved
        approved_sales = PurchaseRequest.objects.filter(
            request_type=RequestType.SALE,
            status=PurchaseRequestStatus.APPROVED,
        )

        purchase_requests = (
            self.get_queryset()
            .filter(
                request_type=RequestType.PURCHASE,
                status__in=[
                    PurchaseRequestStatus.APPROVED,
                    PurchaseRequestStatus.COMPLETED,
                ],
            )
            .prefetch_related(
                Prefetch(
                    "sale_requests", queryset=approved_sales, to_attr="approved_sales"
                )
            )
        )

        realized_profit, total_invested = self.calculate_profit_and_investment(
            purchase_requests
        )

        return generic_response(
            message=MESSAGES["realized_profit_retrieved"],
            status_code=status.HTTP_200_OK,
            data={
                "total_realized_profit": realized_profit,
                "total_invested": total_invested,
            },
        )

    def calculate_profit_and_investment(self, purchase_requests):
        time_ranges = get_custom_time_range()
        profit_result = {}
        base_amount = {}

        for label, date_range in time_ranges.items():
            # Filter by date range
            if isinstance(date_range, tuple) and len(date_range) == 2:
                start, end = date_range
                filtered_purchases = [
                    pr for pr in purchase_requests if start <= pr.created_at <= end
                ]
            elif isinstance(date_range, (datetime, date)):
                filtered_purchases = [
                    pr for pr in purchase_requests if pr.created_at >= date_range
                ]
            else:
                filtered_purchases = purchase_requests

            total_profit = Decimal("0.0")
            total_cost = Decimal("0.0")

            for purchase in filtered_purchases:
                sales_requests = getattr(purchase, "approved_sales", [])
                total_profit += self._calculate_profit(sales_requests, purchase)
                total_cost += purchase.order_cost or Decimal("0.0")

            profit_result[label] = round(total_profit, 2)
            base_amount[label] = round(total_cost, 2)

        return profit_result, base_amount

    def _calculate_profit(self, sales_requests, purchase):
        """Calculate profit from sales related to one purchase."""
        total_revenue = Decimal("0.0")
        quantity_sold = Decimal("0.0")

        for sale in sales_requests:
            revenue = (
                (sale.order_cost or Decimal("0.0"))
                - (sale.platform_fee or Decimal("0.0"))
                - (sale.vat or Decimal("0.0"))
                - (sale.taxes or Decimal("0.0"))
            )
            total_revenue += revenue
            quantity_sold += sale.requested_quantity or Decimal("0.0")

        if quantity_sold > 0 and purchase.order_cost and purchase.requested_quantity:
            cost_per_unit = purchase.order_cost / purchase.requested_quantity
            proportional_cost = quantity_sold * cost_per_unit
        else:
            proportional_cost = Decimal("0.0")

        return total_revenue - proportional_cost


class MyAssetsView(APIView, BasePurchaseRequestView):
    """
    API endpoint to retrieve investor purchase request statistics
    and completed asset breakdown by material.
    """

    permission_classes = [IsAuthenticated]
    queryset = base_purchase_request_queryset()

    def get_queryset(self):
        """Retrieve purchase requests based on the user's role and assigned business."""
        if self.request.user.is_anonymous:
            return PurchaseRequest.objects.none()
        return self.get_queryset_for_role(self.queryset)

    def get(self, request):
        """GET: Return status summary and material-wise breakdown of completed purchases."""
        # Close any stale database connections before starting
        close_old_connections()

        try:
            queryset = self.get_queryset()
            total_investor_assets = get_investors_unsold_assets(queryset)

            completed_purchases = total_investor_assets.filter(
                status__in=[
                    PurchaseRequestStatus.COMPLETED,
                    PurchaseRequestStatus.APPROVED,
                ],
                request_type=RequestType.PURCHASE,
            )

            # Assets purchased (filtering by purchase type only)
            total_purchased_assets = queryset.filter(request_type=RequestType.PURCHASE)

            # Total contribution quantity (allocated to pool/musharaka)
            allocated_assets_contribution_quantity = (
                AssetContribution.objects.filter(
                    purchase_request__in=total_purchased_assets
                ).aggregate(total_quantity=Sum("quantity"))["total_quantity"]
                or 0
            )

            # Annotate investor assets with sold and contribution subqueries
            total_sold_subquery = (
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
                .values("total_sold")[:1]
            )

            total_contribution_subquery = (
                AssetContribution.objects.filter(purchase_request=OuterRef("pk"))
                .values("purchase_request")
                .annotate(total_contributed=Sum("quantity"))
                .values("total_contributed")[:1]
            )

            total_investor_assets = total_investor_assets.annotate(
                total_sold=Coalesce(
                    Subquery(total_sold_subquery, output_field=DecimalField()),
                    Value(Decimal("0.0")),
                ),
                total_contributed=Coalesce(
                    Subquery(total_contribution_subquery, output_field=DecimalField()),
                    Value(Decimal("0.0")),
                ),
                remaining_quantity=ExpressionWrapper(
                    F("requested_quantity") - F("total_sold") - F("total_contributed"),
                    output_field=DecimalField(),
                ),
            )

            purchase_status_counts = {
                # Count of all purchase requests grouped by status
                "purchase_requests_counts": {
                    "pending": total_investor_assets.filter(
                        status=PurchaseRequestStatus.PENDING,
                        remaining_quantity__gt=0,
                    ).count(),
                    "approved": total_investor_assets.filter(
                        status__in=[
                            PurchaseRequestStatus.APPROVED,
                            PurchaseRequestStatus.COMPLETED,
                        ],
                        remaining_quantity__gt=0,
                    ).count(),
                    "total": total_purchased_assets.count(),
                },
                # Total remaining quantity of purchase requests grouped by status
                "purchase_requests_quantities": {
                    "pending": total_investor_assets.filter(
                        status=PurchaseRequestStatus.PENDING,
                        remaining_quantity__gt=0,
                    ).aggregate(total=Sum("remaining_quantity"))["total"]
                    or 0,
                    "approved": total_investor_assets.filter(
                        status__in=[
                            PurchaseRequestStatus.APPROVED,
                            PurchaseRequestStatus.COMPLETED,
                        ],
                        remaining_quantity__gt=0,
                    ).aggregate(total=Sum("remaining_quantity"))["total"]
                    or 0,
                    # Quantity already allocated (e.g., to pools or musharakah)
                    "allocated": allocated_assets_contribution_quantity,
                    #
                    "total": (
                        total_investor_assets.filter(
                            remaining_quantity__gt=0
                        ).aggregate(total=Sum("remaining_quantity"))["total"]
                        or 0
                    )
                    + allocated_assets_contribution_quantity,
                },
            }

            material_breakdown = self.get_material_assets(completed_purchases)

            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["purchased_assets_statistics_retrieved"],
                data={**purchase_status_counts, **material_breakdown},
            )
        finally:
            # Always close connections after database operations
            close_old_connections()

    def get_material_assets(self, completed_purchases):
        """
        Returns a detailed breakdown of purchased assets grouped by material.

        Metals are organized by material name and carat type, while stones are listed as flat entries.
        The breakdown includes total remaining quantity, total cost, and the latest purchase date.
        """
        data = {"metal": {}, "stone": []}
        return {
            "material_assets_value": self.aggregate_material_data(
                data, completed_purchases, detailed=True
            )
        }

    def aggregate_material_data(self, material_data, purchases, detailed=False):
        """
        Aggregates asset data based on type, carat, remaining quantity, cost, and purchase history.

        Remaining quantity is calculated by excluding amounts that have already been sold or allocated.
        For metals, quantity is also adjusted using the associated metal weight.
        The result includes both quantity and cost grouped accordingly.
        """
        # total_allocated, total_sold, and total_contributed are already annotated in queryset
        # order_cost is showing all remaining qty purchased cost (requested_qty - sold - allocated)
        # remaining_quantity is a model-level property (not a database field) representing the quantity that is not sold or allocated.
        assets = purchases.values(
            material_name=F("precious_item__material_item__name"),
            material_type=F("precious_item__material_type"),
            carat_type=F("precious_item__carat_type__name"),
        ).annotate(
            remaining_quantity=ExpressionWrapper(
                F("requested_quantity") - F("total_allocated"),
                output_field=FloatField(),
            ),
            total_quantity=Case(
                When(
                    precious_item__material_type="metal",
                    then=ExpressionWrapper(
                        (F("requested_quantity") - F("total_allocated"))
                        * F("precious_item__precious_metal__weight"),
                        output_field=FloatField(),
                    ),
                ),
                default=F("requested_quantity") - F("total_allocated"),
                output_field=FloatField(),
            ),
            order_cost=ExpressionWrapper(
                (F("requested_quantity") - F("total_allocated"))
                * F("order_cost")
                / F("requested_quantity"),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            ),
            last_purchased_at=Max("completed_at"),
        )

        for asset in assets:
            material_type = asset["material_type"]
            material_name = asset["material_name"]
            carat_type = asset.get("carat_type") or "Unknown"
            total_quantity = asset.get("total_quantity") or 0
            total_cost = asset.get("order_cost") or 0
            last_purchased_at = asset.get("last_purchased_at")

            if material_type == "metal":
                # Metal should use carat_type
                if detailed:
                    metal_carat_data = (
                        material_data["metal"]
                        .setdefault(material_name, {})
                        .setdefault(
                            carat_type,
                            {
                                "total_quantity": 0,
                                "total_cost": 0,
                                "last_purchased_at": None,
                            },
                        )
                    )

                    metal_carat_data["total_quantity"] += total_quantity
                    metal_carat_data["total_cost"] += total_cost

                    # Update last_purchased_at if more recent
                    if not metal_carat_data["last_purchased_at"] or (
                        last_purchased_at
                        and last_purchased_at > metal_carat_data["last_purchased_at"]
                    ):
                        metal_carat_data["last_purchased_at"] = last_purchased_at
                else:
                    material_data["metal"].setdefault(material_name, {}).setdefault(
                        carat_type, 0
                    )
                    material_data["metal"][material_name][carat_type] += total_quantity

            else:  # Handle stones (non-metal)
                if detailed:
                    material_data["stone"].append(
                        {
                            "material_name": material_name,
                            "total_quantity": total_quantity,
                            "total_cost": total_cost,
                            "last_purchased_at": last_purchased_at,
                        }
                    )
                else:
                    material_data["stone"].setdefault(material_name, 0)
                    material_data["stone"][material_name] += total_cost

        return material_data


class SaleRequestCreateView(BasePurchaseRequestView, CreateAPIView):
    """Handles creating asset sale requests from completed purchase requests."""

    permission_classes = [IsAuthenticated]
    serializer_class = SaleRequestSerializer
    response_serializer_class = PurchaseRequestResponseSerializer

    def post(self, request, *args, **kwargs):
        """Create a new asset sale request from a completed purchase request."""

        user = request.user
        organization_code = request.auth.get("organization_code")

        # If investor is individual then pass full name or else pass business name
        investor_name = get_user_or_business_name(request)
        if not investor_name:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["business_account_not_found"],
            )

        # Check subscription feature access (selling assets requires PURCHASE_ASSETS feature)
        # Only validate for INVESTOR role users
        business = get_business_from_user_token(request, "business")
        if (
            business
            and business.business_account_type == UserRoleBusinessChoices.INVESTOR
        ):
            try:
                check_subscription_feature_access(
                    business, SubscriptionFeatureChoices.PURCHASE_ASSETS
                )
            except ValidationError as ve:
                error_msg = (
                    ve.detail[0] if isinstance(ve.detail, list) else str(ve.detail)
                )
                return generic_response(
                    status_code=status.HTTP_403_FORBIDDEN,
                    error_message=error_msg,
                )

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        sale_request_instance = serializer.save()

        # Fetch seller business instances
        seller_business_instance = sale_request_instance.precious_item.business

        # Fetch users and tokens for notifications
        users_in_seller_business = User.objects.filter(
            user_assigned_businesses__business=seller_business_instance,
            user_preference__notifications_enabled=True,
        )
        tokens = get_fcm_tokens_for_users(users_in_seller_business)
        title = "Sale request created."
        content_type = ContentType.objects.get_for_model(PurchaseRequest)
        notification_type = NotificationTypes.SALE_REQUEST_CREATED
        purchase_request_id = sale_request_instance.related_purchase_request.id
        if tokens:
            body = f"Sale request for the precious item '{sale_request_instance.precious_item.name}' has been created."

            # Create a notification for each seller's business user
            notifications = [
                Notification(
                    user=user,
                    title=title,
                    message=body,
                    notification_type=notification_type,
                    content_type=content_type,
                    object_id=purchase_request_id,
                )
                for user in users_in_seller_business
            ]
            # Bulk insert notifications, ignoring conflicts from concurrent operations
            Notification.objects.bulk_create(notifications, ignore_conflicts=True)

            # Serialize just **one** notification (since all are identical)
            notification_data = {
                "notification_type": notification_type,
                "id": str(sale_request_instance.id),
            }

            # Send notifications to seller's business users asynchronously
            send_notification_count_to_users(users_in_seller_business)
            send_notification.delay(tokens, title, body, notification_data)

        # Send notification to admin
        user_type = (
            "(Business)" if user.user_type == UserType.BUSINESS else "(Individual)"
        )
        message = f"'{investor_name}' {user_type} has created an asset sale request for '{sale_request_instance.precious_item}' from the business '{sale_request_instance.precious_item.business}'."
        send_notifications_to_organization_admins(
            organization_code,
            title,
            message,
            notification_type,
            content_type,
            sale_request_instance.id,
            UserRoleChoices.TAQABETH_ENFORCER,
        )

        return generic_response(
            status_code=status.HTTP_201_CREATED,
            message=MESSAGES["sale_request_created"],
            data=self.response_serializer_class(sale_request_instance).data,
        )


class SaleRequestConfirmationView(UpdateAPIView):
    """View for investor to approve/reject sale requests with proposed price."""

    permission_classes = [IsAuthenticated]
    serializer_class = SaleRequestConfirmationSerializer

    def get_queryset(self):
        """Filter sale requests for the investor's business."""
        if self.request.user.is_anonymous:
            return PurchaseRequest.objects.none()

        business = get_business_from_user_token(self.request, "business")
        if not business:
            return PurchaseRequest.objects.none()

        return base_purchase_request_queryset().filter(
            business=business,
            request_type=RequestType.SALE,
        )

    def get_object(self):
        """Retrieve the sale request instance."""
        sale_request_id = self.kwargs.get("pk")
        try:
            return self.get_queryset().get(id=sale_request_id)
        except PurchaseRequest.DoesNotExist:
            raise Http404

    @PermissionManager(PURCHASE_REQUEST_VIEW_PERMISSION)
    def patch(self, request, *args, **kwargs):
        """Approve or reject a sale request with proposed price."""
        try:
            sale_request = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["purchase_request_not_found"],
            )

        serializer = self.get_serializer(
            data=request.data, context={"sale_request": sale_request}
        )
        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        new_status = serializer.validated_data["status"]

        # Update the sale request status
        # Flow: PENDING_SELLER_PRICE -> PENDING_INVESTOR_CONFIRMATION -> PENDING (if approved) / REJECTED (if rejected)
        # When investor approves, status becomes PENDING (seller can approve/reject for final payment)
        # When investor rejects, status becomes REJECTED
        if new_status == PurchaseRequestStatus.APPROVED:
            # Investor approved, set status to PENDING so seller can approve/reject for final payment
            sale_request.status = PurchaseRequestStatus.PENDING
        elif new_status == PurchaseRequestStatus.REJECTED:
            # Investor rejected, set status to REJECTED
            sale_request.status = PurchaseRequestStatus.REJECTED

        sale_request.action_by = request.user
        sale_request.save()

        # If approved, seller will use UpdatePurchaseRequestStatusView to approve
        # which will trigger the payment flow (seller needs to approve to trigger payment)

        # Send notification to seller
        seller_business = sale_request.precious_item.business
        users_in_seller_business = User.objects.filter(
            user_assigned_businesses__business=seller_business,
            user_preference__notifications_enabled=True,
        )

        if users_in_seller_business.exists():
            title = (
                "Sale request approved by investor."
                if new_status == PurchaseRequestStatus.APPROVED
                else "Sale request rejected by investor."
            )
            body = (
                f"Investor has approved your proposed price for sale request '{sale_request.precious_item.name}'."
                if new_status == PurchaseRequestStatus.APPROVED
                else f"Investor has rejected your proposed price for sale request '{sale_request.precious_item.name}'."
            )
            # We use this notification type (SALE_REQUEST_CREATED) after the investor accepts
            # the price because we want to redirect the user to the sale request approval page.
            notification_type = (
                NotificationTypes.SALE_REQUEST_CREATED
                if new_status == PurchaseRequestStatus.APPROVED
                else NotificationTypes.SALE_REQUEST_REJECTED
            )
            content_type = ContentType.objects.get_for_model(PurchaseRequest)

            tokens = get_fcm_tokens_for_users(users_in_seller_business)
            if tokens:
                notifications = [
                    Notification(
                        user=user,
                        title=title,
                        message=body,
                        notification_type=notification_type,
                        content_type=content_type,
                        object_id=sale_request.id,
                    )
                    for user in users_in_seller_business
                ]
                Notification.objects.bulk_create(notifications, ignore_conflicts=True)

                notification_data = {
                    "notification_type": notification_type,
                    "id": str(sale_request.id),
                }

                send_notification_count_to_users(users_in_seller_business)
                send_notification.delay(tokens, title, body, notification_data)

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=(
                MESSAGES["sale_request_approved"]
                if new_status == PurchaseRequestStatus.APPROVED
                else MESSAGES["sale_request_rejected"]
            ),
            data=PurchaseRequestResponseSerializer(sale_request).data,
        )


class SerialNumberValidationAPIView(APIView):
    """
    API to validate serial_number and system_serial_number uniqueness.

    - serial_number + purchase_request_id → scoped check
    - system_serial_number → global check

    If both are provided, serial_number validation is applied.
    """

    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        request_body=SerialNumberValidationSerializer,
        responses={
            200: openapi.Response(
                description="Validation result",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "exists": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        "message": openapi.Schema(type=openapi.TYPE_STRING),
                    },
                ),
            ),
            400: openapi.Response(description="Invalid request"),
            404: openapi.Response(description="Purchase request not found"),
        },
    )
    def post(self, request):
        serializer = SerialNumberValidationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        serial_number = serializer.validated_data.get("serial_number")
        system_serial_number = serializer.validated_data.get("system_serial_number")
        purchase_request_id = serializer.validated_data.get("purchase_request_id")

        if serial_number:
            if not PurchaseRequest.objects.filter(id=purchase_request_id).exists():
                return generic_response(
                    status_code=status.HTTP_404_NOT_FOUND,
                    error_message=MESSAGES["purchase_request_not_found"],
                )

            exists = PreciousItemUnit.objects.filter(
                purchase_request_id=purchase_request_id,
                serial_number__iexact=serial_number,
            ).exists()

            return generic_response(
                status_code=status.HTTP_200_OK,
                data={
                    "exists": exists,
                    "message": (
                        MESSAGES["serial_number_exists"]
                        if exists
                        else MESSAGES["serial_number_unique"]
                    ),
                },
            )

        exists = (
            PreciousItemUnit.objects.filter(
                system_serial_number__iexact=system_serial_number
            )
            .exclude(system_serial_number__isnull=True)
            .exclude(system_serial_number="")
            .exists()
        )

        return generic_response(
            status_code=status.HTTP_200_OK,
            data={
                "exists": exists,
                "message": (
                    MESSAGES["system_serial_number_exists"]
                    if exists
                    else MESSAGES["system_serial_number_unique"]
                ),
            },
        )
