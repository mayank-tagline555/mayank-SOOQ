from collections import defaultdict
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from django.http import Http404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.generics import ListAPIView
from rest_framework.generics import ListCreateAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.generics import UpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.validators import ValidationError

from account.message import MESSAGES as ACCOUNT_MESSAGE
from account.models import BusinessAccount
from account.models import Transaction
from account.models import User
from account.utils import get_user_or_business_name
from jeweler.filters import ManufacturerBusinessFilter
from jeweler.filters import ManufacturingRequestFilter
from jeweler.message import MESSAGES as JEWELER_MESSAGES
from jeweler.models import JewelryDesign
from jeweler.models import JewelryProduction
from jeweler.models import ManufacturingProductRequestedQuantity
from jeweler.models import ManufacturingRequest
from jeweler.models import MusharakahContractRequest
from jeweler.models import MusharakahContractRequestQuantity
from jeweler.serializers import AllJewelryProductStatusUpdateSerializers
from jeweler.serializers import (
    JewelryProductionProductJewelerInspectionStatusSerializer,
)
from jeweler.serializers import ManufacturerBusinessSerializer
from jeweler.serializers import ManufacturingEstimationRequestStatusUpdateSerializer
from jeweler.serializers import ManufacturingRequestCreateSerializer
from jeweler.serializers import ManufacturingRequestEstimateSerializer
from jeweler.serializers import ManufacturingRequestPaymentTransactionSerilaizer
from jeweler.serializers import ManufacturingRequestResponseSerializer
from jeweler.serializers import MusharakahContractRequestResponseSerializer
from jeweler.serializers import ProductionPaymentSerializer
from manufacturer.message import MESSAGES as MANUFACTURER_MESSAGES
from manufacturer.models import ManufacturingEstimationRequest
from manufacturer.serializers import JewelryProductionDetailSerializer
from manufacturer.views.production_hub import JewelryProductionListAPIView
from sooq_althahab.constants import JEWELRY_PRODUCTION_PRODUCT_CHANGE_PERMISSION
from sooq_althahab.constants import JEWELRY_PRODUCTION_VIEW_PERMISSION
from sooq_althahab.constants import MANUFACTURER_BUSINESS_VIEW_PERMISSION
from sooq_althahab.constants import MANUFACTURING_REQUEST_CREATE_PERMISSION
from sooq_althahab.constants import MANUFACTURING_REQUEST_VIEW_PERMISSION
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.jeweler import ManufactureType
from sooq_althahab.enums.jeweler import MaterialSource
from sooq_althahab.enums.jeweler import MusharakahContractStatus
from sooq_althahab.enums.jeweler import ProductProductionStatus
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.manufacturer import ManufactureRequestStatus
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.helper import PermissionManager
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab.utils import handle_validation_error
from sooq_althahab.utils import send_notifications
from sooq_althahab.utils import send_notifications_to_organization_admins
from sooq_althahab_admin.message import MESSAGES as ADMIN_MESSAGES


class ManufacturerBusinessAccountListAPIView(ListAPIView):
    """API view to list manufacturer business account."""

    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    serializer_class = ManufacturerBusinessSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = ManufacturerBusinessFilter

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return BusinessAccount.objects.none()
        queryset = BusinessAccount.objects.filter(
            business_account_type=UserRoleBusinessChoices.MANUFACTURER,
            is_suspended=False,
        )
        return queryset

    @PermissionManager(MANUFACTURER_BUSINESS_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return generic_response(
            status_code=status.HTTP_200_OK,
            data=serializer.data,
            message=JEWELER_MESSAGES["manufacturer_business_account_fetched"],
        )


class ManufacturingRequestBaseQueryset:
    """Base queryset for manufacturing request."""

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return ManufacturingRequest.objects.none()

        business = get_business_from_user_token(self.request, "business")
        queryset = (
            ManufacturingRequest.objects.filter(
                organization_id=user.organization_id, business=business
            )
            .select_related("business", "design")  # FK relationships
            .prefetch_related(
                "manufacturing_product_requested_quantities__jewelry_product",
                "manufacturing_targets__material_item",
                "manufacturing_targets__carat_type",
                "manufacturing_targets__shape_cut",
                "direct_manufacturers",
            )
        )
        return queryset


class ManufacturingRequestListCreateAPIView(
    ManufacturingRequestBaseQueryset, ListCreateAPIView
):
    """API view to list and create manufacturing requests."""

    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    serializer_class = ManufacturingRequestCreateSerializer
    repsonse_serializer_class = ManufacturingRequestResponseSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = ManufacturingRequestFilter

    @PermissionManager(MANUFACTURING_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.repsonse_serializer_class(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            data=response_data,
            message=JEWELER_MESSAGES["manufacturing_request_fetched"],
        )

    @PermissionManager(MANUFACTURING_REQUEST_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        """Handles creating a manufacturing  design."""

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            manufacturing_request = serializer.save()
            if (
                manufacturing_request.manufacturer_type
                == ManufactureType.DIRECT_MANUFACTURER
            ):
                users_in_business = User.objects.filter(
                    user_assigned_businesses__business__in=manufacturing_request.direct_manufacturers.all(),
                    user_preference__notifications_enabled=True,
                ).distinct()

                send_notifications(
                    users_in_business,
                    f"Jeweler invites you to submit manufacturing estimation.",
                    f"Jeweler has shared Manufacturing Request ID ({manufacturing_request.pk}) for estimation. Please submit your estimation.",
                    NotificationTypes.MANUFACTURING_REQUEST_CREATED,
                    ContentType.objects.get_for_model(ManufacturingRequest),
                    manufacturing_request.pk,
                )
            return generic_response(
                data=serializer.data,
                message=JEWELER_MESSAGES["manufacturing_request_created"],
                status_code=status.HTTP_201_CREATED,
            )

        return handle_serializer_errors(serializer)


class BusinessManufacturingRequestRetrieveAPIView(
    ManufacturingRequestBaseQueryset, RetrieveAPIView
):
    """Base API view to retrieve a specific manufacturing request."""

    permission_classes = [IsAuthenticated]
    serializer_class = ManufacturingRequestEstimateSerializer

    @PermissionManager(MANUFACTURING_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data,
                message=JEWELER_MESSAGES["manufacturing_request_fetched"],
                status_code=status.HTTP_200_OK,
            )
        except Http404:
            return generic_response(
                error_message=JEWELER_MESSAGES[
                    "manufacturing_request_request_not_found"
                ],
                status_code=status.HTTP_404_NOT_FOUND,
            )


class ManufacturingEstimationRequestStatusUpdateAPIView(UpdateAPIView):
    """API view to status update manufacturing estimation requests."""

    permission_classes = [IsAuthenticated]
    queryset = ManufacturingEstimationRequest.objects.all()
    serializer_class = ManufacturingEstimationRequestStatusUpdateSerializer
    http_method_names = ["patch"]

    def patch(self, request, *args, **kwargs):
        """Handle status update requests."""

        try:
            instance = self.get_object()
        except:
            return generic_response(
                message=JEWELER_MESSAGES["manufacturing_estimation_request_not_found"],
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        serializer = self.get_serializer(instance, data=request.data, partial=True)

        if serializer.is_valid():
            # Store manufacturing request ID for notifications
            manufacturing_request_id = instance.manufacturing_request.pk

            # Before accepting, get all pending estimation requests that will be auto-rejected
            # This allows us to send notifications only to those who were just rejected
            pending_estimation_requests_to_be_rejected = []
            requested_status = request.data.get("status")

            if requested_status == ManufactureRequestStatus.ACCEPTED:
                # Get all other estimation requests that will be auto-rejected
                # Exclude requests that are already REJECTED to avoid sending duplicate notifications
                # Only send notifications to requests that are being rejected for the first time
                pending_estimation_requests_to_be_rejected = list(
                    ManufacturingEstimationRequest.objects.filter(
                        manufacturing_request=instance.manufacturing_request,
                    )
                    .exclude(id=instance.id)
                    .exclude(status=ManufactureRequestStatus.REJECTED)
                )

            manufacturing_estimation_request = serializer.save()

            if (
                manufacturing_estimation_request.status
                == ManufactureRequestStatus.ACCEPTED
            ):
                # Send approval notification to the accepted manufacturer
                users_in_business = User.objects.filter(
                    user_assigned_businesses__business=manufacturing_estimation_request.business,
                    user_preference__notifications_enabled=True,
                )
                message = JEWELER_MESSAGES["manufacturing_estimation_request_approved"]
                send_notifications(
                    users_in_business,
                    f"Manufacturing estimation request has been approved.",
                    f"Your estimation has been approved for Manufacturing Request ID {manufacturing_request_id}.",
                    NotificationTypes.MANUFACTURING_ESTIMATION_REQUEST_ACCEPTED,
                    ContentType.objects.get_for_model(ManufacturingEstimationRequest),
                    manufacturing_request_id,
                )

                # Send rejection notifications to manufacturers whose requests were auto-rejected
                # Get the businesses from the requests that were just rejected
                if pending_estimation_requests_to_be_rejected:
                    rejected_businesses = set(
                        req.business
                        for req in pending_estimation_requests_to_be_rejected
                    )

                    for business in rejected_businesses:
                        users_in_rejected_business = User.objects.filter(
                            user_assigned_businesses__business=business,
                            user_preference__notifications_enabled=True,
                        )
                        send_notifications(
                            users_in_rejected_business,
                            f"Manufacturing estimation request has been rejected.",
                            f"Your estimation has been rejected for Manufacturing Request ID {manufacturing_request_id}.",
                            NotificationTypes.MANUFACTURING_ESTIMATION_REQUEST_REJECTED,
                            ContentType.objects.get_for_model(
                                ManufacturingEstimationRequest
                            ),
                            manufacturing_request_id,
                        )

            else:
                # Send rejection notification for manually rejected request
                users_in_business = User.objects.filter(
                    user_assigned_businesses__business=manufacturing_estimation_request.business,
                    user_preference__notifications_enabled=True,
                )
                message = JEWELER_MESSAGES["manufacturing_estimation_request_rejected"]
                send_notifications(
                    users_in_business,
                    f"Manufacturing estimation request has been rejected.",
                    f"Your estimation has been rejected for Manufacturing Request ID {manufacturing_request_id}.",
                    NotificationTypes.MANUFACTURING_ESTIMATION_REQUEST_REJECTED,
                    ContentType.objects.get_for_model(ManufacturingEstimationRequest),
                    manufacturing_request_id,
                )

            return generic_response(
                data=self.get_serializer(manufacturing_estimation_request).data,
                message=message,
                status_code=status.HTTP_200_OK,
            )
        return handle_serializer_errors(serializer)


class ManufacturingRequestPaymentTransactionAPIView(CreateAPIView):
    """API view to handle the payment of manufacturing requests."""

    permission_classes = [IsAuthenticated]
    serializer_class = ManufacturingRequestPaymentTransactionSerilaizer

    def post(self, request, *args, **kwargs):
        """Handles manufacturing request payment transaction."""

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            try:
                transaction = serializer.save()

                users_in_jeweler_business = User.objects.filter(
                    user_assigned_businesses__business=transaction.from_business,
                    user_preference__notifications_enabled=True,
                )
                users_in_manufacturer_business = User.objects.filter(
                    user_assigned_businesses__business=transaction.to_business,
                    user_preference__notifications_enabled=True,
                )

                # Send notification to Jeweler
                send_notifications(
                    users_in_jeweler_business,
                    f"Amount debited from your wallet.",
                    f"BHD {transaction.amount:.2f} has been debited from your wallet for the manufacturing request for the jewelry design.",
                    NotificationTypes.MANUFACTURING_REQUEST_PAYMENT,
                    ContentType.objects.get_for_model(Transaction),
                    transaction.pk,
                )

                # Send notification to Manufacturer
                amount = transaction.amount - transaction.vat - transaction.platform_fee
                send_notifications(
                    users_in_manufacturer_business,
                    f"Amount credited to your wallet.",
                    f"BHD {amount:.2f} has been credited to your wallet for the estimation of manufacturing request.",
                    NotificationTypes.MANUFACTURING_REQUEST_PAYMENT,
                    ContentType.objects.get_for_model(Transaction),
                    transaction.pk,
                )

                return generic_response(
                    data=serializer.data,
                    message=JEWELER_MESSAGES["manufacturing_request_payment_created"],
                    status_code=status.HTTP_201_CREATED,
                )
            except ValidationError as ve:
                # Handle ValidationError raised in create method
                return handle_validation_error(ve)

        return handle_serializer_errors(serializer)


class JewelryDesignMusharakahContractsListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MusharakahContractRequestResponseSerializer
    pagination_class = CommonPagination

    def get_queryset(self):
        design_id = self.request.query_params.get("design_id")

        if not design_id:
            return MusharakahContractRequest.objects.none()

        try:
            jewelry_design = JewelryDesign.objects.get(id=design_id)
        except JewelryDesign.DoesNotExist:
            return MusharakahContractRequest.objects.none()

        completed_musharakah_requests = MusharakahContractRequest.objects.filter(
            musharakah_contract_designs__design=jewelry_design,
            status=RequestStatus.APPROVED,
            musharakah_contract_status=MusharakahContractStatus.ACTIVE,
        ).distinct()

        return completed_musharakah_requests

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            data=response_data,
            message=JEWELER_MESSAGES["musharakah_contract_request_fetched"],
        )


class JewelryProductJewelerInspectionStatusAPIVew(UpdateAPIView):
    """
    API View to update the jeweler inspection status of individual jewelry products
    requested under a specific manufacturing request in a jewelry production.

    Purpose:
        - This endpoint is typically used by inspectors or authorized users
          to mark each requested product as "Approved", "Rejected", or "Pending".
        - It helps track which individual components of a production order
          have passed inspection.
    """

    serializer_class = JewelryProductionProductJewelerInspectionStatusSerializer

    queryset = ManufacturingProductRequestedQuantity.objects.all()
    http_method_names = ["patch"]

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return self.queryset.none()

        business = get_business_from_user_token(self.request, "business")
        queryset = self.queryset.filter(
            manufacturing_request__business=business,
            production_status=ProductProductionStatus.COMPLETED,
        ).select_related("manufacturing_request", "jewelry_product")
        return queryset

    @PermissionManager(JEWELRY_PRODUCTION_PRODUCT_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            organization_code = request.user.organization_id.code
            name = get_user_or_business_name(request)
            instance = self.get_object()
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            if serializer.is_valid():
                manufacturing_product_requested = serializer.save()

                manufacturing_product = ManufacturingProductRequestedQuantity.objects.filter(
                    manufacturing_request=manufacturing_product_requested.manufacturing_request,
                    jeweler_inspection_status__in=[
                        RequestStatus.REJECTED,
                        RequestStatus.PENDING,
                    ],
                )

                jewelry_production = JewelryProduction.objects.filter(
                    manufacturing_request=manufacturing_product_requested.manufacturing_request
                ).first()

                if not manufacturing_product:
                    jewelry_production.is_jeweler_approved = True
                    jewelry_production.save()

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
                    manufacturing_product_requested.jeweler_inspection_status
                    == RequestStatus.APPROVED
                ):
                    title = f"Jeweler has approved your jewelry product."
                    body = f"{name} has approved your jewelry product: {manufacturing_product_requested.jewelry_product.product_name}."

                elif (
                    manufacturing_product_requested.jeweler_inspection_status
                    == RequestStatus.REJECTED
                ):
                    title = f"Jeweler has rejected your jewelry product."
                    body = f"{name} has rejected your jewelry product: {manufacturing_product_requested.jewelry_product.product_name}."

                send_notifications(
                    users_in_business,
                    title,
                    body,
                    NotificationTypes.JEWELRY_PRODUCT_INSPECTION,
                    ContentType.objects.get_for_model(JewelryProduction),
                    jewelry_production.id,
                )

                send_notifications_to_organization_admins(
                    organization_code,
                    f"Inspection task is waiting for you.",
                    f"There are still products are waiting under inspection.",
                    NotificationTypes.JEWELRY_PRODUCT_INSPECTION,
                    ContentType.objects.get_for_model(JewelryProduction),
                    jewelry_production.id,
                    UserRoleChoices.JEWELLERY_INSPECTOR,
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


class AllJewelryProductJewelerInspectionStatusAPIVew(UpdateAPIView):
    """
    API View to update the jeweler inspection status of individual jewelry products
    requested under a specific manufacturing request in a jewelry production.

    Purpose:
        - This endpoint is typically used by inspectors or authorized users
          to mark each requested product as "Approved", "Rejected", or "Pending".
        - It helps track which individual components of a production order
          have passed inspection.
    """

    serializer_class = AllJewelryProductStatusUpdateSerializers

    queryset = JewelryProduction.objects.all()
    http_method_names = ["patch"]

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return self.queryset.none()

        business = get_business_from_user_token(self.request, "business")
        queryset = self.queryset.filter(
            manufacturing_request__business=business,
            production_status=ProductProductionStatus.COMPLETED,
        ).select_related("manufacturing_request")
        return queryset

    @PermissionManager(JEWELRY_PRODUCTION_PRODUCT_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            organization_code = request.user.organization_id.code
            name = get_user_or_business_name(request)
            instance = self.get_object()
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            if serializer.is_valid():
                jewelry_production = serializer.save()

                # Get manufacturer business
                manufacturer_business = ManufacturingEstimationRequest.objects.filter(
                    manufacturing_request=jewelry_production.manufacturing_request,
                    status=ManufactureRequestStatus.ACCEPTED,
                ).first()

                product_count = ManufacturingProductRequestedQuantity.objects.filter(
                    manufacturing_request=jewelry_production.manufacturing_request
                ).count()

                users_in_business = User.objects.filter(
                    user_assigned_businesses__business=manufacturer_business.business,
                    user_preference__notifications_enabled=True,
                )
                if jewelry_production.is_jeweler_approved:
                    title = f"Jeweler has approved your jewelry products."
                    body = f"{name} has approved {product_count} products."
                else:
                    title = f"Jeweler has rejected your jewelry products."
                    body = f"{name} has rejected {product_count} products."

                send_notifications(
                    users_in_business,
                    title,
                    body,
                    NotificationTypes.JEWELRY_PRODUCT_INSPECTION,
                    ContentType.objects.get_for_model(JewelryProduction),
                    instance.id,
                )

                send_notifications_to_organization_admins(
                    organization_code,
                    f"Inspection task is waiting for you.",
                    f"There are still products pending inspection. Please review them at your earliest convenience.",
                    NotificationTypes.JEWELRY_PRODUCT_INSPECTION,
                    ContentType.objects.get_for_model(JewelryProduction),
                    instance.id,
                    UserRoleChoices.JEWELLERY_INSPECTOR,
                )

                return generic_response(
                    status_code=status.HTTP_200_OK,
                    message=ADMIN_MESSAGES["jewelry_product_inspection_status_updated"],
                    data=JewelryProductionDetailSerializer(jewelry_production).data,
                )
            return handle_serializer_errors(serializer)
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MANUFACTURER_MESSAGES["jewelry_product_not_found"],
            )


class JewelryProductionQueryset:
    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryProduction.objects.none()

        business = get_business_from_user_token(self.request, "business")

        return (
            JewelryProduction.objects.filter(
                organization_id=user.organization_id,
                manufacturing_request__business=business,
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


class JewelryProductionAPIView(JewelryProductionQueryset, JewelryProductionListAPIView):
    """API view to list all jewelry productions."""

    pass


class JewelryProductionRetrieveAPIView(JewelryProductionQueryset, RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = JewelryProductionDetailSerializer
    http_method_names = ["get"]

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


class ProductionPaymentCreateAPIView(CreateAPIView):
    """

    API View to create a Production Payment record.
    Supports payments using either cash or contributed assets.
    """

    serializer_class = ProductionPaymentSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        try:
            business = get_business_from_user_token(request, "business")

            serializer = self.get_serializer(
                data=request.data, context={"request": request}
            )
            if serializer.is_valid():
                production_payment = serializer.save()

                # send notifications
                users_in_manufacturer_business = User.objects.filter(
                    user_assigned_businesses__business=production_payment.jewelry_production.manufacturer,
                    user_preference__notifications_enabled=True,
                )
                users_in_jeweler_business = User.objects.filter(
                    user_assigned_businesses__business=business,
                    user_preference__notifications_enabled=True,
                )

                payment_type = production_payment.payment_type
                design_id = (
                    production_payment.jewelry_production.manufacturing_request.design.id
                )
                transaction_id = (
                    Transaction.objects.filter(
                        jewelry_production=production_payment.jewelry_production
                    )
                    .first()
                    .id
                )

                # send notifications to jeweler business
                send_notifications(
                    users_in_jeweler_business,
                    f"Amount debited from your wallet.",
                    f"BHD {production_payment.total_amount:.2f} has been debited from your wallet for the manufacturing request related to jewelry design ID ({design_id}).",
                    NotificationTypes.JEWELRY_PRODUCTION_PAYMENT,
                    ContentType.objects.get_for_model(Transaction),
                    transaction_id,
                )

                # send notifications to manufacturer business
                if payment_type in [
                    MaterialSource.ASSET,
                    MaterialSource.MUSHARAKAH,
                    MaterialSource.MUSHARAKAH_AND_ASSET,
                ]:
                    message = (
                        f"Your payment for jewelry design ID ({design_id}) has been completed via {payment_type.replace('_', ' ').title()}."
                        f"{f'BHD {production_payment.correction_amount} has been credited to your wallet' if production_payment.correction_amount and production_payment.correction_amount > 0 else ''}."
                    )
                else:  # CASH
                    total = (
                        Decimal(production_payment.metal_amount)
                        + Decimal(production_payment.stone_amount)
                        + Decimal(production_payment.correction_amount)
                    )
                    message = f"BHD {total} has been credited to your wallet for the manufacturing request related to jewelry design ID ({design_id})."

                send_notifications(
                    users_in_manufacturer_business,
                    f"Amount credited to your wallet.",
                    message,
                    NotificationTypes.JEWELRY_PRODUCTION_PAYMENT,
                    ContentType.objects.get_for_model(Transaction),
                    transaction_id,
                )

                return generic_response(
                    status_code=status.HTTP_200_OK,
                    message=JEWELER_MESSAGES["production_payment_success"],
                    data=serializer.data,
                )
            return handle_serializer_errors(serializer)
        except ValidationError as ve:
            return generic_response(
                data=None,
                error_message=ve.detail[0],
                status_code=status.HTTP_400_BAD_REQUEST,
            )
