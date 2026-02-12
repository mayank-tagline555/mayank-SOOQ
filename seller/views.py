from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import CharField
from django.db.models import Count
from django.db.models import F
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import Sum
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.http import Http404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.generics import ListCreateAPIView
from rest_framework.generics import RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.validators import ValidationError
from rest_framework.views import APIView

from account.message import MESSAGES as ACCOUNT_MESSAGE
from account.mixins import ReceiptNumberMixin
from account.models import Address
from account.models import CountryToContinent
from account.models import Organization
from account.models import Transaction
from account.models import User
from account.models import UserAssignedBusiness
from account.models import Wallet
from investor.message import MESSAGES as INVESTOR_MESSAGE
from investor.models import PreciousItemUnit
from investor.models import PurchaseRequest
from investor.utils import get_total_withdrawal_pending_amount
from seller.filters import PreciousItemFilter
from seller.filters import PurchaseRequestFilter
from sooq_althahab.constants import ADMINS_PRECIOUS_ITEM_VIEW_PERMISSION
from sooq_althahab.constants import PRECIOUS_ITEM_CHANGE_PERMISSION
from sooq_althahab.constants import PRECIOUS_ITEM_CREATE_PERMISSION
from sooq_althahab.constants import PRECIOUS_ITEM_DELETE_PERMISSION
from sooq_althahab.constants import PRECIOUS_ITEM_VIEW_PERMISSION
from sooq_althahab.constants import PURCHASE_REQUEST_VIEW_PERMISSION
from sooq_althahab.constants import SELLER_DASHBOARD_VIEW_PERMISSION
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.enums.investor import RequestType
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.helper import PermissionManager
from sooq_althahab.querysets.purchase_request import base_purchase_request_queryset
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.tasks import send_notification
from sooq_althahab.tasks import send_purchase_request_email
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab.utils import send_notification_count_to_users
from sooq_althahab.utils import send_notifications_to_organization_admins
from sooq_althahab_admin.models import Notification

from .message import MESSAGES
from .models import PreciousItem
from .serializers import CreatePreciousItemSerializer
from .serializers import PreciousItemBaseSerializer
from .serializers import PreciousItemReportNumberSerializer
from .serializers import PreciousItemResponseSerializer
from .serializers import PurchaseRequestResponseSerializer
from .serializers import SaleRequestDeductionAmountSerializer
from .serializers import SalesByContinentSerializer
from .serializers import SellerDashboardSerializer
from .serializers import UpdatePreciousItemSerializer
from .utils import get_fcm_tokens_for_users
from .utils import get_sales_data


class BasePreciousItemView:
    """
    Base view class for precious items (metals and stones).
    This class is responsible for filtering the queryset based on the user's business.
    """

    pagination_class = CommonPagination
    permission_classes = [IsAuthenticated]
    serializer_class = CreatePreciousItemSerializer
    queryset = PreciousItem.objects.select_related(
        "material_item", "precious_metal", "precious_stone"
    ).prefetch_related("images")

    def get_queryset(self):
        """Returns a filtered queryset based on the user's assigned business."""

        if self.request.user.is_anonymous:
            return PreciousItem.objects.none()

        queryset = self.queryset.annotate(
            completed_asset_purchase_request_count=Coalesce(
                Count(
                    "purchase_requests",
                    filter=Q(
                        purchase_requests__status=PurchaseRequestStatus.COMPLETED,
                        purchase_requests__request_type=RequestType.PURCHASE,
                    ),
                    distinct=True,
                ),
                Value(0),
            )
        )

        # Get the business
        business = get_business_from_user_token(self.request, "business")

        # Filter by business if provided, otherwise filter by the user's business
        if not business:
            return queryset.none()
        return queryset.filter(business=business)


class PreciousItemListCreateView(BasePreciousItemView, ListCreateAPIView):
    """
    Handles listing and creating precious metal items.
    """

    # Define the serializer for both list and create actions
    serializer_class = CreatePreciousItemSerializer  # We will use this for POST (creation), modify if needed

    # Use DjangoFilterBackend to enable filtering through query params
    filter_backends = (DjangoFilterBackend,)
    filterset_class = PreciousItemFilter  # Apply the filter set

    def get_serializer_class(self):
        if self.request.method in ["POST"]:
            return CreatePreciousItemSerializer
        return PreciousItemResponseSerializer

    @swagger_auto_schema(
        operation_description="Retrieve a list of Precious Metals with applied filters.",
        manual_parameters=[
            openapi.Parameter(
                "ordering",
                openapi.IN_QUERY,
                description="Order by `created_at, weight` field. Use `-` to sort in descending order.\n\n**Example**: `-created_at`.",
                type=openapi.TYPE_STRING,
            ),
            openapi.Parameter(
                "is_enabled",
                openapi.IN_QUERY,
                description="Filter by enabled status (true or false).\n\n**Example**: `true`",
                type=openapi.TYPE_BOOLEAN,
            ),
            openapi.Parameter(
                "material_type",
                openapi.IN_QUERY,
                description="Filter by material type (metal/stone).\n\n**Example**: `metal`",
                type=openapi.TYPE_STRING,
            ),
            openapi.Parameter(
                "material_item",
                openapi.IN_QUERY,
                description="Filter by material item.\n\n**Example**: `Gold, Silver, Ruby, etc.`",
                type=openapi.TYPE_STRING,
            ),
        ],
        responses={200: PreciousItemResponseSerializer(many=True)},
    )
    @PermissionManager(PRECIOUS_ITEM_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Retrieve a list of Precious Metals with applied filters."""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(response_data)

    @PermissionManager(PRECIOUS_ITEM_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        """Create a new Precious Item."""

        # Use the CreatePreciousMetalSerializer to create a new PreciousMetal, including related models
        try:
            serializer = self.get_serializer(data=request.data)
            if serializer.is_valid():
                # This will also create PreciousItem and PreciousItemImages
                precious_item = serializer.save()
                return generic_response(
                    data=PreciousItemBaseSerializer(precious_item).data,
                    message=MESSAGES["precious_metal_item_created"],
                    status_code=status.HTTP_201_CREATED,
                )
            return handle_serializer_errors(serializer)
        except ValidationError as ve:
            return generic_response(
                data=None,
                error_message=ve.detail[0],
                status_code=status.HTTP_400_BAD_REQUEST,
            )


class AdminPreciousItemListView(ListAPIView):
    """list of admins precious items."""

    pagination_class = CommonPagination
    permission_classes = [IsAuthenticated]
    serializer_class = PreciousItemBaseSerializer

    def get_queryset(self):
        queryset = PreciousItem.objects.select_related(
            "material_item", "precious_metal", "precious_stone"
        ).prefetch_related("images")

        return queryset.filter(created_by__in=settings.DEFAULT_SELLER_IDS)

    filter_backends = (DjangoFilterBackend,)
    filterset_class = PreciousItemFilter

    @swagger_auto_schema(
        operation_description="Retrieve a list of Precious Metals with applied filters.",
        manual_parameters=[
            openapi.Parameter(
                "ordering",
                openapi.IN_QUERY,
                description="Order by `created_at, weight` field. Use `-` to sort in descending order.\n\n**Example**: `-created_at`.",
                type=openapi.TYPE_STRING,
            ),
            openapi.Parameter(
                "is_enabled",
                openapi.IN_QUERY,
                description="Filter by enabled status (true or false).\n\n**Example**: `true`",
                type=openapi.TYPE_BOOLEAN,
            ),
            openapi.Parameter(
                "material_type",
                openapi.IN_QUERY,
                description="Filter by material type (metal/stone).\n\n**Example**: `metal`",
                type=openapi.TYPE_STRING,
            ),
            openapi.Parameter(
                "material_item",
                openapi.IN_QUERY,
                description="Filter by material item.\n\n**Example**: `Gold, Silver, Ruby, etc.`",
                type=openapi.TYPE_STRING,
            ),
        ],
        responses={200: PreciousItemResponseSerializer(many=True)},
    )
    @PermissionManager(ADMINS_PRECIOUS_ITEM_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Retrieve a list of Admins Precious Metals with applied filters."""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(response_data)


class PreciousItemRetrieveUpdateDeleteView(
    BasePreciousItemView, RetrieveUpdateDestroyAPIView
):
    """
    Handles retrieving, updating, and deleting a single Precious Item.
    """

    http_method_names = ["get", "patch", "delete"]

    def get_serializer_class(self):
        if self.request.method in ["PATCH"]:
            return UpdatePreciousItemSerializer
        return PreciousItemResponseSerializer

    @PermissionManager(PRECIOUS_ITEM_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Retrieve a specific Precious Item."""

        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance).data

            return generic_response(
                data=serializer,
                message=MESSAGES["precious_item_fetched"],
                status_code=status.HTTP_200_OK,
            )
        except Http404:
            return generic_response(
                error_message=MESSAGES["precious_item_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

    @PermissionManager(PRECIOUS_ITEM_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        """Update a specific Precious Item."""

        try:
            try:
                instance = self.get_object()
            except Http404:
                return generic_response(
                    error_message=MESSAGES["precious_item_not_found"],
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            if serializer.is_valid():
                precious_item = serializer.save()
                precious_item.refresh_from_db()
                return generic_response(
                    data=PreciousItemResponseSerializer(precious_item).data,
                    message=MESSAGES["precious_item_updated"],
                )
            return handle_serializer_errors(serializer)
        except ValidationError as ve:
            return generic_response(
                error_message=str(ve.detail[0]), status_code=status.HTTP_400_BAD_REQUEST
            )

    @PermissionManager(PRECIOUS_ITEM_DELETE_PERMISSION)
    def delete(self, request, *args, **kwargs):
        """Delete or disable a specific Precious Item."""
        try:
            instance = self.get_object()

            # Check if the item is linked to any purchase requests
            is_linked = instance.purchase_requests.exists()

            if is_linked:
                # Disable instead of delete
                instance.is_enabled = False
                instance.save(update_fields=["is_enabled"])
                message = MESSAGES["precious_item_disabled"]
            else:
                # Safe to delete if unlinked
                instance.delete()
                message = MESSAGES["precious_item_deleted"]

            return generic_response(
                message=message,
                status_code=status.HTTP_200_OK,
            )

        except Http404:
            return generic_response(
                error_message=MESSAGES["precious_item_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )


#####################################################################################
################################## Purchase Request APIs ############################
#####################################################################################

from rest_framework.generics import UpdateAPIView

from .serializers import UpdatePurchaseRequestStatusSerializer


class BasePurchaseRequestView:
    permission_classes = [IsAuthenticated]
    serializer_class = PurchaseRequestResponseSerializer

    def get_queryset(self):
        """
        Returns a filtered queryset based on the user's assigned business.
        Adds creator_full_name annotation.
        """
        if self.request.user.is_anonymous:
            return PurchaseRequest.objects.none()

        # Filter by business if provided, otherwise by precious items creator (Seller)
        business = get_business_from_user_token(self.request, "business")
        if not business:
            return PurchaseRequest.objects.none()
        return base_purchase_request_queryset().filter(precious_item__business=business)


class PurchaseRequestListView(BasePurchaseRequestView, ListAPIView):
    """Handles listing and creating purchase requests."""

    pagination_class = CommonPagination
    filter_backends = (DjangoFilterBackend,)
    filterset_class = PurchaseRequestFilter

    @PermissionManager(PURCHASE_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["purchase_request_fetched"],
            data=response_data,
        )


class UpdatePurchaseRequestStatusView(UpdateAPIView):
    permission_classes = [IsAuthenticated]

    serializer_class = UpdatePurchaseRequestStatusSerializer
    http_method_names = ["patch"]

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return PurchaseRequest.objects.none()

        business = get_business_from_user_token(self.request, "business")

        queryset = PurchaseRequest.global_objects.select_related(
            "precious_item", "precious_item__business"
        ).filter(precious_item__business=business)

        return queryset

    def send_notifications(
        self, users, title, message, notification_type, content_type, object_id
    ):
        """
        Sends notifications to specified users.

        This method retrieves the FCM tokens for the given users and sends push notifications asynchronously.
        Additionally, it creates in-app notification records for each user.
        """

        # Extract user IDs from the QuerySet/list of users
        # get_fcm_tokens_for_users expects a list of user IDs, not User objects
        if hasattr(users, "values_list"):
            # If it's a QuerySet, extract IDs efficiently
            user_ids = list(users.values_list("id", flat=True))
        else:
            # If it's already a list, extract IDs from User objects
            user_ids = [user.id for user in users] if users else []

        # Get all FCM tokens for the users
        tokens = get_fcm_tokens_for_users(user_ids)

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

        # Serialize just **one** notification (since all are identical)
        notification_data = {
            "notification_type": notification_type,
            "id": str(object_id),
        }
        # Send a bulk push notification asynchronously
        send_notification_count_to_users(users)
        send_notification.delay(tokens, title, message, notification_data)

    def patch(self, request, *args, **kwargs):
        user = request.user
        organization_code = request.auth.get("organization_code")
        try:
            purchase_request_instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=INVESTOR_MESSAGE["purchase_request_not_found"],
            )

        purchase_request_serializer = self.get_serializer(
            purchase_request_instance, data=request.data, partial=True
        )
        if not purchase_request_serializer.is_valid():
            return handle_serializer_errors(purchase_request_serializer)

        purchase_request_status = purchase_request_serializer.validated_data["status"]
        request_type = purchase_request_instance.request_type
        precious_item = purchase_request_instance.precious_item

        # Check if the purchase request status is "APPROVED" and request type is "PURCHASE"
        request_type_purchase = request_type == RequestType.PURCHASE

        # Determine if this is an approval action that should trigger payment
        # Flow for sale requests: PENDING_SELLER_PRICE -> PENDING_INVESTOR_CONFIRMATION -> PENDING (investor approved) -> APPROVED (seller approves, triggers payment)
        # Flow for purchase requests: PENDING -> APPROVED (seller approves, triggers payment)
        purchase_request_status_approved = (
            purchase_request_status == PurchaseRequestStatus.APPROVED
        )

        # =============================
        # 📌 Handle Serial Numbers here
        # =============================
        serial_numbers = request.data.get("serial_numbers", [])

        if purchase_request_status_approved:
            if request_type_purchase:
                # Check duplicates already existing in DB for this seller
                existing_serials = PreciousItemUnit.objects.filter(
                    precious_item=precious_item,
                    serial_number__in=serial_numbers,
                ).values_list("serial_number", flat=True)

                if existing_serials:
                    duplicates_str = ", ".join(sorted(existing_serials))
                    return generic_response(
                        status_code=status.HTTP_404_NOT_FOUND,
                        error_message=MESSAGES["serial_number_already_exist"].format(
                            serial_numbers=duplicates_str
                        ),
                    )

                # Create PreciousItemUnit for each serial
                units_to_create = [
                    PreciousItemUnit(
                        purchase_request=purchase_request_instance,
                        precious_item=precious_item,
                        serial_number=serial_number,
                    )
                    for serial_number in serial_numbers
                ]
                PreciousItemUnit.objects.bulk_create(units_to_create)

            else:  # SALE request
                qty_to_sell = purchase_request_instance.requested_quantity
                related_purchase_request = (
                    purchase_request_instance.related_purchase_request
                )

                # Serial numbers are required for SALE requests
                if not serial_numbers:
                    return generic_response(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        error_message=MESSAGES["serial_number_required"],
                    )

                # Base query for available units (exclude partially used units)
                # Partially used units are those returned from musharakah with payment_allocations
                # IMPORTANT: Units that are already in musharakah contracts or pools CANNOT be sold
                # They must be released from those allocations first before they can be sold
                base_queryset = PreciousItemUnit.objects.filter(
                    precious_item=precious_item,
                    purchase_request=related_purchase_request,
                    sale_request__isnull=True,  # Not already sold
                    musharakah_contract__isnull=True,  # Not in musharakah contract
                    pool__isnull=True,  # Not in pool
                    payment_allocations__isnull=True,  # Exclude partially used units
                )

                # Filter by the specific serial numbers provided
                available_units = base_queryset.filter(serial_number__in=serial_numbers)

                # Check if all provided serial numbers were found
                found_serial_numbers = set(
                    available_units.values_list("serial_number", flat=True)
                )
                provided_serial_numbers = set(serial_numbers)

                if len(found_serial_numbers) != len(provided_serial_numbers):
                    missing_serials = provided_serial_numbers - found_serial_numbers
                    missing_str = ", ".join(sorted(missing_serials))
                    return generic_response(
                        status_code=status.HTTP_404_NOT_FOUND,
                        error_message=MESSAGES[
                            "serial_number_not_found_or_unavailable"
                        ].format(serial_numbers=missing_str),
                    )

                # Validate that the count matches the requested quantity
                if available_units.count() != qty_to_sell:
                    return generic_response(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        error_message=MESSAGES["serial_number_quantity_mismatch"],
                    )

                unit_ids = [u.id for u in available_units]

                # When approving a sale request, set sale_request FK
                # Note: We don't need to clear musharakah_contract and pool here because
                # the query above already ensures these are null (units must not be in musharakah or pool to create sale request)
                PreciousItemUnit.objects.filter(id__in=unit_ids).update(
                    sale_request=purchase_request_instance,
                )

        # Set approved_at and invoice_number if approving
        if purchase_request_status_approved:
            if not purchase_request_instance.approved_at:
                purchase_request_instance.approved_at = timezone.now()
            if not purchase_request_instance.invoice_number:
                mixin = ReceiptNumberMixin()
                purchase_request_instance.invoice_number = (
                    mixin.generate_receipt_number(
                        users_business=purchase_request_instance.business,
                        model_cls=PurchaseRequest,
                    )
                )

        # Fetch requesting business (could be investor or jeweler) and seller business instances
        try:
            requesting_business_instance = purchase_request_instance.business
            seller_business_instance = precious_item.business
        except Exception as e:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=ACCOUNT_MESSAGE["business_account_not_found"],
            )

        # Fetch users and tokens for notifications
        # Note: requesting_business_instance can be either an INVESTOR or JEWELER business
        # Query users directly from each business to ensure we get all users correctly
        users_in_seller_business = User.objects.filter(
            user_assigned_businesses__business=seller_business_instance,
            user_preference__notifications_enabled=True,
        ).distinct()

        # This includes users from both investor and jeweler businesses that made the purchase request
        # Query directly from the requesting business to ensure all users are included
        users_in_requesting_business = User.objects.filter(
            user_assigned_businesses__business=requesting_business_instance,
            user_preference__notifications_enabled=True,
        ).distinct()

        # Keep the old variable name for backward compatibility with rest of the code
        users_in_investor_business = users_in_requesting_business
        investor_business_instance = requesting_business_instance

        # Determine which notification type to send based on the request type PURCHASE/SALE
        if request_type_purchase:  # PURCHASE request
            notification_type = (
                NotificationTypes.PURCHASE_REQUEST_APPROVED
                if purchase_request_status_approved
                else NotificationTypes.PURCHASE_REQUEST_REJECTED
            )

        else:  # SALE request
            notification_type = (
                NotificationTypes.SALE_REQUEST_APPROVED
                if purchase_request_status_approved
                else NotificationTypes.SALE_REQUEST_REJECTED
            )

        # Handle asset approval and transactions
        if purchase_request_status_approved:
            purchase_request_instance.action_by = user

            wallet_manager = Wallet.objects
            try:
                investor_business_wallet = wallet_manager.get(
                    business=investor_business_instance
                )
                seller_business_wallet = wallet_manager.get(
                    business=seller_business_instance
                )
            except Wallet.DoesNotExist:
                return generic_response(
                    error_message=MESSAGES["wallet_not_found"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Determine which wallet to deduct and credit
            # Amount_to_deduct refers to the amount that will be deducted from the user's wallet.
            if request_type_purchase:  # PURCHASE request
                from_wallet = investor_business_wallet
                to_wallet = seller_business_wallet
                transaction_type_text = RequestType.PURCHASE
                amount_to_deduct = purchase_request_instance.total_cost
            else:  # SALE request
                from_wallet = seller_business_wallet
                to_wallet = investor_business_wallet
                transaction_type_text = RequestType.SALE
                amount_to_deduct = purchase_request_instance.order_cost
                if precious_item.material_type == MaterialType.STONE:
                    precious_item.is_enabled = True
                    precious_item.save()

            # Check if balance is sufficient
            # Total pending withdrawals for business
            """
            ⚠️ IMPORTANT NOTE ABOUT PENDING WITHDRAWAL BALANCE CHECK

            Currently, the total pending withdrawal amount is calculated using
            `seller_business_instance`, regardless of which business wallet is
            actually being debited (`from_wallet`).

            This works correctly in SALE requests because:
                - The seller is the payer (from_wallet.business == seller_business_instance)

            However, in PURCHASE requests:
                - The investor/requesting business is the payer
                - The pending withdrawal calculation still uses seller_business_instance
                - This may lead to incorrect balance validation

            Potential Risks:
                - If the investor has large pending withdrawals, they may be able to
                overspend because their own pending withdrawals are not considered.
                - If the seller has large pending withdrawals, a valid purchase may be
                incorrectly rejected.

            Recommended Future Improvement:
                The pending withdrawal calculation should use `from_wallet.business`
                instead of `seller_business_instance` to ensure the balance check is
                always performed against the actual payer.

            This would ensure consistent financial validation across both
            PURCHASE and SALE flows.

            """
            total_withdrawal_pending_amount = get_total_withdrawal_pending_amount(
                seller_business_instance  # from_wallet.business
            )

            if (
                from_wallet.balance - total_withdrawal_pending_amount
            ) < amount_to_deduct:
                return generic_response(
                    error_message=INVESTOR_MESSAGE["insufficient_balance"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Atomic transaction
            """
            ⚠️ IMPORTANT NOTE ABOUT TRANSACTIONAL CONSISTENCY

            Some approval-related operations (such as serial number creation/update,
            approved_at assignment, and invoice generation) occur before entering
            the `transaction.atomic()` block that handles wallet deduction and
            transaction creation.

            If an exception occurs during the wallet transfer process,
            the financial transaction will roll back, but earlier operations
            (serial number changes or metadata updates) will not.

            This may lead to temporary data inconsistency between:
                - Inventory state
                - Purchase request metadata
                - Financial transaction records

            Future improvement:
            Consider wrapping all approval-related operations inside a single
            `transaction.atomic()` block to ensure full consistency.
            """

            with transaction.atomic():
                savepoint = transaction.savepoint()

                """
                NOTE:

                `base_order_cost` is calculated differently for PURCHASE and SALE
                requests (including premium for purchase).

                Currently, this variable is not used in the subsequent logic.
                """

                if request_type_purchase:
                    # If purchase request, seller gets base order cost = order cost + premium
                    base_order_cost = (
                        purchase_request_instance.order_cost
                        + purchase_request_instance.premium
                    )
                else:
                    # If sale request, seller gets base order cost
                    base_order_cost = purchase_request_instance.order_cost

                # Get VAT rate from organization (same as used when creating the purchase request)
                """
                NOTE:

                `purchase_request_instance.organization_id` is used here to retrieve
                the organization for VAT calculation.

                If this field returns an integer ID instead of an Organization object,
                accessing `organization.vat_rate` will raise an AttributeError.
                """

                organization = purchase_request_instance.organization_id
                vat_rate = organization.vat_rate if organization else Decimal("0.0000")

                transaction_entry = Transaction.objects.create(
                    from_business=from_wallet.business,
                    to_business=to_wallet.business,
                    created_by=user,
                    transaction_type=TransactionType.PAYMENT,
                    amount=purchase_request_instance.total_cost,
                    status=TransactionStatus.PENDING,
                    purchase_request=purchase_request_instance,
                    taxes=purchase_request_instance.taxes,
                    vat=purchase_request_instance.vat,
                    vat_rate=vat_rate,
                    platform_fee=purchase_request_instance.platform_fee,
                )

                try:
                    # Deduct balance from sender's wallet
                    from_wallet.balance -= amount_to_deduct
                    from_wallet.save()

                    # Calculate amount to add to receiver's wallet
                    if request_type_purchase:
                        amount_to_add = (
                            purchase_request_instance.order_cost
                            + purchase_request_instance.premium
                        )
                    else:
                        amount_to_add = (
                            purchase_request_instance.order_cost
                            - purchase_request_instance.platform_fee
                            - purchase_request_instance.vat
                            - purchase_request_instance.taxes
                        )

                    # Add balance to receiver's wallet
                    to_wallet.balance += amount_to_add
                    to_wallet.save()

                    # Mark transaction as completed
                    transaction_entry.status = TransactionStatus.SUCCESS
                    transaction_entry.save()
                    transaction.savepoint_commit(savepoint)

                    organization = request.user.organization_id

                    recipients_queryset = (
                        users_in_investor_business
                        if request_type_purchase
                        else users_in_seller_business
                    )

                    recipients = list(
                        recipients_queryset.values_list("email", flat=True)
                    )

                    send_purchase_request_email.delay(
                        transaction_entry.pk,
                        from_wallet.pk,
                        organization.pk,
                        recipients,
                    )
                except Exception as e:
                    transaction.savepoint_rollback(savepoint)

                    transaction_entry.status = TransactionStatus.FAILED
                    transaction_entry.save()

                    self.send_notifications(
                        (
                            users_in_investor_business
                            if request_type_purchase
                            else users_in_seller_business
                        ),
                        "Transaction Failed",
                        f"Your {transaction_type_text} transaction for {precious_item.material_type} '{precious_item.name}' has failed.",
                        NotificationTypes.PURCHASE_REQUEST_PAYMENT_FAILED,
                        ContentType.objects.get_for_model(Transaction),
                        transaction_entry.id,
                    )

                    return generic_response(
                        error_message=f"Transaction failed: {str(e)}",
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

            # Determine the recipients of success notifications
            # For PURCHASE: Requesting business (investor/jeweler) is buyer (pays), Seller is seller (receives)
            # For SALE: Seller is buyer (pays), Requesting business (investor/jeweler) is seller (receives)
            # Note: In SALE requests, requesting business (investor/jeweler) is selling their asset, so they receive payment
            #       Seller is buying the asset, so they pay
            if request_type_purchase:
                # PURCHASE request: Requesting business (investor/jeweler) pays, Seller receives
                payer_users = users_in_investor_business  # This is aliased to users_in_requesting_business
                receiver_users = users_in_seller_business
            else:
                # SALE request: Seller pays, Requesting business (investor/jeweler) receives
                payer_users = users_in_seller_business
                receiver_users = users_in_investor_business  # This is aliased to users_in_requesting_business

            # Send notification to payer (person whose wallet is debited)
            self.send_notifications(
                payer_users,
                "Amount debited from your wallet.",
                f"BHD {amount_to_deduct} has been debited from your wallet for the {transaction_type_text} of {precious_item.material_type} '{precious_item.name}'.",
                NotificationTypes.PURCHASE_REQUEST_PAYMENT_TRANSFER,
                ContentType.objects.get_for_model(Transaction),
                transaction_entry.id,
            )

            # Send notification to receiver (person whose wallet is credited)
            self.send_notifications(
                receiver_users,
                "Amount credited to your wallet.",
                f"BHD {amount_to_add} has been credited to your wallet for the {transaction_type_text} of {precious_item.material_type} '{precious_item.name}'.",
                NotificationTypes.PURCHASE_REQUEST_PAYMENT_RECEIVED,
                ContentType.objects.get_for_model(Transaction),
                transaction_entry.id,
            )
        else:
            # Disable the precious item if its material type is stone
            if precious_item.material_type == MaterialType.STONE:
                precious_item.is_enabled = True
                precious_item.save()

            # Handle sale request rejection: Clear sale_request from units
            # When a sale request is rejected, we need to remove the sale_request reference
            # from the units so they can be used again (e.g., in musharakah contracts or pools)
            if not request_type_purchase:  # SALE request
                # Clear sale_request from all units that were associated with this sale request
                PreciousItemUnit.objects.filter(
                    sale_request=purchase_request_instance
                ).update(sale_request=None)

        # Handle approval/rejection notifications
        # Send notification only to the requesting business (investor or jeweler) whose request was approved/rejected
        # Note: Seller does not receive this notification as they are the one approving/rejecting
        title = f"Asset {request_type.lower()} request {'approved' if purchase_request_status_approved else 'rejected'}."
        body = f"Your asset {request_type.lower()} request for {precious_item.material_type} '{precious_item.name}' has been {'approved' if purchase_request_status_approved else 'rejected'}."

        # Send notification only to users from the requesting business (INVESTOR or JEWELER)
        notification_recipients = users_in_requesting_business

        # Determine the correct ID for navigation:
        # - For PURCHASE requests: use the purchase request ID
        # - For SALE requests: use the related purchase request ID (for proper navigation to the original asset)
        if request_type == RequestType.SALE:
            # Sale requests should redirect to the related purchase request
            notification_object_id = (
                purchase_request_instance.related_purchase_request.id
            )
        else:
            # Purchase requests use their own ID
            notification_object_id = purchase_request_instance.id

        self.send_notifications(
            notification_recipients,
            title,
            body,
            notification_type,
            ContentType.objects.get_for_model(PurchaseRequest),
            notification_object_id,
        )

        # Update the purchase request status at the very end all operations are successful
        purchase_request_serializer.save()

        # Send notification to admin
        message = f"'{precious_item.business}' business has {'approved' if purchase_request_status_approved else 'rejected'} an asset {request_type.lower()} request for '{precious_item}' for the business '{investor_business_instance}'."
        send_notifications_to_organization_admins(
            organization_code,
            title,
            message,
            notification_type,
            ContentType.objects.get_for_model(PurchaseRequest),
            purchase_request_instance.id,
            UserRoleChoices.TAQABETH_ENFORCER,
        )

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["purchase_request_updated"],
            data=purchase_request_serializer.data,
        )


class SellerDashboardApiView(ListAPIView):
    """
    API view to return dashboard data for asset purchase and sale requests recieved from the users.
    Provides sales insights for the current month and year.
    """

    permission_classes = [IsAuthenticated]
    queryset = PurchaseRequest.global_objects.select_related(
        "precious_item", "precious_item__created_by", "precious_item__material_item"
    )
    serializer_class = SellerDashboardSerializer

    @PermissionManager(SELLER_DASHBOARD_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Fetch and return the dashboard data for the seller."""

        current_date = timezone.now()
        month_start = current_date.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        year_start = current_date.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )

        business = get_business_from_user_token(request, "business")
        if not business:
            return generic_response(
                error_message=ACCOUNT_MESSAGE["business_account_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Get purchase requests for the logged-in user (seller)
        user_purchase_requests = self.queryset.filter(precious_item__business=business)

        completed_requests = user_purchase_requests.filter(
            status__in=[
                PurchaseRequestStatus.APPROVED,
                PurchaseRequestStatus.COMPLETED,
            ],
            request_type=RequestType.PURCHASE,
        )

        # Fetch sales data for the current month and year
        month_sales_data = get_sales_data(
            user_purchase_requests, completed_requests, month_start, business
        )
        year_sales_data = get_sales_data(
            user_purchase_requests, completed_requests, year_start, business
        )

        # Serialize and return the response
        response_data = {
            "month": self.get_serializer(month_sales_data).data,
            "year": self.get_serializer(year_sales_data).data,
        }

        return generic_response(response_data)


class SalesByContinentApiView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SalesByContinentSerializer

    @swagger_auto_schema(
        operation_description="Get the percentage of sales by continent.",
        manual_parameters=[
            openapi.Parameter(
                "filter",
                openapi.IN_QUERY,
                description="Filter for sales data: 'current_date', 'week', or 'month'.",
                type=openapi.TYPE_STRING,
            )
        ],
        responses={200: SalesByContinentSerializer(many=True)},
    )
    @PermissionManager(SELLER_DASHBOARD_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Handles GET request to fetch sales data by continent."""

        sales_filter_type = request.query_params.get("filter", "current_date")

        # Determine the sales start date based on the filter type
        current_date = timezone.now().date()
        sales_start_date = {
            "week": current_date - timezone.timedelta(days=7),
            "month": current_date.replace(day=1),
        }.get(sales_filter_type, current_date)

        # Retrieve the current business instance
        business_instance = get_business_from_user_token(request, "business")
        if not business_instance:
            return generic_response(
                error_message=ACCOUNT_MESSAGE["business_account_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Subquery to get the nationality of the first available address for each user
        user_nationality_subquery = Address.objects.filter(
            user=OuterRef("created_by")
        ).values("nationality")[:1]

        # Query for sales records
        sales_records = (
            PurchaseRequest.objects.filter(
                request_type=RequestType.PURCHASE,
                status__in=[
                    PurchaseRequestStatus.APPROVED,
                    PurchaseRequestStatus.COMPLETED,
                ],
                approved_at__date__range=(sales_start_date, current_date),
                precious_item__business=business_instance,
            )
            .select_related("precious_item__material_item", "created_by")
            .annotate(
                # Map the user's nationality to a continent
                nationality=Coalesce(
                    Subquery(user_nationality_subquery, output_field=CharField()),
                    Value("Other"),
                ),
                continent=Subquery(
                    CountryToContinent.objects.filter(
                        country__iexact=OuterRef("nationality")
                    ).values("continent")[:1],
                    output_field=CharField(),
                ),
                # Extract material item name from related fields
                material_item_name=F("precious_item__material_item__name"),
                total_order_cost=Sum("order_cost"),
                total_premium=Sum("premium"),
            )
        )

        # Aggregate sales by continent
        continent_sales_summary = defaultdict(
            lambda: {"sales": Decimal(0), "material_items": set()}
        )
        total_sales_amount = Decimal(0)

        for item in sales_records:
            continent = item.continent  # Handle missing continent data
            total_sales = item.total_order_cost + (item.total_premium or Decimal(0))
            continent_sales_summary[continent]["sales"] += total_sales or Decimal(0)
            continent_sales_summary[continent]["material_items"].add(
                item.material_item_name
            )
            total_sales_amount += total_sales or Decimal(0)

        # Prevent division by zero
        total_sales_amount = total_sales_amount or Decimal(1)

        # Format the sales data into a structured response
        formatted_sales_response = [
            {
                "continent": continent,
                "sales_amount": data["sales"],
                "sales_percentage": round(
                    (data["sales"] / total_sales_amount) * 100, 2
                ),
                "material_items_sold": list(data["material_items"]),
            }
            for continent, data in continent_sales_summary.items()
        ]

        return generic_response(
            data=self.get_serializer(formatted_sales_response, many=True).data,
            message=MESSAGES["sales_by_continent_fetched"],
        )


class PreciousItemReportNumberExistsAPIView(APIView):
    """API to check whether a report number exists in PreciousItem."""

    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(request_body=PreciousItemReportNumberSerializer)
    @PermissionManager(PRECIOUS_ITEM_CREATE_PERMISSION)
    def post(self, request):
        serializer = PreciousItemReportNumberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        report_number = serializer.validated_data["report_number"]
        exists = PreciousItem.global_objects.filter(
            report_number=report_number
        ).exists()

        message = (
            MESSAGES["report_number_exist"]
            if exists
            else MESSAGES["report_number_is_valid"]
        )

        return generic_response(
            data={"exists": exists},
            message=message,
        )


class SaleRequestSetDeductionAmountView(UpdatePurchaseRequestStatusView):
    """View for seller to set deduction amount on sale requests."""

    serializer_class = SaleRequestDeductionAmountSerializer
    http_method_names = ["patch"]

    def get_queryset(self):
        """Filter sale requests for the seller's business."""
        if self.request.user.is_anonymous:
            return PurchaseRequest.objects.none()

        business = get_business_from_user_token(self.request, "business")
        if not business:
            return PurchaseRequest.objects.none()

        return base_purchase_request_queryset().filter(
            precious_item__business=business,
            request_type=RequestType.SALE,
        )

    @PermissionManager(PURCHASE_REQUEST_VIEW_PERMISSION)
    def patch(self, request, *args, **kwargs):
        """Set deduction amount on a sale request."""
        try:
            sale_request = self.get_object()
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=INVESTOR_MESSAGE["purchase_request_not_found"],
            )

        serializer = self.get_serializer(sale_request, data=request.data, partial=True)
        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        updated_sale_request = serializer.save()

        # Send notification to requesting business (investor or jeweler) who made the sale request
        # Note: sale_request.business can be either an INVESTOR or JEWELER business
        users_in_requesting_business = User.objects.filter(
            user_assigned_businesses__business=sale_request.business,
            user_preference__notifications_enabled=True,
        )

        if users_in_requesting_business.exists():
            title = "Sale request price updated."
            body = f"Seller has set a price for your sale request for '{sale_request.precious_item.name}'. Please review and confirm."
            notification_type = NotificationTypes.SALE_REQUEST_CREATED
            content_type = ContentType.objects.get_for_model(PurchaseRequest)

            # Use the related purchase request ID for proper navigation
            # This allows users to be redirected to the original purchase request
            # Note: Sale requests always have a related_purchase_request
            purchase_request_id = sale_request.related_purchase_request.id

            self.send_notifications(
                users_in_requesting_business,
                title,
                body,
                notification_type,
                content_type,
                purchase_request_id,
            )

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["purchase_request_updated"],
            data=PurchaseRequestResponseSerializer(updated_sale_request).data,
        )
