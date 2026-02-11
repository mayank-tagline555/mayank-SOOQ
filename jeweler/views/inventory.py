from decimal import Decimal

from django.db.models import DecimalField
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import Sum
from django.db.models import Value
from django.db.models import When
from django.db.models.functions import Coalesce
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from account.message import MESSAGES as ACCOUNT_MESSAGES
from jeweler.message import MESSAGES as JEWELER_MESSAGES
from jeweler.models import JewelryProductMarketplace
from jeweler.models import JewelryStock
from jeweler.models import JewelryStockSale
from jeweler.models import ManufacturingProductRequestedQuantity
from manufacturer.models import ProductManufacturingEstimatedPrice
from sooq_althahab.constants import JEWELRY_PRODUCT_VIEW_PERMISSION
from sooq_althahab.constants import STOCK_MANAGEMENT_VIEW_PERMISSION
from sooq_althahab.enums.jeweler import DeliveryStatus
from sooq_althahab.helper import PermissionManager
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response
from sooq_althahab_admin.filters import JewelryProductMarketplaceFilter
from sooq_althahab_admin.filters import JewelryStockFilter
from sooq_althahab_admin.filters import JewelryStockSaleFilter
from sooq_althahab_admin.serializers import JewelryProductMarketplaceSerializer
from sooq_althahab_admin.serializers import JewelrySaleDetailSerializer
from sooq_althahab_admin.serializers import JewelrySaleListSerializer
from sooq_althahab_admin.serializers import JewelryStockDetailSerializer
from sooq_althahab_admin.serializers import JewelryStockListSerializer


class JewelryInventoryDashboardAPIView(APIView):
    """API view for jeweler inventory dashboard statistics."""

    permission_classes = [IsAuthenticated]

    @PermissionManager(JEWELRY_PRODUCT_VIEW_PERMISSION)
    def get(self, request):
        """Get dashboard statistics for jeweler inventory."""

        user = request.user
        if not user:
            return generic_response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ACCOUNT_MESSAGES["user_not_found"],
            )

        business = get_business_from_user_token(request, "business")
        if not business:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ACCOUNT_MESSAGES["business_account_not_found"],
            )

        # Get all stocks for this jeweler's products
        stocks = JewelryStock.objects.filter(
            jewelry_product__jewelry_design__business=business,
            organization_id=user.organization_id,
            manufacturing_product__manufacturing_request__jewelry_production__delivery_status=DeliveryStatus.DELIVERED,
        )

        # Calculate based on jewelry_product.quantity for each stock
        # Then aggregate based on is_published_to_marketplace status
        stock_quantities = stocks.aggregate(
            # Unpublished: Sum of jewelry_product.quantity for stocks where is_published_to_marketplace=False
            unpublished_total=Coalesce(
                Sum(
                    "jewelry_product__quantity",
                    filter=Q(is_published_to_marketplace=False),
                ),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            ),
            # Published: Sum of jewelry_product.quantity for stocks where is_published_to_marketplace=True
            published_total=Coalesce(
                Sum(
                    "jewelry_product__quantity",
                    filter=Q(is_published_to_marketplace=True),
                ),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            ),
        )
        # Unpublished: Total jewelry_product.quantity of stocks not published to marketplace
        unpublished_count = stock_quantities["unpublished_total"]
        # Published: Total jewelry_product.quantity of stocks published to marketplace
        published_count = stock_quantities["published_total"]

        # Get marketplace entries for recently published
        marketplace_entries = JewelryProductMarketplace.objects.filter(
            jewelry_product__jewelry_design__business=business,
            organization_id=user.organization_id,
        )
        # Sold: Total quantity sold (sum of quantities from sales)
        sold_quantity = JewelryStockSale.objects.filter(
            manufacturing_request__business=business,
        ).aggregate(
            total_sold=Coalesce(
                Sum("quantity"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            )
        )
        sold_count = sold_quantity["total_sold"]

        # Highest profit designs (placeholder - update with actual profit calculation)
        highest_profit_designs = self.get_top_profit_designs(business)

        # Recently published designs
        recently_published = (
            marketplace_entries.filter(is_active=True)
            .select_related("jewelry_product", "jewelry_product__product_type")
            .order_by("-published_at")[:4]
        )
        recently_published_data = JewelryProductMarketplaceSerializer(
            recently_published, many=True
        ).data

        dashboard_data = {
            "general_insights": {
                "unpublished": unpublished_count,
                "published": published_count,
                "sold": sold_count,
            },
            "highest_profit_designs": highest_profit_designs,
            "recently_published_designs": recently_published_data,
        }

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=JEWELER_MESSAGES["inventory_dashboard_statistics"],
            data=dashboard_data,
        )

    def get_top_profit_designs(self, business):
        """Return top 2 profitable jewelry designs for dashboard."""

        # Estimated price for the exact product sold
        estimated_price_subquery = ProductManufacturingEstimatedPrice.objects.filter(
            requested_product__manufacturing_request=OuterRef("manufacturing_request"),
            requested_product__jewelry_product=OuterRef("jewelry_product"),
        ).values("estimated_price")[:1]

        # Requested quantity for that product
        requested_qty_subquery = ManufacturingProductRequestedQuantity.objects.filter(
            manufacturing_request=OuterRef("manufacturing_request"),
            jewelry_product=OuterRef("jewelry_product"),
        ).values("quantity")[:1]

        # Stone prices for the entire manufacturing request (still valid)
        stone_price_sum = Sum(
            "manufacturing_request__jewelry_production__stone_prices__stone_price",
            distinct=True,
        )

        sales = (
            JewelryStockSale.objects.filter(manufacturing_request__business=business)
            .annotate(
                estimated_price_per_piece=Subquery(
                    estimated_price_subquery,
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
                requested_qty=Subquery(
                    requested_qty_subquery,
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
                stone_cost_per_piece=Coalesce(
                    stone_price_sum,
                    Value(0),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
            )
            .annotate(
                manufact_cost_per_piece=ExpressionWrapper(
                    F("estimated_price_per_piece"),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
                manufact_cost_for_sold=ExpressionWrapper(
                    F("estimated_price_per_piece") * F("quantity"),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
                stone_cost_for_sold=ExpressionWrapper(
                    F("stone_cost_per_piece") * F("quantity"),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
                profit=ExpressionWrapper(
                    F("sale_price")
                    - F("manufact_cost_for_sold")
                    - F("stone_cost_for_sold"),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
            )
            .order_by("-profit")[:2]
        )

        return [
            {
                "sale_id": s.id,
                "jewelry_product": s.jewelry_product.product_name,
                "quantity_sold": s.quantity,
                "profit": s.profit,
                "sale_price": s.sale_price,
            }
            for s in sales
        ]


class JewelryInventoryStockListAPIView(ListAPIView):
    """API view to list jewelry inventory stocks for jeweler mobile app.
    Shows products in showroom and marketplace.
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

        business = get_business_from_user_token(self.request, "business")
        if not business:
            return JewelryStock.objects.none()

        # Get stocks for this jeweler's products that have been delivered
        queryset = (
            JewelryStock.objects.select_related(
                "jewelry_product",
                "jewelry_product__product_type",
                "jewelry_product__jewelry_design",
                "manufacturing_product",
            )
            .filter(
                jewelry_product__jewelry_design__business=business,
                organization_id=user.organization_id,
                manufacturing_product__manufacturing_request__jewelry_production__delivery_status=DeliveryStatus.DELIVERED,
            )
            .order_by("-created_at")
        )

        return queryset

    @swagger_auto_schema(
        operation_description="Retrieve a list of jewelry inventory stocks with applied filters.",
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
                "ordering",
                openapi.IN_QUERY,
                description="Order by field. Use - for descending. E.g., 'created_at' or '-created_at'.\n\n**Available fields**: `created_at`, `showroom_quantity`, `marketplace_quantity`",
                type=openapi.TYPE_STRING,
                required=False,
            ),
        ],
        responses={200: JewelryStockListSerializer(many=True)},
    )
    @PermissionManager(JEWELRY_PRODUCT_VIEW_PERMISSION)
    def list(self, request, *args, **kwargs):
        """Handles the GET request to list inventory stocks."""

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=JEWELER_MESSAGES["inventory_dashboard_list_fetched_successfully"],
            data=response_data,
        )


class JewelryInventoryStockRetrieveAPIView(RetrieveAPIView):
    """API view to retrieve a single jewelry inventory stock item."""

    serializer_class = JewelryStockDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryStock.objects.none()

        business = get_business_from_user_token(self.request, "business")
        if not business:
            return JewelryStock.objects.none()

        return JewelryStock.objects.select_related(
            "jewelry_product",
            "jewelry_product__product_type",
            "jewelry_product__jewelry_design",
            "manufacturing_product",
        ).filter(
            jewelry_product__jewelry_design__business=business,
            organization_id=user.organization_id,
        )

    @PermissionManager(JEWELRY_PRODUCT_VIEW_PERMISSION)
    def retrieve(self, request, *args, **kwargs):
        """Handles GET request for single inventory stock item."""

        instance = self.get_object()
        serializer = self.get_serializer(instance)

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=JEWELER_MESSAGES["inventory_stock_details_fetched_successfully"],
            data=serializer.data,
        )


class JewelryInventoryMarketplaceListAPIView(ListAPIView):
    """API view to list published marketplace products for jeweler."""

    serializer_class = JewelryProductMarketplaceSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = JewelryProductMarketplaceFilter

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryProductMarketplace.objects.none()

        business = get_business_from_user_token(self.request, "business")
        if not business:
            return JewelryProductMarketplace.objects.none()

        queryset = JewelryProductMarketplace.objects.select_related(
            "jewelry_product",
            "jewelry_product__product_type",
            "jewelry_product__jewelry_design",
            "jewelry_stock",
        ).filter(
            jewelry_product__jewelry_design__business=business,
            organization_id=user.organization_id,
        )

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
    @PermissionManager(JEWELRY_PRODUCT_VIEW_PERMISSION)
    def list(self, request, *args, **kwargs):
        """Handles the GET request to list marketplace products."""

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=JEWELER_MESSAGES["marketplace_product_list_fetched_successfully"],
            data=response_data,
        )


class JewelryProductSaleListAPIView(ListAPIView):
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
        business = get_business_from_user_token(self.request, "business")
        queryset = JewelryStockSale.objects.select_related(
            "manufacturing_request",
            "jewelry_product",
            "jewelry_product__product_type",
            "jewelry_stock",
        ).filter(manufacturing_request__business=business)

        return queryset.order_by("-sale_date", "-created_at")

    @PermissionManager(STOCK_MANAGEMENT_VIEW_PERMISSION)
    def list(self, request, *args, **kwargs):
        """Handles the GET request to list sales."""

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=JEWELER_MESSAGES["jewelry_sales_list_fetched_successfully"],
            data=response_data,
        )


class JewelryProductSaleRetrieveAPIView(RetrieveAPIView):
    """API view to retrieve a single jewelry sale record."""

    serializer_class = JewelrySaleDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryStockSale.objects.none()

        business = get_business_from_user_token(self.request, "business")
        if not business:
            return JewelryStockSale.objects.none()

        return (
            JewelryStockSale.objects.select_related(
                "manufacturing_request",
                "jewelry_product",
                "jewelry_product__product_type",
                "jewelry_product__jewelry_design",
                "jewelry_stock",
            )
            .prefetch_related("profit_distributions")
            .filter(manufacturing_request__business=business)
        )

    @PermissionManager(STOCK_MANAGEMENT_VIEW_PERMISSION)
    def retrieve(self, request, *args, **kwargs):
        """Handles GET request for single sale record."""

        instance = self.get_object()
        serializer = self.get_serializer(instance)

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=JEWELER_MESSAGES["jewelry_sales_details_fetched_successfully"],
            data=serializer.data,
        )


class InventoryInsightsAPIView(APIView):
    """API view to retrieve inventory history for jeweler."""

    permission_classes = [IsAuthenticated]

    @PermissionManager(STOCK_MANAGEMENT_VIEW_PERMISSION)
    def get(self, request):
        """Get inventory history for jeweler."""

        business = get_business_from_user_token(request, "business")

        # Estimated price for the exact product sold
        estimated_price_subquery = ProductManufacturingEstimatedPrice.objects.filter(
            requested_product__manufacturing_request=OuterRef("manufacturing_request"),
            requested_product__jewelry_product=OuterRef("jewelry_product"),
        ).values("estimated_price")[:1]

        # Requested quantity for that product
        requested_qty_subquery = ManufacturingProductRequestedQuantity.objects.filter(
            manufacturing_request=OuterRef("manufacturing_request"),
            jewelry_product=OuterRef("jewelry_product"),
        ).values("quantity")[:1]

        # Stone prices for the entire manufacturing request (still valid)
        stone_price_sum = Sum(
            "manufacturing_request__jewelry_production__stone_prices__stone_price",
            distinct=True,
        )

        sales = (
            JewelryStockSale.objects.filter(manufacturing_request__business=business)
            .annotate(
                estimated_price_per_piece=Subquery(
                    estimated_price_subquery,
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
                requested_qty=Subquery(
                    requested_qty_subquery,
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
                stone_cost_per_piece=Coalesce(
                    stone_price_sum,
                    Value(0),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
            )
            .annotate(
                manufact_cost_per_piece=ExpressionWrapper(
                    F("estimated_price_per_piece"),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
                manufact_cost_for_sold=ExpressionWrapper(
                    F("estimated_price_per_piece") * F("quantity"),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
                stone_cost_for_sold=ExpressionWrapper(
                    F("stone_cost_per_piece") * F("quantity"),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
                profit=ExpressionWrapper(
                    F("sale_price")
                    - F("manufact_cost_for_sold")
                    - F("stone_cost_for_sold"),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
            )
            .aggregate(
                total_profit=Coalesce(
                    Sum("profit"),
                    Value(0),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
                total_quantity=Coalesce(
                    Sum("quantity"),
                    Value(0),
                    output_field=DecimalField(max_digits=20, decimal_places=4),
                ),
            )
        )

        history_data = {
            "total_profit": sales["total_profit"],
            "total_sold_quantity": sales["total_quantity"],
        }

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=JEWELER_MESSAGES["inventory_general_insights_fetched_successfully"],
            data=history_data,
        )
