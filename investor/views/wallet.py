import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models import Case
from django.db.models import CharField
from django.db.models import Q
from django.db.models import Value
from django.db.models import When
from django.http import Http404
from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.generics import CreateAPIView
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.status import HTTP_200_OK
from rest_framework.status import HTTP_201_CREATED
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.status import HTTP_404_NOT_FOUND
from rest_framework.views import APIView

from account.models import Transaction
from account.models import Wallet
from account.serializers import WalletSerializer
from account.utils import get_user_or_business_name
from investor.message import MESSAGES
from investor.serializers import DepositTransactionSerializer
from investor.serializers import TransactionDetailResponseSerializer
from investor.serializers import TransactionResponseSerializer
from investor.serializers import WithdrawTransactionSerializer
from investor.utils import get_transaction_object
from sooq_althahab.billing.subscription.pdf_utils import render_subscription_invoice_pdf
from sooq_althahab.billing.transaction.helpers import (
    get_transaction_receipt_context_and_template,
)
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransferVia
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.account import UserType
from sooq_althahab.enums.investor import RequestType
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.tasks import send_receipt_to_mail
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab.utils import send_notifications_to_organization_admins
from sooq_althahab_admin.filters import TransactionFilter

logger = logging.getLogger(__name__)


class WalletAPIView(RetrieveAPIView):
    """Retrieve wallet balance for the authenticated user."""

    serializer_class = WalletSerializer
    permission_classes = [IsAuthenticated]
    queryset = Wallet.objects.all()

    def get(self, request, *args, **kwargs):
        try:
            business = get_business_from_user_token(request, "business")
            wallet = self.queryset.get(business=business)
            serializer = self.get_serializer(wallet)
            return generic_response(
                status_code=HTTP_200_OK,
                message=MESSAGES["wallet_balance_retrieved"],
                data=serializer.data,
            )
        except:
            return generic_response(
                status_code=HTTP_404_NOT_FOUND,
                error_message=MESSAGES["wallet_not_found"],
            )


class WalletTopUpViaAdminAPIView(CreateAPIView):
    """Handles top-up transactions via admin."""

    permission_classes = [IsAuthenticated]
    serializer_class = DepositTransactionSerializer
    response_serializer_class = TransactionResponseSerializer

    def post(self, request):
        user = request.user
        organization_code = request.auth.get("organization_code")

        name = get_user_or_business_name(request)
        if not name:
            generic_response(
                status_code=HTTP_404_NOT_FOUND,
                message=MESSAGES["business_account_not_found"],
            )

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        transaction = serializer.save()

        # Send notification to admin
        title = "Top-up request"
        user_type = (
            "(Business)" if user.user_type == UserType.BUSINESS else "(Individual)"
        )
        message = (
            f"'{name}' {user_type} has requested a top-up of BHD {transaction.amount}."
        )
        send_notifications_to_organization_admins(
            organization_code,
            title,
            message,
            NotificationTypes.DEPOSIT_REQUEST_CREATED,
            ContentType.objects.get_for_model(Transaction),
            transaction.id,
            UserRoleChoices.ADMIN,
        )

        return generic_response(
            status_code=HTTP_201_CREATED,
            message=MESSAGES["deposit_request_created"],
            data=self.response_serializer_class(transaction).data,
        )


class WalletWithdrawAPIView(CreateAPIView):
    """Handles withdraw transactions."""

    permission_classes = [IsAuthenticated]
    serializer_class = WithdrawTransactionSerializer
    response_serializer_class = TransactionResponseSerializer

    def post(self, request):
        user = request.user
        organization_code = request.auth.get("organization_code")

        # If investor is individual then pass full name or else pass business name
        name = get_user_or_business_name(request)

        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        transaction = serializer.save()

        # Send notification to admin
        title = "Withdraw request"
        user_type = (
            "(Business)" if user.user_type == UserType.BUSINESS else "(Individual)"
        )
        message = f"'{name}' {user_type} has requested a withdraw of BHD {transaction.amount}."
        send_notifications_to_organization_admins(
            organization_code,
            title,
            message,
            NotificationTypes.WITHDRAW_REQUEST_CREATED,
            ContentType.objects.get_for_model(Transaction),
            transaction.id,
            UserRoleChoices.ADMIN,
        )

        return generic_response(
            status_code=HTTP_201_CREATED,
            message=MESSAGES["withdraw_request_created"],
            data=self.response_serializer_class(transaction).data,
        )


class TransactionListAPIView(ListAPIView):
    """Retrieve all transactions for the authenticated user."""

    serializer_class = TransactionResponseSerializer
    permission_classes = [IsAuthenticated]
    queryset = Transaction.global_objects.exclude(
        transfer_via=TransferVia.BENEFIT_PAY, status=TransactionStatus.PENDING
    ).select_related("from_business", "to_business", "purchase_request", "created_by")
    pagination_class = CommonPagination
    filterset_class = TransactionFilter
    filter_backends = (DjangoFilterBackend,)

    def get_queryset(self):
        user = self.request.user

        if not user.is_authenticated:
            return self.queryset.none()

        # Get user's business
        try:
            business = get_business_from_user_token(self.request, "business")
        except:
            return self.queryset.none()

        return (
            self.queryset.filter(Q(from_business=business) | Q(to_business=business))
            .order_by("-created_at")
            .annotate(
                transaction_source_type=Case(
                    When(
                        purchase_request__isnull=False, then=Value("purchase_request")
                    ),
                    When(
                        manufacturing_request__isnull=False,
                        then=Value("manufacturing_request"),
                    ),
                    When(
                        jewelry_production__isnull=False,
                        then=Value("jewelry_production"),
                    ),
                    When(
                        business_subscription__isnull=False,
                        then=Value("business_subscription"),
                    ),
                    default=Value("other"),
                    output_field=CharField(),
                )
            )
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=HTTP_200_OK,
            message=MESSAGES["transactions_fetched"],
            data=response_data,
        )


class TransactionDetailAPIView(RetrieveAPIView):
    """Retrieve a specific transaction by ID."""

    permission_classes = [IsAuthenticated]
    serializer_class = TransactionDetailResponseSerializer

    queryset = Transaction.global_objects.select_related(
        "from_business",
        "to_business",
        "purchase_request",
        "manufacturing_request",
        "jewelry_production",
        "business_subscription",
        "created_by",
    ).annotate(
        transaction_source_type=Case(
            When(purchase_request__isnull=False, then=Value("purchase_request")),
            When(
                manufacturing_request__isnull=False, then=Value("manufacturing_request")
            ),
            When(jewelry_production__isnull=False, then=Value("jewelry_production")),
            When(
                business_subscription__isnull=False, then=Value("business_subscription")
            ),
            default=Value("other"),
            output_field=CharField(),
        )
    )

    def get(self, request, *args, **kwargs):
        try:
            transaction = self.get_object()
            serializer = self.get_serializer(transaction)
            return generic_response(
                status_code=HTTP_200_OK,
                message=MESSAGES["transaction_retrieved"],
                data=serializer.data,
            )
        except Http404:
            return generic_response(
                status_code=HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["transaction_not_found"],
            )


class TransactionReceiptDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        """Handle GET request to download wallet transaction as PDF."""
        organization = request.user.organization_id

        transaction = get_transaction_object(pk)

        context, template_name, filename = get_transaction_receipt_context_and_template(
            transaction, organization
        )
        if not context:
            return generic_response(
                message=MESSAGES["transaction_type_invalid"],
                status_code=HTTP_400_BAD_REQUEST,
            )

        pdf_file = render_subscription_invoice_pdf(template_name, context)

        return HttpResponse(
            pdf_file,
            content_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


class TransactionReceiptEmailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        """Send transaction receipt/invoice PDF via email."""
        user = request.user
        organization = user.organization_id

        transaction = get_transaction_object(pk)

        context, template_name, filename = get_transaction_receipt_context_and_template(
            transaction, organization
        )
        if not context:
            return generic_response(
                message=MESSAGES["transaction_type_invalid"],
                status_code=HTTP_400_BAD_REQUEST,
            )

        business = get_business_from_user_token(request, "business")
        purchase_request = getattr(transaction, "purchase_request", None)

        if business.business_account_type == "SELLER":
            if purchase_request.request_type == RequestType.PURCHASE:
                amount = purchase_request.order_cost + purchase_request.premium
            else:
                amount = (
                    purchase_request.order_cost
                    if purchase_request.request_type == RequestType.SALE
                    else transaction.amount
                )
        else:
            amount = transaction.amount

        email_context = {
            "business_name": business.name,
            "transaction_id": transaction.id,
            "date": transaction.created_at.date(),
            "amount": amount,
            "organization_logo_url": context.get("organization_logo_url", ""),
        }

        send_receipt_to_mail.delay(
            user.email, email_context, context, template_name, filename
        )
        return generic_response(
            status_code=HTTP_200_OK,
            message=MESSAGES["transaction_receipt_mailed"],
        )
