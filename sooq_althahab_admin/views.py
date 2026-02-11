import logging
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count
from django.db.models import F
from django.db.models import Prefetch
from django.db.models import Q
from django.db.models import Sum
from django.http import Http404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework import viewsets
from rest_framework.generics import CreateAPIView
from rest_framework.generics import DestroyAPIView
from rest_framework.generics import ListAPIView
from rest_framework.generics import ListCreateAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.generics import RetrieveUpdateDestroyAPIView
from rest_framework.generics import UpdateAPIView
from rest_framework.mixins import CreateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from account.message import MESSAGES as ACCOUNT_MESSAGES
from account.models import Address
from account.models import BusinessAccount
from account.models import Organization
from account.models import OrganizationCurrency
from account.models import OrganizationRiskLevel
from account.models import Transaction
from account.models import User
from account.models import UserAssignedBusiness
from account.models import UserPreference
from account.models import Wallet
from account.utils import get_user_or_business_name
from investor.message import MESSAGES as INVESTOR_MESSAGES
from investor.models import AssetContribution
from investor.models import PreciousItemUnit
from investor.models import PurchaseRequest
from investor.serializers import PurchaseRequestResponseSerializer
from investor.serializers import TransactionResponseSerializer
from jeweler.filters import MusharakahContractRequestFilter
from jeweler.message import MESSAGES as JEWELER_MESSAGES
from jeweler.models import JewelryProductStonePrice
from jeweler.models import JewelryProfitDistribution
from jeweler.models import ManufacturingProductRequestedQuantity
from jeweler.models import ManufacturingRequest
from jeweler.models import ManufacturingTarget
from jeweler.models import MusharakahContractRenewal
from jeweler.models import MusharakahContractRequest
from jeweler.models import MusharakahContractTerminationRequest
from jeweler.models import ProductionPayment
from jeweler.serializers import MusharakahContractRequestResponseSerializer
from manufacturer.models import ManufacturingEstimationRequest
from manufacturer.models import ProductManufacturingEstimatedPrice
from manufacturer.views.manufacturing_requests import ManufacturingRequestListAPIView
from manufacturer.views.manufacturing_requests import (
    ManufacturingRequestRetrieveAPIView,
)
from seller.filters import PurchaseRequestFilter
from seller.serializers import PreciousItemUnitResponseSerializer
from seller.serializers import PurchaseRequestDetailsSerializer
from seller.utils import get_fcm_tokens_for_users
from sooq_althahab.constants import ADMIN_PURCHASE_REQUEST_CHANGE_PERMISSION
from sooq_althahab.constants import ADMIN_PURCHASE_REQUEST_VIEW_PERMISSION
from sooq_althahab.constants import BUSINESS_RISK_LEVEL_CHANGE_PERMISSION
from sooq_althahab.constants import JEWELRY_PRODUCT_COLOR_CHANGE_PERMISSION
from sooq_althahab.constants import JEWELRY_PRODUCT_COLOR_CREATE_PERMISSION
from sooq_althahab.constants import JEWELRY_PRODUCT_COLOR_VIEW_PERMISSION
from sooq_althahab.constants import JEWELRY_PRODUCT_TYPE_CHANGE_PERMISSION
from sooq_althahab.constants import JEWELRY_PRODUCT_TYPE_CREATE_PERMISSION
from sooq_althahab.constants import JEWELRY_PRODUCT_TYPE_VIEW_PERMISSION
from sooq_althahab.constants import MANAGE_BUSINESS_ACCOUNT_SUSPENSION_CHANGE_PERMISSION
from sooq_althahab.constants import MANAGE_USER_SUSPENSION_CHANGE_PERMISSION
from sooq_althahab.constants import MATERIAL_ITEM_CREATE_PERMISSION
from sooq_althahab.constants import MATERIAL_ITEM_VIEW_PERMISSION
from sooq_althahab.constants import METAL_CARAT_TYPE_CHANGE_PERMISSION
from sooq_althahab.constants import METAL_CARAT_TYPE_CREATE_PERMISSION
from sooq_althahab.constants import METAL_CARAT_TYPE_VIEW_PERMISSION
from sooq_althahab.constants import MUSHARAKAH_CONTRACT_RENEWAL_CREATE_PERMISSION
from sooq_althahab.constants import MUSHARAKAH_CONTRACT_REQUEST_CHANGE_PERMISSION
from sooq_althahab.constants import (
    MUSHARAKAH_CONTRACT_REQUEST_TERMINATE_CHANGE_PERMISSION,
)
from sooq_althahab.constants import MUSHARAKAH_CONTRACT_REQUEST_VIEW_PERMISSION
from sooq_althahab.constants import (
    MUSHARAKAH_CONTRACT_TERMINATION_REQUEST_CHANGE_PERMISSION,
)
from sooq_althahab.constants import (
    MUSHARAKAH_CONTRACT_TERMINATION_REQUEST_CREATE_PERMISSION,
)
from sooq_althahab.constants import (
    MUSHARAKAH_CONTRACT_TERMINATION_REQUEST_VIEW_PERMISSION,
)
from sooq_althahab.constants import MUSHARAKAH_DURATION_CHANGE_PERMISSION
from sooq_althahab.constants import MUSHARAKAH_DURATION_CREATE_PERMISSION
from sooq_althahab.constants import MUSHARAKAH_DURATION_VIEW_PERMISSION
from sooq_althahab.constants import ORGANIZATION_BANK_ACCOUNT_CHANGE_PERMISSION
from sooq_althahab.constants import ORGANIZATION_BANK_ACCOUNT_CREATE_PERMISSION
from sooq_althahab.constants import ORGANIZATION_BANK_ACCOUNT_VIEW_PERMISSION
from sooq_althahab.constants import ORGANIZATION_CHANGE_PERMISSION
from sooq_althahab.constants import ORGANIZATION_CURRENCY_CHANGE_PERMISSION
from sooq_althahab.constants import ORGANIZATION_CURRENCY_CREATE_PERMISSION
from sooq_althahab.constants import ORGANIZATION_CURRENCY_VIEW_PERMISSION
from sooq_althahab.constants import ORGANIZATION_VIEW_PERMISSION
from sooq_althahab.constants import POOL_CHANGE_PERMISSION
from sooq_althahab.constants import POOL_CREATE_PERMISSION
from sooq_althahab.constants import POOL_VIEW_PERMISSION
from sooq_althahab.constants import PRECIOUS_ITEM_ATTRIBUTES_VIEW_PERMISSION
from sooq_althahab.constants import PRECIOUS_ITEM_UNIT_VIEW_PERMISSION
from sooq_althahab.constants import RISK_LEVEL_CHANGE_PERMISSION
from sooq_althahab.constants import RISK_LEVEL_CREATE_PERMISSION
from sooq_althahab.constants import RISK_LEVEL_VIEW_PERMISSION
from sooq_althahab.constants import STONE_CLARITY_CHANGE_PERMISSION
from sooq_althahab.constants import STONE_CLARITY_CREATE_PERMISSION
from sooq_althahab.constants import STONE_CLARITY_VIEW_PERMISSION
from sooq_althahab.constants import STONE_CUT_SHAPE_CHANGE_PERMISSION
from sooq_althahab.constants import STONE_CUT_SHAPE_CREATE_PERMISSION
from sooq_althahab.constants import STONE_CUT_SHAPE_VIEW_PERMISSION
from sooq_althahab.constants import SUBADMIN_CHANGE_PERMISSION
from sooq_althahab.constants import SUBADMIN_CREATE_PERMISSION
from sooq_althahab.constants import SUBADMIN_DELETE_PERMISSION
from sooq_althahab.constants import SUBADMIN_VIEW_PERMISSION
from sooq_althahab.constants import TRANSACTION_VIEW_PERMISSION
from sooq_althahab.constants import USER_VIEW_PERMISSION
from sooq_althahab.enums.account import SubscriptionStatusChoices
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.account import UserStatus
from sooq_althahab.enums.account import UserType
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.enums.jeweler import AssetContributionStatus
from sooq_althahab.enums.jeweler import ContractTerminator
from sooq_althahab.enums.jeweler import ImpactedParties
from sooq_althahab.enums.jeweler import RefineSellPaymentOption
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.enums.sooq_althahab_admin import PoolStatus
from sooq_althahab.enums.sooq_althahab_admin import Status
from sooq_althahab.enums.sooq_althahab_admin import StoneOrigin
from sooq_althahab.helper import PermissionManager
from sooq_althahab.querysets.purchase_request import base_purchase_request_queryset
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.tasks import send_mail
from sooq_althahab.tasks import send_notification
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab.utils import send_notification_count_to_users
from sooq_althahab.utils import send_notifications
from sooq_althahab_admin.filters import BusinessFilter
from sooq_althahab_admin.filters import InvestorBusinessFilter
from sooq_althahab_admin.filters import JewelryProductColorFilter
from sooq_althahab_admin.filters import JewelryProductTypeFilter
from sooq_althahab_admin.filters import JewelryProfitDistributionFilter
from sooq_althahab_admin.filters import MaterialItemFilter
from sooq_althahab_admin.filters import MetalCaratTypeFilter
from sooq_althahab_admin.filters import MusharakahContractTerminationFilter
from sooq_althahab_admin.filters import MusharakahDurationChoicesFilter
from sooq_althahab_admin.filters import PoolFilter
from sooq_althahab_admin.filters import StoneClarityFilter
from sooq_althahab_admin.filters import StoneCutShapeFilter
from sooq_althahab_admin.filters import SubAdminFilter
from sooq_althahab_admin.filters import TransactionFilter
from sooq_althahab_admin.filters import UserFilter
from sooq_althahab_admin.models import BillingDetails
from sooq_althahab_admin.models import BusinessSubscriptionPlan
from sooq_althahab_admin.models import GlobalMetal
from sooq_althahab_admin.models import JewelryProductColor
from sooq_althahab_admin.models import JewelryProductType
from sooq_althahab_admin.models import MaterialItem
from sooq_althahab_admin.models import MetalCaratType
from sooq_althahab_admin.models import MetalPriceHistory
from sooq_althahab_admin.models import MusharakahDurationChoices
from sooq_althahab_admin.models import Notification
from sooq_althahab_admin.models import OrganizationBankAccount
from sooq_althahab_admin.models import Pool
from sooq_althahab_admin.models import PoolContribution
from sooq_althahab_admin.models import StoneClarity
from sooq_althahab_admin.models import StoneCutShape
from sooq_althahab_admin.models import SubscriptionPlan
from sooq_althahab_admin.serializers import BusinessSubscriptionPlanSerializer
from sooq_althahab_admin.serializers import MaterialItemDetailSerializer
from sooq_althahab_admin.serializers import SubscriptionTransactionDetailSerializer
from sooq_althahab_admin.serializers import SubscriptionTransactionListSerializer

from .message import MESSAGES
from .serializers import AdminMusharakahContractTerminationRequestSerializer
from .serializers import BusinessAccountSuspensionSerializer
from .serializers import BusinessRiskLevelUpdateSerializer
from .serializers import BusinessWithOwnerSerializer
from .serializers import GlobalMetalSerializer
from .serializers import InvestorBusinessWithOwnerSerializer
from .serializers import JewelryProductColorSerializer
from .serializers import JewelryProductTypeSerializer
from .serializers import JewelryProfitDistributionSerializer
from .serializers import MaterialItemSerializer
from .serializers import MaterialItemUpdateSerializer
from .serializers import MetalCaratTypeSerializer
from .serializers import MusharakahContractManufacturingCostCreateSerializer
from .serializers import MusharakahContractManufacturingCostResponseSerializer
from .serializers import MusharakahContractRenewalSerializer
from .serializers import MusharakahContractRequestFromTerminatedCreateSerializer
from .serializers import MusharakahContractRequestPreApprovalSerializer
from .serializers import MusharakahContractRequestSerializer
from .serializers import MusharakahContractRequestStatusUpdateSerializer
from .serializers import MusharakahContractRequestTerminationUpdateSerializer
from .serializers import MusharakahContractTerminationRequestResponseSerializer
from .serializers import MusharakahContractTerminationRequestUpdateStatusSerializer
from .serializers import MusharakahDurationChoiceSerializer
from .serializers import OrganizationBankAccountSerializer
from .serializers import OrganizationCurrencySerializer
from .serializers import OrganizationCurrencyUpdateSerializer
from .serializers import OrganizationResponseSerializer
from .serializers import OrganizationRiskLevelSerializer
from .serializers import OrganizationSerializer
from .serializers import PoolContributionUpdateSerializer
from .serializers import PoolCreateSerializer
from .serializers import PoolDetailsSerializer
from .serializers import PoolResponseSerializer
from .serializers import PoolUpdateSerializer
from .serializers import PreciousItemAttributes
from .serializers import PreciousItemUnitBulkAdminUpdateSerializer
from .serializers import PurchaseRequestUpdateSerializer
from .serializers import StoneClaritySerializer
from .serializers import StoneCutShapeSerializer
from .serializers import SubAdminCreateSerializer
from .serializers import SubAdminSerializer
from .serializers import SubscriptionPlanSerializer
from .serializers import TransactionUpdateSerializer
from .serializers import UserSerializer
from .serializers import UserSuspensionStatusUpdateSerializer
from .serializers import UserUpdateSerializer

logger = logging.getLogger(__name__)

########################################################################################
################################# User and Business APIs ###############################
########################################################################################


class BaseBusinessListAPIView(ListAPIView):
    """Base class for handling business-related listings with common filtering logic."""

    BUSINESS_ROLES = [
        UserRoleBusinessChoices.SELLER,
        UserRoleBusinessChoices.JEWELER,
        UserRoleBusinessChoices.INVESTOR,
        UserRoleBusinessChoices.MANUFACTURER,
    ]

    def get_paginated_response_data(self, queryset, message):
        """Handles pagination and response formatting."""
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK, message=message, data=response_data
        )


class BusinessListAPIView(BaseBusinessListAPIView):
    serializer_class = BusinessWithOwnerSerializer  # Create a new serializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    queryset = BusinessAccount.global_objects.all().order_by("-created_at")
    filter_backends = [DjangoFilterBackend]
    filterset_class = BusinessFilter

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return self.queryset.none()

        latest_subscription_prefetch = Prefetch(
            "business_subscription_plan",  # <-- Correct related_name
            queryset=BusinessSubscriptionPlan.global_objects.order_by("-created_at"),
            to_attr="prefetched_subscriptions",
        )

        # prefetch UserAssignedBusiness (soft-deleted included)
        user_assigned_prefetch = Prefetch(
            "user_assigned_businesses",
            queryset=UserAssignedBusiness.global_objects.prefetch_related(
                Prefetch(
                    "user",
                    queryset=User.global_objects.all(),
                    to_attr="prefetched_user",  # attach user here instead of using .user
                )
            ),
            to_attr="all_user_assigned_businesses",
        )

        return (
            self.queryset.prefetch_related(
                user_assigned_prefetch,
                latest_subscription_prefetch,
            )
            .annotate(total_users=Count("user_assigned_businesses"))
            .distinct()
        )

    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        return self.get_paginated_response_data(
            queryset, message=MESSAGES["business_list_retrieved"]
        )


class InvestorListAPIView(BaseBusinessListAPIView):
    """
    API endpoint for listing investor businesses with owner information.

    This API is optimized for performance and returns only essential business information:
    - Business ID, name, and business account type
    - Owner user ID and name

    Filters:
    - Only shows businesses with business_account_type = 'INVESTOR'
    - Business has any subscription plan (business_subscription_plan__isnull=False)
    """

    serializer_class = InvestorBusinessWithOwnerSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    queryset = BusinessAccount.global_objects.all().order_by("created_at")
    filter_backends = [DjangoFilterBackend]
    filterset_class = InvestorBusinessFilter

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return self.queryset.none()

        owner_qs = UserAssignedBusiness.objects.filter(is_owner=True).select_related(
            "user"
        )

        # Filter by investor business type and activated business status
        queryset = (
            self.queryset.filter(
                business_account_type=UserRoleBusinessChoices.INVESTOR,
                is_suspended=False,
                business_subscription_plan__isnull=False,
            )
            .prefetch_related(
                Prefetch(
                    "user_assigned_businesses",
                    queryset=owner_qs,
                    to_attr="prefetched_owners",
                )
            )
            .distinct()
        )
        return queryset

    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        return self.get_paginated_response_data(
            queryset, message=MESSAGES["investor_business_listed"]
        )


class BusinessDeleteAPIView(DestroyAPIView):
    permission_classes = [IsAuthenticated]
    queryset = BusinessAccount.global_objects.all()

    def delete(self, request, *args, **kwargs):
        try:
            business = self.get_object()
        except BusinessAccount.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=ACCOUNT_MESSAGES["business_account_not_found"],
            )

        # Validate subscription before deletion
        subscription = (
            BusinessSubscriptionPlan.objects.filter(business=business)
            .order_by("-start_date")
            .first()
        )

        # If subscription exists and it's NOT FAILED or PENDING → block deletion
        if subscription and subscription.status not in [
            SubscriptionStatusChoices.FAILED,
            SubscriptionStatusChoices.PENDING,
        ]:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=MESSAGES["business_has_subscription_plan"],
            )

        user_assigned_business = UserAssignedBusiness.global_objects.filter(
            business=business, is_owner=True
        ).first()

        if not user_assigned_business:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ACCOUNT_MESSAGES["owner_not_found_in_the_assigne_business"],
            )

        owner = user_assigned_business.user

        # Check assigned users count
        assigned_users_count = UserAssignedBusiness.global_objects.filter(
            business=business
        ).count()
        if assigned_users_count > 1:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=MESSAGES["validate_for_the_existing_users_in_the_business"],
            )

        # Perform PERMANENT delete inside a transaction
        with transaction.atomic():
            user_pref = UserPreference.objects.filter(user=owner).first()
            if user_pref:
                user_pref.hard_delete()
            wallet = Wallet.objects.filter(business=business).first()
            if wallet:
                wallet.hard_delete()
            user_assigned_business.hard_delete()
            owner.hard_delete()
            business.hard_delete()

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["business_and_associate_record_are_deleted"],
        )


class SubAdminViewSet(viewsets.ModelViewSet):
    """
    Admin's Authentication and Sub-Admin creation functionalities are handled here.
    Provides CRUD operations for the User model and adds specific endpoints for creating sub-admins.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = SubAdminCreateSerializer
    response_serializer_class = SubAdminSerializer
    queryset = User.global_objects.all()
    http_method_names = ["get", "post", "delete", "patch"]
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = SubAdminFilter
    SUB_ADMIN_ROLES = [
        UserRoleChoices.TAQABETH_ENFORCER,
        UserRoleChoices.JEWELLERY_INSPECTOR,
        UserRoleChoices.JEWELLERY_BUYER,
    ]

    def get_queryset(self):
        """Handle filtering of sub-admins based on the organization of the logged-in user."""
        if self.request.user.is_anonymous:
            return self.queryset.none()

        return self.queryset.filter(
            user_roles__role__in=self.SUB_ADMIN_ROLES,
            organization_id=self.request.user.organization_id,
        ).distinct()

    @PermissionManager(SUBADMIN_CREATE_PERMISSION)
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        organization_code = request.auth.get("organization_code")

        if serializer.is_valid():
            sub_admin = serializer.save()

            login_link = f"{settings.FRONTEND_BASE_URL}/login"

            # Send mail to the created sub-admin
            context = {
                "name": sub_admin.get_full_name(),
                "email": sub_admin.email,
                "password": request.data.get("password"),
                "role": request.data.get("role"),
                "login_link": login_link,
            }
            send_mail.delay(
                "Your Sub-admin Account Has Been Created",
                "templates/sub-admin-create.html",
                context,
                [sub_admin.email],
                organization_code=organization_code,
            )
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["sub_admin_created"],
            )

        return handle_serializer_errors(serializer)

    @PermissionManager(SUBADMIN_DELETE_PERMISSION)
    def destroy(self, request, pk=None):
        try:
            user = self.queryset.get(pk=pk)
            if not user.user_roles.filter(role__in=self.SUB_ADMIN_ROLES).exists():
                return generic_response(
                    status_code=status.HTTP_403_FORBIDDEN,
                    error_message=MESSAGES["user_not_sub_admin"],
                )

            user.delete()
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["sub_admin_deleted"],
            )
        except User.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["user_not_found"],
            )

    @PermissionManager(SUBADMIN_CHANGE_PERMISSION)
    def partial_update(self, request, *args, **kwargs):
        """Partial update of sub-admin details, including role."""
        try:
            user = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["user_not_found"],
            )

        serializer = self.serializer_class(user, data=request.data, partial=True)
        if serializer.is_valid():
            user = serializer.save()
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["user_updated"],
                data=self.response_serializer_class(user).data,
            )

        return handle_serializer_errors(serializer)

    @PermissionManager(SUBADMIN_VIEW_PERMISSION)
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.response_serializer_class(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["sub_admin_list"],
            data=response_data,
        )

    @PermissionManager(SUBADMIN_VIEW_PERMISSION)
    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.response_serializer_class(instance)
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["sub_admin_detail"],
                data=serializer.data,
            )
        except User.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["user_not_found"],
            )


class UserListAPIView(BaseBusinessListAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    queryset = User.global_objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = UserFilter

    def get_queryset(self):
        """Returns users with business roles."""
        if self.request.user.is_anonymous:
            return self.queryset.none()
        return self.queryset.filter(
            user_assigned_businesses__business__business_account_type__in=self.BUSINESS_ROLES
        )

    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data

        return generic_response(
            message=MESSAGES["users_listed"],
            data=response_data,
        )


class UserSuspensionStatusUpdateAPIView(UpdateAPIView):
    serializer_class = UserSuspensionStatusUpdateSerializer
    response_serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    queryset = User.objects.all()
    http_method_names = ["patch"]

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return self.queryset.none()

        role = self.request.auth.get("role")
        user = self.request.user

        # If the role is ADMIN, TAQABETH_ENFORCER, JEWELLERY_INSPECTOR, or JEWELLERY_BUYER,
        # return the queryset of all users within their organization.
        if role in UserRoleChoices:
            return self.queryset.filter(organization_id=user.organization_id)

        # Get business for restricted roles
        business = get_business_from_user_token(self.request, "business")
        if not business:
            return self.queryset.none()

        # Return filtered queryset for SELLER, JEWELER, INVESTOR, MANUFACTURER
        return self.queryset.filter(
            organization_id=user.organization_id,
            user_assigned_businesses__business=business,
            user_assigned_businesses__is_owner=False,
        )

    @PermissionManager(MANAGE_USER_SUSPENSION_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            user = self.get_object()
        except User.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["user_not_found"],
            )

        serializer = self.get_serializer(user, data=request.data, partial=True)
        organization_code = request.auth.get("organization_code")

        if serializer.is_valid():
            user = serializer.save()

            # Send email to user
            context = {
                "name": user.get_full_name(),
                "email": user.email,
                "support_email": settings.CONTACT_SUPPORT_EMAIL,
                "support_contact_number": settings.SUPPORT_CONTACT_NUMBER,
            }
            subject = (
                "Account has been reactivated."
                if user.is_active
                else "Account has been suspended."
            )
            template = (
                "templates/activate-user.html"
                if user.is_active
                else "templates/suspend-user.html"
            )
            send_mail.delay(
                subject,
                template,
                context,
                [user.email],
                organization_code=organization_code,
            )
            return generic_response(
                data=self.response_serializer_class(user).data,
                status_code=status.HTTP_200_OK,
                message=(
                    MESSAGES["user_reactivated"]
                    if user.is_active
                    else MESSAGES["user_suspended"]
                ),
            )
        return handle_serializer_errors(serializer)


class UserRetrieveAPIView(RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        return (
            UserUpdateSerializer if self.request.method == "PATCH" else UserSerializer
        )

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return User.objects.none()

        # Prefetch related addresses
        address_prefetch = Prefetch(
            "addresses",
            queryset=Address.global_objects.all(),
            to_attr="prefetched_addresses",
        )

        # Prefetch User -> Business relations inside BusinessAccount
        business_user_prefetch = Prefetch(
            "user_assigned_businesses",
            queryset=UserAssignedBusiness.global_objects.prefetch_related(
                Prefetch(
                    "user",
                    queryset=User.global_objects.all(),
                    to_attr="prefetched_user",
                )
            ),
            to_attr="all_user_assigned_businesses",
        )

        # Prefetch BusinessAccount details
        business_prefetch = Prefetch(
            "business",
            queryset=BusinessAccount.global_objects.prefetch_related(
                # Latest subscription plans
                Prefetch(
                    "business_subscription_plan",
                    queryset=BusinessSubscriptionPlan.global_objects.order_by(
                        "-created_at"
                    ),
                    to_attr="prefetched_subscriptions",
                ),
                Prefetch(
                    "wallets",
                    queryset=Wallet.objects.all(),
                    to_attr="prefetched_wallets",
                ),
                business_user_prefetch,
            ),
            to_attr="prefetched_business",
        )

        # Prefetch UserAssignedBusiness for top-level User
        user_business_prefetch = Prefetch(
            "user_assigned_businesses",
            queryset=UserAssignedBusiness.global_objects.prefetch_related(
                Prefetch(
                    "user",
                    queryset=User.global_objects.all(),
                    to_attr="prefetched_user",
                ),
                business_prefetch,
            ),
            to_attr="all_user_assigned_businesses",
        )

        # Final queryset
        return (
            User.global_objects.select_related("bank_account")
            .prefetch_related(
                address_prefetch,
                user_business_prefetch,
            )
            .distinct()
        )

    @PermissionManager(USER_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data, message=MESSAGES["users_details_fetched"]
            )
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["user_not_found"],
            )

    def patch(self, request, *args, **kwargs):
        try:
            user = self.get_object()
        except User.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["user_not_found"],
            )

        serializer = self.get_serializer(user, data=request.data, partial=True)

        if serializer.is_valid():
            user = serializer.save()
            updated_fields = getattr(serializer, "updated_fields", [])
            organization_code = request.auth.get("organization_code")

            # Initialize context with always-included fields
            context = {
                "full_name": user.get_full_name(),
            }

            # Determine notification title, body, and add relevant updated fields to context
            if "email" in updated_fields and "phone_number" in updated_fields:
                title = "Contact Information Updated"
                body = "Your email and phone number have been successfully updated."
                context.update(
                    {
                        "email": user.email,
                        "phone_number": str(user.phone_number),
                    }
                )
            elif "email" in updated_fields:
                title = "Email Address Updated"
                body = "Your email address has been successfully updated. If this wasn't you, please contact support immediately."
                context.update(
                    {
                        "email": user.email,
                    }
                )
            elif "phone_number" in updated_fields:
                title = "Phone Number Updated"
                body = "Your phone number has been successfully updated. If you didn't make this change, reach out to our support team right away."
                context.update(
                    {
                        "phone_number": str(user.phone_number),
                    }
                )
            else:
                title = "Profile Updated"
                body = "Your profile details have been updated successfully."

            context.update(
                {
                    "title": title,
                    "body": body,
                }
            )

            send_notifications(
                [user],
                title,
                body,
                NotificationTypes.USER_UPDATED,
                ContentType.objects.get_for_model(User),
                user.id,
            )

            send_mail.delay(
                title,
                "templates/user-update.html",
                context,
                [user.email],
                organization_code=organization_code,
            )

            return generic_response(
                status_code=status.HTTP_200_OK,
                data=UserSerializer(user).data,
                message=ACCOUNT_MESSAGES["user_updated"],
            )

        return handle_serializer_errors(serializer)


class BusinessAccountSuspensionUpdateAPIView(UpdateAPIView):
    serializer_class = BusinessAccountSuspensionSerializer
    permission_classes = [IsAuthenticated]
    queryset = BusinessAccount.global_objects.all()
    http_method_names = ["patch"]

    @PermissionManager(MANAGE_BUSINESS_ACCOUNT_SUSPENSION_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            business = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["user_not_found"],
            )

        serializer = self.get_serializer(business, data=request.data, partial=True)
        if serializer.is_valid():
            business = serializer.save()

            if business.is_suspended:
                message = MESSAGES["business_account_suspended"]
            else:
                message = MESSAGES["business_account_reactivated"]

            return generic_response(
                status_code=status.HTTP_200_OK,
                message=message,
            )
        return handle_serializer_errors(serializer)


########################################################################################
################################# Purchase Request APIs ################################
########################################################################################


class PurchaseRequestListAPIView(BaseBusinessListAPIView):
    """API view to list purchase requests within the authenticated user's organization."""

    serializer_class = PurchaseRequestDetailsSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = PurchaseRequestFilter

    def get_queryset(self):
        """Returns purchase requests belonging to the authenticated user's organization."""
        if self.request.user.is_anonymous:
            return PurchaseRequest.objects.none()

        return base_purchase_request_queryset().filter(
            organization_id=self.request.user.organization_id
        )

    @PermissionManager(ADMIN_PURCHASE_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        return self.get_paginated_response_data(
            queryset, MESSAGES["purchase_request_fetched"]
        )


class PurchaseRequestRetrieveAPIView(BaseBusinessListAPIView, RetrieveAPIView):
    """API view for admins to retrieve a specific purchase request."""

    serializer_class = PurchaseRequestDetailsSerializer
    permission_classes = [IsAuthenticated]
    queryset = base_purchase_request_queryset()

    @PermissionManager(ADMIN_PURCHASE_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data, message=MESSAGES["purchase_request_retrieved"]
            )
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=INVESTOR_MESSAGES["purchase_request_not_found"],
            )


class AdminPurchaseRequestUpdateAPIView(UpdateAPIView):
    permission_classes = [IsAuthenticated]
    queryset = base_purchase_request_queryset()
    serializer_class = PurchaseRequestUpdateSerializer
    http_method_names = ["patch"]

    def get_queryset(self):
        """Handle queryset by organization."""
        if self.request.user.is_anonymous:
            return self.queryset.none()

        user = self.request.user
        return self.queryset.filter(organization_id=user.organization_id)

    def get_object(self):
        """Retrieve the Purchase Request instance."""

        try:
            return self.get_queryset().get(id=self.kwargs.get("id"))
        except PurchaseRequest.DoesNotExist:
            raise Http404

    @PermissionManager(ADMIN_PURCHASE_REQUEST_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                error_message=INVESTOR_MESSAGES["purchase_request_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        serializer.save()

        if instance.status == PurchaseRequestStatus.COMPLETED:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["purchase_request_already_completed"],
            )

        if instance.status != PurchaseRequestStatus.APPROVED:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["purchase_request_approved_error"],
            )

        instance.status = PurchaseRequestStatus.COMPLETED
        instance.completed_at = timezone.now()
        instance.save()

        serializer = PurchaseRequestResponseSerializer(instance)

        # Fetch users and tokens for notifications
        seller_business_users = User.objects.filter(
            user_assigned_businesses__business=instance.precious_item.business,
            user_preference__notifications_enabled=True,
        )
        investor_business_users = User.objects.filter(
            user_assigned_businesses__business=instance.business,
            user_preference__notifications_enabled=True,
        )

        # Send notification to seller's
        self.send_notifications(
            seller_business_users,
            f"{instance.precious_item.name} has been received by Sooq Al Thahab.",
            f"Sooq Al Thahab has received your precious item '{instance.precious_item.material_type} - {instance.precious_item.name}'.",
            NotificationTypes.PURCHASE_REQUEST_COMPLETED,
            ContentType.objects.get_for_model(PurchaseRequest),
            instance.id,
        )

        # Send notification to investor's
        self.send_notifications(
            investor_business_users,
            f"{instance.precious_item.name} has been received by Sooq Al Thahab.",
            f"Sooq Al Thahab has received your precious item, for purchase request of '{instance.precious_item.material_type} - {instance.precious_item.name}'.",
            NotificationTypes.PURCHASE_REQUEST_COMPLETED,
            ContentType.objects.get_for_model(PurchaseRequest),
            instance.id,
        )

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["purchase_request_status_completed"],
            data=serializer.data,
        )

    def send_notifications(
        self,
        users,
        title,
        message,
        notification_type,
        content_type,
        object_id,
    ):
        """
        Sends notifications to specified users.

        This method retrieves the FCM tokens for the given users and sends push notifications asynchronously.
        Additionally, it creates in-app notification records for each user.
        """
        tokens = get_fcm_tokens_for_users(list(users))

        if not tokens:
            return

        notifications = [
            Notification(
                user=user,
                title=title,
                message=message,
                notification_type=notification_type,
                content_type=content_type,
                object_id=object_id,
            )
            for user in users
        ]
        # Bulk insert all notifications, ignoring conflicts from concurrent operations
        Notification.objects.bulk_create(notifications, ignore_conflicts=True)

        # Serialize just **one** notification (since all are identical)
        notification_data = {
            "notification_type": notification_type,
            "id": str(object_id),
        }

        # Send a bulk push notification asynchronously
        send_notification_count_to_users(users)
        send_notification.delay(tokens, title, message, notification_data)


########################################################################################
#################################### Material Item APIs ################################
########################################################################################


class MaterialItemListCreateAPIView(BaseBusinessListAPIView, ListCreateAPIView):
    """API view to list and create Material Items within the authenticated user's organization."""

    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = MaterialItemFilter

    def get_serializer_class(self):
        if self.request.method in ["POST"]:
            return MaterialItemSerializer
        return MaterialItemDetailSerializer

    def get_queryset(self):
        """Returns Material Items belonging to the authenticated user's organization."""
        if self.request.user.is_anonymous:
            return MaterialItem.objects.none()
        return MaterialItem.objects.filter(
            organization_id=self.request.user.organization_id
        )

    @PermissionManager(MATERIAL_ITEM_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        return self.get_paginated_response_data(
            queryset, MESSAGES["material_items_retrieved"]
        )

    @PermissionManager(MATERIAL_ITEM_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        """Handles Material Item creation, ensuring uniqueness within the organization.
        Only 'stone' type material items can be created.
        """
        data = request.data
        name = data.get("name")
        material_type = data.get("material_type")
        stone_origin = data.get("stone_origin")

        # Ensure only stone-type material items can be created
        if material_type.lower() != MaterialType.STONE:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["only_stone_creation_allowed"],
            )

        if not stone_origin:
            stone_origin = StoneOrigin.NATURAL

        if (
            self.get_queryset()
            .filter(name__iexact=name, stone_origin=stone_origin)
            .exists()
        ):
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["material_item_already_exists"],
            )

        serializer = self.get_serializer(data=data)
        if serializer.is_valid():
            material_item = serializer.save(
                created_by=request.user, organization_id=request.user.organization_id
            )
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["material_item_created"],
                data=MaterialItemDetailSerializer(material_item).data,
            )

        return handle_serializer_errors(serializer)


class GlobalMetalListAPIView(ListAPIView):
    queryset = GlobalMetal.objects.all()
    serializer_class = GlobalMetalSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get"]


class MaterialItemUpdateViewSet(UpdateAPIView):
    queryset = MaterialItem.objects.all()
    serializer_class = MaterialItemUpdateSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["patch"]

    def get_queryset(self):
        "Handle queryset by organization."
        if self.request.user.is_anonymous:
            return self.queryset.none()

        user = self.request.user
        return self.queryset.filter(organization_id=user.organization_id)

    def patch(self, request, *args, **kwargs):
        """Handle PATCH request to enable/disable Material Item."""

        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            if not serializer.is_valid():
                return handle_serializer_errors(serializer)

            serializer.save(updated_by=request.user)
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["material_item_updated"],
                data=serializer.data,
            )
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["material_item_not_found"],
            )


########################################################################################
#################################### Organization APIs #################################
########################################################################################


class OrganizationRetrieveUpdateViewSet(RetrieveUpdateAPIView):
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch"]
    response_serializer_class = OrganizationResponseSerializer

    @PermissionManager(ORGANIZATION_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """
        Retrieve the user's preferences.
        """
        user = request.user
        try:
            instance = self.get_queryset().get(pk=user.organization_id.id)
            serializer = self.response_serializer_class(instance)
            return generic_response(
                data=serializer.data,
                message=MESSAGES["organization_details_fetched"],
                status_code=status.HTTP_200_OK,
            )
        except Organization.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=ACCOUNT_MESSAGES["organization_not_found"],
            )

    @PermissionManager(ORGANIZATION_CHANGE_PERMISSION)
    def update(self, request, *args, **kwargs):
        """Handle Patch request to update organization taxes and fees."""
        user = request.user
        try:
            instance = self.get_queryset().get(pk=user.organization_id.id)
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            if not serializer.is_valid():
                return handle_serializer_errors(serializer)

            organization = serializer.save(updated_by=user)
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["organization_taxes_and_fees_updated"],
                data=self.response_serializer_class(organization).data,
            )
        except Organization.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=ACCOUNT_MESSAGES["organization_not_found"],
            )


class OrganizationCurrencyCreateView(ListCreateAPIView):
    queryset = OrganizationCurrency.objects.all()
    serializer_class = OrganizationCurrencySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination

    def get_queryset(self):
        """Filter organization currencies by the current user's organization."""

        if self.request.user.is_anonymous:
            return self.queryset.none()

        return OrganizationCurrency.objects.filter(
            organization_id=self.request.user.organization_id
        ).order_by("-created_at")

    @PermissionManager(ORGANIZATION_CURRENCY_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["organization_currencies_fetched"],
            data=response_data,
        )

    @PermissionManager(ORGANIZATION_CURRENCY_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        """Handle POST request to create organization currency."""

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["organization_currency_created"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)


class OrganizationCurrencyUpdateView(UpdateAPIView):
    queryset = OrganizationCurrency.objects.all()
    serializer_class = OrganizationCurrencyUpdateSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["patch"]

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return OrganizationCurrency.objects.none()

        # Extract organization_code from the authentication token
        organization_code = self.request.auth.get("organization_code")

        try:
            organization = Organization.objects.get(code=organization_code)
        except Organization.DoesNotExist:
            return self.queryset.none()

        # Return all currencies linked to this organization
        return self.queryset.filter(organization=organization)

    @PermissionManager(ORGANIZATION_CURRENCY_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                message=MESSAGES["organization_currency_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                data=serializer.data,
                message=MESSAGES["organization_currency_update"],
                status_code=status.HTTP_200_OK,
            )

        return handle_serializer_errors(serializer)


class OrganizationBankAccountCreateRetrieveUpdateAPIView(
    CreateModelMixin, RetrieveUpdateAPIView
):
    permission_classes = [IsAuthenticated]
    queryset = OrganizationBankAccount.objects.all()
    serializer_class = OrganizationBankAccountSerializer
    http_method_names = ["get", "patch", "post"]

    @PermissionManager(ORGANIZATION_BANK_ACCOUNT_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        organization = request.user.organization_id

        if OrganizationBankAccount.objects.filter(organization=organization).exists():
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["organization_bank_account_already_exists"],
            )

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["organization_bank_account_created"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)

    @PermissionManager(ORGANIZATION_BANK_ACCOUNT_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Retrieve Organization bank acount."""
        user = request.user
        try:
            instance = self.get_queryset().get(organization=user.organization_id)
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data,
                message=MESSAGES["organization_bank_account_fetched"],
                status_code=status.HTTP_200_OK,
            )
        except OrganizationBankAccount.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["organization_bank_account_not_found"],
            )

    @PermissionManager(ORGANIZATION_BANK_ACCOUNT_CHANGE_PERMISSION)
    def update(self, request, *args, **kwargs):
        """Handle Patch request to update organization bank account."""
        user = request.user
        try:
            instance = self.get_queryset().get(organization=user.organization_id)
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            if not serializer.is_valid():
                return handle_serializer_errors(serializer)

            serializer.save()
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["organization_bank_account_updated"],
                data=serializer.data,
            )
        except OrganizationBankAccount.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["organization_bank_account_not_found"],
            )


########################################################################################
#################################### Transaction APIs ##################################
########################################################################################


class TransactionListAdminAPIView(BaseBusinessListAPIView, ListAPIView):
    """Admin API to list all transactions."""

    serializer_class = TransactionResponseSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = TransactionFilter

    def get_queryset(self):
        """Retrieve transactions belonging to the request user's organization."""
        user = self.request.user
        if user.is_anonymous:
            return Transaction.objects.none()

        return (
            Transaction.global_objects.select_related(
                "from_business", "to_business", "purchase_request", "created_by"
            )
            .filter(
                created_by__organization_id=user.organization_id,
                business_subscription__isnull=True,
            )
            .order_by("-created_at")
        )

    @PermissionManager(TRANSACTION_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        return self.get_paginated_response_data(
            queryset, MESSAGES["transactions_fetched"]
        )


class TransactionRetrieveAdminAPIView(RetrieveAPIView):
    """Admin API to retrieve a specific transaction within the request user's organization."""

    serializer_class = TransactionResponseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Ensure the transaction belongs to the request user's organization."""
        user = self.request.user
        if user.is_anonymous:
            return Transaction.objects.none()

        return Transaction.global_objects.filter(
            created_by__organization_id=user.organization_id,
            business_subscription__isnull=True,
        )

    @PermissionManager(TRANSACTION_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            transaction = self.get_object()
            serializer = self.get_serializer(transaction)
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["transaction_retrieved"],
                data=serializer.data,
            )
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["transaction_not_found"],
            )


class WalletTransactionsStatusApproveRejectUpdateAPIView(UpdateAPIView):
    """API for updating transactions (PATCH)."""

    serializer_class = TransactionUpdateSerializer
    response_serializer_class = TransactionResponseSerializer
    permission_classes = [IsAuthenticated]
    queryset = Transaction.global_objects.select_related("from_business", "to_business")
    http_method_names = ["patch"]

    def get_business_owner(self, business):
        """Return the owner UserAssignedBusiness for a given business, or None."""
        if not business:
            return None
        return (
            UserAssignedBusiness.objects.filter(business=business, is_owner=True)
            .select_related("user")
            .first()
        )

    def patch(self, request, *args, **kwargs):
        """Handle PATCH requests."""
        try:
            instance = self.get_object()
        except:
            return generic_response(
                message=MESSAGES["transaction_not_found"],
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        from_owner = self.get_business_owner(instance.from_business)
        to_owner = self.get_business_owner(instance.to_business)

        if (from_owner and from_owner.user.is_deleted) or (
            to_owner and to_owner.user.is_deleted
        ):
            return generic_response(
                message=MESSAGES["restrict_to_update_transaction"],
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)

        if serializer.is_valid():
            transaction = serializer.save()

            # Send notifications to users
            # Get users associated with the business
            users_in_business = User.objects.filter(
                user_assigned_businesses__business=instance.from_business,
                user_preference__notifications_enabled=True,
            )

            message = None

            if transaction.transaction_type == TransactionType.WITHDRAWAL:
                if transaction.status == TransactionStatus.APPROVED:
                    message = MESSAGES["withdraw_request_accepted"]
                    self.send_notifications(
                        users_in_business,
                        "Withdraw request has been approved.",
                        f"Withdraw request of BHD {transaction.amount} has been approved.",
                        NotificationTypes.WITHDRAW_REQUEST_APPROVED,
                        ContentType.objects.get_for_model(Transaction),
                        instance.pk,
                    )
                    # Send invoice email to accounts for approved withdrawal transactions
                    try:
                        from sooq_althahab.billing.transaction.invoice_utils import (
                            send_withdrawal_invoice_to_accounts,
                        )

                        organization = transaction.from_business.organization_id
                        if organization:
                            logger.info(
                                f"[Admin] Sending withdrawal invoice email for transaction {transaction.id}, organization: {organization.id}"
                            )
                            send_withdrawal_invoice_to_accounts(
                                transaction, organization
                            )
                        else:
                            logger.warning(
                                f"[Admin] Organization not found for transaction {transaction.id}, cannot send invoice email"
                            )
                    except Exception as invoice_error:
                        logger.error(
                            f"[Admin] Failed to send withdrawal invoice email for transaction {transaction.id}: {str(invoice_error)}",
                            exc_info=True,
                        )
                elif transaction.status == TransactionStatus.REJECTED:
                    message = MESSAGES["withdraw_request_rejected"]
                    self.send_notifications(
                        users_in_business,
                        "Withdraw request has been rejected.",
                        f"Withdraw request of BHD {transaction.amount} has been rejected.",
                        NotificationTypes.WITHDRAW_REQUEST_REJECTED,
                        ContentType.objects.get_for_model(Transaction),
                        instance.pk,
                    )

            elif transaction.transaction_type == TransactionType.DEPOSIT:
                if transaction.status == TransactionStatus.APPROVED:
                    message = MESSAGES["deposit_request_accepted"]
                    self.send_notifications(
                        users_in_business,
                        "Deposit request has been approved.",
                        f"Deposit request of BHD {transaction.amount} has been approved.",
                        NotificationTypes.DEPOSIT_REQUEST_APPROVED,
                        ContentType.objects.get_for_model(Transaction),
                        instance.pk,
                    )
                    # Send invoice email to accounts for approved top-up transactions
                    try:
                        from sooq_althahab.billing.transaction.invoice_utils import (
                            send_topup_invoice_to_accounts,
                        )

                        organization = transaction.from_business.organization_id
                        if organization:
                            logger.info(
                                f"[Admin] Sending top-up invoice email for transaction {transaction.id}, organization: {organization.id}"
                            )
                            send_topup_invoice_to_accounts(transaction, organization)
                        else:
                            logger.warning(
                                f"[Admin] Organization not found for transaction {transaction.id}, cannot send invoice email"
                            )
                    except Exception as invoice_error:
                        logger.error(
                            f"[Admin] Failed to send top-up invoice email for transaction {transaction.id}: {str(invoice_error)}",
                            exc_info=True,
                        )
                elif transaction.status == TransactionStatus.REJECTED:
                    message = MESSAGES["deposit_request_rejected"]
                    self.send_notifications(
                        users_in_business,
                        "Deposit request has been rejected.",
                        f"Deposit request of BHD {transaction.amount} has been rejected.",
                        NotificationTypes.DEPOSIT_REQUEST_REJECTED,
                        ContentType.objects.get_for_model(Transaction),
                        instance.pk,
                    )

            return generic_response(
                message=message,
                status_code=status.HTTP_200_OK,
                data=self.response_serializer_class(transaction).data,
            )

        return handle_serializer_errors(serializer)

    def send_notifications(
        self, users, title, message, notification_type, content_type, object_id
    ):
        """
        Sends notifications to specified users.

        This method retrieves the FCM tokens for the given users and sends push notifications asynchronously.
        Additionally, it creates in-app notification records for each user.
        """

        # Get all FCM tokens for the users
        tokens = get_fcm_tokens_for_users(list(users))

        # If no valid FCM tokens found, exit early
        if not tokens:
            return

        notifications = [
            Notification(
                user=user,
                title=title,
                message=message,
                notification_type=notification_type,
                content_type=content_type,
                object_id=object_id,
            )
            for user in users
        ]
        # Bulk insert all notifications, ignoring conflicts from concurrent operations
        Notification.objects.bulk_create(notifications, ignore_conflicts=True)

        notification_data = {
            "notification_type": notification_type,
            "id": str(object_id),
        }

        # Send a bulk push notification asynchronously
        send_notification_count_to_users(users)
        send_notification.delay(tokens, title, message, notification_data)


########################################################################################
#################################### Common APIs #######################################
########################################################################################


class StoneCutShapeListCreateAPIView(ListCreateAPIView):
    """API view to create or list of Stone Cut and Shape."""

    permission_classes = [IsAuthenticated]
    serializer_class = StoneCutShapeSerializer
    queryset = StoneCutShape.objects.all()
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = StoneCutShapeFilter

    def get_queryset(self):
        "Handle queryset by organization."
        if self.request.user.is_anonymous:
            return self.queryset.none()

        user = self.request.user
        return self.queryset.filter(organization_id=user.organization_id)

    @PermissionManager(STONE_CUT_SHAPE_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_201_CREATED,
            message=MESSAGES["stone_cut_shape_fetched"],
            data=response_data,
        )

    @PermissionManager(STONE_CUT_SHAPE_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["stone_cut_shape_created"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)


class StoneCutShapeRetrieveUpdateAPIView(RetrieveUpdateAPIView):
    """API view to retrieve or update Precious Stone Cut and Shape."""

    permission_classes = [IsAuthenticated]
    serializer_class = StoneCutShapeSerializer
    queryset = StoneCutShape.objects.all()
    http_method_names = ["patch", "get"]

    @PermissionManager(STONE_CUT_SHAPE_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data,
                message=MESSAGES["stone_cut_shape_fetched"],
                status_code=status.HTTP_200_OK,
            )
        except:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["stone_cut_shape_not_found"],
            )

    @PermissionManager(STONE_CUT_SHAPE_CHANGE_PERMISSION)
    def update(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["stone_cut_shape_not_found"],
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["stone_cut_shape_updated"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)


class MetalCaratTypeListCreateAPIView(ListCreateAPIView):
    """API view to create or list Metal carat type."""

    permission_classes = [IsAuthenticated]
    serializer_class = MetalCaratTypeSerializer
    queryset = MetalCaratType.objects.all().order_by("-name")
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = MetalCaratTypeFilter

    def get_queryset(self):
        "Handle queryset by organization."
        if self.request.user.is_anonymous:
            return self.queryset.none()

        user = self.request.user
        return self.queryset.filter(organization_id=user.organization_id)

    @PermissionManager(METAL_CARAT_TYPE_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["metal_carat_type_created"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)

    @PermissionManager(METAL_CARAT_TYPE_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_201_CREATED,
            message=MESSAGES["metal_carat_type_fetched"],
            data=response_data,
        )


class MetalCaratTypeRetrieveUpdateAPIView(RetrieveUpdateAPIView):
    """API view to retrieve or update Metal carat type."""

    permission_classes = [IsAuthenticated]
    serializer_class = MetalCaratTypeSerializer
    queryset = MetalCaratType.objects.all()
    http_method_names = ["patch", "get"]

    @PermissionManager(METAL_CARAT_TYPE_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data,
                message=MESSAGES["metal_carat_type_fetched"],
                status_code=status.HTTP_200_OK,
            )
        except:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["metal_carat_type_not_found"],
            )

    @PermissionManager(METAL_CARAT_TYPE_CHANGE_PERMISSION)
    def update(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["metal_carat_type_not_found"],
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["metal_carat_type_updated"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)


class StoneClarityListCreateAPIView(ListCreateAPIView):
    """API view to create or list Stone clarity."""

    permission_classes = [IsAuthenticated]
    serializer_class = StoneClaritySerializer
    queryset = StoneClarity.objects.all()
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = StoneClarityFilter

    def get_queryset(self):
        "Handle queryset by organization."
        if self.request.user.is_anonymous:
            return self.queryset.none()

        user = self.request.user
        return self.queryset.filter(organization_id=user.organization_id)

    @PermissionManager(STONE_CLARITY_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["stone_clarity_created"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)

    @PermissionManager(STONE_CLARITY_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["stone_clarity_fetched"],
            data=response_data,
        )


class StoneClarityRetrieveUpdateAPIView(RetrieveUpdateAPIView):
    """API view to retrieve or update Stone clarity."""

    permission_classes = [IsAuthenticated]
    serializer_class = StoneClaritySerializer
    queryset = StoneClarity.objects.all()
    http_method_names = ["patch", "get"]

    @PermissionManager(STONE_CLARITY_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data,
                message=MESSAGES["stone_clarity_fetched"],
                status_code=status.HTTP_200_OK,
            )
        except:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["stone_clarity_not_found"],
            )

    @PermissionManager(STONE_CLARITY_CHANGE_PERMISSION)
    def update(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["stone_clarity_not_found"],
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["stone_clarity_updated"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)


class JewelryProductTypeListCreateAPIView(ListCreateAPIView):
    """API view to create or list jewelry product type."""

    permission_classes = [IsAuthenticated]
    serializer_class = JewelryProductTypeSerializer
    queryset = JewelryProductType.objects.all()
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = JewelryProductTypeFilter

    def get_queryset(self):
        "Handle queryset by organization."
        if self.request.user.is_anonymous:
            return self.queryset.none()

        user = self.request.user
        return self.queryset.filter(organization_id=user.organization_id)

    @PermissionManager(JEWELRY_PRODUCT_TYPE_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["jewelry_product_type_created"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)

    @PermissionManager(JEWELRY_PRODUCT_TYPE_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_201_CREATED,
            message=MESSAGES["jewelry_product_type_fetched"],
            data=response_data,
        )


class JewelryProductTypeRetrieveUpdateAPIView(RetrieveUpdateAPIView):
    """API view to retrieve or update jewelry product type."""

    permission_classes = [IsAuthenticated]
    serializer_class = JewelryProductTypeSerializer
    queryset = JewelryProductType.objects.all()
    http_method_names = ["patch", "get"]

    @PermissionManager(JEWELRY_PRODUCT_TYPE_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data,
                message=MESSAGES["jewelry_product_type_fetched"],
                status_code=status.HTTP_200_OK,
            )
        except:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["jewelry_product_type_not_found"],
            )

    @PermissionManager(JEWELRY_PRODUCT_TYPE_CHANGE_PERMISSION)
    def update(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["jewelry_product_type_not_found"],
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["jewelry_product_type_updated"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)


class JewelryProductColorListCreateAPIView(ListCreateAPIView):
    """API view to create or list jewelry product color."""

    permission_classes = [IsAuthenticated]
    serializer_class = JewelryProductColorSerializer
    queryset = JewelryProductColor.objects.all()
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = JewelryProductColorFilter

    def get_queryset(self):
        "Handle queryset by organization."
        if self.request.user.is_anonymous:
            return self.queryset.none()

        user = self.request.user
        return self.queryset.filter(organization_id=user.organization_id)

    @PermissionManager(JEWELRY_PRODUCT_COLOR_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["jewelry_product_color_created"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)

    @PermissionManager(JEWELRY_PRODUCT_COLOR_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["jewelry_product_color_fetched"],
            data=response_data,
        )


class JewelryProductColorRetrieveUpdateAPIView(RetrieveUpdateAPIView):
    """API view to retrieve or update jewelry product color."""

    permission_classes = [IsAuthenticated]
    serializer_class = JewelryProductColorSerializer
    queryset = JewelryProductColor.objects.all()
    http_method_names = ["patch", "get"]

    @PermissionManager(JEWELRY_PRODUCT_COLOR_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data,
                message=MESSAGES["jewelry_product_color_fetched"],
                status_code=status.HTTP_200_OK,
            )
        except:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["jewelry_product_color_not_found"],
            )

    @PermissionManager(JEWELRY_PRODUCT_COLOR_CHANGE_PERMISSION)
    def update(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["jewelry_product_color_not_found"],
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["jewelry_product_color_updated"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)


class PreciousItemAttributesAPIView(APIView):
    """API to fetch master data with optional search on specific model by name."""

    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Fetch master data (cut shapes, carats, colors, etc.). "
        "Use `search_field` and `search_value` to filter a specific model by `name`.",
        manual_parameters=[
            openapi.Parameter(
                "search_field",
                openapi.IN_QUERY,
                description="Identifier of the model to search (e.g., 'stone_cut_shapes', 'metal_carat_types', "
                "'material_items', 'jewelry_product_types', 'jewelry_product_colors', 'musharakah_duration_choices', 'stone_clarity')",
                type=openapi.TYPE_STRING,
            ),
            openapi.Parameter(
                "search_value",
                openapi.IN_QUERY,
                description="Text to search within the 'name' field of the selected `search_field` model.",
                type=openapi.TYPE_STRING,
            ),
        ],
        responses={200: PreciousItemAttributes},
    )
    @PermissionManager(PRECIOUS_ITEM_ATTRIBUTES_VIEW_PERMISSION)
    def get(self, request):
        organization_id = request.user.organization_id
        search_field = request.query_params.get("search_field")
        search_value = request.query_params.get("search_value")

        # Map field name to actual model queryset
        model_mapping = {
            "stone_cut_shapes": StoneCutShape,
            "metal_carat_types": MetalCaratType,
            "material_items": MaterialItem,
            "jewelry_product_types": JewelryProductType,
            "jewelry_product_colors": JewelryProductColor,
            "musharakah_duration_choices": MusharakahDurationChoices,
            "stone_clarity": StoneClarity,
        }

        combined_data = {}

        for key, model in model_mapping.items():
            queryset = model.objects.filter(organization_id=organization_id)

            if key == search_field and search_value:
                queryset = queryset.filter(name__icontains=search_value)

            # Apply ordering by name for metal carat types
            if key == "metal_carat_types":
                queryset = queryset.order_by("-name")

            combined_data[key] = queryset

        serializer = PreciousItemAttributes(combined_data)

        return generic_response(
            data=serializer.data,
            message=MESSAGES["data_fetched"],
            status_code=status.HTTP_200_OK,
        )


class MusharakahDurationChoiceListCreateAPIView(ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MusharakahDurationChoiceSerializer
    queryset = MusharakahDurationChoices.objects.all()
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = MusharakahDurationChoicesFilter

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return self.queryset.none()
        return self.queryset.filter(organization_id=user.organization_id)

    @PermissionManager(MUSHARAKAH_DURATION_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["musharakah_duration_created"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)

    @PermissionManager(MUSHARAKAH_DURATION_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["musharakah_duration_fetched"],
            data=response_data,
        )


class MusharakahDurationChoiceRetrieveUpdateAPIView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MusharakahDurationChoiceSerializer
    queryset = MusharakahDurationChoices.objects.all()
    http_method_names = ["get", "patch"]

    @PermissionManager(MUSHARAKAH_DURATION_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data,
                message=MESSAGES["musharakah_duration_fetched"],
                status_code=status.HTTP_200_OK,
            )
        except:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["musharakah_duration_not_found"],
            )

    @PermissionManager(MUSHARAKAH_DURATION_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["musharakah_duration_not_found"],
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["musharakah_duration_updated"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)


########################################################################################
#################################### Pool APIs #########################################
########################################################################################


class BasePoolView:
    permission_classes = [IsAuthenticated]
    queryset = Pool.objects.all()

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return self.queryset.none()
        return self.queryset.filter(organization_id=user.organization_id)


class PoolListCreateAPIView(BasePoolView, ListCreateAPIView):
    """API view to list and create pools."""

    serializer_class = PoolCreateSerializer
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = PoolFilter
    response_serializer_class = PoolResponseSerializer

    def get_serializer_class(self):
        if self.request.method in ["POST"]:
            return self.serializer_class
        return self.response_serializer_class

    @PermissionManager(POOL_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["pool_fetched"],
            data=self.get_paginated_response(serializer.data).data,
        )

    @PermissionManager(POOL_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            pool = serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["pool_created"],
                data=self.get_serializer(pool).data,
            )
        return handle_serializer_errors(serializer)


class PoolRetrieveUpdateAPIView(BasePoolView, RetrieveUpdateAPIView):
    """API view to retrieve and update pool details."""

    serializer_class = PoolUpdateSerializer
    http_method_names = ["get", "patch"]
    response_serializer_class = PoolDetailsSerializer

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return self.serializer_class
        return self.response_serializer_class

    @PermissionManager(POOL_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["pool_not_found"],
            )

        serializer = self.get_serializer(instance)
        return generic_response(
            data=serializer.data,
            message=MESSAGES["pool_fetched"],
            status_code=status.HTTP_200_OK,
        )

    def _check_and_update_pool_status(
        self, instance, serializer, participation_duration=None, target=None
    ):
        """
        Helper method to check and update pool status based on fulfillment and participation date.

        Args:
            instance: The Pool instance
            serializer: The serializer instance
            participation_duration: New participation duration (if being updated)
            target: New target (if being updated)
        """
        if instance.status == PoolStatus.SETTLED:
            return  # Don't update status for settled pools

        # Apply target update to instance in memory if target is being updated
        if target is not None:
            instance.target = target

        # Calculate the participation duration date
        new_participation_date = None
        if instance.created_at:
            duration = (
                participation_duration
                if participation_duration is not None
                else instance.participation_duration
            )
            if duration:
                new_participation_date = instance.created_at + timedelta(
                    days=int(duration)
                )

        # Check if pool target is fulfilled (remaining target is zero)
        remaining_target = instance.remaining_target
        is_fulfilled = False

        if not instance.musharakah_contract_request:
            # For pools without musharakah_contract_request
            total_remaining = remaining_target.get("total_remaining", Decimal("0"))
            if total_remaining <= 0:
                is_fulfilled = True
        else:
            # For pools with musharakah_contract_request
            # Check if all metal and stone requirements are fulfilled
            metal_requirements = remaining_target.get("metal", {})
            stone_requirements = remaining_target.get("stone", {})

            # Check all metal requirements are zero or less
            all_metal_fulfilled = True
            for item_name, carats in metal_requirements.items():
                for carat, remaining in carats.items():
                    if remaining > 0:
                        all_metal_fulfilled = False
                        break
                if not all_metal_fulfilled:
                    break

            # Check all stone requirements are zero or less
            all_stone_fulfilled = True
            for item_name, shapes in stone_requirements.items():
                for shape, weights in shapes.items():
                    for weight, remaining in weights.items():
                        if remaining > 0:
                            all_stone_fulfilled = False
                            break
                    if not all_stone_fulfilled:
                        break
                if not all_stone_fulfilled:
                    break

            if all_metal_fulfilled and all_stone_fulfilled:
                is_fulfilled = True

        # Determine pool status based on fulfillment and date
        # Pool should be CLOSED if:
        #   1. Pool target is fulfilled, OR
        #   2. Participation date has passed
        # Pool should be OPEN if:
        #   1. Pool target is NOT fulfilled AND participation date is in the future
        if is_fulfilled:
            # Pool is fulfilled, so it should be CLOSED
            serializer.validated_data["status"] = PoolStatus.CLOSED
        elif new_participation_date:
            # Pool is not fulfilled, check the date
            if new_participation_date > timezone.now():
                # Date is in the future, pool should be OPEN
                serializer.validated_data["status"] = PoolStatus.OPEN
            else:
                # Date has passed, pool should be CLOSED
                serializer.validated_data["status"] = PoolStatus.CLOSED
        else:
            # If no participation date is set but pool is not fulfilled, keep it OPEN
            # (This handles edge cases where participation_duration might be None)
            serializer.validated_data["status"] = PoolStatus.OPEN

    @PermissionManager(POOL_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["pool_not_found"],
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            # Check if participation_duration or target is being updated
            participation_duration = request.data.get("participation_duration")
            target = request.data.get("target")

            # Check and update status if participation_duration or target is being updated
            if participation_duration is not None or target is not None:
                self._check_and_update_pool_status(
                    instance, serializer, participation_duration, target
                )

            serializer.save()

            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["pool_updated"],
                data=serializer.data,
            )

        return handle_serializer_errors(serializer)


class PoolContributionUpdateAPIView(UpdateAPIView):
    queryset = PoolContribution.objects.all()
    serializer_class = PoolContributionUpdateSerializer
    permission_classes = [IsAuthenticated]

    def _is_pool_fulfilled(self, remaining_target):
        """Determines if the pool's contribution target has been fulfilled."""
        if "total_remaining" in remaining_target:
            return remaining_target["total_remaining"] <= 0

        # For musharakah pools, check if all metal and stone requirements are fulfilled
        metal_target = remaining_target.get("metal", {})
        stone_target = remaining_target.get("stone", {})

        metal_fulfilled = all(
            remaining_weight <= 0
            for item_dict in metal_target.values()
            for remaining_weight in item_dict.values()
        )

        stone_fulfilled = all(
            remaining_quantity <= 0
            for shape_dicts in stone_target.values()
            for weight_dict in shape_dicts.values()
            for remaining_quantity in weight_dict.values()
        )

        return metal_fulfilled and stone_fulfilled

    def _get_remaining_weight(self, remaining_target):
        """
        Extract remaining weight from remaining_target.
        Returns Decimal representing remaining weight, or None if pool is fulfilled.
        """
        from decimal import Decimal

        if "total_remaining" in remaining_target:
            remaining = remaining_target["total_remaining"]
            return remaining if remaining > 0 else None

        # For musharakah pools, calculate total remaining
        metal_target = remaining_target.get("metal", {})
        stone_target = remaining_target.get("stone", {})

        total_remaining = Decimal("0.00")

        # Sum all metal remaining weights
        for item_dict in metal_target.values():
            for remaining_weight in item_dict.values():
                if remaining_weight > 0:
                    total_remaining += Decimal(str(remaining_weight))

        # Sum all stone remaining quantities
        for shape_dicts in stone_target.values():
            for weight_dict in shape_dicts.values():
                for remaining_quantity in weight_dict.values():
                    if remaining_quantity > 0:
                        total_remaining += Decimal(str(remaining_quantity))

        return total_remaining if total_remaining > 0 else None

    def _notify_investors_of_pool_opportunity(self, pool, remaining_target):
        """
        Send notifications to all investors in the organization about pool opportunity.

        Only sends notification if:
        1. Pool has remaining weight > 0
        2. Pool status is OPEN
        3. NO pending contributions exist for this pool (all decisions are made)

        This ensures notifications are only sent when the pool is truly available
        for new contributions, not while admin is still reviewing pending ones.
        """
        from decimal import Decimal

        from sooq_althahab.enums.account import UserRoleBusinessChoices
        from sooq_althahab.enums.jeweler import RequestStatus

        # Get remaining weight
        remaining_weight = self._get_remaining_weight(remaining_target)

        # Only send notification if there's remaining weight
        if remaining_weight is None or remaining_weight <= 0:
            return

        # Check if pool is still OPEN
        if pool.status != PoolStatus.OPEN:
            return

        # Check if there are any pending contributions for this pool
        # If there are pending contributions, don't notify yet (admin might approve them)
        # This ensures notification is ONLY sent on the LAST approval/rejection
        # when all contributions have been processed (approved or rejected)
        pending_contributions = PoolContribution.objects.filter(
            pool=pool,
            status=RequestStatus.PENDING,
        )

        if pending_contributions.exists():
            # There are still pending contributions - don't notify yet
            # Admin might approve them and fill the pool
            # This notification will be sent only when the LAST pending contribution is processed
            return

        try:
            # Get all investor businesses in the organization (excluding soft-deleted)
            investor_businesses = BusinessAccount.global_objects.filter(
                organization_id=pool.organization_id,
                business_account_type=UserRoleBusinessChoices.INVESTOR,
            )

            # Get all users assigned to investor businesses with notifications enabled
            investor_users = User.objects.filter(
                user_assigned_businesses__business__in=investor_businesses,
                user_preference__notifications_enabled=True,
            ).distinct()

            if not investor_users.exists():
                return

            # Format remaining weight for display
            remaining_weight_str = f"{remaining_weight:.2f}".rstrip("0").rstrip(".")

            # Send notification to all investors
            send_notifications(
                investor_users,
                f"Pool Opportunity Available - {pool.name}",
                f"Pool '{pool.name}' has {remaining_weight_str}g remaining. Contribute now to complete the pool!",
                notification_type=NotificationTypes.POOL_OPPORTUNITY_AVAILABLE,
                content_type=ContentType.objects.get_for_model(Pool),
                object_id=pool.pk,
            )
        except Exception as e:
            # Log error but don't fail the request if notification sending fails
            logger = logging.getLogger(__name__)
            logger.error(
                f"Failed to send pool opportunity notification "
                f"(pool: {pool.pk}, remaining_weight: {remaining_weight}): {e}",
                exc_info=True,
            )

    @PermissionManager(POOL_CHANGE_PERMISSION)
    def update(self, request, *args, **kwargs):
        fund_status = request.data.get("fund_status")
        partial = kwargs.pop("partial", True)
        instance = self.get_object()
        old_status = instance.status
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        updated_instance = serializer.save()

        # Refresh pool from database to get latest data
        pool = Pool.objects.get(pk=updated_instance.pool.pk)

        # Check if status changed to approved or rejected
        status_changed_to_approved = (
            old_status != RequestStatus.ADMIN_APPROVED
            and updated_instance.status == RequestStatus.ADMIN_APPROVED
        )
        status_changed_to_rejected = (
            old_status != RequestStatus.REJECTED
            and updated_instance.status == RequestStatus.REJECTED
        )

        # If contribution was approved or rejected, check if pool target is now fulfilled
        if status_changed_to_approved or status_changed_to_rejected:
            # Refresh pool again to ensure we have latest contributions
            pool.refresh_from_db()
            remaining_target = pool.remaining_target

            if (
                self._is_pool_fulfilled(remaining_target)
                and pool.status == PoolStatus.OPEN
            ):
                # Close the pool as target is reached with approved contributions
                pool.status = PoolStatus.CLOSED
                pool.save()
            elif pool.status == PoolStatus.OPEN:
                # Pool is still open and has remaining weight
                # Only notify if this is the LAST approval/rejection (no pending contributions)
                # This ensures notification is sent only once when all decisions are made
                self._notify_investors_of_pool_opportunity(pool, remaining_target)

        # Also check if pool is already closed and reject any pending contributions
        # This handles cases where pool was closed previously or contributions were created after closure
        pool.refresh_from_db()
        if pool.status == PoolStatus.CLOSED:
            # Reject all pending contributions since pool is closed
            pending_contributions = (
                PoolContribution.objects.filter(
                    pool=pool,
                    status=RequestStatus.PENDING,
                )
                .exclude(id=updated_instance.id)
                .select_related("participant")
            )

            if pending_contributions.exists():
                # Get all participants whose contributions will be rejected
                rejected_participants = [
                    contribution.participant for contribution in pending_contributions
                ]

                # Get contribution IDs before updating (since update() doesn't refresh objects)
                contribution_ids = list(
                    pending_contributions.values_list("id", flat=True)
                )

                # Update status to rejected
                pending_contributions.update(status=RequestStatus.REJECTED)

                # Also reject all asset contributions associated with these rejected pool contributions
                AssetContribution.objects.filter(
                    pool_contributor_id__in=contribution_ids,
                    status__in=[
                        AssetContributionStatus.PENDING,
                        AssetContributionStatus.ADMIN_APPROVED,
                    ],
                ).update(status=AssetContributionStatus.REJECTED)

                # Note: We don't need to clear pool FK here because these are pending contributions
                # that were never approved, so their units were never linked to the pool

                # Send notifications to all users whose contributions were automatically rejected
                for participant in rejected_participants:
                    participant_users = User.objects.filter(
                        user_assigned_businesses__business_id=participant.id,
                        user_preference__notifications_enabled=True,
                    ).distinct()

                    if participant_users.exists():
                        try:
                            send_notifications(
                                participant_users,
                                "Pool Contribution Rejected - Pool Closed",
                                f"Your contribution for pool '{pool.name}' has been rejected because the pool target has been reached and the pool is now closed.",
                                notification_type=NotificationTypes.POOL_CONTRIBUTION_REJECTED,
                                content_type=ContentType.objects.get_for_model(Pool),
                                object_id=pool.pk,
                            )
                        except Exception as e:
                            logger = logging.getLogger(__name__)
                            logger.error(
                                f"Failed to send notification for auto-rejected contribution "
                                f"(participant: {participant.id}, pool: {pool.pk}): {e}",
                                exc_info=True,
                            )

        # Fix: Use business_id instead of business_id__in with a single ID
        investor_business_users = User.objects.filter(
            user_assigned_businesses__business_id=updated_instance.participant.id,
            user_preference__notifications_enabled=True,
        ).distinct()

        # If pool contribution was rejected (manually or automatically), also reject associated asset contributions
        if updated_instance.status == RequestStatus.REJECTED:
            AssetContribution.objects.filter(
                pool_contributor=updated_instance,
                status__in=[
                    AssetContributionStatus.PENDING,
                    AssetContributionStatus.ADMIN_APPROVED,
                ],
            ).update(status=AssetContributionStatus.REJECTED)

        title = None
        if updated_instance.status == RequestStatus.ADMIN_APPROVED:
            title = "Your contribution for pool has been approved."
            body = f"Your contribution for pool '{pool.name}' has been approved by Sooq Al Thahab."
            message = MESSAGES["pool_contributor_approved"]
            notification_type = NotificationTypes.POOL_CONTRIBUTION_APPROVED
        elif updated_instance.status == RequestStatus.REJECTED:
            title = "Your contribution for pool has been rejected."
            body = f"Your contribution for pool '{pool.name}' has been rejected by Sooq Al Thahab."
            message = MESSAGES["pool_contributor_rejected"]
            notification_type = NotificationTypes.POOL_CONTRIBUTION_REJECTED
        elif fund_status:
            message = MESSAGES["fund_status_updated"]
        else:
            message = MESSAGES["serial_number_added"]
        if title:
            try:
                send_notifications(
                    investor_business_users,
                    title,
                    body,
                    notification_type=notification_type,
                    content_type=ContentType.objects.get_for_model(Pool),
                    object_id=pool.pk,
                )
            except Exception as e:
                # Log error but don't fail the request if notification sending fails
                # This ensures the approval/rejection still succeeds even if notifications fail
                logger = logging.getLogger(__name__)
                logger.error(
                    f"Failed to send notifications for pool contribution {updated_instance.id}: {e}",
                    exc_info=True,
                )

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=message,
            data=serializer.data,
        )


########################################################################################
########################## Musharakah Contract Request APIs #############################
########################################################################################


class BaseMusharakahContractRequestView:
    permission_classes = [IsAuthenticated]
    serializer_class = MusharakahContractRequestSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return MusharakahContractRequest.objects.none()
        return (
            MusharakahContractRequest.objects.filter(
                organization_id=user.organization_id
            )
            .select_related(
                "jeweler",
                "investor",
                "duration_in_days",
                "action_by",
            )
            .prefetch_related(
                "asset_contributions",
                "musharakah_contract_renewals",
            )
        )


class MusharakahContractRequestListAPIView(
    BaseMusharakahContractRequestView, ListAPIView
):
    """List all Musharakah contract requests for the user's organization."""

    pagination_class = CommonPagination
    filter_backends = (DjangoFilterBackend,)
    filterset_class = MusharakahContractRequestFilter

    @PermissionManager(MUSHARAKAH_CONTRACT_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset().filter(pools__isnull=True))
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return generic_response(
            data=self.get_paginated_response(serializer.data).data,
            message=JEWELER_MESSAGES["musharakah_contract_request_fetched"],
            status_code=status.HTTP_200_OK,
        )


class MusharakahContractRequestRetrieveAPIView(
    BaseMusharakahContractRequestView, RetrieveAPIView
):
    """Retrieve details of a specific Musharakah contract request."""

    @PermissionManager(MUSHARAKAH_CONTRACT_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=JEWELER_MESSAGES["musharakah_contract_request_not_found"],
            )

        serializer = self.get_serializer(instance)
        return generic_response(
            data=serializer.data,
            message=JEWELER_MESSAGES["musharakah_contract_request_fetched"],
            status_code=status.HTTP_200_OK,
        )


class MusharakahContractRequestPreApprovalAPIView(
    BaseMusharakahContractRequestView, UpdateAPIView
):
    """
    First layer approval: Initial review and approval of Musharakah contract request.
    After this approval, users can see their request is approved and waiting for final review.
    """

    serializer_class = MusharakahContractRequestPreApprovalSerializer
    http_method_names = ["patch"]

    @PermissionManager(MUSHARAKAH_CONTRACT_REQUEST_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        data = request.data
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=JEWELER_MESSAGES["musharakah_contract_request_not_found"],
            )

        serializer = self.get_serializer(instance, data=data, partial=True)
        if serializer.is_valid():
            musharakah_contract_request = serializer.save()

            # Get Jeweler and investor owner
            jeweler_business_owner = UserAssignedBusiness.objects.filter(
                business=musharakah_contract_request.jeweler, is_owner=True
            ).first()
            investor_business_owner = UserAssignedBusiness.objects.filter(
                business=musharakah_contract_request.investor, is_owner=True
            ).first()

            # Get Jeweler and Investor business users
            jeweler_business_users = User.objects.filter(
                user_assigned_businesses__business=musharakah_contract_request.jeweler,
                user_preference__notifications_enabled=True,
            )
            investor_business_users = User.objects.filter(
                user_assigned_businesses__business=musharakah_contract_request.investor,
                user_preference__notifications_enabled=True,
            )

            # If user user_type is business then pass business name else user fullname
            if jeweler_business_owner.user.user_type == UserType.BUSINESS:
                jeweler_name = jeweler_business_owner.business.name
            else:
                jeweler_name = jeweler_business_owner.user.fullname

            if investor_business_owner.user.user_type == UserType.BUSINESS:
                investor_name = investor_business_owner.business.name
            else:
                investor_name = investor_business_owner.user.fullname

            if data.get("status") == RequestStatus.ADMIN_APPROVED:
                message = MESSAGES.get(
                    "musharakah_contract_request_admin_approved",
                    "Musharakah contract request has been initially approved successfully.",
                )

                send_notifications(
                    list(jeweler_business_users) + list(investor_business_users),
                    "Musharakah Contract Admin Approval Completed",
                    f"The Musharakah contract between {jeweler_name} and {investor_name} has successfully passed the admin verification stage. The contract is now awaiting final approval, which includes the verification of all contributed materials by Sooq Al Thahab.",
                    NotificationTypes.MUSHARAKAH_CONTRACT_REQUEST_APPROVED,
                    ContentType.objects.get_for_model(MusharakahContractRequest),
                    musharakah_contract_request.pk,
                )
            else:
                message = MESSAGES["musharakah_contract_request_rejected"]

                # Reject all asset contributions for this musharakah contract request
                # This returns the assets to the investor's available assets list
                asset_contributions = AssetContribution.objects.filter(
                    musharakah_contract_request=musharakah_contract_request,
                    production_payment__isnull=True,
                    status__in=[
                        AssetContributionStatus.PENDING,
                        AssetContributionStatus.ADMIN_APPROVED,
                        AssetContributionStatus.APPROVED,
                    ],
                )
                asset_contributions.update(status=AssetContributionStatus.REJECTED)

                # Clear musharakah_contract FK from all precious item units linked to this contract
                # This releases the units so they can be used again (e.g., in sale requests or pools)
                PreciousItemUnit.objects.filter(
                    musharakah_contract=musharakah_contract_request
                ).update(musharakah_contract=None)

                send_notifications(
                    list(jeweler_business_users) + list(investor_business_users),
                    "Musharakah Contract Admin Review Rejected",
                    f"The Musharakah contract between {jeweler_name} and {investor_name} has been rejected by Sooq Al Thahab.",
                    NotificationTypes.MUSHARAKAH_CONTRACT_REQUEST_REJECTED,
                    ContentType.objects.get_for_model(MusharakahContractRequest),
                    musharakah_contract_request.pk,
                )

            return generic_response(
                status_code=status.HTTP_200_OK,
                message=message,
                data=serializer.data,
            )

        return handle_serializer_errors(serializer)


class MusharakahContractRequestStatusUpdateAPIView(
    BaseMusharakahContractRequestView, UpdateAPIView
):
    """
    Second layer approval: Final approval after reviewing all contributed materials.
    This reviews all materials contributed by the investor and gives final approval.
    Requires admin-approval before this step.
    """

    serializer_class = MusharakahContractRequestStatusUpdateSerializer
    http_method_names = ["patch"]

    @PermissionManager(MUSHARAKAH_CONTRACT_REQUEST_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        data = request.data
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=JEWELER_MESSAGES["musharakah_contract_request_not_found"],
            )

        serializer = self.get_serializer(instance, data=data, partial=True)
        if serializer.is_valid():
            musharakah_contract_request = serializer.save()

            # Send notifiction
            # Get Jeweler and investor owner
            jeweler_business_owner = UserAssignedBusiness.objects.filter(
                business=musharakah_contract_request.jeweler, is_owner=True
            ).first()
            investor_business_owner = UserAssignedBusiness.objects.filter(
                business=musharakah_contract_request.investor, is_owner=True
            ).first()

            # Get Jeweler and Investor business users
            jeweler_business_users = User.objects.filter(
                user_assigned_businesses__business=musharakah_contract_request.jeweler,
                user_preference__notifications_enabled=True,
            )
            investor_business_users = User.objects.filter(
                user_assigned_businesses__business=musharakah_contract_request.investor,
                user_preference__notifications_enabled=True,
            )

            # If user user_type is business then pass business name else user fullname
            if jeweler_business_owner.user.user_type == UserType.BUSINESS:
                jeweler_name = jeweler_business_owner.business.name
            else:
                jeweler_name = jeweler_business_owner.user.fullname

            if investor_business_owner.user.user_type == UserType.BUSINESS:
                investor_name = investor_business_owner.business.name
            else:
                investor_name = investor_business_owner.user.fullname

            if data.get("status") == RequestStatus.APPROVED:
                message = MESSAGES["musharakah_contract_request_approved"]

                send_notifications(
                    list(jeweler_business_users) + list(investor_business_users),
                    "Musharakah Contract assets contribution has been approved by Sooq Al Thahab",
                    f"The Musharakah contract between {jeweler_name} and {investor_name} has been approved by Sooq Al Thahab. All contributed materials have been verified and accepted. The contract is now active and you may proceed with the partnership.",
                    NotificationTypes.MUSHARAKAH_CONTRACT_REQUEST_APPROVED,
                    ContentType.objects.get_for_model(MusharakahContractRequest),
                    musharakah_contract_request.pk,
                )
            else:
                message = MESSAGES["musharakah_contract_request_rejected"]

                # Reject all asset contributions for this musharakah contract request
                # This returns the assets to the investor's available assets list
                asset_contributions = AssetContribution.objects.filter(
                    musharakah_contract_request=musharakah_contract_request,
                    production_payment__isnull=True,
                    status__in=[
                        AssetContributionStatus.PENDING,
                        AssetContributionStatus.ADMIN_APPROVED,
                        AssetContributionStatus.APPROVED,
                    ],
                )
                asset_contributions.update(status=AssetContributionStatus.REJECTED)

                # Clear musharakah_contract FK from all precious item units linked to this contract
                # This releases the units so they can be used again (e.g., in sale requests or pools)
                PreciousItemUnit.objects.filter(
                    musharakah_contract=musharakah_contract_request
                ).update(musharakah_contract=None)

                send_notifications(
                    list(jeweler_business_users) + list(investor_business_users),
                    "Musharakah contract has been rejected by Sooq Al Thahab",
                    f"The Musharakah contract between {jeweler_name} and {investor_name} has been rejected by Sooq Al Thahab.",
                    NotificationTypes.MUSHARAKAH_CONTRACT_REQUEST_REJECTED,
                    ContentType.objects.get_for_model(MusharakahContractRequest),
                    musharakah_contract_request.pk,
                )

            return generic_response(
                status_code=status.HTTP_200_OK,
                message=message,
                data=serializer.data,
            )

        return handle_serializer_errors(serializer)


class MusharakahContractRequestTerminationUpdateAPIView(
    BaseMusharakahContractRequestView, UpdateAPIView
):
    """Update a status of Musharakah contract request."""

    serializer_class = MusharakahContractRequestTerminationUpdateSerializer
    http_method_names = ["patch"]

    @PermissionManager(MUSHARAKAH_CONTRACT_REQUEST_TERMINATE_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        """
        Partially update a Musharakah contract request and handle termination flow.
        - Updates contract termination status.
        - Suspends impacted party's business account.
        - Sends notifications to all related business users.
        - Sends suspension email to the impacted business owner.
        """
        data = request.data
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=JEWELER_MESSAGES["musharakah_contract_request_not_found"],
            )

        serializer = self.get_serializer(instance, data=data, partial=True)
        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        musharakah_contract_request = serializer.save()
        impacted_party = musharakah_contract_request.impacted_party

        # --- Business Owners (Jeweler & Investor) ---
        jeweler_owner = (
            UserAssignedBusiness.objects.filter(
                business=musharakah_contract_request.jeweler, is_owner=True
            )
            .select_related("user", "business")
            .first()
        )

        investor_owner = (
            UserAssignedBusiness.objects.filter(
                business=musharakah_contract_request.investor, is_owner=True
            )
            .select_related("user", "business")
            .first()
        )

        if not jeweler_owner or not investor_owner:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["business_owners_not_found"],
            )

        # --- Impacted Party Owner Details ---
        if impacted_party == ImpactedParties.INVESTOR:
            impacted_owner = investor_owner
        else:
            impacted_owner = jeweler_owner

        impacted_business = impacted_owner.business
        impacted_owner_name = impacted_owner.user.fullname
        impacted_owner_email = impacted_owner.user.email

        # --- Collect Business Users with Notifications Enabled ---
        jeweler_users = User.objects.filter(
            user_assigned_businesses__business=musharakah_contract_request.jeweler,
            user_preference__notifications_enabled=True,
        )
        investor_users = User.objects.filter(
            user_assigned_businesses__business=musharakah_contract_request.investor,
            user_preference__notifications_enabled=True,
        )

        # --- Business Display Names ---
        jeweler_name = (
            jeweler_owner.business.name
            if jeweler_owner.user.user_type == UserType.BUSINESS
            else jeweler_owner.user.fullname
        )
        investor_name = (
            investor_owner.business.name
            if investor_owner.user.user_type == UserType.BUSINESS
            else investor_owner.user.fullname
        )

        # --- Send In-App Notifications ---
        send_notifications(
            list(jeweler_users) + list(investor_users),
            "Musharakah Contract terminated by Sooq Al Thahab",
            f"The Musharakah contract between {jeweler_name} and {investor_name} has been terminated by Sooq Al Thahab.",
            NotificationTypes.MUSHARAKAH_CONTRACT_TERMINATED,
            ContentType.objects.get_for_model(MusharakahContractRequest),
            musharakah_contract_request.pk,
        )

        # --- Send Email to Impacted Party Owner ---
        context = {
            "name": impacted_owner_name,
            "email": impacted_owner_email,
            "support_email": settings.CONTACT_SUPPORT_EMAIL,
            "support_contact_number": settings.SUPPORT_CONTACT_NUMBER,
        }
        subject = "Your business account has been suspended."
        template = (
            "templates/suspend-user.html"
            if impacted_business.is_suspended
            else "templates/activate-user.html"
        )
        send_mail.delay(
            subject,
            template,
            context,
            [impacted_owner_email],
            organization_code=request.headers.get("Organization-Code"),
        )

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["musharakah_contract_request_terminated"],
            data=serializer.data,
        )


class MusharakahContractRequestFromTerminatedCreateAPIView(CreateAPIView):
    """Create a new musharakah contract request from a terminated contract."""

    permission_classes = [IsAuthenticated]
    serializer_class = MusharakahContractRequestFromTerminatedCreateSerializer

    # @PermissionManager(MUSHARAKAH_CONTRACT_REQUEST_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            musharakah_contract_request = serializer.save()

            # Return the created contract details
            response_serializer = MusharakahContractRequestResponseSerializer(
                musharakah_contract_request
            )

            return generic_response(
                data=response_serializer.data,
                message=JEWELER_MESSAGES["musharakah_contract_request_created"],
                status_code=status.HTTP_201_CREATED,
            )

        return handle_serializer_errors(serializer)


class MusharakahContractTerminationRequestListAPIView(ListAPIView):
    pagination_class = CommonPagination
    permission_classes = [IsAuthenticated]
    queryset = MusharakahContractTerminationRequest.objects.select_related(
        "musharakah_contract_request"
    )
    serializer_class = MusharakahContractTerminationRequestResponseSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = MusharakahContractTerminationFilter

    @PermissionManager(MUSHARAKAH_CONTRACT_TERMINATION_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return generic_response(
            data=self.get_paginated_response(serializer.data).data,
            message=MESSAGES["musharakah_contract_termination_request_fetched"],
            status_code=status.HTTP_200_OK,
        )


class MusharakahContractTerminationRequestStatusUpdateAPIView(UpdateAPIView):
    serializer_class = MusharakahContractTerminationRequestUpdateStatusSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["patch"]
    queryset = MusharakahContractTerminationRequest.objects.select_related(
        "musharakah_contract_request"
    )

    @PermissionManager(MUSHARAKAH_CONTRACT_TERMINATION_REQUEST_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=JEWELER_MESSAGES[
                    "musharakah_contract_termination_request_not_found"
                ],
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            termination_request = serializer.save()
            musharakah_contract = termination_request.musharakah_contract_request

            # --------------------------
            # Prepare users
            # --------------------------
            jeweler_users = User.objects.filter(
                user_assigned_businesses__business=musharakah_contract.jeweler,
                user_preference__notifications_enabled=True,
            )
            investor_users = User.objects.filter(
                user_assigned_businesses__business=musharakah_contract.investor,
                user_preference__notifications_enabled=True,
            )

            jeweler_name = musharakah_contract.jeweler.name
            investor_name = musharakah_contract.investor.name

            if "status" in request.data:
                if termination_request.status == RequestStatus.APPROVED:
                    termination_request_by = termination_request.termination_request_by
                    terminator_name = (
                        jeweler_name
                        if termination_request_by == ContractTerminator.JEWELER
                        else investor_name
                    )

                    # Get all approved asset contributions for this musharakah
                    asset_contributions = AssetContribution.objects.filter(
                        musharakah_contract_request=musharakah_contract,
                        production_payment__isnull=True,
                        status=RequestStatus.APPROVED,
                    )

                    # Update all asset contributions status to REJECTED after processing
                    asset_contributions.update(
                        status=AssetContributionStatus.TERMINATED
                    )

                    # Counterparty notification
                    title = f"Musharakah Contract has been terminated by {termination_request_by.capitalize()}"
                    message = f"The Musharakah Contract has been terminated by {terminator_name}."
                    notification_type = NotificationTypes.MUSHARAKAH_CONTRACT_TERMINATED
                    target_users = (
                        investor_users
                        if termination_request_by == ContractTerminator.JEWELER
                        else jeweler_users
                    )
                    send_notifications(
                        target_users,
                        title,
                        message,
                        notification_type,
                        ContentType.objects.get_for_model(MusharakahContractRequest),
                        musharakah_contract.pk,
                    )

                    # Approver notification
                    title = "Musharakah Contract termination approved"
                    message = f"The termination request for the Musharakah contract with {investor_name} has been approved by Sooq Al Thahab."
                    notification_type = (
                        NotificationTypes.MUSHARAKAH_CONTRACT_TERMINATION_REQUEST_APPROVED
                    )
                    target_users = (
                        jeweler_users
                        if termination_request_by == ContractTerminator.JEWELER
                        else investor_users
                    )
                    send_notifications(
                        target_users,
                        title,
                        message,
                        notification_type,
                        ContentType.objects.get_for_model(MusharakahContractRequest),
                        musharakah_contract.pk,
                    )
                else:
                    title = "Musharakah Contract termination rejected"
                    message = f"The termination request for the Musharakah contract with {investor_name} has been rejected by Sooq Al Thahab."
                    notification_type = (
                        NotificationTypes.MUSHARAKAH_CONTRACT_TERMINATION_REQUEST_REJECTED
                    )
                    send_notifications(
                        jeweler_users,
                        title,
                        message,
                        notification_type,
                        ContentType.objects.get_for_model(MusharakahContractRequest),
                        musharakah_contract.pk,
                    )

            elif "logistics_cost" in request.data or "insurance_fee" in request.data:
                if (
                    termination_request.logistics_cost_payable_by
                    == ContractTerminator.INVESTOR
                ):
                    # Investor pays → notify both
                    jeweler_title = (
                        "Settlement Payment Request for Musharakah Contract Termination"
                    )
                    investor_title = (
                        "Early Termination Payment Request for Musharakah Contract"
                    )
                    jeweler_message = "Sooq Al Thahab has added the Logistics and Insurance cost. The investor is required to make the payment. Please proceed."
                    investor_message = "Sooq Al Thahab has requested payment to proceed with the early termination of the Musharakah contract. Please complete the payment."
                    notification_type = (
                        NotificationTypes.MUSHARAKAH_CONTRACT_TERMINATION_PAYMENT_REQUEST
                    )
                    send_notifications(
                        jeweler_users,
                        jeweler_title,
                        jeweler_message,
                        notification_type,
                        ContentType.objects.get_for_model(MusharakahContractRequest),
                        musharakah_contract.pk,
                    )
                    send_notifications(
                        investor_users,
                        investor_title,
                        investor_message,
                        notification_type,
                        ContentType.objects.get_for_model(MusharakahContractRequest),
                        musharakah_contract.pk,
                    )
                else:
                    # Jeweler pays → notify jeweler only
                    title = "Settlement Payment Notification for Musharakah Contract Termination"
                    message = "Sooq Al Thahab has added the Logistics and Insurance cost. The jeweler is responsible for making the payment."
                    notification_type = (
                        NotificationTypes.MUSHARAKAH_CONTRACT_TERMINATION_PAYMENT_REQUEST
                    )

                    send_notifications(
                        jeweler_users,
                        title,
                        message,
                        notification_type,
                        ContentType.objects.get_for_model(MusharakahContractRequest),
                        musharakah_contract.pk,
                    )

            elif "cost_retail_payment_option" in request.data:
                title = "Early Termination Payment Request for Musharakah Contract"
                message = "Sooq Al Thahab has requested payment to proceed with the early termination of the Musharakah contract. Please complete the payment."
                notification_type = (
                    NotificationTypes.MUSHARAKAH_CONTRACT_TERMINATION_PAYMENT_REQUEST
                )
                send_notifications(
                    investor_users,
                    title,
                    message,
                    notification_type,
                    ContentType.objects.get_for_model(MusharakahContractRequest),
                    musharakah_contract.pk,
                )

            elif "refine_sell_payment_option" in request.data:
                if (
                    termination_request.refine_sell_payment_option
                    == RefineSellPaymentOption.REFINE
                ):
                    title = "Refining Cost Payment Request"
                    message = "Sooq Al Thahab has added the refining cost. Please complete the payment to proceed with the Musharakah contract termination."
                    notification_type = (
                        NotificationTypes.MUSHARAKAH_CONTRACT_TERMINATION_PAYMENT_REQUEST
                    )
                else:
                    title = "Sell Option Selected for Musharakah Contract Termination"
                    message = "Sooq Al Thahab has selected the sell option. The Musharakah contract will be terminated via the asset sell process."
                    notification_type = NotificationTypes.MUSHARAKAH_CONTRACT_TERMINATED

                send_notifications(
                    investor_users,
                    title,
                    message,
                    notification_type,
                    ContentType.objects.get_for_model(MusharakahContractRequest),
                    musharakah_contract.pk,
                )

            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["termination_request_updated"],
                data=serializer.data,
            )

        return handle_serializer_errors(serializer)


class MusharakahContractRenewalCreateAPIView(CreateAPIView):
    """Create a new Musharakah contract renewal."""

    serializer_class = MusharakahContractRenewalSerializer
    queryset = MusharakahContractRenewal.objects.all()
    permission_classes = [IsAuthenticated]

    @PermissionManager(MUSHARAKAH_CONTRACT_RENEWAL_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            musharakah_contract_renewal = serializer.save()

            # Send notifiction
            # Get Jeweler and investor owner
            jeweler_business_owner = UserAssignedBusiness.objects.filter(
                business=musharakah_contract_renewal.musharakah_contract_request.jeweler,
                is_owner=True,
            ).first()
            investor_business_owner = UserAssignedBusiness.objects.filter(
                business=musharakah_contract_renewal.musharakah_contract_request.investor,
                is_owner=True,
            ).first()

            # Get Jeweler and Investor business users
            jeweler_business_users = User.objects.filter(
                user_assigned_businesses__business=musharakah_contract_renewal.musharakah_contract_request.jeweler,
                user_preference__notifications_enabled=True,
            )
            investor_business_users = User.objects.filter(
                user_assigned_businesses__business=musharakah_contract_renewal.musharakah_contract_request.investor,
                user_preference__notifications_enabled=True,
            )

            # If user user_type is business then pass business name else user fullname
            if jeweler_business_owner.user.user_type == UserType.BUSINESS:
                jeweler_name = jeweler_business_owner.business.name
            else:
                jeweler_name = jeweler_business_owner.user.fullname

            if investor_business_owner.user.user_type == UserType.BUSINESS:
                investor_name = investor_business_owner.business.name
            else:
                investor_name = investor_business_owner.user.fullname

            send_notifications(
                list(jeweler_business_users) + list(investor_business_users),
                "Musharakah Contract Renewal by Sooq Al Thahab",
                f"The Musharakah contract between {jeweler_name} and {investor_name} has been successfully renewed until {musharakah_contract_renewal.expiry_date.date()} by Sooq Al Thahab.",
                NotificationTypes.MUSHARAKAH_CONTRACT_RENEWAL,
                ContentType.objects.get_for_model(MusharakahContractRequest),
                musharakah_contract_renewal.musharakah_contract_request.pk,
            )
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["musharakah_contract_renewed"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)


########################################################################################
############################## Subscription Plan APIs ##################################
########################################################################################


class OrganizationFilteredQuerysetMixin:
    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return SubscriptionPlan.objects.none()

        filters = {"organization_id": user.organization_id}

        role = self.request.query_params.get("role")
        business_type = self.request.query_params.get("business_type")

        if role:
            filters["role"] = role
        if business_type:
            filters["business_type"] = business_type

        return SubscriptionPlan.objects.filter(**filters)


class SubscriptionPlanListCreateAPIView(
    OrganizationFilteredQuerysetMixin, ListCreateAPIView
):
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionPlanSerializer
    pagination_class = CommonPagination

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            plan = serializer.save(
                organization_id=request.user.organization_id, created_by=request.user
            )
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["subscription_plan_created"],
                data=self.serializer_class(plan).data,
            )
        return handle_serializer_errors(serializer)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["subscription_plans_retrieved"],
            data=response_data,
        )


class SubscriptionPlanRetrieveUpdateDeleteAPIView(
    OrganizationFilteredQuerysetMixin, RetrieveUpdateDestroyAPIView
):
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionPlanSerializer
    http_method_names = ["get", "patch", "delete"]

    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except SubscriptionPlan.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["subscription_plan_not_found"],
            )

        serializer = self.get_serializer(instance)
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["subscription_plan_retrieved"],
            data=serializer.data,
        )

    def patch(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except SubscriptionPlan.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["subscription_plan_not_found"],
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)

        if serializer.is_valid():
            # Save updated subscription plan
            # NOTE: Plan template updates do NOT affect existing users
            # Only new users subscribing to this plan will get the updated rates
            serializer.save(updated_by=request.user, updated_at=timezone.now())

            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["subscription_plan_updated"],
                data=serializer.data,
            )

        return handle_serializer_errors(serializer)

    def delete(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except SubscriptionPlan.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["subscription_plan_not_found"],
            )

        # Check if any BusinessSubscriptionPlan is linked to this plan
        linked_subscriptions = BusinessSubscriptionPlan.objects.filter(
            subscription_plan=instance
        ).exists()

        if linked_subscriptions:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["subscription_plan_linked_to_subscriptions"],
            )

        # If not linked, allow deletion
        instance.delete()
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["subscription_plan_deleted"],
        )


class ToggleSubscriptionPlanStatusAPIView(
    OrganizationFilteredQuerysetMixin, UpdateAPIView
):
    queryset = SubscriptionPlan.objects.all()
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsAuthenticated]

    def patch(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except SubscriptionPlan.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["subscription_plan_not_found"],
            )

        is_active = request.data.get("is_active")
        if is_active is None:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["missing_field_is_active"],
            )

        instance.is_active = is_active
        instance.save()
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["subscription_plan_activation_status_updated"],
            data={"id": instance.id, "is_active": instance.is_active},
        )


########################################################################################
############################## Manufacturing Request APIs ##############################
########################################################################################


class BaseManufacturingRequestQueryset:
    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return ManufacturingRequest.objects.none()
        queryset = (
            ManufacturingRequest.objects.filter(
                organization_id=user.organization_id,
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


class ManufacturingRequestListView(
    BaseManufacturingRequestQueryset, ManufacturingRequestListAPIView
):
    """API view to list all jewelry manufacturing requests."""

    pass


class ManufacturingRequestDetailsAPIView(
    BaseManufacturingRequestQueryset, ManufacturingRequestRetrieveAPIView
):
    "API view to retrieve detailed information about a specific manufacturing request."

    pass


class BusinessSubscriptionPlanRetrieveAdminAPIView(RetrieveAPIView):
    """
    Retrieve the details of a Business Subscription Plan by ID (admin only).
    """

    permission_classes = [IsAuthenticated]
    serializer_class = BusinessSubscriptionPlanSerializer
    queryset = BusinessSubscriptionPlan.objects.all()

    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data,
                message=MESSAGES["business_subscription_details_fetched"],
            )
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["business_subscription_not_found"],
            )


class OrganizationRiskLevelListCreateAPIView(ListCreateAPIView):
    """List and create risk levels for the authenticated admin's organization."""

    permission_classes = [IsAuthenticated]
    serializer_class = OrganizationRiskLevelSerializer
    pagination_class = CommonPagination
    queryset = OrganizationRiskLevel.objects.all()

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return self.queryset.none()
        return self.queryset.filter(organization_id=user.organization_id).order_by(
            "-created_at"
        )

    @PermissionManager(RISK_LEVEL_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["risk_levels_fetched"],
            data=response_data,
        )

    @PermissionManager(RISK_LEVEL_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["risk_level_created"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)


class OrganizationRiskLevelRetrieveUpdateAPIView(RetrieveUpdateAPIView):
    """Retrieve or update a specific risk level for the authenticated admin's organization."""

    permission_classes = [IsAuthenticated]
    serializer_class = OrganizationRiskLevelSerializer
    queryset = OrganizationRiskLevel.objects.all()
    http_method_names = ["patch", "get"]

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return self.queryset.none()
        return self.queryset.filter(organization_id=self.request.user.organization_id)

    @PermissionManager(RISK_LEVEL_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                message=MESSAGES["risk_level_not_found"],
            )

        serializer = self.get_serializer(instance)
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["risk_level_retrieved"],
            data=serializer.data,
        )

    @PermissionManager(RISK_LEVEL_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                message=MESSAGES["risk_level_not_found"],
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(updated_by=request.user)
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["risk_level_updated"],
                data=serializer.data,
            )

        return handle_serializer_errors(serializer)


class AdminBusinessRiskLevelUpdateAPIView(UpdateAPIView):
    """Admin: Update the risk level of a business account."""

    permission_classes = [IsAuthenticated]
    serializer_class = BusinessRiskLevelUpdateSerializer
    queryset = BusinessAccount.objects.all()
    http_method_names = ["patch"]

    @PermissionManager(BUSINESS_RISK_LEVEL_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        try:
            business = self.get_object()

            if business.business_account_type != UserRoleBusinessChoices.JEWELER:
                return generic_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_message=MESSAGES[
                        "risk_level_update_allowed_for_jeweler_only"
                    ],
                )

            serializer = self.serializer_class(
                business, data=request.data, partial=True
            )
            if serializer.is_valid():
                serializer.save()
                return generic_response(
                    status_code=status.HTTP_200_OK,
                    message=MESSAGES["business_risk_level_updated"],
                    data=serializer.data,
                )
            return handle_serializer_errors(serializer)

        except Http404:
            return generic_response(
                error_message=ACCOUNT_MESSAGES["business_account_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )


class PreciousItemUnitAPIView(ListAPIView):
    """List all precious item units."""

    permission_classes = [IsAuthenticated]
    serializer_class = PreciousItemUnitResponseSerializer
    queryset = PreciousItemUnit.objects.all()

    def get_queryset(self):
        """Filter precious item units based on query parameters."""
        queryset = super().get_queryset()

        musharakah_contract_request_id = self.request.query_params.get(
            "musharakah_contract_request"
        )
        pool_id = self.request.query_params.get("pool")
        business_id = self.request.query_params.get("business")
        if musharakah_contract_request_id:
            purchase_requests = PurchaseRequest.objects.filter(
                asset_contributions__musharakah_contract_request__id=musharakah_contract_request_id
            ).distinct()
            queryset = queryset.filter(purchase_request__in=purchase_requests)
            return queryset

        elif pool_id and business_id:
            # Get asset contributions for this specific pool and business
            asset_contributions = AssetContribution.objects.filter(
                pool__id=pool_id,
                business=business_id,
                pool__isnull=False,
            ).select_related("purchase_request")

            if not asset_contributions.exists():
                return queryset.none()

            # Get purchase request IDs from these specific asset contributions
            purchase_request_ids = asset_contributions.values_list(
                "purchase_request_id", flat=True
            ).distinct()

            # Get statuses of these asset contributions to determine filtering logic
            approved_statuses = [
                AssetContributionStatus.APPROVED,
                AssetContributionStatus.ADMIN_APPROVED,
            ]
            approved_contributions = asset_contributions.filter(
                status__in=approved_statuses
            )
            pending_contributions = asset_contributions.filter(
                status=AssetContributionStatus.PENDING
            )

            # For approved contributions: only show units already allocated to this pool
            if approved_contributions.exists():
                approved_pr_ids = approved_contributions.values_list(
                    "purchase_request_id", flat=True
                ).distinct()
                approved_units = queryset.filter(
                    purchase_request_id__in=approved_pr_ids,
                    pool__id=pool_id,  # Only units allocated to this specific pool
                )
            else:
                approved_units = queryset.none()

            # For pending contributions: show available units (not in other pools, not sold)
            if pending_contributions.exists():
                pending_pr_ids = pending_contributions.values_list(
                    "purchase_request_id", flat=True
                ).distinct()
                pending_units = queryset.filter(
                    purchase_request_id__in=pending_pr_ids,
                    sale_request__isnull=True,  # Not sold
                    pool__isnull=True,  # Not allocated to any pool yet
                )
            else:
                pending_units = queryset.none()

            # Combine both sets of units
            queryset = queryset.filter(
                Q(id__in=approved_units.values_list("id", flat=True))
                | Q(id__in=pending_units.values_list("id", flat=True))
            )

            return queryset

        return queryset.none()

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(
                name="musharakah_contract_request",
                in_=openapi.IN_QUERY,
                description="Musharakah Contract Request ID to filter precious item units associated with it purchase request.",
                type=openapi.TYPE_STRING,
                required=False,
            ),
            openapi.Parameter(
                name="business",
                in_=openapi.IN_QUERY,
                description="Business ID to filter precious item units associated with it purchase request.",
                type=openapi.TYPE_STRING,
                required=False,
            ),
            openapi.Parameter(
                name="pool",
                in_=openapi.IN_QUERY,
                description="Pool ID to filter precious item units associated with it purchase request.",
                type=openapi.TYPE_STRING,
                required=False,
            ),
        ]
    )
    @PermissionManager(PRECIOUS_ITEM_UNIT_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["precious_item_units_fetched"],
            data=serializer.data,
        )


class PreciousItemUnitUpdateView(UpdateAPIView):
    """
    Admin bulk update:
    - PreciousItemUnit.serial_number
    - PreciousItemUnit.system_serial_number
    - PurchaseRequest.storage_box_number
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PreciousItemUnitBulkAdminUpdateSerializer
    queryset = PurchaseRequest.objects.all()

    def patch(self, request, *args, **kwargs):
        purchase_request = self.get_object()
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        data = serializer.validated_data
        units_data = data.get("units", [])

        with transaction.atomic():
            # Update box number ONLY
            if "storage_box_number" in data:
                purchase_request.storage_box_number = data["storage_box_number"]
                purchase_request.save(update_fields=["storage_box_number"])

            # If no units provided, STOP here (box-only update)
            if not units_data:
                return generic_response(
                    status_code=status.HTTP_200_OK,
                    message=MESSAGES["storage_box_number_updated"],
                )

            # --------------------------------------------------
            # Validate unit ownership
            # --------------------------------------------------
            unit_ids = [item["id"] for item in units_data]

            existing_units = PreciousItemUnit.objects.filter(
                id__in=unit_ids,
                purchase_request=purchase_request,
            )

            existing_ids = set(str(unit.id) for unit in existing_units)
            missing_ids = [uid for uid in unit_ids if uid not in existing_ids]

            if missing_ids:
                return generic_response(
                    error_message=MESSAGES["missing_precious_item_units_id"].format(
                        missing_ids=missing_ids
                    ),
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            # --------------------------------------------------
            # Update units
            # --------------------------------------------------
            update_map = {item["id"]: item for item in units_data}
            update_list = []

            for unit in existing_units:
                payload = update_map[str(unit.id)]
                updated = False

                if "serial_number" in payload:
                    unit.serial_number = payload["serial_number"]
                    updated = True

                if "system_serial_number" in payload:
                    unit.system_serial_number = payload["system_serial_number"]
                    updated = True

                if updated:
                    update_list.append(unit)

            if update_list:
                PreciousItemUnit.objects.bulk_update(
                    update_list,
                    ["serial_number", "system_serial_number"],
                )

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["precious_item_units_and_box_number_updated"],
        )


########################################################################################
############################### Subscription Transaction APIs ########################
########################################################################################


class SubscriptionTransactionListAdminAPIView(BaseBusinessListAPIView, ListAPIView):
    """Admin API to list subscription transactions only with enhanced details."""

    serializer_class = SubscriptionTransactionListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = TransactionFilter

    def get_queryset(self):
        """Retrieve subscription transactions belonging to the request user's organization."""
        user = self.request.user
        if user.is_anonymous:
            return Transaction.objects.none()

        return (
            Transaction.global_objects.select_related(
                "from_business",
                "to_business",
                "business_subscription",
                "business_subscription__subscription_plan",
                "business_subscription__business_saved_card_token",
                "created_by",
            )
            .prefetch_related(
                Prefetch(
                    "from_business__user_assigned_businesses",
                    queryset=UserAssignedBusiness.objects.filter(is_owner=True),
                    to_attr="prefetched_owners",
                ),
                Prefetch(
                    "from_business__billing_details",
                    queryset=BillingDetails.objects.order_by("-created_at"),
                    to_attr="prefetched_billing_details",
                ),
            )
            .filter(
                created_by__organization_id=user.organization_id,
                business_subscription__isnull=False,  # Only subscription transactions
            )
            .order_by("-created_at")
        )

    @PermissionManager(TRANSACTION_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        return self.get_paginated_response_data(
            queryset, MESSAGES["subscription_transactions_fetched"]
        )


class SubscriptionTransactionRetrieveAdminAPIView(RetrieveAPIView):
    """Admin API to retrieve a specific subscription transaction with full details."""

    serializer_class = SubscriptionTransactionDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Ensure the subscription transaction belongs to the request user's organization."""
        user = self.request.user
        if user.is_anonymous:
            return Transaction.objects.none()

        return (
            Transaction.global_objects.select_related(
                "from_business",
                "to_business",
                "business_subscription",
                "business_subscription__subscription_plan",
                "business_subscription__business_saved_card_token",
                "purchase_request",
                "manufacturing_request",
                "jewelry_production",
                "created_by",
            )
            .prefetch_related(
                Prefetch(
                    "from_business__user_assigned_businesses",
                    queryset=UserAssignedBusiness.objects.filter(is_owner=True),
                    to_attr="prefetched_owners",
                ),
                Prefetch(
                    "from_business__billing_details",
                    queryset=BillingDetails.objects.order_by("-created_at"),
                    to_attr="prefetched_billing_details",
                ),
            )
            .filter(
                created_by__organization_id=user.organization_id,
                business_subscription__isnull=False,  # Only subscription transactions
            )
            .order_by("-created_at")
        )

    @PermissionManager(TRANSACTION_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            transaction = self.get_object()
            serializer = self.get_serializer(transaction)
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["transaction_retrieved"],
                data=serializer.data,
            )
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["transaction_not_found"],
            )


class MusharakahContractManufacturingCostAPIView(CreateAPIView):
    """Return total estimation cost for a given Musharakah contract."""

    permission_classes = [IsAuthenticated]
    serializer_class = MusharakahContractManufacturingCostCreateSerializer

    def post(self, request, *args, **kwargs):
        musharakah_contract_id = request.data.get("musharakah_contract_id")
        organization = request.user.organization_id

        # Fetch all production payments associated with this Musharakah contract
        payments = ProductionPayment.objects.filter(
            musharakah_contract_id=musharakah_contract_id
        )

        default_currency = OrganizationCurrency.objects.filter(
            organization=organization,
            is_default=True,
        ).first()

        total_estimation_cost = Decimal("0.00")
        total_live_metal_price = Decimal("0.00")
        total_retail_price = Decimal("0.00")
        for payment in payments:
            production = payment.jewelry_production

            # Find estimation request related to the production’s manufacturing request
            estimation = ManufacturingEstimationRequest.objects.filter(
                manufacturing_request=production.manufacturing_request
            ).first()

            # If estimation exists, sum up all estimated prices linked to it
            if estimation:
                estimated_prices = ProductManufacturingEstimatedPrice.objects.filter(
                    estimation_request=estimation
                ).aggregate(total=Sum("estimated_price"))
                estimated_cost = estimated_prices.get("total") or Decimal("0.00")
                # Add total estimated price (if any) to cumulative cost
                total_estimation_cost += estimated_cost

            total_product = (
                ManufacturingProductRequestedQuantity.objects.filter(
                    manufacturing_request=production.manufacturing_request
                )
                .select_related("jewelry_product")
                .aggregate(
                    total_quantity=Sum("quantity"),
                    total_premium=Sum(
                        F("quantity") * F("jewelry_product__premium_price")
                    ),
                )
            )
            total_premium = total_product.get("total_premium") or 0

            total_stone_price = JewelryProductStonePrice.objects.filter(
                jewelry_production=production
            ).aggregate(total=Sum("stone_price"))["total"] or Decimal("0.00")

            manufacturing_target = ManufacturingTarget.objects.filter(
                manufacturing_request=production.manufacturing_request,
            )

            # Metal price
            metal_targets = manufacturing_target.filter(
                material_type=MaterialType.METAL
            )
            metal_summary = defaultdict(Decimal)

            for metal in metal_targets:
                key = (metal.material_item_id, metal.carat_type_id)
                metal_summary[key] = {
                    "material_item": metal.material_item,
                    "carat_type": metal.carat_type,
                    "weight": Decimal(0),
                }
                metal_summary[key]["weight"] += metal.weight

            total_live_metal_price += self.get_live_metal_price(
                metal_summary, default_currency
            )

            total_retail_price = (
                total_stone_price
                + total_premium
                + estimated_cost
                + total_live_metal_price
            )

        response_data = {
            "total_manufacturing_cost": total_estimation_cost,
            "total_retail_price": total_retail_price,
        }

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=JEWELER_MESSAGES[
                "musharakah_contract_manufacturing_cost_retrieved"
            ],
            data=MusharakahContractManufacturingCostResponseSerializer(
                response_data
            ).data,
        )

    def get_live_metal_price(self, assets, currency_rate):
        """Fetch real-time price for contributed metals and compute total value."""

        if not assets:
            return Decimal(0)

        # Get distinct latest prices for all metals in one query
        latest_prices_qs = (
            MetalPriceHistory.objects.filter(
                global_metal__in=[
                    a["material_item"].global_metal for a in assets.values()
                ]
            )
            .order_by("global_metal", "-created_at")
            .distinct("global_metal")  # Postgres DISTINCT ON
        )

        # Build lookup dict {global_metal_id: price}
        latest_prices = {mp.global_metal_id: mp.price for mp in latest_prices_qs}

        total_metal_price = Decimal(0)

        # Iterate over values (dicts), not keys (tuples)
        for asset in assets.values():
            material_item = asset["material_item"]
            carat_type = asset["carat_type"]
            weight = asset["weight"]

            metal_price = latest_prices.get(material_item.global_metal_id)
            if not metal_price:
                continue

            # Example: 22k -> 22
            carat_number = int(carat_type.name.rstrip("k"))

            # Price adjusted for purity
            price_per_unit = (carat_number * metal_price) / 24

            total_metal_price += Decimal(price_per_unit) * weight * currency_rate.rate

        return round(total_metal_price, 2)


class AdminMusharakahContractTerminationRequestCreateAPIView(CreateAPIView):
    """Handles creating a Musharakah Contract Termination Request."""

    serializer_class = AdminMusharakahContractTerminationRequestSerializer
    permission_classes = [IsAuthenticated]

    @PermissionManager(MUSHARAKAH_CONTRACT_TERMINATION_REQUEST_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        """Handles creating a Musharakah Contract Request Termination Request."""

        # If investor is individual then pass full name or else pass business name

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            musharakah_contract_termination_request = serializer.save()
            termination_request_by = (
                musharakah_contract_termination_request.termination_request_by
            )
            musharakah_contract = (
                musharakah_contract_termination_request.musharakah_contract_request
            )
            if termination_request_by == ContractTerminator.JEWELER:
                business = musharakah_contract.jeweler
            else:
                business = musharakah_contract.investor

            all_users_in_related_business = User.objects.filter(
                user_assigned_businesses__business=business,
                user_preference__notifications_enabled=True,
            ).distinct()

            # send notification to admin
            title = "Musharakah contract termination request."
            message = f"'The Sooq Al Thahab has initiated a musharakah contract termination process based on a request from {business.name}."
            send_notifications(
                [all_users_in_related_business],
                title,
                message,
                NotificationTypes.MUSHARAKAH_CONTRACT_TERMINATION_REQUEST,
                ContentType.objects.get_for_model(MusharakahContractRequest),
                musharakah_contract_termination_request.musharakah_contract_request.id,
            )

            return generic_response(
                data=self.get_serializer(musharakah_contract_termination_request).data,
                message=JEWELER_MESSAGES[
                    "musharakah_contract_terminate_request_created"
                ],
                status_code=status.HTTP_201_CREATED,
            )

        return handle_serializer_errors(serializer)


class JewelryProfitDistributionListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    serializer_class = JewelryProfitDistributionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = JewelryProfitDistributionFilter

    queryset = JewelryProfitDistribution.objects.select_related(
        "jewelry_sale",
        "musharakah_contract",
        "recipient_business",
    ).all()

    def get_queryset(self):
        """Returns Material Items belonging to the authenticated user's organization."""
        if self.request.user.is_anonymous:
            return self.queryset.none()
        return self.queryset.filter(organization_id=self.request.user.organization_id)

    @PermissionManager(MATERIAL_ITEM_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["jewelry_profit_distributions_fetched"],
            data=response_data,
        )


class JewelryProfitDistributionDetailView(RetrieveAPIView):
    serializer_class = JewelryProfitDistributionSerializer
    permission_classes = [IsAuthenticated]
    queryset = JewelryProfitDistribution.objects.select_related(
        "jewelry_sale",
        "musharakah_contract",
        "recipient_business",
    ).all()

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return self.queryset.none()

        queryset = self.queryset.filter(
            organization_id=self.request.user.organization_id
        )
        return queryset

    @PermissionManager(MUSHARAKAH_CONTRACT_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["jewelry_profit_distribution_not_found"],
            )

        serializer = self.get_serializer(instance)
        return generic_response(
            data=serializer.data,
            message=MESSAGES["jewelry_profit_distributions_retrieved"],
            status_code=status.HTTP_200_OK,
        )
