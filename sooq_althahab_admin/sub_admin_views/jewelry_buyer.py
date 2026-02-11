from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.generics import UpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from account.message import MESSAGES as ACCOUNT_MESSAGES
from account.models import Transaction
from account.models import User
from jeweler.models import JewelryProductMarketplace
from jeweler.models import JewelryStock
from jeweler.models import JewelryStockSale
from jeweler.models import ManufacturingProductRequestedQuantity
from sooq_althahab.constants import STOCK_MANAGEMENT_UPDATE_PERMISSION
from sooq_althahab.constants import STOCK_MANAGEMENT_VIEW_PERMISSION
from sooq_althahab.enums.jeweler import DeliveryStatus
from sooq_althahab.enums.jeweler import StockStatus
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.helper import PermissionManager
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab.utils import send_notifications
from sooq_althahab_admin.filters import JewelryProductMarketplaceFilter
from sooq_althahab_admin.filters import JewelryStockFilter
from sooq_althahab_admin.filters import JewelryStockSaleFilter
from sooq_althahab_admin.message import MESSAGES as ADMIN_MESSAGES
from sooq_althahab_admin.serializers import JewelryProductMarketplaceCreateSerializer
from sooq_althahab_admin.serializers import JewelryProductMarketplaceSerializer
from sooq_althahab_admin.serializers import JewelrySaleCreateSerializer
from sooq_althahab_admin.serializers import JewelrySaleDetailSerializer
from sooq_althahab_admin.serializers import JewelrySaleListSerializer
from sooq_althahab_admin.serializers import JewelrySaleUpdateSerializer
from sooq_althahab_admin.serializers import JewelryStockDetailSerializer
from sooq_althahab_admin.serializers import JewelryStockListSerializer
from sooq_althahab_admin.serializers import JewelryStockUpdateSerializer
from sooq_althahab_admin.serializers import (
    ManufacturingProductRequestedQuantityDetailSerializer,
)

#######################################################################################
############################### Stock Management Views ###############################
#######################################################################################


class JewelryStockListAPIView(ListAPIView):
    """API view to list all jewelry stocks with filtering options.
    Only shows products that have been delivered to showroom by Jewelry Inspector.
    """

    serializer_class = JewelryStockListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = JewelryStockFilter

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryStock.objects.none()

        # Only show stocks for products that have been delivered to
        queryset = (
            JewelryStock.objects.select_related(
                "jewelry_product",
                "jewelry_product__product_type",
                "jewelry_product__jewelry_design",
                "manufacturing_product",
                "manufacturing_product__manufacturing_request",
                "manufacturing_product__manufacturing_request__jewelry_production",
            )
            .prefetch_related(
                "jewelry_product__jewelry_product_attachments",
                "jewelry_product__product_materials__material_item",
                "jewelry_product__product_materials__color",
                "jewelry_product__product_materials__carat_type",
                "jewelry_product__product_materials__shape_cut",
            )
            .filter(
                organization_id=user.organization_id,
                manufacturing_product__manufacturing_request__jewelry_production__delivery_status=DeliveryStatus.DELIVERED,
            )
            .order_by("-created_at")
        )

        return queryset

    @swagger_auto_schema(
        operation_description="Retrieve a list of jewelry stocks with applied filters.",
        manual_parameters=[
            openapi.Parameter(
                "product_name",
                openapi.IN_QUERY,
                description="Filter by product name (case-insensitive search).\n\n**Example**: `ring`",
                type=openapi.TYPE_STRING,
                required=False,
            ),
            openapi.Parameter(
                "location",
                openapi.IN_QUERY,
                description="Filter by location (SHOWROOM, MARKETPLACE, BOTH).\n\n**Example**: `SHOWROOM`",
                type=openapi.TYPE_STRING,
                enum=["SHOWROOM", "MARKETPLACE", "BOTH"],
                required=False,
            ),
            openapi.Parameter(
                "showroom_status",
                openapi.IN_QUERY,
                description="Filter by showroom status (IN_STOCK, OUT_OF_STOCK).\n\n**Example**: `IN_STOCK`",
                type=openapi.TYPE_STRING,
                enum=["IN_STOCK", "OUT_OF_STOCK"],
                required=False,
            ),
            openapi.Parameter(
                "marketplace_status",
                openapi.IN_QUERY,
                description="Filter by marketplace status (IN_STOCK, OUT_OF_STOCK).\n\n**Example**: `IN_STOCK`",
                type=openapi.TYPE_STRING,
                enum=["IN_STOCK", "OUT_OF_STOCK"],
                required=False,
            ),
            openapi.Parameter(
                "is_published_to_marketplace",
                openapi.IN_QUERY,
                description="Filter by published status (true or false).\n\n**Example**: `true`",
                type=openapi.TYPE_BOOLEAN,
                required=False,
            ),
            openapi.Parameter(
                "created_at_min",
                openapi.IN_QUERY,
                description="Filter stocks created from this date (YYYY-MM-DD HH:MM:SS).\n\n**Example**: `2025-01-01 00:00:00`",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATETIME,
                required=False,
            ),
            openapi.Parameter(
                "created_at_max",
                openapi.IN_QUERY,
                description="Filter stocks created up to this date (YYYY-MM-DD HH:MM:SS).\n\n**Example**: `2025-12-31 23:59:59`",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATETIME,
                required=False,
            ),
            openapi.Parameter(
                "ordering",
                openapi.IN_QUERY,
                description="Order by field. Use - for descending. E.g., 'created_at' or '-created_at'.\n\n**Available fields**: `created_at`, `showroom_quantity`, `marketplace_quantity`",
                type=openapi.TYPE_STRING,
                required=False,
            ),
        ],
        responses={200: JewelryStockListSerializer(many=True)},
    )
    @PermissionManager(STOCK_MANAGEMENT_VIEW_PERMISSION)
    def list(self, request, *args, **kwargs):
        """Handles the GET request to list stocks."""

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=ADMIN_MESSAGES["stock_list_fetched_successfully"],
            data=response_data,
        )


class JewelryStockRetrieveAPIView(RetrieveAPIView):
    """API view to retrieve a single jewelry stock item."""

    serializer_class = JewelryStockDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryStock.objects.none()

        return (
            JewelryStock.objects.select_related(
                "jewelry_product",
                "jewelry_product__product_type",
                "jewelry_product__jewelry_design",
                "manufacturing_product",
            )
            .prefetch_related(
                "jewelry_product__jewelry_product_attachments",
                "jewelry_product__product_materials__material_item",
                "jewelry_product__product_materials__color",
                "jewelry_product__product_materials__carat_type",
                "jewelry_product__product_materials__shape_cut",
            )
            .filter(organization_id=user.organization_id)
        )

    @PermissionManager(STOCK_MANAGEMENT_VIEW_PERMISSION)
    def retrieve(self, request, *args, **kwargs):
        """Handles GET request for single stock item."""

        instance = self.get_object()
        serializer = self.get_serializer(instance)

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=ADMIN_MESSAGES["stock_details_fetched_successfully"],
            data=serializer.data,
        )


class JewelryStockUpdateAPIView(UpdateAPIView):
    """API view to update jewelry stock quantities."""

    serializer_class = JewelryStockUpdateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryStock.objects.none()

        return JewelryStock.objects.filter(organization_id=user.organization_id)

    @PermissionManager(STOCK_MANAGEMENT_VIEW_PERMISSION)
    def update(self, request, *args, **kwargs):
        """Handles PATCH/PUT request to update stock."""

        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=ADMIN_MESSAGES["stock_details_updated_successfully"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)


#######################################################################################
############################### Marketplace Views ####################################
#######################################################################################


class JewelryProductMarketplaceListAPIView(ListAPIView):
    """API view to list products published to marketplace."""

    serializer_class = JewelryProductMarketplaceSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = JewelryProductMarketplaceFilter

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryProductMarketplace.objects.none()

        queryset = JewelryProductMarketplace.objects.select_related(
            "jewelry_product",
            "jewelry_product__product_type",
            "jewelry_stock",
        ).filter(organization_id=user.organization_id)

        return queryset.order_by("-published_at")

    @swagger_auto_schema(
        operation_description="Retrieve a list of marketplace products with applied filters.",
        manual_parameters=[
            openapi.Parameter(
                "product_name",
                openapi.IN_QUERY,
                description="Filter by product name (case-insensitive search).\n\n**Example**: `ring`",
                type=openapi.TYPE_STRING,
                required=False,
            ),
            openapi.Parameter(
                "is_active",
                openapi.IN_QUERY,
                description="Filter by active status (true or false).\n\n**Example**: `true`",
                type=openapi.TYPE_BOOLEAN,
                required=False,
            ),
            openapi.Parameter(
                "published_at_min",
                openapi.IN_QUERY,
                description="Filter products published from this date (YYYY-MM-DD HH:MM:SS).\n\n**Example**: `2025-01-01 00:00:00`",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATETIME,
                required=False,
            ),
            openapi.Parameter(
                "published_at_max",
                openapi.IN_QUERY,
                description="Filter products published up to this date (YYYY-MM-DD HH:MM:SS).\n\n**Example**: `2025-12-31 23:59:59`",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATETIME,
                required=False,
            ),
            openapi.Parameter(
                "ordering",
                openapi.IN_QUERY,
                description="Order by field. Use - for descending. E.g., 'published_at' or '-published_at'.\n\n**Available fields**: `published_at`, `published_quantity`",
                type=openapi.TYPE_STRING,
                required=False,
            ),
        ],
        responses={200: JewelryProductMarketplaceSerializer(many=True)},
    )
    @PermissionManager(STOCK_MANAGEMENT_VIEW_PERMISSION)
    def list(self, request, *args, **kwargs):
        """Handles the GET request to list marketplace products."""

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=ADMIN_MESSAGES["Marketplace_product_list_fetched_successfully"],
            data=response_data,
        )


class JewelryProductMarketplaceCreateAPIView(CreateAPIView):
    """API view to publish a product to marketplace."""

    serializer_class = JewelryProductMarketplaceCreateSerializer
    permission_classes = [IsAuthenticated]

    @PermissionManager(STOCK_MANAGEMENT_VIEW_PERMISSION)
    def create(self, request, *args, **kwargs):
        """Handles POST request to publish product to marketplace."""

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            marketplace_entry = serializer.save()
            response_serializer = JewelryProductMarketplaceSerializer(marketplace_entry)
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=ADMIN_MESSAGES["marketplace_product_created_successfully"],
                data=response_serializer.data,
            )
        return handle_serializer_errors(serializer)


#######################################################################################
############################### Dashboard View #######################################
#######################################################################################


class JewelryBuyerDashboardAPIView(APIView):
    """API view for jewelry buyer dashboard statistics."""

    permission_classes = [IsAuthenticated]

    @PermissionManager(STOCK_MANAGEMENT_VIEW_PERMISSION)
    def get(self, request):
        """Get dashboard statistics for jewelry buyer."""

        user = request.user
        if not user:
            return generic_response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ACCOUNT_MESSAGES["user_not_found"],
            )

        # Calculate statistics
        stocks = JewelryStock.objects.filter(organization_id=user.organization_id)

        # Showroom statistics
        showroom_in_stock = (
            stocks.filter(showroom_status=StockStatus.IN_STOCK).aggregate(
                total=Sum("showroom_quantity")
            )["total"]
            or 0
        )
        showroom_out_of_stock = stocks.filter(
            showroom_status=StockStatus.OUT_OF_STOCK
        ).count()

        # Marketplace statistics
        marketplace_in_stock = (
            stocks.filter(marketplace_status=StockStatus.IN_STOCK).aggregate(
                total=Sum("marketplace_quantity")
            )["total"]
            or 0
        )
        marketplace_out_of_stock = stocks.filter(
            marketplace_status=StockStatus.OUT_OF_STOCK
        ).count()

        dashboard_data = {
            "showroom": {
                "in_stock": float(showroom_in_stock),
                "out_of_stock": showroom_out_of_stock,
            },
            "marketplace": {
                "in_stock": float(marketplace_in_stock),
                "out_of_stock": marketplace_out_of_stock,
            },
        }

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=ADMIN_MESSAGES["jeweler_buyer_dashboard_statistics"],
            data=dashboard_data,
        )


#######################################################################################
############################### Legacy Views (for backward compatibility) ###########
#######################################################################################


class StockListAPIView(ListAPIView):
    """Legacy view - lists manufacturing products ready for stock management."""

    serializer_class = ManufacturingProductRequestedQuantityDetailSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination

    def get_queryset(self):
        return (
            ManufacturingProductRequestedQuantity.objects.select_related(
                "manufacturing_request",
                "manufacturing_request__jewelry_production",
                "jewelry_product",
            )
            .filter(
                manufacturing_request__jewelry_production__is_payment_completed=True
            )
            .order_by("-created_at")
        )

    @PermissionManager(STOCK_MANAGEMENT_VIEW_PERMISSION)
    def list(self, request, *args, **kwargs):
        """Handles the GET request to list"""

        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=ADMIN_MESSAGES["stock_list_fetched_successfully"],
            data=response_data,
        )


class StockRetrieveAPIView(RetrieveAPIView):
    """Legacy view - retrieves a manufacturing product ready for stock management."""

    serializer_class = ManufacturingProductRequestedQuantityDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ManufacturingProductRequestedQuantity.objects.select_related(
            "manufacturing_request",
            "manufacturing_request__jewelry_production",
            "jewelry_product",
        ).filter(manufacturing_request__jewelry_production__is_payment_completed=True)

    @PermissionManager(STOCK_MANAGEMENT_VIEW_PERMISSION)
    def retrieve(self, request, *args, **kwargs):
        """Handles GET request for single stock item"""

        instance = self.get_object()
        serializer = self.get_serializer(instance)

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=ADMIN_MESSAGES["stock_details_fetched_successfully"],
            data=serializer.data,
        )


#######################################################################################
############################### Sales Management Views ###############################
#######################################################################################


class JewelrySaleListAPIView(ListAPIView):
    """API view to list jewelry sales with filtering options."""

    serializer_class = JewelrySaleListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = JewelryStockSaleFilter

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryStockSale.objects.none()

        queryset = JewelryStockSale.objects.select_related(
            "jewelry_product",
            "jewelry_product__product_type",
            "jewelry_stock",
        ).filter(organization_id=user.organization_id)

        return queryset.order_by("-sale_date", "-created_at")

    @swagger_auto_schema(
        operation_description="Retrieve a list of jewelry sales with applied filters.",
        manual_parameters=[
            openapi.Parameter(
                "product_name",
                openapi.IN_QUERY,
                description="Filter by product name (case-insensitive search).\n\n**Example**: `ring`",
                type=openapi.TYPE_STRING,
                required=False,
            ),
            openapi.Parameter(
                "sale_location",
                openapi.IN_QUERY,
                description="Filter by sale location (SHOWROOM, MARKETPLACE).\n\n**Example**: `SHOWROOM`",
                type=openapi.TYPE_STRING,
                enum=["SHOWROOM", "MARKETPLACE"],
                required=False,
            ),
            openapi.Parameter(
                "status",
                openapi.IN_QUERY,
                description="Filter by status",
                type=openapi.TYPE_STRING,
                enum=["NEW", "IN_PROGRESS", "DELIVERED"],
                required=False,
            ),
            openapi.Parameter(
                "customer_name",
                openapi.IN_QUERY,
                description="Filter by customer name (case-insensitive search).\n\n**Example**: `John`",
                type=openapi.TYPE_STRING,
                required=False,
            ),
            openapi.Parameter(
                "sale_date_min",
                openapi.IN_QUERY,
                description="Filter sales from this date (YYYY-MM-DD).\n\n**Example**: `2025-01-01`",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                required=False,
            ),
            openapi.Parameter(
                "sale_date_max",
                openapi.IN_QUERY,
                description="Filter sales up to this date (YYYY-MM-DD).\n\n**Example**: `2025-12-31`",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                required=False,
            ),
            openapi.Parameter(
                "ordering",
                openapi.IN_QUERY,
                description="Order by field. Use - for descending. E.g., 'sale_date' or '-sale_date'.\n\n**Available fields**: `sale_date`, `created_at`, `sale_price`",
                type=openapi.TYPE_STRING,
                required=False,
            ),
        ],
        responses={200: JewelrySaleListSerializer(many=True)},
    )
    @PermissionManager(STOCK_MANAGEMENT_VIEW_PERMISSION)
    def list(self, request, *args, **kwargs):
        """Handles the GET request to list sales."""

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=ADMIN_MESSAGES["sale_list_fetched_successfully"],
            data=response_data,
        )


class JewelrySaleRetrieveUpdateAPIView(RetrieveUpdateAPIView):
    """API view to retrieve or update a jewelry sale."""

    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch"]

    def get_serializer_class(self):
        # Use different serializer for GET vs PUT/PATCH
        if self.request.method in ["PATCH"]:
            return JewelrySaleUpdateSerializer
        return JewelrySaleDetailSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryStockSale.objects.none()

        return JewelryStockSale.objects.select_related(
            "manufacturing_request",
            "jewelry_product",
            "jewelry_product__product_type",
            "jewelry_stock",
        ).filter(organization_id=user.organization_id)

    @PermissionManager(STOCK_MANAGEMENT_VIEW_PERMISSION)
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=ADMIN_MESSAGES["sale_details_fetched_successfully"],
            data=serializer.data,
        )

    @PermissionManager(
        STOCK_MANAGEMENT_UPDATE_PERMISSION
    )  # or UPDATE permission if separate
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=ADMIN_MESSAGES["sale_updated_successfully"],
            data=serializer.data,
        )


class JewelrySaleCreateAPIView(CreateAPIView):
    """API view to create a jewelry sale."""

    serializer_class = JewelrySaleCreateSerializer
    permission_classes = [IsAuthenticated]

    @PermissionManager(STOCK_MANAGEMENT_VIEW_PERMISSION)
    def create(self, request, *args, **kwargs):
        """Handles POST request to create sale."""

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            sale = serializer.save()
            response_serializer = JewelrySaleDetailSerializer(sale)
            # Serializer attaches notification context on the instance
            notification_data = getattr(serializer, "notification_data", {})

            if notification_data.get("jeweler_transaction_id"):
                if notification_data.get("jeweler_business"):
                    user_in_jeweler_business = User.objects.filter(
                        user_assigned_businesses__business=notification_data.get(
                            "jeweler_business"
                        ),
                        user_preference__notifications_enabled=True,
                    )
                    send_notifications(
                        user_in_jeweler_business,
                        "Profit credited to your wallet for Jewelry Sale",
                        f"BHD {notification_data.get('jeweler_profit_amount')} has been credited to your wallet as profit from your jewelry sale.",
                        NotificationTypes.SOLD_JEWELRY_PROFIT_DISTRIBUTION,
                        ContentType.objects.get_for_model(Transaction),
                        notification_data.get("jeweler_transaction_id"),
                    )

                if notification_data.get("investor_business"):
                    user_in_investor_business = User.objects.filter(
                        user_assigned_businesses__business=notification_data.get(
                            "investor_business"
                        ),
                        user_preference__notifications_enabled=True,
                    )
                    send_notifications(
                        user_in_investor_business,
                        "Profit credited to your wallet for Jewelry Sale",
                        f"BHD {notification_data.get('investor_profit_amount')} has been credited to your wallet as profit from jewelry sale investment.",
                        NotificationTypes.SOLD_JEWELRY_PROFIT_DISTRIBUTION,
                        ContentType.objects.get_for_model(Transaction),
                        notification_data.get("investor_transaction_id"),
                    )

            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=ADMIN_MESSAGES["sale_created_successfully"],
                data=response_serializer.data,
            )
        return handle_serializer_errors(serializer)
