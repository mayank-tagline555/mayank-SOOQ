from datetime import date
from datetime import datetime

from django.contrib.contenttypes.models import ContentType
from django.db.models import DecimalField
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import Sum
from django.http import Http404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.status import HTTP_201_CREATED
from rest_framework.views import APIView

from account.message import MESSAGES as ACCOUNT_MESSAGES
from account.models import User
from account.utils import get_user_or_business_name
from jeweler.message import MESSAGES as JEWELER_MESSAGES
from jeweler.models import JewelryProduction
from jeweler.models import ManufacturingRequest
from jeweler.serializers import ManufacturingRequestResponseSerializer
from manufacturer.filters import ManufacturingRequestFilter
from manufacturer.message import MESSAGES
from manufacturer.models import ManufacturingEstimationRequest
from manufacturer.serializers import CorrectionValueSerializer
from manufacturer.serializers import ManufacturingEstimationRequestSerializer
from manufacturer.serializers import ManufacturingRequestDetailSerializer
from seller.utils import get_custom_time_range
from sooq_althahab.constants import MANUFACTURING_REQUEST_ESTIMATION_CREATE_PERMISSION
from sooq_althahab.constants import MANUFACTURING_REQUEST_VIEW_PERMISSION
from sooq_althahab.enums.account import UserType
from sooq_althahab.enums.jeweler import ManufacturingStatus
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.manufacturer import ManufactureRequestStatus
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.helper import PermissionManager
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab.utils import send_notifications


class ManufacturingRequestQueryset:
    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return ManufacturingRequest.objects.none()

        business = get_business_from_user_token(self.request, "business")
        queryset = (
            ManufacturingRequest.objects.filter(organization_id=user.organization_id)
            .exclude(estimation_requests__business=business)
            .select_related("business", "design")
            .prefetch_related(
                "manufacturing_product_requested_quantities__jewelry_product",
                "manufacturing_targets__material_item",
                "manufacturing_targets__carat_type",
                "manufacturing_targets__shape_cut",
                "direct_manufacturers",
            )
        )
        return queryset


class ManufacturingRequestListAPIView(ManufacturingRequestQueryset, ListAPIView):
    """API view to list all jewelry manufacturing requests."""

    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    serializer_class = ManufacturingRequestResponseSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = ManufacturingRequestFilter

    @PermissionManager(MANUFACTURING_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            data=response_data,
            message=JEWELER_MESSAGES["manufacturing_request_fetched"],
        )


class ManufacturingRequestRetrieveAPIView(RetrieveAPIView):
    """
    API view to retrieve detailed information about a specific manufacturing request.
    Inherits from:
        - ManufacturingRequestQueryset: Provides queryset as per all data.
        - BaseManufacturingRequestRetrieveAPIView: Handles retrieval logic and serialization.
    This view is typically used to fetch all relevant details, including related products,
    materials, pricing, and status, for a single manufacturing request instance.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ManufacturingRequestDetailSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return ManufacturingRequest.objects.none()

        queryset = (
            ManufacturingRequest.objects.filter(organization_id=user.organization_id)
            .select_related("business", "design")
            .prefetch_related(
                "manufacturing_product_requested_quantities__jewelry_product",
                "manufacturing_targets__material_item",
                "manufacturing_targets__carat_type",
                "manufacturing_targets__shape_cut",
                "direct_manufacturers",
            )
        )
        return queryset

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
                error_message=JEWELER_MESSAGES["manufacturing_request_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )


class ManufacturingEstimationRequestCreateAPIView(CreateAPIView):
    """API view to create a manufacturing estimation request."""

    permission_classes = [IsAuthenticated]
    serializer_class = ManufacturingEstimationRequestSerializer

    @PermissionManager(MANUFACTURING_REQUEST_ESTIMATION_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        name = get_user_or_business_name(request)
        user = request.user
        user_type = (
            "(Business)" if user.user_type == UserType.BUSINESS else "(Individual)"
        )

        if serializer.is_valid():
            instance = serializer.save()

            users_in_business = User.objects.filter(
                user_assigned_businesses__business=instance.manufacturing_request.business,
                user_preference__notifications_enabled=True,
            ).distinct()

            # Send notification
            send_notifications(
                users_in_business,
                f"Estimation received for your manufacturing request.",
                f"{name} ({user_type}) has submitted an estimation for your manufacturing request.",
                NotificationTypes.MANUFACTURING_ESTIMATION_REQUEST,
                ContentType.objects.get_for_model(ManufacturingEstimationRequest),
                instance.manufacturing_request.pk,
            )
            return generic_response(
                status_code=HTTP_201_CREATED,
                message=MESSAGES["manufacturing_request_estimation_created"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)


class EstimationManufacturingListAPIView(ListAPIView):
    """API view to list all manufacturing requests in which login has submitted estimation."""

    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    serializer_class = ManufacturingRequestDetailSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = ManufacturingRequestFilter

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return ManufacturingRequest.objects.none()
        business = get_business_from_user_token(self.request, "business")
        queryset = (
            ManufacturingRequest.objects.filter(
                organization_id=user.organization_id,
                estimation_requests__business=business,
            )
            .select_related("business", "design")
            .prefetch_related(
                "manufacturing_product_requested_quantities__jewelry_product",
                "manufacturing_targets__material_item",
                "manufacturing_targets__carat_type",
                "manufacturing_targets__shape_cut",
                "direct_manufacturers",
            )
        ).distinct()
        return queryset

    @PermissionManager(MANUFACTURING_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            data=response_data,
            message=JEWELER_MESSAGES["manufacturing_request_fetched"],
        )


class CorrectionValueCreateAPIView(CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CorrectionValueSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            instance = serializer.save()

            name = get_user_or_business_name(request)
            user = request.user
            user_type = (
                "(Business)" if user.user_type == UserType.BUSINESS else "(Individual)"
            )

            users_in_business = User.objects.filter(
                user_assigned_businesses__business=instance.manufacturing_request.business,
                user_preference__notifications_enabled=True,
            ).distinct()

            # Send notification
            send_notifications(
                users_in_business,
                f"Correction amount received for your Jewelry Production.",
                f"{name} {user_type} has submitted a correction amount for your Jewelry Production.",
                NotificationTypes.JEWELRY_PRODUCTION_CORRECTION_AMOUNT_ADDED,
                ContentType.objects.get_for_model(JewelryProduction),
                instance.manufacturing_request.jewelry_production.pk,
            )

            return generic_response(
                data=serializer.data,
                message=JEWELER_MESSAGES["correction_amount_added"],
                status_code=status.HTTP_201_CREATED,
            )

        return handle_serializer_errors(serializer)


class ManufacturerDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        business = get_business_from_user_token(request, "business")
        if not business:
            return generic_response(
                error_message=ACCOUNT_MESSAGES["business_account_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

        estimation_qs = ManufacturingEstimationRequest.objects.filter(
            status=ManufactureRequestStatus.ACCEPTED, business=business
        ).annotate(
            total_amount=ExpressionWrapper(
                F("estimated_prices__estimated_price")
                * F("estimated_prices__requested_product__quantity"),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            )
        )

        total_sale = (
            estimation_qs.filter(
                manufacturing_request__status=ManufacturingStatus.COMPLETED
            ).aggregate(total=Sum("total_amount"))["total"]
            or 0
        )

        outstanding_fees = self.get_outstanding_fees(estimation_qs)

        data = {"total_sale": total_sale, "outstanding_fees": outstanding_fees}
        return generic_response(
            data=data,
            message=MESSAGES["dashboard_data_fetched"],
            status_code=status.HTTP_201_CREATED,
        )

    def get_outstanding_fees(self, estimation_queryset):
        """
        Returns a dict of outstanding fees grouped by custom time ranges.
        """
        time_ranges = get_custom_time_range()

        # Filter for outstanding estimations
        filtered_queryset = estimation_queryset.filter(
            manufacturing_request__status=ManufacturingStatus.PAYMENT_PENDING
        )

        outstanding_fees = {}

        for label, date_range in time_ranges.items():
            if isinstance(date_range, tuple) and len(date_range) == 2:
                start, end = date_range
                total = (
                    filtered_queryset.filter(created_at__range=(start, end)).aggregate(
                        total=Sum("total_amount")
                    )["total"]
                    or 0
                )
            elif isinstance(date_range, (datetime, date)):
                total = (
                    filtered_queryset.filter(created_at__gte=date_range).aggregate(
                        total=Sum("total_amount")
                    )["total"]
                    or 0
                )
            else:
                # If no filtering range, return total of entire filtered set
                total = (
                    filtered_queryset.aggregate(total=Sum("total_amount"))["total"] or 0
                )

            outstanding_fees[label] = total

        return outstanding_fees
