from django.contrib.contenttypes.models import ContentType
from django.db.models import Case
from django.db.models import Count
from django.db.models import IntegerField
from django.db.models import When
from django.http import Http404
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.generics import UpdateAPIView
from rest_framework.permissions import IsAuthenticated

from account.models import User
from jeweler.models import JewelryProduction
from jeweler.models import ManufacturingProductRequestedQuantity
from manufacturer.message import MESSAGES as MANUFACTURER_MESSAGES
from manufacturer.models import ManufacturingEstimationRequest
from manufacturer.serializers import JewelryProductionDetailSerializer
from manufacturer.views.production_hub import JewelryProductionListAPIView
from sooq_althahab.constants import JEWELRY_PRODUCTION_CHANGE_PERMISSION
from sooq_althahab.constants import JEWELRY_PRODUCTION_PRODUCT_CHANGE_PERMISSION
from sooq_althahab.constants import JEWELRY_PRODUCTION_VIEW_PERMISSION
from sooq_althahab.enums.jeweler import DeliveryStatus
from sooq_althahab.enums.jeweler import InspectionStatus
from sooq_althahab.enums.jeweler import ProductionStatus
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.manufacturer import ManufactureRequestStatus
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.helper import PermissionManager
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab.utils import send_notifications
from sooq_althahab_admin.message import MESSAGES as ADMIN_MESSAGES
from sooq_althahab_admin.serializers import DashboardSerializer
from sooq_althahab_admin.serializers import (
    JewelryProductionDeliveryStatusUpdateSerializer,
)
from sooq_althahab_admin.serializers import (
    JewelryProductionInspectionStatusUpdateSerializer,
)
from sooq_althahab_admin.serializers import (
    JewelryProductionProductCommentUpdateSerializer,
)
from sooq_althahab_admin.serializers import (
    JewelryProductionProductInspectionStatusUpdateSerializer,
)


class JewelryProductionInspectionQueryset:
    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryProduction.objects.none()

        queryset = JewelryProduction.objects.filter(
            production_status=ProductionStatus.COMPLETED,
            is_jeweler_approved=True,
            organization_id=user.organization_id,
        )

        return queryset


class JewelryProductionInspectionListAPIView(
    JewelryProductionInspectionQueryset, JewelryProductionListAPIView
):
    "API view to get list of jewelry production with production status."

    pass


class JewelryProductionInspectionRetriveAPIView(
    JewelryProductionInspectionQueryset, RetrieveAPIView
):
    "API view to get retrieve of jewelry production with production status."

    permission_classes = [IsAuthenticated]
    serializer_class = JewelryProductionDetailSerializer

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


class JewelryProductionInspectionStatusUpdateAPIView(
    JewelryProductionInspectionQueryset, UpdateAPIView
):
    serializer_class = JewelryProductionInspectionStatusUpdateSerializer
    http_method_names = ["patch"]
    permission_classes = [IsAuthenticated]

    @PermissionManager(JEWELRY_PRODUCTION_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            business = self.get_object()
            serializer = self.get_serializer(business, data=request.data, partial=True)
            if serializer.is_valid():
                jewelry_production = serializer.save()

                users_in_business = User.objects.filter(
                    user_assigned_businesses__business=jewelry_production.manufacturing_request.business,
                    user_preference__notifications_enabled=True,
                )

                if (
                    jewelry_production.admin_inspection_status
                    == InspectionStatus.IN_PROGRESS
                ):
                    title = (
                        "Sooq Al Thahab has started inspecting your jewelry production."
                    )
                    body = "Jewelry production Inspection request is currently under inspection."

                if (
                    jewelry_production.admin_inspection_status
                    == InspectionStatus.COMPLETED
                ):
                    title = "Sooq Al Thahab has completed inspecting your jewelry production."
                    body = "Jewelry production Inspection request has been completed."

                if (
                    jewelry_production.admin_inspection_status
                    == InspectionStatus.ADMIN_APPROVAL
                ):
                    title = "Sooq Al Thahab has approved your jewelry production."
                    body = "Jewelry production Inspection request has been approved successfully."

                send_notifications(
                    users_in_business,
                    title,
                    body,
                    NotificationTypes.JEWELRY_PRODUCT_INSPECTION,
                    ContentType.objects.get_for_model(
                        ManufacturingProductRequestedQuantity
                    ),
                    jewelry_production.id,
                )

                return generic_response(
                    status_code=status.HTTP_200_OK,
                    message=ADMIN_MESSAGES["jewelry_inspection_status_updated"],
                    data=serializer.data,
                )
            return handle_serializer_errors(serializer)
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MANUFACTURER_MESSAGES["jewelry_production_not_found"],
            )


class JewelryProductionProductInspectionStatusUpdateAPIView(UpdateAPIView):
    """
    API View to update the inspection status of individual jewelry products
    requested under a specific manufacturing request in a jewelry production.

    Purpose:
        - This endpoint is typically used by inspectors or authorized users
          to mark each requested product as "Approved", "Rejected", or "Pending".
        - It helps track which individual components of a production order
          have passed inspection.
    """

    serializer_class = JewelryProductionProductInspectionStatusUpdateSerializer
    queryset = ManufacturingProductRequestedQuantity.objects.all()
    http_method_names = ["patch"]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return self.queryset.none()

        queryset = self.queryset.select_related(
            "manufacturing_request", "jewelry_product"
        )
        return queryset

    @PermissionManager(JEWELRY_PRODUCTION_PRODUCT_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            if serializer.is_valid():
                manufacturing_product_requested = serializer.save()

                # Get manufacturer business
                manufacturer_business = ManufacturingEstimationRequest.objects.filter(
                    manufacturing_request=manufacturing_product_requested.manufacturing_request,
                    status=ManufactureRequestStatus.ACCEPTED,
                ).first()

                users_in_business = User.objects.filter(
                    user_assigned_businesses__business=manufacturer_business.business,
                    user_preference__notifications_enabled=True,
                )
                if (
                    manufacturing_product_requested.admin_inspection_status
                    == RequestStatus.APPROVED
                ):
                    title = f"Sooq Al Thahab has approved your jewelry product."
                    body = f"Sooq Al Thahab has approved your jewelry product: {manufacturing_product_requested.jewelry_product.product_name}."
                elif (
                    manufacturing_product_requested.admin_inspection_status
                    == RequestStatus.REJECTED
                ):
                    title = f"Sooq Al Thahab has rejected your jewelry product."
                    body = f"Sooq Al Thahab has rejected your jewelry product: {manufacturing_product_requested.jewelry_product.product_name}."

                jewelry_production = JewelryProduction.objects.filter(
                    manufacturing_request=manufacturing_product_requested.manufacturing_request
                ).first()

                send_notifications(
                    users_in_business,
                    title,
                    body,
                    NotificationTypes.JEWELRY_PRODUCT_INSPECTION,
                    ContentType.objects.get_for_model(JewelryProduction),
                    jewelry_production.id
                    if jewelry_production
                    else manufacturing_product_requested.manufacturing_request.id,
                )
                return generic_response(
                    status_code=status.HTTP_200_OK,
                    message=ADMIN_MESSAGES["jewelry_product_inspection_status_updated"],
                    data=serializer.data,
                )
            return handle_serializer_errors(serializer)
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MANUFACTURER_MESSAGES["jewelry_product_not_found"],
            )


class JewelryProductionDeliveryStatusAPIView(
    JewelryProductionInspectionQueryset, UpdateAPIView
):
    """
    API View to update the delivery status of a jewelry production.
    Sends notifications to all relevant users in the jeweler's business when the status changes.
    """

    serializer_class = JewelryProductionDeliveryStatusUpdateSerializer
    http_method_names = ["patch"]
    permission_classes = [IsAuthenticated]

    DELIVERY_STATUS_NOTIFICATIONS = {
        DeliveryStatus.OUT_FOR_DELIVERY: {
            "title": "Your jewelry products is out for delivery to the showroom",
            "message": (
                "Your jewelry products has been dispatched and is currently out for delivery to the showroom."
            ),
        },
        DeliveryStatus.DELIVERED: {
            "title": "Your jewelry products has been delivered to the showroom",
            "message": (
                "Your jewelry products has been successfully delivered to the showroom."
            ),
        },
    }

    def update(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance, data=request.data, partial=True)

            if serializer.is_valid():
                serializer.save()
                status_value = serializer.validated_data.get("delivery_status")

                # Notify users in the jeweler's business
                jeweler_business = instance.manufacturing_request.business
                users_in_jeweler_business = User.objects.filter(
                    user_assigned_businesses__business=jeweler_business,
                    user_preference__notifications_enabled=True,
                )

                notification_data = self.DELIVERY_STATUS_NOTIFICATIONS.get(status_value)
                if notification_data:
                    send_notifications(
                        users_in_jeweler_business,
                        notification_data["title"],
                        notification_data["message"],
                        NotificationTypes.JEWELRY_PRODUCTION_DELIVERY_STATUS,
                        ContentType.objects.get_for_model(JewelryProduction),
                        instance.id,
                    )

                return generic_response(
                    data=serializer.data,
                    status_code=status.HTTP_200_OK,
                    message=ADMIN_MESSAGES["jewelry_products_delivery_status_updated"],
                )
            return handle_serializer_errors(serializer)
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MANUFACTURER_MESSAGES["jewelry_production_not_found"],
            )


class JewelryProductionProductCommentUpdateAPIView(UpdateAPIView):
    serializer_class = JewelryProductionProductCommentUpdateSerializer
    http_method_names = ["patch"]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return ManufacturingProductRequestedQuantity.objects.none()

        queryset = ManufacturingProductRequestedQuantity.objects.all()
        return queryset

    @PermissionManager(JEWELRY_PRODUCTION_PRODUCT_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return generic_response(
                    status_code=status.HTTP_200_OK,
                    message=ADMIN_MESSAGES["jewelry_product_comment_added"],
                    data=serializer.data,
                )
            return handle_serializer_errors(serializer)
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MANUFACTURER_MESSAGES["jewelry_product_not_found"],
            )


class JewelryInspectorDashboardAPIView(
    JewelryProductionInspectionQueryset, ListAPIView
):
    serializer_class = DashboardSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        counts = queryset.aggregate(
            new=Count(
                Case(
                    When(admin_inspection_status=InspectionStatus.PENDING, then=1),
                    output_field=IntegerField(),
                )
            ),
            in_progress=Count(
                Case(
                    When(admin_inspection_status=InspectionStatus.IN_PROGRESS, then=1),
                    output_field=IntegerField(),
                )
            ),
            completed=Count(
                Case(
                    When(
                        admin_inspection_status__in=[
                            InspectionStatus.COMPLETED,
                            InspectionStatus.ADMIN_APPROVAL,
                        ],
                        then=1,
                    ),
                    output_field=IntegerField(),
                )
            ),
        )

        serializer = self.get_serializer(counts)

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MANUFACTURER_MESSAGES["dashboard_data_fetched"],
            data=serializer.data,
        )
