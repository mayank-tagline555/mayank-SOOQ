from django.contrib.contenttypes.models import ContentType
from django.http import Http404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.generics import UpdateAPIView
from rest_framework.permissions import IsAuthenticated

from account.models import User
from jeweler.models import JewelryProduction
from jeweler.models import JewelryProductStonePrice
from jeweler.models import ManufacturingProductRequestedQuantity
from manufacturer.filters import JewelryProductionFilter
from manufacturer.message import MESSAGES as MANUFACTURER_MESSAGES
from manufacturer.serializers import JewelryProductionDetailSerializer
from manufacturer.serializers import JewelryProductionUpdateSerializer
from manufacturer.serializers import JewelryProductStatusUpdateSerializer
from manufacturer.serializers import JewelryProductStonePriceSerializer
from sooq_althahab.constants import JEWELRY_PRODUCTION_CHANGE_PERMISSION
from sooq_althahab.constants import JEWELRY_PRODUCTION_PRODUCT_CHANGE_PERMISSION
from sooq_althahab.constants import JEWELRY_PRODUCTION_VIEW_PERMISSION
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.helper import PermissionManager
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab.utils import send_notifications


class JewelryProductionQuerysetView:
    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryProduction.objects.none()

        business = get_business_from_user_token(self.request, "business")

        return (
            JewelryProduction.objects.filter(
                organization_id=user.organization_id,
                manufacturer=business,
            )
            .select_related(
                "manufacturing_request",
                "manufacturing_request__business",
                "manufacturing_request__created_by",
                "design",
            )
            .prefetch_related(
                "design__jewelry_products",
                "manufacturing_request__manufacturing_targets",
                "manufacturing_request__manufacturing_product_requested_quantities",
                "manufacturing_request__manufacturing_product_requested_quantities__jewelry_product",
                "manufacturing_request__manufacturing_product_requested_quantities__jewelry_product__jewelry_product_attachments",
                "manufacturing_request__manufacturing_product_requested_quantities__jewelry_product__product_materials",
                "manufacturing_request__manufacturing_product_requested_quantities__jewelry_product__product_materials__material_item",
                "manufacturing_request__manufacturing_product_requested_quantities__jewelry_product__product_materials__carat_type",
                "manufacturing_request__manufacturing_product_requested_quantities__jewelry_product__product_materials__color",
                "manufacturing_request__manufacturing_product_requested_quantities__jewelry_product__product_materials__shape_cut",
            )
        )


class JewelryProductionListAPIView(JewelryProductionQuerysetView, ListAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    serializer_class = JewelryProductionDetailSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = JewelryProductionFilter

    @PermissionManager(JEWELRY_PRODUCTION_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            data=response_data,
            message=MANUFACTURER_MESSAGES["jewelry_production_fetched"],
        )


class JewelryProductionUpdateRetrieveAPIView(
    JewelryProductionQuerysetView, RetrieveUpdateAPIView
):
    permission_classes = [IsAuthenticated]
    serializer_class = JewelryProductionDetailSerializer
    http_method_names = ["patch", "get"]

    def get_serializer_class(self):
        if self.request.method in ["PATCH"]:
            return JewelryProductionUpdateSerializer
        return JewelryProductionDetailSerializer

    @PermissionManager(JEWELRY_PRODUCTION_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            jewelry_production = self.get_object()
            serializer = self.get_serializer(jewelry_production)
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MANUFACTURER_MESSAGES["jewelry_production_fetched"],
                data=serializer.data,
            )
        except Http404:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MANUFACTURER_MESSAGES["jewelry_production_not_found"],
            )

    @PermissionManager(JEWELRY_PRODUCTION_CHANGE_PERMISSION)
    def patch(self, request, pk=None):
        try:
            jewelry_production = self.get_object()
            serializer = self.get_serializer(
                jewelry_production, data=request.data, partial=True
            )
            if serializer.is_valid():
                jewelry_production_serializer = serializer.save()

                updated_fields = serializer.validated_data.keys()

                # Determine the message based on which fields were updated
                if "production_status" in updated_fields:
                    # If production status was updated.
                    message = MANUFACTURER_MESSAGES["jewelry_production_status_updated"]
                    title = "Jewelry production status has been updated"
                    body = f"The status of your jewelry production request has been updated to '{jewelry_production_serializer.production_status}'."

                else:
                    # If delivery date was updated.
                    message = MANUFACTURER_MESSAGES[
                        "jewelry_production_delivery_date_updated"
                    ]
                    title = "Jewelry production delivery date has been Updated"
                    body = "The delivery date for your jewelry production request has been updated. Please review the latest schedule."

                users_in_business = User.objects.filter(
                    user_assigned_businesses__business=jewelry_production_serializer.manufacturing_request.business,
                    user_preference__notifications_enabled=True,
                )

                send_notifications(
                    users_in_business,
                    title,
                    body,
                    NotificationTypes.JEWELRY_PRODUCTION_STATUS_UPDATED,
                    ContentType.objects.get_for_model(JewelryProduction),
                    jewelry_production_serializer.pk,
                )
                return generic_response(
                    status_code=status.HTTP_200_OK,
                    message=message,
                    data=serializer.data,
                )
            return handle_serializer_errors(serializer)
        except Http404:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MANUFACTURER_MESSAGES["jewelry_production_not_found"],
            )


class JewelryProductStatusUpdateAPIView(UpdateAPIView):
    serializer_class = JewelryProductStatusUpdateSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["patch"]

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return ManufacturingProductRequestedQuantity.objects.none()

        business = get_business_from_user_token(self.request, "business")
        if not business:
            return ManufacturingProductRequestedQuantity.objects.none()

        return ManufacturingProductRequestedQuantity.objects.select_related(
            "manufacturing_request"
        ).filter(manufacturing_request__organization_id=user.organization_id)

    @PermissionManager(JEWELRY_PRODUCTION_PRODUCT_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            business = self.get_object()
            serializer = self.get_serializer(business, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return generic_response(
                    status_code=status.HTTP_200_OK,
                    message=MANUFACTURER_MESSAGES["jewelry_product_status_updated"],
                    data=serializer.data,
                )
            return handle_serializer_errors(serializer)
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MANUFACTURER_MESSAGES["jewelry_product_not_found"],
            )


class JewelryProductStonePriceCreateAPIView(CreateAPIView):
    serializer_class = JewelryProductStonePriceSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(created_by=self.request.user)
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MANUFACTURER_MESSAGES["stone_price_added"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)
