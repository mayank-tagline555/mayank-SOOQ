from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import DateTimeField
from django.db.models import DecimalField
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import Sum
from django.http import Http404
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils import translation
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg.utils import swagger_auto_schema
from rest_framework import serializers
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.generics import UpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.validators import ValidationError
from rest_framework.views import APIView

from account.message import MESSAGES as ACCOUNT_MESSAGES
from account.models import OrganizationCurrency
from account.models import Transaction
from account.models import User
from account.models import Wallet
from account.utils import get_user_or_business_name
from investor.message import MESSAGES as INVESTOR_MESSAGES
from investor.serializers import LogisticCostPaymentSerializer
from investor.serializers import MusharakahContractAgreementPreviewSerializer
from investor.serializers import MusharakahContractEarlyTerminationPaymentSerializer
from investor.serializers import MusharakahContractProfitSerializer
from investor.serializers import MusharakahContractRequestAssetContributionSerializer
from investor.serializers import MusharakahContractRequestSummarySerializer
from investor.serializers import RefiningCostPaymentSerializer
from investor.utils import get_total_hold_amount_for_investor
from investor.utils import get_total_withdrawal_pending_amount
from jeweler.filters import MusharakahContractRequestFilter
from jeweler.message import MESSAGES as JEWELER_MESSAGES
from jeweler.models import MusharakahContractRequest
from jeweler.models import MusharakahContractTerminationRequest
from jeweler.serializers import MusharakahContractRequestResponseSerializer
from jeweler.serializers import MusharakahContractRequestRetrieveSerializer
from seller.utils import get_fcm_tokens_for_users
from sooq_althahab.billing.subscription.helpers import check_subscription_feature_access
from sooq_althahab.constants import LOGISTIC_COST_PAYMENT_PERMISSION
from sooq_althahab.constants import (
    MUSHARAKAH_CONTRACT_REQUEST_ASSET_CONTRIBUTION_CHANGE_PERMISSION,
)
from sooq_althahab.constants import MUSHARAKAH_CONTRACT_REQUEST_VIEW_PERMISSION
from sooq_althahab.enums.account import MusharakahContractTerminationPaymentType
from sooq_althahab.enums.account import SubscriptionFeatureChoices
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.account import UserType
from sooq_althahab.enums.jeweler import ContractTerminator
from sooq_althahab.enums.jeweler import CostRetailPaymentOption
from sooq_althahab.enums.jeweler import LogisticCostPayableBy
from sooq_althahab.enums.jeweler import MusharakahContractStatus
from sooq_althahab.enums.jeweler import RefineSellPaymentOption
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.helper import PermissionManager
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.tasks import send_notification
from sooq_althahab.tasks import send_termination_reciept_mail
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab.utils import send_notification_count_to_users
from sooq_althahab.utils import send_notifications
from sooq_althahab.utils import send_notifications_to_organization_admins
from sooq_althahab_admin.models import MetalPriceHistory
from sooq_althahab_admin.models import Notification


class MusharakahContractRequestListViewAPIView(ListAPIView):
    """Handles listing of Musharakah Contract Requests."""

    permission_classes = [IsAuthenticated]
    queryset = MusharakahContractRequest.objects.all()
    pagination_class = CommonPagination
    filter_backends = (DjangoFilterBackend,)
    filterset_class = MusharakahContractRequestFilter
    serializer_class = MusharakahContractRequestResponseSerializer

    def get_queryset(self):
        """Returns the queryset for the view."""
        user = self.request.user
        if self.request.user.is_anonymous:
            return self.queryset.none()

        business = get_business_from_user_token(self.request, "business")

        return self.queryset.filter(
            organization_id=user.organization_id,
            investor__isnull=True,
        ).exclude(terminated_musharakah_contract__investor=business)

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


class MusharakahContractRequestRetriveAPIView(RetrieveAPIView):
    queryset = MusharakahContractRequest.objects.all()
    serializer_class = MusharakahContractRequestRetrieveSerializer
    permission_classes = [IsAuthenticated]

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
                error_message=JEWELER_MESSAGES["musharakah_contract_request_not_found"],
            )

        serializer = self.get_serializer(instance)
        return generic_response(
            data=serializer.data,
            message=JEWELER_MESSAGES["musharakah_contract_request_fetched"],
            status_code=status.HTTP_200_OK,
        )


class MusharakahContractRequestAssetContributionUpdateAPIView(UpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MusharakahContractRequestAssetContributionSerializer
    queryset = MusharakahContractRequest.objects.select_related(
        "investor"
    ).prefetch_related(
        "musharakah_contract_request_quantities__jewelry_product__product_materials"
    )
    response_serializer_class = MusharakahContractRequestResponseSerializer
    http_method_names = ["patch"]

    @PermissionManager(MUSHARAKAH_CONTRACT_REQUEST_ASSET_CONTRIBUTION_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        user = request.user
        organization_code = request.user.organization_id.code

        # Check subscription feature access (only for INVESTOR role)
        business = get_business_from_user_token(request, "business")
        if (
            business
            and business.business_account_type == UserRoleBusinessChoices.INVESTOR
        ):
            try:
                check_subscription_feature_access(
                    business, SubscriptionFeatureChoices.JOIN_MUSHARAKAH
                )
            except ValidationError as ve:
                error_msg = (
                    ve.detail[0] if isinstance(ve.detail, list) else str(ve.detail)
                )
                return generic_response(
                    status_code=status.HTTP_403_FORBIDDEN,
                    error_message=error_msg,
                )

        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=JEWELER_MESSAGES["musharakah_contract_request_not_found"],
            )
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            musharakah_contract_request_contribution = serializer.save()

            # Send notification
            users_in_jeweler_business = User.objects.filter(
                user_assigned_businesses__business=musharakah_contract_request_contribution.jeweler,
                user_preference__notifications_enabled=True,
            )
            tokens = get_fcm_tokens_for_users(users_in_jeweler_business)

            # If user has business then send name of business or else send fullname of user
            name = get_user_or_business_name(request)
            user_type = (
                "(Business)" if user.user_type == UserType.BUSINESS else "(Individual)"
            )
            title = "The investor has contributed their asset to the Musharakah Contract Request."
            message = f"'{name}' {user_type} has contributed their asset to the Musharakah Contract Request."
            content_type = ContentType.objects.get_for_model(MusharakahContractRequest)
            notification_type = (
                NotificationTypes.ASSET_CONTRIBUTED_IN_MUSHARAKAH_CONTRACT_REQUEST
            )

            # Create a notification for each seller's business user
            notifications = [
                Notification(
                    user=user,
                    title=title,
                    message=message,
                    notification_type=notification_type,
                    content_type=content_type,
                    object_id=musharakah_contract_request_contribution.id,
                )
                for user in users_in_jeweler_business
            ]
            # Bulk insert notifications, ignoring conflicts from concurrent operations
            Notification.objects.bulk_create(notifications, ignore_conflicts=True)

            notification_data = {
                "notification_type": notification_type,
                "id": str(musharakah_contract_request_contribution.id),
            }

            # Send notifications to jeweler's business users asynchronously
            send_notification_count_to_users(users_in_jeweler_business)
            send_notification.delay(tokens, title, message, notification_data)

            send_notifications_to_organization_admins(
                organization_code,
                title,
                message,
                notification_type,
                content_type,
                musharakah_contract_request_contribution.id,
                UserRoleChoices.TAQABETH_ENFORCER,
            )

            return generic_response(
                status_code=status.HTTP_200_OK,
                message=INVESTOR_MESSAGES[
                    "asset_contributed_in_musharakah_contract_request"
                ],
                data=self.response_serializer_class(
                    musharakah_contract_request_contribution
                ).data,
            )
        return handle_serializer_errors(serializer)


class MusharakahContractRequestSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]
    queryset = MusharakahContractRequest.objects.all()
    serializer = MusharakahContractRequestSummarySerializer

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return self.queryset.none()

        business = get_business_from_user_token(self.request, "business")
        if not business:
            return self.queryset.none()

        # Apply filters and annotate computed_expiry_date
        base_qs = self.queryset.filter(
            organization_id=self.request.user.organization_id, investor=business
        ).annotate(
            computed_expiry_date=ExpressionWrapper(
                F("approved_at") + F("duration_in_days__days") * timedelta(days=1),
                output_field=DateTimeField(),
            )
        )

        return base_qs

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        # All active musharakah contract request count
        active_count = queryset.filter(
            status=RequestStatus.APPROVED,
            musharakah_contract_status=MusharakahContractStatus.ACTIVE,
            computed_expiry_date__gt=timezone.now(),
        ).count()

        # All expired musharakah contract request count
        expired_count = queryset.filter(
            status=RequestStatus.APPROVED,
            musharakah_contract_status=MusharakahContractStatus.ACTIVE,
            computed_expiry_date__lt=timezone.now(),
        ).count()
        data = {
            "total_count": queryset.count(),
            "active_count": active_count,
            "expired_count": expired_count,
        }

        serializer = self.serializer(data).data
        return generic_response(
            data=serializer,
            message=INVESTOR_MESSAGES["musharakah_contract_request_summary_retrieved"],
            status_code=status.HTTP_200_OK,
        )


class MusharakahContractRequestAPIView(MusharakahContractRequestListViewAPIView):
    """Handles listing of Musharakah Contract Requests for the logged-in user in the role of an investor."""

    def get_queryset(self):
        """Returns the queryset for the view."""
        user = self.request.user
        if self.request.user.is_anonymous:
            return self.queryset.none()

        business = get_business_from_user_token(self.request, "business")
        if not business:
            return self.queryset.none()

        return self.queryset.filter(
            organization_id=user.organization_id,
            investor=business,
            status__in=[
                RequestStatus.APPROVED,
                RequestStatus.PENDING,
                RequestStatus.ADMIN_APPROVED,
            ],
        )


class LogisticCostPaymentCreateAPI(CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LogisticCostPaymentSerializer

    @PermissionManager(LOGISTIC_COST_PAYMENT_PERMISSION)
    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            user = request.user

            # Business associated with the current user (from JWT token)
            business = get_business_from_user_token(request, "business")

            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                return handle_serializer_errors(serializer)

            musharakah_contract_id = serializer.validated_data.get(
                "musharakah_contract_id"
            )

            # Extract Musharakah Contract Request ID from validated serializer data
            musharakah_contract_termination_request = (
                MusharakahContractTerminationRequest.objects.filter(
                    musharakah_contract_request__id=musharakah_contract_id
                ).first()
            )
            # Get Musharakah Contract
            musharakah_contract = (
                musharakah_contract_termination_request.musharakah_contract_request
            )

            if (
                musharakah_contract_termination_request.logistics_cost_payable_by
                == LogisticCostPayableBy.JEWELER
            ):
                return generic_response(
                    message=INVESTOR_MESSAGES["logistic_cost_payable_by_jeweler"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Check if the termination was NOT requested by the Jeweler
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
                musharakah_contract_termination_payment_type=MusharakahContractTerminationPaymentType.INVESTOR_LOGISTIC_FEE_PAYMENT_TRANSACTION,
            ).first()

            if not payment_transaction:
                return generic_response(
                    message=INVESTOR_MESSAGES[
                        "logistic_cost_payment_already_processed"
                    ],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Fetch wallet of the jeweler’s business
            wallet = Wallet.objects.filter(business=business).first()
            payment_transaction.previous_balance = wallet.balance

            # Calculate amounts already hold or pending for withdrawal
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
                # Insufficient balance in jeweler’s wallet
                return generic_response(
                    message=ACCOUNT_MESSAGES["insufficient_balance"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Deduct termination fee from jeweler’s wallet
            wallet.balance -= payment_transaction.amount
            wallet.save()

            # Record the termination fee transaction
            payment_transaction.status = TransactionStatus.APPROVED
            payment_transaction.current_balance = wallet.balance
            payment_transaction.payment_completed_at = timezone.now()
            payment_transaction.save()
            musharakah_contract_termination_request.save()

            # Send notification to organization admins
            organization = user.organization_id

            if user.user_type == UserType.BUSINESS:
                user_type = "(Business)"
                name = business.name
            else:
                user_type = "(Individual)"
                name = user.fullname

            subject = "Musharakah Early Termination"
            send_termination_reciept_mail.delay(
                user.pk,
                organization.pk,
                business.pk,
                payment_transaction.pk,
                musharakah_contract_termination_request.pk,
                subject,
                musharakah_contract_termination_request.logistics_cost,
                subject,
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


class RefiningCostPaymentCreateAPI(CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RefiningCostPaymentSerializer

    @PermissionManager(LOGISTIC_COST_PAYMENT_PERMISSION)
    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            user = request.user

            # Business associated with the current user (from JWT token)
            business = get_business_from_user_token(request, "business")

            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                return handle_serializer_errors(serializer)

            musharakah_contract_id = serializer.validated_data.get(
                "musharakah_contract_id"
            )

            # Extract Musharakah Contract Request ID from validated serializer data
            musharakah_contract_termination_request = (
                MusharakahContractTerminationRequest.objects.filter(
                    musharakah_contract_request__id=musharakah_contract_id
                ).first()
            )
            # Get Musharakah Contract
            musharakah_contract = (
                musharakah_contract_termination_request.musharakah_contract_request
            )

            is_refine = (
                musharakah_contract_termination_request.refine_sell_payment_option
                == RefineSellPaymentOption.REFINE
            )
            if (
                not is_refine
                and not musharakah_contract_termination_request.refining_cost
            ):
                return generic_response(
                    message=INVESTOR_MESSAGES[
                        "sooq_al_thahab_has_not_added_refining_cost"
                    ],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            payment_transaction = Transaction.objects.filter(
                musharakah_contract=musharakah_contract,
                status=TransactionStatus.PENDING,
                musharakah_contract_termination_payment_type=MusharakahContractTerminationPaymentType.INVESTOR_REFINING_COST_PAYMENT_TRANSACTION,
            ).first()

            if payment_transaction.status == TransactionStatus.APPROVED:
                return generic_response(
                    message=INVESTOR_MESSAGES[
                        "refining_cost_payment_already_processed"
                    ],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Fetch wallet of the jeweler’s business
            wallet = Wallet.objects.filter(business=business).first()
            payment_transaction.previous_balance = wallet.balance

            # Calculate amounts already hold or pending for withdrawal
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
                # Insufficient balance in jeweler’s wallet
                return generic_response(
                    message=ACCOUNT_MESSAGES["insufficient_balance"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Deduct termination fee from jeweler’s wallet
            wallet.balance -= payment_transaction.amount
            wallet.save()

            # Record the termination fee transaction
            payment_transaction.status = TransactionStatus.APPROVED
            payment_transaction.current_balance = wallet.balance
            payment_transaction.payment_completed_at = timezone.now()
            payment_transaction.save()

            musharakah_contract_termination_request.status = RequestStatus.APPROVED
            musharakah_contract_termination_request.save()
            musharakah_contract.musharakah_contract_status = (
                MusharakahContractStatus.TERMINATED
            )
            musharakah_contract.save()

            # Send notification to organization admins
            organization = user.organization_id

            if user.user_type == UserType.BUSINESS:
                user_type = "(Business)"
                name = business.name
            else:
                user_type = "(Individual)"
                name = user.fullname

            subject = "Musharakah Early Termination"
            send_termination_reciept_mail.delay(
                user.pk,
                organization.pk,
                business.pk,
                payment_transaction.pk,
                musharakah_contract_termination_request.pk,
                subject,
                musharakah_contract_termination_request.refining_cost,
                subject,
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
                message=INVESTOR_MESSAGES["refining_cost_processed_successfully"],
                status_code=status.HTTP_201_CREATED,
                data=serializer.data,
            )


class MusharakahContractEarlyTerminationPaymentCreateAPIView(CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MusharakahContractEarlyTerminationPaymentSerializer

    @PermissionManager(LOGISTIC_COST_PAYMENT_PERMISSION)
    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            user = request.user
            # Business associated with the current user (from JWT token)
            business = get_business_from_user_token(request, "business")

            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                return handle_serializer_errors(serializer)

            musharakah_contract_id = serializer.validated_data.get(
                "musharakah_contract_id"
            )

            # Extract Musharakah Contract Request ID from validated serializer data
            musharakah_contract_termination_request = (
                MusharakahContractTerminationRequest.objects.filter(
                    musharakah_contract_request__id=musharakah_contract_id
                ).first()
            )
            # Get Musharakah Contract
            musharakah_contract = (
                musharakah_contract_termination_request.musharakah_contract_request
            )

            if (
                musharakah_contract_termination_request.termination_request_by
                != ContractTerminator.INVESTOR
            ):
                return generic_response(
                    message=JEWELER_MESSAGES["termination_request_by_jeweler"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            if not musharakah_contract_termination_request.cost_retail_payment_option:
                return generic_response(
                    message=INVESTOR_MESSAGES[
                        "manufacturing_cost_payment_option_not_selected"
                    ],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            payment_transaction = Transaction.objects.filter(
                musharakah_contract=musharakah_contract,
                status=TransactionStatus.PENDING,
                musharakah_contract_termination_payment_type=MusharakahContractTerminationPaymentType.INVESTOR_EARLY_TERMINATION_PAYMENT_TRANSACTION,
            ).first()

            if payment_transaction.status == TransactionStatus.APPROVED:
                return generic_response(
                    message=INVESTOR_MESSAGES[
                        "early_termination_fee_payment_already_processed"
                    ],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            # Fetch wallet of the jeweler’s business
            wallet = Wallet.objects.filter(business=business).first()
            payment_transaction.previous_balance = wallet.balance

            # Calculate amounts already hold or pending for withdrawal
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
                # Insufficient balance in jeweler’s wallet
                return generic_response(
                    message=ACCOUNT_MESSAGES["insufficient_balance"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Deduct termination fee from jeweler’s wallet
            wallet.balance -= payment_transaction.amount
            wallet.save()

            # Record the musharakah contract termination fee transaction in the Transaction table
            payment_transaction.status = TransactionStatus.APPROVED
            payment_transaction.current_balance = wallet.balance
            payment_transaction.payment_completed_at = timezone.now()
            payment_transaction.save()

            musharakah_contract_termination_request.is_investor_early_termination_payment = (
                True
            )
            musharakah_contract_termination_request.save()

            # Send notification to organization admins
            organization = user.organization_id

            if user.user_type == UserType.BUSINESS:
                user_type = "(Business)"
                name = business.name
            else:
                user_type = "(Individual)"
                name = user.fullname

            subject = "Musharakah Early Termination"
            if (
                musharakah_contract_termination_request.cost_retail_payment_option
                == CostRetailPaymentOption.PAY_RETAIL
            ):
                sub_total = max(
                    musharakah_contract.penalty_amount,
                    musharakah_contract_termination_request.retail_price,
                )
            else:
                sub_total = max(
                    musharakah_contract.penalty_amount,
                    musharakah_contract_termination_request.manufacturing_cost,
                )

            send_termination_reciept_mail.delay(
                user.pk,
                organization.pk,
                business.pk,
                payment_transaction.pk,
                musharakah_contract_termination_request.pk,
                subject,
                sub_total,
                subject,
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


class MusharakahContractAgreementAPIView(APIView):
    """Handles retrieving Musharakah Contract Agreement details for investor preview with proposed asset contributions."""

    permission_classes = [IsAuthenticated]
    serializer_class = MusharakahContractAgreementPreviewSerializer

    @swagger_auto_schema(
        operation_description="Preview musharakah contract agreement HTML with proposed asset contributions",
        request_body=MusharakahContractAgreementPreviewSerializer,
        responses={200: "HTML string response", 400: "Bad request", 404: "Not found"},
    )
    @PermissionManager(MUSHARAKAH_CONTRACT_REQUEST_VIEW_PERMISSION)
    def post(self, request, pk, *args, **kwargs):
        """Generates and returns HTML for Musharakah Contract Agreement preview with calculated contribution values."""
        from decimal import ROUND_HALF_UP
        from decimal import Decimal

        from investor.models import PurchaseRequest

        user = request.user
        organization = user.organization_id

        # Get business from token
        business = get_business_from_user_token(request, "business")
        if not business:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=INVESTOR_MESSAGES["business_account_not_found"],
            )

        # Validate request data
        serializer = MusharakahContractAgreementPreviewSerializer(data=request.data)
        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        # Get the musharakah contract request
        try:
            musharakah_contract_request = (
                MusharakahContractRequest.objects.select_related("jeweler", "investor")
                .prefetch_related(
                    "musharakah_contract_request_quantities__jewelry_product__product_materials",
                )
                .get(
                    id=pk,
                    organization_id=organization,
                )
            )
        except MusharakahContractRequest.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=JEWELER_MESSAGES["musharakah_contract_request_not_found"],
            )

        # Get validated asset contributions
        asset_contributions_data = serializer.validated_data.get(
            "asset_contributions", []
        )

        # Calculate the total price_locked value from the proposed purchase requests
        contribution_value = Decimal("0.00")

        # If no asset contributions provided, try to get from saved asset_contributions
        if not asset_contributions_data:
            # Calculate from saved asset_contributions if available
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
            purchase_request_ids = [
                contribution.get("purchase_request")
                for contribution in asset_contributions_data
            ]

            # Fetch all purchase requests in one query
            purchase_requests = PurchaseRequest.objects.filter(
                id__in=purchase_request_ids, business=business
            ).in_bulk()

            default_currency = OrganizationCurrency.objects.filter(
                organization=organization,
                is_default=True,
            ).first()

            for contribution_data in asset_contributions_data:
                pr_id = contribution_data.get("purchase_request")
                quantity = contribution_data.get("quantity")

                purchase_request = purchase_requests.get(pr_id)
                if not purchase_request:
                    return generic_response(
                        status_code=status.HTTP_404_NOT_FOUND,
                        error_message=INVESTOR_MESSAGES["purchase_request_not_found"],
                    )

                price_locked = self._calculate_price_locked_for_preview(
                    purchase_request,
                    default_currency,
                )

                # Calculate contribution value: price_locked * quantity
                item_total = price_locked * Decimal(str(quantity))
                contribution_value += item_total

            precious_items_value = contribution_value.quantize(
                Decimal("0.00"), rounding=ROUND_HALF_UP
            )

        # Serialize the contract data with request context
        # Use MusharakahContractRequestResponseSerializer instead of RetrieveSerializer
        # to avoid including contract_details which calculates from saved asset_contributions
        contract_serializer = MusharakahContractRequestResponseSerializer(
            musharakah_contract_request, context={"request": request}
        )
        serialized_data = contract_serializer.data

        # Generate HTML with the calculated contribution value
        try:
            html_string = self.generate_musharakah_contract_agreement_html(
                request,
                musharakah_contract_request,
                organization.name,
                organization.arabic_name or organization.name,
                serialized_data,
                precious_items_value,
            )
        except Exception as e:
            raise

        return generic_response(
            message=INVESTOR_MESSAGES["musharakah_contract_agreement_retrieved"],
            status_code=status.HTTP_200_OK,
            data=html_string,
        )

    def generate_musharakah_contract_agreement_html(
        self,
        request,
        musharakah_contract_request,
        organization_name,
        organization_arabic_name,
        serialized_contract,
        precious_items_value,
    ):
        """Generates HTML for Musharakah Contract Agreement with calculated investor contribution."""
        from decimal import Decimal

        # Determine the correct organization name based on request language
        current_language = translation.get_language()
        if current_language == "ar" and organization_arabic_name:
            org_name = organization_arabic_name
        else:
            org_name = organization_name

        context = {
            "musharakah_contract": self.generate_musharaka_contract_context_preview(
                musharakah_contract_request, serialized_contract, precious_items_value
            ),
            "organization_name": org_name,
        }
        html_string = render_to_string(
            "musharakah_contract/musharakah-contract-response.html",
            context,
        )
        return html_string

    def generate_musharaka_contract_context_preview(
        self,
        musharakah_contract_request,
        serialized_musharakah_contract,
        precious_items_value,
    ):
        """Generate contract context for preview with calculated contribution value."""
        from datetime import datetime
        from decimal import Decimal

        from sooq_althahab.billing.transaction.helpers import get_user_contact_details
        from sooq_althahab.enums.sooq_althahab_admin import MaterialType

        # === Jeweler details ===
        jeweler_data = serialized_musharakah_contract.get("jeweler") or {}
        jeweler_owner = jeweler_data.get("owner") or {}
        jeweler_address = (
            get_user_contact_details(jeweler_owner.get("id"))
            if jeweler_owner.get("id")
            else {}
        )

        # === Investor details ===
        investor_data = serialized_musharakah_contract.get("investor") or {}
        investor_owner = investor_data.get("owner") or {}
        investor_address = (
            get_user_contact_details(investor_owner.get("id"))
            if investor_owner.get("id")
            else {}
        )

        approved_at_str = serialized_musharakah_contract.get("approved_at")
        approved_at = None
        try:
            if approved_at_str:
                approved_at = datetime.fromisoformat(approved_at_str).date()
        except (ValueError, TypeError, AttributeError):
            approved_at = None

        expiry_date_str = serialized_musharakah_contract.get("expiry_date")

        # Safely get expiry_days from duration_in_days
        expiry_days = None
        try:
            if musharakah_contract_request.duration_in_days:
                expiry_days = musharakah_contract_request.duration_in_days.days
        except (AttributeError, TypeError):
            expiry_days = None

        # Calculate expiry_date properly with safe error handling
        expiry_date = None
        try:
            if expiry_date_str:
                expiry_date = datetime.fromisoformat(expiry_date_str).date()
            elif approved_at and expiry_days:
                # Calculate expiry date from approved_at + days
                expiry_date = approved_at + timedelta(days=expiry_days)
        except (ValueError, TypeError, AttributeError):
            expiry_date = None
        # If neither expiry_date_str nor approved_at+expiry_days, expiry_date remains None
        # and we'll show expiry_days in the template instead

        # === Jewelry Designs & Materials ===
        materials = []
        designs = []
        design_value = Decimal("0.00")

        designs_data = (
            serialized_musharakah_contract.get("musharakah_contract_designs", []) or []
        )

        jewelry_products = [
            product
            for item in designs_data
            for product in (item.get("design", {}).get("jewelry_products") or [])
        ]

        quantities_map = {
            requested_quantity.get("jewelry_product"): requested_quantity.get(
                "quantity"
            )
            for requested_quantity in serialized_musharakah_contract.get(
                "musharakah_contract_request_quantities", []
            )
        }

        for product in jewelry_products:
            designs.append(product.get("product_name", "N/A"))
            price = Decimal(str(product.get("price", 0) or 0))
            design_value += price

            for material in product.get("product_materials", []) or []:
                materials.append(
                    {
                        "item": material.get("material_item", "N/A"),
                        "quantity": quantities_map.get(
                            product.get("id"), material.get("quantity", 0)
                        ),
                        "weight": material.get("weight", 0),
                        "weight_unit": (
                            "g"
                            if material.get("material_type") == MaterialType.METAL
                            else "ct"
                        ),
                        "carat_type": material.get("carat_type", "N/A"),
                        "type": material.get("material_type", "N/A"),
                    }
                )

        investor_signature = (
            serialized_musharakah_contract.get("investor_signature") or {}
        )
        investor_signature_url = (
            investor_signature.get("url", "")
            if isinstance(investor_signature, dict)
            else ""
        )

        jeweler_signature = (
            serialized_musharakah_contract.get("jeweler_signature") or {}
        )
        jeweler_signature_url = (
            jeweler_signature.get("url", "")
            if isinstance(jeweler_signature, dict)
            else ""
        )

        return {
            "jeweler": {
                "name": jeweler_data.get("name") or jeweler_owner.get("name", "N/A"),
                "address": jeweler_address.get("address", "N/A"),
                "country": jeweler_address.get("country", "N/A"),
                "phone": jeweler_owner.get("phone_number", "N/A"),
            },
            "investor": {
                "name": investor_data.get("name") or investor_owner.get("name", "N/A"),
                "address": investor_address.get("address", "N/A"),
                "country": investor_address.get("country", "N/A"),
                "phone": investor_owner.get("phone_number", "N/A"),
            },
            "materials": materials,
            "designs": designs,
            "precious_items_value": precious_items_value,
            "design_value": design_value,
            "business_capital_value": str(
                (precious_items_value + design_value).quantize(Decimal("0.01"))
            ),
            "penalty_amount": serialized_musharakah_contract.get(
                "penalty_amount", Decimal("0.00")
            ),
            "expiry_date": expiry_date,
            "expiry_days": expiry_days,
            "investor_profit_sharing_ratio": serialized_musharakah_contract.get(
                "musharakah_equity", 0
            ),
            "jeweler_profit_sharing_ratio": Decimal("100.00")
            - Decimal(
                str(serialized_musharakah_contract.get("musharakah_equity", 0) or 0)
            ),
            "approved_at": approved_at or "N/A",
            "investor_signature": investor_signature_url,
            "jeweler_signature": jeweler_signature_url,
        }

    def _calculate_price_locked_for_preview(self, purchase_request, currency_obj):
        """Return unit price for stones (saved) and computed live unit price for metals.

        For preview we compute current metal price from latest `MetalPriceHistory` and
        keep stones at their saved `price_locked`.
        """
        try:
            if not currency_obj:
                return Decimal(0)

            precious_item = purchase_request.precious_item
            material_type = getattr(precious_item, "material_type", None)

            # Stones: use saved unit price (price_locked is total for qty=1)
            if material_type == MaterialType.STONE:
                stone_price = Decimal(str(purchase_request.price_locked or 0))
                return stone_price

            # Metals: compute from latest metal price history
            global_metal = precious_item.material_item.global_metal

            latest_metal_price = (
                MetalPriceHistory.objects.filter(global_metal=global_metal)
                .order_by("global_metal", "-created_at")
                .first()
            )
            if not latest_metal_price:
                return Decimal(0)

            carat_type = precious_item.carat_type
            carat_number = int(str(carat_type.name).rstrip("k")) if carat_type else 24

            price_per_unit = (
                Decimal(carat_number) * Decimal(latest_metal_price.price)
            ) / Decimal(24)

            weight = (
                Decimal(str(precious_item.precious_metal.weight))
                if getattr(precious_item, "precious_metal", None)
                and precious_item.precious_metal
                else Decimal(0)
            )

            exchange_rate = Decimal(str(currency_obj.rate))

            # Return unit price (for one asset unit); caller multiplies by quantity
            final_price = (Decimal(price_per_unit) * weight * exchange_rate).quantize(
                Decimal("0.01")
            )
            return final_price

        except Exception as e:
            raise serializers.ValidationError(INVESTOR_MESSAGES["something_wrong"])


class MusharakahContractProfitAPIView(APIView):
    """API view to get total profit from musharakah contracts for investor."""

    permission_classes = [IsAuthenticated]
    serializer_class = MusharakahContractProfitSerializer

    def get(self, request, *args, **kwargs):
        """Get total profit from musharakah contract profit distributions."""
        user = request.user

        if user.is_anonymous:
            return generic_response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_message=INVESTOR_MESSAGES["business_account_not_found"],
            )

        # Get business from token
        business = get_business_from_user_token(request, "business")
        if not business:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=INVESTOR_MESSAGES["business_account_not_found"],
            )

        # Filter transactions where:
        # - to_business = investor's business
        # - profit_distribution is not null
        # - profit_distribution.musharakah_contract is not null
        # - status = SUCCESS
        total_profit = Transaction.objects.filter(
            to_business=business,
            profit_distribution__isnull=False,
            profit_distribution__musharakah_contract__isnull=False,
            status=TransactionStatus.SUCCESS,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        # Ensure total_profit is a Decimal
        if not isinstance(total_profit, Decimal):
            total_profit = Decimal(str(total_profit))

        data = {
            "total_profit": total_profit,
        }

        serializer = self.serializer_class(data)
        return generic_response(
            data=serializer.data,
            message=INVESTOR_MESSAGES["musharakah_contract_profit_retrieved"],
            status_code=status.HTTP_200_OK,
        )
