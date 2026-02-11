from collections import defaultdict
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count
from django.db.models import DecimalField
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import Q
from django.db.models import Sum
from django.http import Http404
from django.template.loader import render_to_string
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.generics import ListCreateAPIView
from rest_framework.generics import RetrieveDestroyAPIView
from rest_framework.generics import UpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from account.message import MESSAGES as ACCOUNT_MESSAGE
from account.models import Organization
from account.models import Transaction
from account.models import User
from account.models import Wallet
from account.utils import get_user_or_business_name
from investor.message import MESSAGES as INVESTOR_MESSAGES
from investor.models import AssetContribution
from investor.utils import get_total_hold_amount_for_investor
from investor.utils import get_total_withdrawal_pending_amount
from jeweler.filters import MusharakahContractRequestFilter
from jeweler.message import MESSAGES as JEWELER_MESSAGES
from jeweler.models import JewelryDesign
from jeweler.models import MusharakahContractRequest
from jeweler.models import MusharakahContractRequestQuantity
from jeweler.models import MusharakahContractTerminationRequest
from jeweler.serializers import MusharakahContractAgreementDetailSerializer
from jeweler.serializers import MusharakahContractRequestAgreementResponseSerializer
from jeweler.serializers import MusharakahContractRequestCreateSerializer
from jeweler.serializers import MusharakahContractRequestQuantitySerializer
from jeweler.serializers import MusharakahContractRequestQuantityUpdateSerializer
from jeweler.serializers import MusharakahContractRequestResponseSerializer
from jeweler.serializers import MusharakahContractRequestRetrieveSerializer
from jeweler.serializers import MusharakahContractRequestStatisticsSerializer
from jeweler.serializers import MusharakahContractTerminationRequestSerializer
from jeweler.serializers import SettlementSummaryPaymentSerializer
from jeweler.utils import generate_musharaka_contract_context
from sooq_althahab.billing.subscription.helpers import prepare_organization_details
from sooq_althahab.billing.transaction.helpers import get_organization_logo_url
from sooq_althahab.constants import MUSHARAKAH_CONTRACT_REQUEST_CREATE_PERMISSION
from sooq_althahab.constants import (
    MUSHARAKAH_CONTRACT_REQUEST_QUANTITY_CHANGE_PERMISSION,
)
from sooq_althahab.constants import MUSHARAKAH_CONTRACT_REQUEST_VIEW_PERMISSION
from sooq_althahab.constants import (
    MUSHARAKAH_CONTRACT_TERMINATION_REQUEST_CREATE_PERMISSION,
)
from sooq_althahab.constants import SETTLEMENT_SUMMARY_PAYMENT_PERMISSION
from sooq_althahab.enums.account import MusharakahContractTerminationPaymentType
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.account import UserType
from sooq_althahab.enums.investor import ContributionType
from sooq_althahab.enums.jeweler import ContractTerminator
from sooq_althahab.enums.jeweler import LogisticCostPayableBy
from sooq_althahab.enums.jeweler import MusharakahContractStatus
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.helper import PermissionManager
from sooq_althahab.payment_gateway_services.credimax.subscription.free_trial_utils import (
    FreeTrialLimitationError,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.free_trial_utils import (
    validate_business_action_limits,
)
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.tasks import generate_pdf_response
from sooq_althahab.tasks import send_termination_reciept_mail
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab.utils import send_notifications
from sooq_althahab.utils import send_notifications_to_organization_admins
from sooq_althahab_admin.models import GlobalMetal
from sooq_althahab_admin.models import MetalPriceHistory


class MusharakahContractRequestBaseView:
    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return MusharakahContractRequest.objects.none()

        business = get_business_from_user_token(self.request, "business")
        if not business:
            return MusharakahContractRequest.objects.none()

        return MusharakahContractRequest.objects.filter(
            jeweler=business, organization_id=user.organization_id
        )


class MusharakahContractRequestListCreateView(
    MusharakahContractRequestBaseView, ListCreateAPIView
):
    """Handles listing and creating Musharakah Contract Requests."""

    permission_classes = [IsAuthenticated]
    queryset = MusharakahContractRequest.objects.all()
    pagination_class = CommonPagination
    filter_backends = (DjangoFilterBackend,)
    filterset_class = MusharakahContractRequestFilter

    def get_serializer_class(self):
        return (
            MusharakahContractRequestCreateSerializer
            if self.request.method == "POST"
            else MusharakahContractRequestResponseSerializer
        )

    @PermissionManager(MUSHARAKAH_CONTRACT_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Handles listing Musharakah Contract Requests."""

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return generic_response(
            data=self.get_paginated_response(serializer.data).data,
            message=JEWELER_MESSAGES["musharakah_contract_request_fetched"],
            status_code=status.HTTP_200_OK,
        )

    @PermissionManager(MUSHARAKAH_CONTRACT_REQUEST_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        """Handles creating a Musharakah Contract Request."""
        user = request.user
        organization_code = user.organization_id.code

        # If investor is individual then pass full name or else pass business name
        name = get_user_or_business_name(request)
        if not name:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ACCOUNT_MESSAGE["business_account_not_found"],
            )

        # Check free trial limitations before creating musharakah contract request
        business = get_business_from_user_token(request, "business")
        if business:
            try:
                # Get the design ID from request data
                design_id = request.data.get("design")
                if design_id:
                    try:
                        design = JewelryDesign.objects.get(id__in=design_id)
                        # Calculate total weight: sum of (weight * quantity) for all products
                        products = design.jewelry_products.annotate(
                            total_weight=ExpressionWrapper(
                                F("weight") * F("quantity"),
                                output_field=DecimalField(
                                    max_digits=20, decimal_places=4
                                ),
                            )
                        )
                        total_weight = products.aggregate(total=Sum("total_weight"))[
                            "total"
                        ] or Decimal("0.00")

                        if total_weight:
                            validate_business_action_limits(
                                business, "musharakah_request", weight=total_weight
                            )
                    except JewelryDesign.DoesNotExist:
                        # Design not found, let serializer handle the validation
                        pass
            except FreeTrialLimitationError as e:
                error_msg = e.messages[0] if e.messages else str(e)
                return generic_response(
                    message=error_msg,
                    status_code=status.HTTP_403_FORBIDDEN,
                )

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            musharakah_contract_request = serializer.save()

            # Send notification to admin
            title = "Musharakah contract request has been created."

            # If user has business then send name of business or else send fullname of user
            name = get_user_or_business_name(request)
            user_type = (
                "(Business)" if user.user_type == UserType.BUSINESS else "(Individual)"
            )
            message = f"'{name}' {user_type} has created a musharakah contract request for Jewlery Design."
            send_notifications_to_organization_admins(
                organization_code,
                title,
                message,
                NotificationTypes.MUSHARAKAH_CONTRACT_REQUEST_CREATED,
                ContentType.objects.get_for_model(MusharakahContractRequest),
                musharakah_contract_request.id,
                UserRoleChoices.TAQABETH_ENFORCER,
            )

            return generic_response(
                data=MusharakahContractRequestResponseSerializer(
                    musharakah_contract_request
                ).data,
                message=JEWELER_MESSAGES["musharakah_contract_request_created"],
                status_code=status.HTTP_201_CREATED,
            )

        return handle_serializer_errors(serializer)


class MusharakahContractTerminationRequestCreateAPIView(CreateAPIView):
    """Handles creating a Musharakah Contract Termination Request."""

    serializer_class = MusharakahContractTerminationRequestSerializer
    permission_classes = [IsAuthenticated]

    @PermissionManager(MUSHARAKAH_CONTRACT_TERMINATION_REQUEST_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        """Handles creating a Musharakah Contract Request Termination Request."""

        user = request.user
        organization_code = user.organization_id.code

        # If investor is individual then pass full name or else pass business name
        name = get_user_or_business_name(request)
        if not name:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ACCOUNT_MESSAGE["business_account_not_found"],
            )

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            musharakah_contract_termination_request = serializer.save()

            # send notification to admin
            title = "Musharakah contract termination request."
            user_type = (
                "(Business)" if user.user_type == UserType.BUSINESS else "(Individual)"
            )
            message = f"'{name}' {user_type} has requested to terminate musharakah contract request {musharakah_contract_termination_request.id}."
            send_notifications_to_organization_admins(
                organization_code,
                title,
                message,
                NotificationTypes.MUSHARAKAH_CONTRACT_TERMINATION_REQUEST,
                ContentType.objects.get_for_model(MusharakahContractRequest),
                musharakah_contract_termination_request.musharakah_contract_request.id,
                UserRoleChoices.TAQABETH_ENFORCER,
            )

            return generic_response(
                data=self.get_serializer(musharakah_contract_termination_request).data,
                message=JEWELER_MESSAGES[
                    "musharakah_contract_terminate_request_created"
                ],
                status_code=status.HTTP_201_CREATED,
            )

        return handle_serializer_errors(serializer)


class MusharakahContractRequestRetrieveAPIView(
    MusharakahContractRequestBaseView,
    RetrieveDestroyAPIView,
):
    """Handles retrieving a single Musharakah Contract Request."""

    permission_classes = [IsAuthenticated]
    serializer_class = MusharakahContractRequestRetrieveSerializer
    queryset = MusharakahContractRequest.objects.all()

    @PermissionManager(MUSHARAKAH_CONTRACT_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Handles retrieving a Musharakah Contract Request instance."""

        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data,
                message=JEWELER_MESSAGES["musharakah_contract_request_fetched"],
                status_code=status.HTTP_200_OK,
            )
        except Http404:
            return generic_response(
                error_message=JEWELER_MESSAGES["musharakah_contract_request_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

    def delete(self, request, *args, **Kwargs):
        """Handles delete a Musharakah Contract Request instance."""

        try:
            instance = self.get_object()
            if instance.investor:
                return generic_response(
                    message=JEWELER_MESSAGES[
                        "delete_musharakah_contract_request_failed_investor_assigned"
                    ],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            instance.delete()
            return generic_response(
                message=JEWELER_MESSAGES["musharakah_contract_request_deleted"],
                status_code=status.HTTP_200_OK,
            )
        except Http404:
            return generic_response(
                error_message=JEWELER_MESSAGES["musharakah_contract_request_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )


class MusharakahContractDownloadAPIView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MusharakahContractRequestResponseSerializer

    def get(self, request, pk):
        """Handle GET request to download Musharakah Contract Request details as a PDF."""

        musharakah_contract_request = (
            MusharakahContractRequest.objects.select_related(
                "jeweler", "investor", "duration_in_days"
            )
            .filter(pk=pk)
            .first()
        )

        if not musharakah_contract_request:
            return generic_response(
                message=JEWELER_MESSAGES["musharakah_contract_request_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not musharakah_contract_request.investor:
            return generic_response(
                message=JEWELER_MESSAGES["musharakah_contract_not_created_yet"],
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if musharakah_contract_request.status != RequestStatus.APPROVED:
            return generic_response(
                message=JEWELER_MESSAGES["musharakah_contract_pending_for_approval"],
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        organization_code = request.auth.get("organization_code")
        organization = Organization.objects.get(code=organization_code)
        organization_details = prepare_organization_details(organization)
        organization_logo_url = get_organization_logo_url(organization)

        serialized_musharakah_contract = self.serializer_class(
            musharakah_contract_request
        ).data
        context = {
            "musharakah_contract": generate_musharaka_contract_context(
                musharakah_contract_request, serialized_musharakah_contract
            ),
            "organization_details": organization_details,
            "organization_logo_url": organization_logo_url,
        }

        return generate_pdf_response(
            "musharakah_contract/musharakah-contract-details.html",
            context,
            filename="musharakah_contract_details.pdf",
        )


class MusharakahContractStatisticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        # Step 1: Identify logged-in business
        business = get_business_from_user_token(request, "business")

        # Step 2: Aggregate contract statistics (including deleted via global_objects)
        queryset = MusharakahContractRequest.global_objects.filter(jeweler=business)

        data = queryset.aggregate(
            total_count=Count("id"),
            active_count=Count(
                "id",
                filter=Q(
                    status=RequestStatus.APPROVED,
                    musharakah_contract_status__in=[
                        MusharakahContractStatus.ACTIVE,
                        MusharakahContractStatus.RENEW,
                    ],
                    deleted_at__isnull=True,
                ),
            ),
            terminated_count=Count(
                "id",
                filter=Q(
                    musharakah_contract_status=MusharakahContractStatus.TERMINATED,
                    deleted_at__isnull=True,
                ),
            ),
            awaiting_admin_approval_count=Count(
                "id",
                filter=Q(
                    status=RequestStatus.PENDING,
                    musharakah_contract_status=MusharakahContractStatus.ACTIVE,
                    deleted_at__isnull=True,
                ),
            ),
            not_assigned_count=Count(
                "id",
                filter=Q(
                    musharakah_contract_status=MusharakahContractStatus.NOT_ASSIGNED,
                    deleted_at__isnull=True,
                ),
            ),
            deleted_count=Count("id", filter=Q(deleted_at__isnull=False)),
        )

        # Step 3: Get all musharakah IDs of this business
        musharakah_ids = MusharakahContractRequest.objects.filter(
            jeweler=business
        ).values_list("id", flat=True)

        # Step 4: Fetch relevant asset contributions
        contributions = AssetContribution.objects.filter(
            musharakah_contract_request_id__in=musharakah_ids,
            contribution_type=ContributionType.MUSHARAKAH,
        ).select_related(
            "purchase_request__precious_item__material_item",
            "purchase_request__precious_item__carat_type",
            "purchase_request__precious_item__precious_stone",
            "purchase_request__precious_item__precious_metal",
        )

        # Step 5: Initialize grouped data containers
        metal_data = defaultdict(lambda: defaultdict(lambda: {"total_quantity": 0}))
        stone_data = defaultdict(lambda: {"total_cost": 0})
        has_data = False

        for contribution in contributions:
            try:
                precious_item = contribution.purchase_request.precious_item
                quantity = float(contribution.quantity or 0)
                material_type = precious_item.material_type
                material_item_name = precious_item.material_item.name
                carat = (
                    precious_item.carat_type.name
                    if precious_item.carat_type
                    else "Unknown"
                )

                if material_type == MaterialType.METAL:
                    weight_per_unit = float(precious_item.precious_metal.weight)
                    total_weight = weight_per_unit * quantity
                    metal_data[material_item_name][carat][
                        "total_quantity"
                    ] += total_weight
                    has_data = True

                elif material_type == MaterialType.STONE:
                    price_per_unit = float(precious_item.precious_stone.price)
                    total_cost = price_per_unit * quantity
                    stone_data[material_item_name]["total_cost"] += total_cost
                    has_data = True

            except Exception:
                continue

        # Step 6: Assemble result
        asset_data = {"material_assets_value": {}}
        if has_data:
            asset_data["material_assets_value"] = {
                "metal": dict(metal_data),
                "stone": dict(stone_data),
            }

        # Step 7: Merge contract statistics with material asset summary
        full_response_data = {**data, **asset_data}

        # Step 8: Validate and return response
        serializer = MusharakahContractRequestStatisticsSerializer(
            data=full_response_data
        )
        serializer.is_valid(raise_exception=True)

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=JEWELER_MESSAGES["musharakah_contract_statistics_retrieved"],
            data=serializer.validated_data,
        )


class MusharakahContractRequestQuantityBulkUpdateAPIView(UpdateAPIView):
    queryset = MusharakahContractRequestQuantity.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = MusharakahContractRequestQuantityUpdateSerializer
    response_serializer_class = MusharakahContractRequestQuantitySerializer
    http_method_names = ["patch"]

    @swagger_auto_schema(
        operation_description="Bulk update Musharakah Contract Request Quantities.",
        request_body=openapi.Schema(
            type=openapi.TYPE_ARRAY,
            items=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                required=["id", "quantity"],
                properties={
                    "id": openapi.Schema(
                        type=openapi.TYPE_STRING, example="mrq_230625375299"
                    ),
                    "quantity": openapi.Schema(
                        type=openapi.TYPE_STRING, example="20.00"
                    ),
                },
            ),
        ),
        responses={
            200: openapi.Response(
                description="List of updated items",
                schema=openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "id": openapi.Schema(type=openapi.TYPE_STRING),
                            "musharakah_contract_request": openapi.Schema(
                                type=openapi.TYPE_STRING
                            ),
                            "jewelry_product": openapi.Schema(type=openapi.TYPE_STRING),
                            "quantity": openapi.Schema(type=openapi.TYPE_STRING),
                        },
                    ),
                ),
            )
        },
    )
    @PermissionManager(MUSHARAKAH_CONTRACT_REQUEST_QUANTITY_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        # mcr stands for musharakah contract request
        mcr_quantity_data_list = request.data

        if not isinstance(mcr_quantity_data_list, list):
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=JEWELER_MESSAGES["invalid_mcr_quantity_payload"],
            )

        updated_quantity_list = []

        for mcr_quantity_data in mcr_quantity_data_list:
            mcr_quantity_id = mcr_quantity_data.get("id")
            new_quantity = mcr_quantity_data.get("quantity")

            if not mcr_quantity_id or new_quantity is None:
                continue

            try:
                quantity_instance = self.queryset.get(pk=mcr_quantity_id)
                serializer = self.get_serializer(
                    quantity_instance, data={"quantity": new_quantity}, partial=True
                )
                if serializer.is_valid():
                    saved_quantity = serializer.save()
                    updated_quantity_list.append(
                        self.response_serializer_class(saved_quantity).data
                    )
            except MusharakahContractRequestQuantity.DoesNotExist:
                continue  # Skip if object doesn't exist

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=JEWELER_MESSAGES["musharakah_contract_request_quantity_updated"],
            data=updated_quantity_list,
        )


class MusharakahContractAgreementPostAPIView(APIView):
    """Handles posting Musharakah Contract Agreement."""

    serializer_class = MusharakahContractAgreementDetailSerializer
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(request_body=MusharakahContractAgreementDetailSerializer)
    @PermissionManager(MUSHARAKAH_CONTRACT_REQUEST_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        """Handles posting Musharakah Contract Agreement."""
        user = request.user
        organization = user.organization_id

        # If investor is individual then pass full name or else pass business name
        name = get_user_or_business_name(request)
        if not name:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ACCOUNT_MESSAGE["business_account_not_found"],
            )

        request.data["jeweler_signature"] = user.pk
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            # Get the musharakah_contract_request instance if it exists (for updates)
            musharakah_contract_request = None
            if hasattr(serializer, "instance") and serializer.instance:
                musharakah_contract_request = serializer.instance
            elif "id" in request.data:
                # Try to get instance from request data if id is provided
                try:
                    musharakah_contract_request = MusharakahContractRequest.objects.get(
                        id=request.data["id"], organization_id=organization
                    )
                except MusharakahContractRequest.DoesNotExist:
                    pass

            musharakah_contract_agreement = (
                MusharakahContractRequestAgreementResponseSerializer(
                    instance=None, data=serializer.validated_data
                )
            )
            musharakah_contract_agreement.is_valid()

            # If we still don't have the instance, try to get it from serialized data
            if (
                not musharakah_contract_request
                and musharakah_contract_agreement.data.get("id")
            ):
                try:
                    musharakah_contract_request = MusharakahContractRequest.objects.get(
                        id=musharakah_contract_agreement.data["id"],
                        organization_id=organization,
                    )
                except MusharakahContractRequest.DoesNotExist:
                    pass

            # Pass both serialized data, validated_data, and instance to access duration_in_days and asset_contributions
            file = self.generate_musharakah_contract_agreement_html(
                request,
                organization.name,
                organization.arabic_name or organization.name,
                musharakah_contract_agreement.data,
                serializer.validated_data,
                musharakah_contract_request,
            )
            return generic_response(
                message=JEWELER_MESSAGES["musharakah_contract_agreement_posted"],
                status_code=status.HTTP_201_CREATED,
                data=file,
            )

        return handle_serializer_errors(serializer)

    def generate_musharakah_contract_agreement_html(
        self,
        request,
        organization_name,
        organization_arabic_name,
        serialized_contract,
        validated_data=None,
        musharakah_contract_request=None,
    ):
        """Generates HTML for Musharakah Contract Agreement."""
        from django.utils import translation

        # Determine the correct organization name based on request language
        current_language = translation.get_language()
        if current_language == "ar" and organization_arabic_name:
            org_name = organization_arabic_name
        else:
            org_name = organization_name

        context = {
            "musharakah_contract": self.generate_musharaka_contract_context(
                serialized_contract, validated_data, musharakah_contract_request
            ),
            "organization_name": org_name,
        }
        html_string = render_to_string(
            "musharakah_contract/musharakah-contract-response.html",
            context,
        )
        return html_string

    def generate_musharaka_contract_context(
        self,
        serialized_musharakah_contract,
        validated_data=None,
        musharakah_contract_request=None,
    ):
        from datetime import datetime
        from datetime import timedelta
        from decimal import ROUND_HALF_UP
        from decimal import Decimal

        from django.db.models import DecimalField
        from django.db.models import F
        from django.db.models import Sum

        from account.models import OrganizationCurrency
        from sooq_althahab.billing.transaction.helpers import get_user_contact_details
        from sooq_althahab_admin.models import GlobalMetal
        from sooq_althahab_admin.models import MetalPriceHistory

        # === Jeweler details ===
        jeweler_data = serialized_musharakah_contract.get("jeweler") or {}
        jeweler_owner = jeweler_data.get("owner") or {}
        jeweler_address = (
            get_user_contact_details(jeweler_owner.get("id"))
            if jeweler_owner.get("id")
            else {}
        )

        # === Jewelry Designs & Materials ===
        materials = []
        designs = []
        design_value = Decimal("0.00")

        # Calculate precious_items_value from asset_contributions if available
        if musharakah_contract_request:
            precious_items_value = (
                musharakah_contract_request.asset_contributions.aggregate(
                    total=Sum(
                        F("quantity") * F("price_locked"),
                        output_field=DecimalField(max_digits=20, decimal_places=2),
                    )
                )["total"]
                or Decimal("0.00")
            )
            precious_items_value = precious_items_value.quantize(
                Decimal("0.00"), rounding=ROUND_HALF_UP
            )
        else:
            precious_items_value = Decimal("0.00")

        # Resolve default organization currency rate
        try:
            org = self.request.user.organization_id
            default_currency = OrganizationCurrency.objects.filter(
                organization=org, is_default=True
            ).first()
            exchange_rate = (
                Decimal(str(default_currency.rate))
                if default_currency and default_currency.rate is not None
                else Decimal("1")
            )
        except Exception:
            exchange_rate = Decimal("1")

        # Extract jewelry products from designs
        designs_data = (
            serialized_musharakah_contract.get("musharakah_contract_designs", []) or []
        )
        jewelry_products = [
            product
            for item in designs_data
            for product in (
                getattr(item.get("design"), "jewelry_products", []).all()
                if item.get("design")
                else []
            )
        ]

        # Map of requested quantities
        quantities_map = {
            rq.get("jewelry_product"): rq.get("quantity")
            for rq in serialized_musharakah_contract.get(
                "musharakah_contract_request_quantities", []
            )
        }

        # Process each jewelry product
        for product in jewelry_products:
            product_name = getattr(product, "product_name", "N/A")
            designs.append(product_name)
            price = Decimal(str(getattr(product, "price", 0) or 0))
            design_value += price

            # FIX: RelatedManager -> QuerySet
            product_materials = getattr(product, "product_materials", None)
            product_materials = product_materials.all() if product_materials else []

            for material in product_materials:
                quantity_value = Decimal(
                    str(
                        quantities_map.get(
                            getattr(product, "id"), getattr(material, "quantity", 0)
                        )
                        or 0
                    )
                )
                weight_value = Decimal(str(getattr(material, "weight", 0) or 0))
                material_item = getattr(material, "material_item", "N/A")
                material_type = getattr(material, "material_type", "N/A")
                carat_type = getattr(material, "carat_type", "N/A")

                materials.append(
                    {
                        "item": material_item,
                        "quantity": quantity_value,
                        "weight": weight_value,
                        "weight_unit": "g"
                        if material_type == MaterialType.METAL
                        else "ct",
                        "carat_type": carat_type,
                        "type": material_type,
                    }
                )

                # Compute precious item valuation if no instance
                if (
                    not musharakah_contract_request
                    and material_type == MaterialType.METAL
                ):
                    global_metal = GlobalMetal.objects.filter(
                        name=material_item
                    ).first()
                    metal_price_record = (
                        MetalPriceHistory.objects.filter(global_metal=global_metal)
                        .order_by("-created_at")
                        .first()
                    )
                    metal_live_price = (
                        Decimal(str(metal_price_record.price))
                        if metal_price_record and metal_price_record.price is not None
                        else Decimal("0.00")
                    )

                    raw_carat = carat_type or ""
                    if isinstance(raw_carat, str):
                        raw_carat = raw_carat.upper().replace("K", "").strip()
                    try:
                        carat_value = Decimal(str(raw_carat))
                    except Exception:
                        carat_value = Decimal("24")

                    scaled_metal_price = (
                        metal_live_price * (carat_value / Decimal(24)) * exchange_rate
                    )
                    precious_items_value += (
                        weight_value * scaled_metal_price * quantity_value
                    )

        # Jeweler signature
        jeweler_signature = (
            serialized_musharakah_contract.get("jeweler_signature") or {}
        )
        jeweler_signature_url = (
            jeweler_signature.get("url") if isinstance(jeweler_signature, dict) else ""
        )

        # Approved and expiry dates
        approved_at = None
        approved_at_str = serialized_musharakah_contract.get("approved_at")
        try:
            if approved_at_str:
                approved_at = datetime.fromisoformat(approved_at_str).date()
        except Exception:
            approved_at = None

        expiry_date = None
        expiry_date_str = serialized_musharakah_contract.get("expiry_date")
        expiry_days = None
        if validated_data:
            duration_obj = validated_data.get("duration_in_days")
            if hasattr(duration_obj, "days"):
                expiry_days = duration_obj.days
            elif isinstance(duration_obj, dict):
                expiry_days = duration_obj.get("days")

        try:
            if expiry_date_str:
                expiry_date = datetime.fromisoformat(expiry_date_str).date()
            elif approved_at and expiry_days:
                expiry_date = approved_at + timedelta(days=expiry_days)
        except Exception:
            expiry_date = None

        musharakah_equity = Decimal(
            str(serialized_musharakah_contract.get("musharakah_equity", 0) or 0)
        )

        return {
            "jeweler": {
                "name": jeweler_data.get("name") or jeweler_owner.get("name", "N/A"),
                "address": jeweler_address.get("address", "N/A"),
                "country": jeweler_address.get("country", "N/A"),
                "phone": jeweler_owner.get("phone_number", "N/A"),
            },
            "materials": materials,
            "designs": designs,
            "design_value": design_value,
            "precious_items_value": precious_items_value,
            "business_capital_value": str(
                (precious_items_value + design_value).quantize(Decimal("0.01"))
            ),
            "penalty_amount": Decimal(
                str(serialized_musharakah_contract.get("penalty_amount", "0.00"))
            ),
            "expiry_date": expiry_date,
            "expiry_days": expiry_days,
            "investor_profit_sharing_ratio": musharakah_equity,
            "jeweler_profit_sharing_ratio": Decimal("100.00") - musharakah_equity,
            "approved_at": approved_at,
            "jeweler_signature": jeweler_signature_url,
        }


class SettlementSummaryPaymentCreateAPI(CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SettlementSummaryPaymentSerializer

    @PermissionManager(SETTLEMENT_SUMMARY_PAYMENT_PERMISSION)
    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            user = request.user
            business = get_business_from_user_token(request, "business")
            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                return handle_serializer_errors(serializer)

            musharakah_contract_id = serializer.validated_data.get(
                "musharakah_contract_id"
            )

            # Fetch the musharakah contract termination request for the given contract ID
            musharakah_contract_termination_request = (
                MusharakahContractTerminationRequest.objects.filter(
                    musharakah_contract_request__id=musharakah_contract_id
                ).first()
            )

            # Get the associated Musharakah Contract object
            musharakah_contract = (
                musharakah_contract_termination_request.musharakah_contract_request
            )

            # Ensure the termination request was made by the jeweler, not the investor
            if (
                musharakah_contract_termination_request.termination_request_by
                != ContractTerminator.JEWELER
            ):
                return generic_response(
                    message=JEWELER_MESSAGES["termination_request_by_investor"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            payment_transaction = Transaction.objects.filter(
                musharakah_contract=musharakah_contract,
                status=TransactionStatus.PENDING,
                musharakah_contract_termination_payment_type=MusharakahContractTerminationPaymentType.JEWELER_SETTLEMENT_PAYMENT_TRANSACTION,
            ).first()

            # Check if the jeweler has already processed settlement payment
            if not payment_transaction:
                return generic_response(
                    message=JEWELER_MESSAGES["settlement_payment_already_processed"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Fetch the wallet of the jeweler’s business
            wallet = Wallet.objects.filter(business=business).first()
            # Check if jeweler's wallet has sufficient balance to cover the total amount
            total_hold_amount_for_purchase_request = get_total_hold_amount_for_investor(
                business
            )

            total_withdrawal_pending_amount = get_total_withdrawal_pending_amount(
                business
            )

            # Check for sufficient balance
            available_balance = (
                wallet.balance
                - total_hold_amount_for_purchase_request
                - total_withdrawal_pending_amount
            )

            if available_balance < payment_transaction.amount:
                return generic_response(
                    message=INVESTOR_MESSAGES["insufficient_balance"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            payment_transaction.previous_balance = wallet.balance
            # Deduct the total payable amount from the jeweler's wallet
            wallet.balance -= payment_transaction.amount
            wallet.save()

            # Record the musharakah contract termination fee transaction in the Transaction table
            payment_transaction.status = TransactionStatus.APPROVED
            payment_transaction.current_balance = wallet.balance
            payment_transaction.payment_completed_at = timezone.now()
            payment_transaction.save()

            # Save the musharakah contract termination request after updating status
            musharakah_contract_termination_request.save()

            # Send notification to organization admins
            organization = user.organization_id

            if user.user_type == UserType.BUSINESS:
                user_type = "(Business)"
                name = business.name
            else:
                user_type = "(Individual)"
                name = user.fullname
            subject = "Settlement Summary payment"

            logistic_cost = (
                musharakah_contract_termination_request.logistics_cost
                if musharakah_contract_termination_request.logistics_cost_payable_by
                == LogisticCostPayableBy.JEWELER
                else Decimal("0.00")
            )
            sub_total = (
                musharakah_contract_termination_request.insurance_fee + logistic_cost
            )

            send_termination_reciept_mail.delay(
                user.pk,
                organization.pk,
                business.pk,
                payment_transaction.pk,
                musharakah_contract_termination_request.pk,
                subject,
                sub_total,
                "Early Termination Sattlement",
            )

            title = "Musharakah contract early termination payment initiated."
            message = f"'{name}' {user_type} has initiated a musharakah conract early termination payment of amount {payment_transaction.amount}."
            send_notifications_to_organization_admins(
                organization.code,
                title,
                message,
                NotificationTypes.MUSHARAKAH_CONTRACT_TERMINATION_PAYMENT,
                ContentType.objects.get_for_model(MusharakahContractRequest),
                musharakah_contract.id,
                UserRoleChoices.TAQABETH_ENFORCER,
            )

            all_users_in_related_business = User.objects.filter(
                user_assigned_businesses__business=business,
                user_preference__notifications_enabled=True,
            ).distinct()

            send_notifications(
                all_users_in_related_business,
                f"Amount debited from your wallet.",
                f"BHD {payment_transaction.amount} has been debited from your wallet for the payment of early termination of musharakah contract {musharakah_contract.id}.",
                NotificationTypes.MUSHARAKAH_CONTRACT_TERMINATION_PAYMENT,
                ContentType.objects.get_for_model(Transaction),
                payment_transaction.id,
            )
            return generic_response(
                message=INVESTOR_MESSAGES["termination_fee_processed_successfully"],
                status_code=status.HTTP_201_CREATED,
                data=serializer.data,
            )
