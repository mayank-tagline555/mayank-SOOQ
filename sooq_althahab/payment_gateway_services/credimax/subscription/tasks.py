import logging
from datetime import datetime
from datetime import timedelta
from decimal import Decimal

from celery import shared_task
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import F
from django.db.models import Q
from django.utils import timezone

from account.models import Transaction
from account.models import User
from account.models import WebhookCall
from investor.models import PurchaseRequest
from sooq_althahab.billing.subscription.email_utils import failed_transaction_send_mail
from sooq_althahab.billing.subscription.services import monthly_subscription_calculation
from sooq_althahab.billing.subscription.services import send_subscription_invoice
from sooq_althahab.billing.subscription.services import (
    send_subscription_receipt_after_payment,
)
from sooq_althahab.billing.transaction.helpers import get_organization_logo_url
from sooq_althahab.enums.account import SubscriptionStatusChoices
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.account import TransferVia
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.account import WebhookCallStatus
from sooq_althahab.enums.account import WebhookEventType
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.enums.sooq_althahab_admin import PaymentStatus
from sooq_althahab.enums.sooq_althahab_admin import SubscriptionPaymentTypeChoices
from sooq_althahab.payment_gateway_services.credimax.subscription.credimax_client import (
    CredimaxClient,
)
from sooq_althahab.utils import send_notifications
from sooq_althahab_admin.models import BusinessSavedCardToken
from sooq_althahab_admin.models import BusinessSubscriptionPlan

logger = logging.getLogger(__name__)

# Prevent duplicate log messages by disabling propagation to root logger
# Django's logging configuration has a root logger with a console handler.
# Without this, logs would appear twice (once from our logger, once from root logger).
logger.propagate = False

# Add a custom handler with prefix for recurring payment logs
# Only add if no handlers exist to avoid duplicates
if not logger.handlers:

    class RecurringPaymentFormatter(logging.Formatter):
        def format(self, record):
            # Add prefix to log messages for recurring payment tasks
            record.msg = f"[RECURRING-PAYMENT-CREDIMAX] {record.msg}"
            return super().format(record)

    handler = logging.StreamHandler()
    handler.setFormatter(RecurringPaymentFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ============================================================================
# TASK 1: SUBSCRIPTION FEE RECURRING TASK (Daily)
# ============================================================================
# Handles fixed subscription fees for:
# - Sellers
# - Manufacturers
# - Jewelers (subscription fee part only, not commission)
# - Investors (non-pro-rata plans only)
#
# Purpose:
# - Deduct subscription fee based on billing cycle
# - Generate invoice-only if payment already done (e.g., yearly prepaid plans)
# ============================================================================
@shared_task
def process_subscription_fee_recurring_payment(business_id=None):
    """
    Daily task for processing fixed subscription fees and checking for expired subscriptions.

    Handles:
    1. Expiring subscriptions that have passed their expiry_date
    2. Processing fixed subscription fees for:
       - SELLER: Fixed subscription fee
       - MANUFACTURER: Fixed subscription fee
       - JEWELER: Fixed subscription fee (commission handled separately)
       - INVESTOR: Only if pro_rata_rate is 0 or None (non-pro-rata plans)

    Business Logic:
    - For PREPAID yearly plans: Generate invoice only, no deduction
    - For PREPAID monthly plans: Deduct monthly fee
    - For POSTPAID plans: Deduct fee at end of billing cycle
    - For FREE_TRIAL: Generate invoice only, no payment

    Args:
        business_id (str, optional): If provided, only process subscription for this business.
                                     If None, process all due subscriptions (scheduled execution).

    Scheduled: Daily at 2:00 AM
    """
    today = timezone.now().date()
    client = CredimaxClient()

    if business_id:
        logger.info(
            f"[SUBSCRIPTION-FEE-TASK] Processing for specific business: {business_id}"
        )
    else:
        logger.info(f"[SUBSCRIPTION-FEE-TASK] Starting daily processing for {today}")

    # Step 1: Process billing for subscriptions due AFTER next_billing_date has passed
    # IMPORTANT: Billing must happen AFTER next_billing_date passes, then expiration happens.
    # Business Logic:
    # - User can use app until next_billing_date (e.g., 2026-01-04 23:59:59)
    # - Task runs on day AFTER next_billing_date (e.g., 2026-01-05 at 2:00 AM)
    # - On 2026-01-05: First bill for the period that ended, THEN expire subscription (if applicable)
    #
    # For POSTPAID: Bill for the period that just ended (next_billing_date was the last day of access)
    # For PREPAID: Bill for the next period (if auto-renew is enabled)
    #
    # Example: next_billing_date = 2026-01-04, today = 2026-01-05
    # - Billing query finds subscription (next_billing_date < today)
    # - Process billing first
    # - Then expiration check runs and expires subscription (if expiry_date < today)

    # Build query for subscriptions due for billing
    # CRITICAL: Use < (strictly less than) instead of <= to ensure task runs AFTER next_billing_date passes
    # This ensures user has access until the end of next_billing_date, then gets billed and logged out the next day
    query = (
        BusinessSubscriptionPlan.objects.filter(
            next_billing_date__lt=today,  # Billing is due (next_billing_date has passed)
            subscription_fee__gt=0,  # MUST have subscription fee
        )
        .filter(
            # Include ACTIVE subscriptions (normal billing)
            # OR EXPIRED subscriptions that need final billing (POSTPAID where next_billing_date == expiry_date)
            # Note: On day after expiry_date, subscription might still be ACTIVE or already EXPIRED
            Q(status=SubscriptionStatusChoices.ACTIVE)
            | Q(
                # EXPIRED subscriptions that need final POSTPAID billing
                status=SubscriptionStatusChoices.EXPIRED,
                payment_type=SubscriptionPaymentTypeChoices.POSTPAID,
                next_billing_date=F("expiry_date"),
            )
        )
        .exclude(
            # Exclude investors with pro-rata plans (handled by pro-rata task)
            Q(subscription_plan__role=UserRoleBusinessChoices.INVESTOR)
            & Q(pro_rata_rate__gt=0)
        )
        .exclude(
            # CRITICAL: Exclude PREPAID subscriptions that have expired
            # For PREPAID: User already paid for the period, so no billing needed when expired
            # Only POSTPAID subscriptions need final billing after expiration
            Q(payment_type=SubscriptionPaymentTypeChoices.PREPAID)
            & Q(expiry_date__lt=today)  # Expired PREPAID subscriptions
        )
        .exclude(
            # CRITICAL: Exclude FREE_TRIAL subscriptions from billing
            # FREE_TRIAL subscriptions should never be billed - they are free
            # They should only be expired when they reach expiry_date
            Q(payment_type=SubscriptionPaymentTypeChoices.FREE_TRIAL)
        )
        # Note: POSTPAID subscriptions with expiry_date < today are included above
        # for final billing (they need to be charged for the period that just ended)
    )

    # Filter by business_id if provided
    if business_id:
        query = query.filter(business_id=business_id)

        # CRITICAL: If filtering by business_id, exclude expired subscriptions that have an ACTIVE or TRIALING subscription
        # This prevents processing old expired subscriptions when a new active/trial subscription exists
        # Only process expired subscriptions if there's no active/trial subscription for the business
        active_subscriptions_exist = BusinessSubscriptionPlan.objects.filter(
            business_id=business_id,
            status__in=[
                SubscriptionStatusChoices.ACTIVE,
                SubscriptionStatusChoices.TRIALING,
            ],
        ).exists()

        if active_subscriptions_exist:
            # If there's an active/trial subscription, exclude expired ones
            # Only process the active/trial subscription(s)
            query = query.filter(
                status__in=[
                    SubscriptionStatusChoices.ACTIVE,
                    SubscriptionStatusChoices.TRIALING,
                ]
            )
            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] Business {business_id} has active/trial subscription(s), "
                f"excluding expired subscriptions from billing"
            )

    due_subscriptions = query.select_related(
        "business",
        "business__organization_id",
        "subscription_plan",
        "business_saved_card_token",
    )

    if business_id:
        logger.info(
            f"[SUBSCRIPTION-FEE-TASK] Found {due_subscriptions.count()} subscription(s) for business {business_id}"
        )
    else:
        logger.info(
            f"[SUBSCRIPTION-FEE-TASK] Found {due_subscriptions.count()} subscriptions due for fixed fee billing"
        )

    for subscription in due_subscriptions:
        business = subscription.business
        subscription_plan = subscription.subscription_plan
        role = subscription_plan.role if subscription_plan else None

        # CRITICAL: Handle billing when expiry_date has passed (day after expiry_date)
        # Business Logic: On day after expiry_date, we need to bill first, then expire
        # - POSTPAID: Always bill if next_billing_date == expiry_date (final billing for period that ended)
        # - PREPAID: Only bill if auto-renew is enabled (charge for next period)
        # - If expiry_date < today and it's not a final billing case, skip (already handled)
        if subscription.expiry_date and subscription.expiry_date < today:
            # This is the day after expiry_date - process final billing if applicable
            if (
                subscription.payment_type == SubscriptionPaymentTypeChoices.POSTPAID
                and subscription.next_billing_date == subscription.expiry_date
            ):
                # POSTPAID final billing: Bill for the period that just ended
                logger.info(
                    f"[SUBSCRIPTION-FEE-TASK] Processing final billing for POSTPAID subscription - "
                    f"business {business.id}, expiry_date: {subscription.expiry_date}, "
                    f"next_billing_date: {subscription.next_billing_date}, today: {today}. "
                    f"This is the final billing for the period that ended on {subscription.expiry_date}."
                )
                # Continue with billing - this is the final billing
            elif (
                subscription.payment_type == SubscriptionPaymentTypeChoices.PREPAID
                and subscription.is_auto_renew
                and subscription.next_billing_date == subscription.expiry_date
            ):
                # PREPAID with auto-renew: Bill for next period
                logger.info(
                    f"[SUBSCRIPTION-FEE-TASK] Processing PREPAID billing with auto-renew - "
                    f"business {business.id}, expiry_date: {subscription.expiry_date}, "
                    f"next_billing_date: {subscription.next_billing_date}, today: {today}. "
                    f"Charging for next period."
                )
                # Continue with billing
            else:
                # Skip billing - not a final billing case or auto-renew disabled
                logger.info(
                    f"[SUBSCRIPTION-FEE-TASK] Skipping billing for business {business.id} - "
                    f"Subscription expired (expiry_date: {subscription.expiry_date}, today: {today}). "
                    f"Not a final billing case. Expiration will be processed in next step."
                )
                continue

        logger.info(
            f"[SUBSCRIPTION-FEE-TASK] Processing business {business.id} - "
            f"Role: {role}, Payment Type: {subscription.payment_type}, "
            f"Subscription Fee: {subscription.subscription_fee}, "
            f"Expiry Date: {subscription.expiry_date}, "
            f"Next Billing Date: {subscription.next_billing_date}"
        )

        # Process the subscription billing
        _process_subscription_billing(subscription, client, today)

    # Step 2: Check and expire subscriptions that have passed their expiry_date
    # IMPORTANT: This runs AFTER billing to ensure subscriptions can be billed first.
    # Business Logic:
    # - User can use app until expiry_date (e.g., 2025-12-29 23:59:59)
    # - Task runs on day AFTER expiry_date (e.g., 2025-12-30 at 2:00 AM)
    # - On 2025-12-30: Billing processes first, then expiration check runs
    # - Subscriptions with expiry_date < today will be expired (unless billing extended expiry_date)
    # Check expiration for all subscriptions (when business_id is None) or for specific business
    _check_and_expire_subscriptions(today, business_id=business_id)


# ============================================================================
# TASK 2: PRO RATA RECURRING TASK (Yearly - Runs on January 1st)
# ============================================================================
# Handles investor pro rata calculations:
# - Prepaid: Recalculate and deduct for remaining assets
# - Postpaid: Charge accumulated pro rata from previous year
#
# Purpose:
# - Recalculate or deduct pro rata charges at year start
# - Must NOT run daily
# ============================================================================
@shared_task
def process_pro_rata_recurring_payment(business_id=None):
    """
    Yearly task for processing investor pro rata fees.

    Runs on: January 1st at 2:00 AM

    Handles:
    1. PREPAID Investors:
       - Recalculate pro rata for remaining assets (using remaining_quantity property)
       - Deduct the updated amount

    2. POSTPAID Investors:
       - Charge accumulated pro rata from previous year
       - Calculate based on purchase requests from previous year
       - If assets were partially sold, charge based on days held

    Business Logic:
    - For METAL: pro_rata = remaining_weight × price_locked × pro_rata_rate
    - For STONE: pro_rata = order_cost × pro_rata_rate
    - Only processes INVESTOR role subscriptions with pro_rata_rate > 0

    Args:
        business_id (str, optional): If provided, only process subscription for this business.
                                     If None, process all investor subscriptions (scheduled execution).
    """
    today = timezone.now().date()

    # Only run on January 1st (unless business_id is provided for testing)
    if not business_id and (today.month != 1 or today.day != 1):
        logger.info(f"[PRO-RATA-TASK] Skipping - not January 1st. Today: {today}")
        return

    if business_id:
        logger.info(f"[PRO-RATA-TASK] Processing for specific business: {business_id}")
    else:
        logger.info(f"[PRO-RATA-TASK] Starting yearly processing for {today}")

    client = CredimaxClient()

    # Build query for investor subscriptions with pro-rata
    query = BusinessSubscriptionPlan.objects.filter(
        status=SubscriptionStatusChoices.ACTIVE,
        subscription_plan__role=UserRoleBusinessChoices.INVESTOR,
        pro_rata_rate__gt=0,
    )

    # Filter by business_id if provided
    if business_id:
        query = query.filter(business_id=business_id)

    investor_subscriptions = query.select_related(
        "business",
        "business__organization_id",
        "subscription_plan",
        "business_saved_card_token",
    )

    if business_id:
        logger.info(
            f"[PRO-RATA-TASK] Found {investor_subscriptions.count()} subscription(s) for business {business_id}"
        )
    else:
        logger.info(
            f"[PRO-RATA-TASK] Found {investor_subscriptions.count()} investor subscriptions with pro-rata"
        )

    for subscription in investor_subscriptions:
        business = subscription.business
        payment_type = subscription.payment_type

        logger.info(
            f"[PRO-RATA-TASK] Processing business {business.id} - Payment Type: {payment_type}"
        )

        try:
            if payment_type == SubscriptionPaymentTypeChoices.PREPAID:
                _process_prepaid_pro_rata_recalculation(subscription, client, today)
            elif payment_type == SubscriptionPaymentTypeChoices.POSTPAID:
                _process_postpaid_pro_rata_charge(subscription, client, today)
            else:
                logger.warning(
                    f"[PRO-RATA-TASK] Skipping business {business.id} - "
                    f"Unsupported payment type: {payment_type}"
                )
        except Exception as e:
            logger.exception(
                f"[PRO-RATA-TASK] Error processing business {business.id}: {e}"
            )


# ============================================================================
# TASK 3: COMMISSION RECURRING TASK (Yearly - Runs on January 1st)
# ============================================================================
# Handles jeweler commission calculations:
# - Calculate commission based on total sales for previous year
# - Deduct during commission recurring task (year-start)
#
# NOTE: This task is commented out for future development.
# Currently, jewelry sales functionality is under development.
# ============================================================================
@shared_task
def process_commission_recurring_payment():
    """
    Yearly task for processing jeweler commission fees.

    Runs on: January 1st at 2:00 AM

    Handles:
    - Calculate commission based on total jewelry sales from previous year
    - Deduct commission amount

    NOTE: This functionality is currently under development.
    The jewelry sales models and functionality are not yet complete.
    This task is left as a placeholder for future implementation.

    TODO: Implement when jewelry sales functionality is complete:
    1. Query all jewelry sales for the jeweler from previous year
    2. Calculate total sales amount
    3. Apply commission_rate from subscription plan
    4. Create billing and process payment
    5. Send invoice and receipt
    """
    today = timezone.now().date()

    # Only run on January 1st
    if today.month != 1 or today.day != 1:
        logger.info(f"[COMMISSION-TASK] Skipping - not January 1st. Today: {today}")
        return

    logger.info(f"[COMMISSION-TASK] Starting yearly processing for {today}")

    # TODO: Implement when jewelry sales functionality is complete
    # For now, just log that this task is not yet implemented
    logger.info(
        "[COMMISSION-TASK] Commission recurring payment task is not yet implemented. "
        "Jewelry sales functionality is under development."
    )

    # Placeholder code structure (commented out):
    # client = CredimaxClient()
    #
    # jeweler_subscriptions = BusinessSubscriptionPlan.objects.filter(
    #     status=SubscriptionStatusChoices.ACTIVE,
    #     subscription_plan__role=UserRoleBusinessChoices.JEWELER,
    #     commission_rate__gt=0,
    # ).select_related(
    #     "business",
    #     "business__organization_id",
    #     "subscription_plan",
    #     "business_saved_card_token",
    # )
    #
    # for subscription in jeweler_subscriptions:
    #     business = subscription.business
    #     previous_year_start = datetime(today.year - 1, 1, 1).date()
    #     previous_year_end = datetime(today.year - 1, 12, 31).date()
    #
    #     # TODO: Query jewelry sales for this jeweler from previous year
    #     # total_sales = get_jeweler_sales_total(business, previous_year_start, previous_year_end)
    #     #
    #     # commission_amount = total_sales * subscription.commission_rate
    #     #
    #     # # Process commission payment
    #     # _process_commission_billing(subscription, commission_amount, client, today)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _get_business_display_name(business):
    """
    Get display name for business.
    If business.name is None or empty, use owner's fullname.

    Args:
        business: BusinessAccount instance

    Returns:
        str: Display name for the business
    """
    from account.utils import get_business_display_name

    return get_business_display_name(business)


def _send_subscription_cancellation_notification(subscription):
    """
    Send FCM notification to all users in the business when subscription is cancelled.
    This triggers automatic logout on the frontend.

    Args:
        subscription: BusinessSubscriptionPlan instance that was cancelled
    """
    try:
        # Get all users associated with the business
        users = User.objects.filter(
            user_assigned_businesses__business=subscription.business,
            user_preference__notifications_enabled=True,
        ).distinct()

        if not users.exists():
            logger.warning(
                f"[SUBSCRIPTION-FEE-TASK] No users found for business {subscription.business.name} "
                f"(subscription {subscription.id}). Skipping cancellation notification."
            )
            return

        # Get subscription plan name for notification message
        plan_name = subscription.subscription_name or (
            subscription.subscription_plan.name
            if subscription.subscription_plan
            else "Subscription Plan"
        )

        # Send FCM notification to all users in the business
        content_type = ContentType.objects.get_for_model(BusinessSubscriptionPlan)
        send_notifications(
            users=users,
            title="Business Subscription Cancelled",
            message=f"Your {plan_name} subscription has been cancelled. Please renew to continue using the application.",
            notification_type=NotificationTypes.BUSINESS_SUBSCRIPTION_SUSPENDED,
            content_type=content_type,
            object_id=str(subscription.id),
        )

        logger.info(
            f"[SUBSCRIPTION-FEE-TASK] Sent cancellation notification to {len(users)} users "
            f"for business {subscription.business.name} (subscription {subscription.id})"
        )

    except Exception as e:
        logger.exception(
            f"[SUBSCRIPTION-FEE-TASK] Error sending cancellation notification for subscription {subscription.id} "
            f"(business: {subscription.business.name}): {e}"
        )
        # Don't fail the cancellation process if notification fails


def _check_and_expire_subscriptions(today, business_id=None):
    """
    Check for expired subscriptions and update their status to EXPIRED.
    Also sends FCM notifications to all users in the business using BUSINESS_SUBSCRIPTION_SUSPENDED
    notification type to trigger logout on the frontend.

    Args:
        today: Current date
        business_id (str, optional): If provided, only check expiration for this specific business.
                                     If None, check all expired subscriptions.
    """
    if business_id:
        logger.info(
            f"[SUBSCRIPTION-FEE-TASK] Checking for expired subscriptions for business {business_id} as of {today}"
        )
    else:
        logger.info(
            f"[SUBSCRIPTION-FEE-TASK] Checking for expired subscriptions as of {today}"
        )

    # Query for expired subscriptions that are still ACTIVE or TRIALING
    # Business Logic:
    # - User can use app until expiry_date (e.g., 2025-12-29 23:59:59)
    # - Task runs on day AFTER expiry_date (e.g., 2025-12-30 at 2:00 AM)
    # - On 2025-12-30: Billing processes first, then expiration check runs
    # - Subscriptions with expiry_date < today should be expired (unless billing extended expiry_date)
    #
    # IMPORTANT: Use lt (less than) to expire subscriptions AFTER expiry_date passes.
    # Example: If expiry_date = 2025-12-29, the subscription will be expired on 2025-12-30 or later.
    # - On 2025-12-30: Billing processes first (if next_billing_date < today)
    #   - If billing succeeds: expiry_date is extended, so expiration won't match (expiry_date > today)
    #   - If billing fails: expiry_date remains 2025-12-29, expiration will find it (expiry_date < today)
    # - On 2025-12-30: Subscription is expired (expiry_date < today) if billing didn't extend it
    query = BusinessSubscriptionPlan.objects.filter(
        status__in=[
            SubscriptionStatusChoices.ACTIVE,
            SubscriptionStatusChoices.TRIALING,
        ],
        expiry_date__lt=today,  # Expire only AFTER expiry_date has passed (not on expiry_date itself)
    ).exclude(expiry_date__isnull=True)

    # Filter by business_id if provided
    if business_id:
        query = query.filter(business_id=business_id)

    expired_subscriptions = query.select_related("business", "subscription_plan")

    expired_count = expired_subscriptions.count()
    logger.info(
        f"[SUBSCRIPTION-FEE-TASK] Found {expired_count} expired subscriptions to process"
    )

    for subscription in expired_subscriptions:
        try:
            # Update status to EXPIRED
            subscription.status = SubscriptionStatusChoices.EXPIRED
            subscription.save(update_fields=["status", "updated_at"])

            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] Updated subscription {subscription.id} "
                f"(business: {subscription.business.name}) status to EXPIRED. "
                f"Expiry date was {subscription.expiry_date}"
            )

            # Get all users associated with the business
            users = User.objects.filter(
                user_assigned_businesses__business=subscription.business,
                user_preference__notifications_enabled=True,
            ).distinct()

            if not users.exists():
                logger.warning(
                    f"[SUBSCRIPTION-FEE-TASK] No users found for business {subscription.business.name} "
                    f"(subscription {subscription.id}). Skipping notification."
                )
                continue

            # Get subscription plan name for notification message
            plan_name = subscription.subscription_name or (
                subscription.subscription_plan.name
                if subscription.subscription_plan
                else "Subscription Plan"
            )

            # Send FCM notification to all users in the business
            content_type = ContentType.objects.get_for_model(BusinessSubscriptionPlan)
            send_notifications(
                users=users,
                title="Business Subscription Expired",
                message=f"Your {plan_name} subscription has expired. Please renew to continue using the application.",
                notification_type=NotificationTypes.BUSINESS_SUBSCRIPTION_SUSPENDED,
                content_type=content_type,
                object_id=str(subscription.id),
            )

            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] Sent expiration notification to {len(users)} users "
                f"for business {subscription.business.name} (subscription {subscription.id})"
            )

        except Exception as e:
            logger.exception(
                f"[SUBSCRIPTION-FEE-TASK] Error processing expired subscription {subscription.id} "
                f"(business: {subscription.business.name}): {e}"
            )
            # Continue processing other subscriptions even if one fails
            continue


def _process_subscription_billing(subscription, client, today):
    """
    Process billing for a subscription (fixed fee).

    Handles:
    - Invoice generation
    - Payment processing (if required)
    - Receipt sending
    - Billing cycle updates
    """
    business = subscription.business
    token_obj = subscription.business_saved_card_token
    payment_type = subscription.payment_type

    # CRITICAL: Handle billing when expiry_date has passed (day after expiry_date)
    # This check is a safety net - the main query should have already filtered correctly
    # Business Logic: On day after expiry_date, we need to bill first, then expire
    if subscription.expiry_date and subscription.expiry_date < today:
        # This is the day after expiry_date - process final billing if applicable
        if (
            subscription.payment_type == SubscriptionPaymentTypeChoices.POSTPAID
            and subscription.next_billing_date == subscription.expiry_date
        ):
            # POSTPAID final billing: Bill for the period that just ended
            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] Processing final billing for POSTPAID subscription - "
                f"business {business.id}, expiry_date: {subscription.expiry_date}, "
                f"next_billing_date: {subscription.next_billing_date}, today: {today}. "
                f"This is the final billing for the period that ended on {subscription.expiry_date}."
            )
            # If this is a monthly billing/yearly payment plan, mark as last cycle
            # to charge full yearly amount instead of monthly divided amount
            if (
                subscription.billing_frequency == "MONTHLY"
                and subscription.payment_interval == "YEARLY"
            ):
                subscription._is_last_billing_cycle = True
            # Continue with billing - this is the final billing
        elif subscription.payment_type == SubscriptionPaymentTypeChoices.PREPAID:
            # PREPAID subscriptions: User already paid for the period that just ended
            # Do NOT process billing - just expire the subscription
            # For PREPAID, billing only happens BEFORE expiry_date (for next period if auto-renew)
            # Once expired, no billing should occur
            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] Skipping PREPAID billing for expired subscription - "
                f"business {business.id}, expiry_date: {subscription.expiry_date}, "
                f"next_billing_date: {subscription.next_billing_date}, today: {today}. "
                f"User already paid for the period. Subscription will be expired without billing."
            )
            return
        else:
            # Skip billing - not a final billing case
            logger.warning(
                f"[SUBSCRIPTION-FEE-TASK] Skipping billing for business {business.id} - "
                f"Subscription has expired (expiry_date: {subscription.expiry_date}, today: {today}). "
                f"Not a final billing case. This should have been caught by the query filter. "
                f"Expiration will be processed separately."
            )
            return

    # Get default card if not set on subscription
    if not token_obj:
        token_obj = _get_default_card_for_business(business, subscription, client)
        if not token_obj:
            logger.warning(
                f"[SUBSCRIPTION-FEE-TASK] Skipping business {business.id} - No payment token"
            )
            return

    # Check if auto-renew is disabled
    if not subscription.is_auto_renew:
        if payment_type == SubscriptionPaymentTypeChoices.PREPAID:
            # PREPAID: Don't charge for next month, skip billing and cancel subscription
            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] Skipping PREPAID business {business.id} - "
                f"Auto-renew is disabled (is_auto_renew=False). No charge for next billing cycle. Cancelling subscription."
            )
            # Cancel subscription to prevent future billing attempts
            subscription.status = SubscriptionStatusChoices.CANCELLED
            subscription.cancelled_date = today
            subscription.save(update_fields=["status", "cancelled_date", "updated_at"])
            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] Subscription cancelled for business {business.id} "
                f"(PREPAID, is_auto_renew=False)"
            )

            # Send cancellation notification to all users in the business
            _send_subscription_cancellation_notification(subscription)

            return
        elif payment_type == SubscriptionPaymentTypeChoices.POSTPAID:
            # POSTPAID: Process billing (invoice and receipt), then cancel subscription
            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] Processing POSTPAID business {business.id} - "
                f"Auto-renew is disabled (is_auto_renew=False). Will process final billing and cancel."
            )
            # Continue with billing process - will set status to CANCELLED after successful payment
        # For FREE_TRIAL, continue normally (no payment required anyway)

    # For POSTPAID plans: Only charge if billing period has ended
    # POSTPAID plans charge AFTER the period ends, not before
    if payment_type == SubscriptionPaymentTypeChoices.POSTPAID:
        if subscription.next_billing_date and subscription.next_billing_date > today:
            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] Skipping POSTPAID business {business.id} - "
                f"Billing period not ended yet (next_billing_date: {subscription.next_billing_date}, today: {today})"
            )
            return

    # Check if payment is required
    requires_payment = payment_type in [
        SubscriptionPaymentTypeChoices.PREPAID,
        SubscriptionPaymentTypeChoices.POSTPAID,
    ]

    # For yearly prepaid plans, only generate invoice (payment already done at purchase time)
    # If payment_interval is YEARLY and payment_type is PREPAID, payment was made upfront
    # Billing frequency determines invoice generation frequency, not payment frequency
    # - If billing_frequency = MONTHLY: Invoice generated monthly (no payment, already paid)
    # - If billing_frequency = YEARLY: Invoice generated yearly (no payment, already paid)
    # IMPORTANT: For PREPAID MONTHLY plans (payment_interval = MONTHLY), payment is deducted on each billing cycle.
    # Example: On 2026-01-26 (next_billing_date), the customer is charged for the next month.
    is_yearly_prepaid = (
        payment_type == SubscriptionPaymentTypeChoices.PREPAID
        and subscription.payment_interval == "YEARLY"
    )

    if is_yearly_prepaid:
        billing_freq = subscription.billing_frequency or "UNKNOWN"
        logger.info(
            f"[SUBSCRIPTION-FEE-TASK] Generating invoice only for yearly prepaid plan "
            f"(billing_frequency={billing_freq}): business {business.id}. "
            f"Payment was already made at purchase time."
        )
        _generate_invoice_only(subscription, today)
        return

    # For POSTPAID plans with monthly billing frequency and yearly payment interval:
    # Generate invoice monthly, but only charge at the last billing cycle
    # Example: 12-month plan with monthly billing, yearly payment
    # - Cycles 1-11: Invoice only (no payment, no receipt)
    # - Cycle 12 (last): Invoice + Payment + Receipt (full yearly amount)
    is_monthly_billing_yearly_payment = (
        payment_type == SubscriptionPaymentTypeChoices.POSTPAID
        and subscription.billing_frequency == "MONTHLY"
        and subscription.payment_interval == "YEARLY"
    )

    if is_monthly_billing_yearly_payment:
        # Determine if this is the last billing cycle
        subscription_plan = subscription.subscription_plan
        duration_months = subscription_plan.duration if subscription_plan else None

        is_last_cycle = False

        # Primary check: Use billing_cycle_count to determine last cycle
        if duration_months:
            # billing_cycle_count starts at 0, so cycle 1 = count 0, cycle 12 = count 11
            # Last cycle is when billing_cycle_count + 1 >= duration_months
            current_cycle = subscription.billing_cycle_count + 1
            is_last_cycle = current_cycle >= duration_months

            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] Monthly billing/yearly payment plan check - "
                f"business {business.id}, cycle {current_cycle} of {duration_months}, "
                f"is_last_cycle={is_last_cycle}"
            )

        # Secondary check: If duration_months is None or cycle count is unclear,
        # check if next_billing_date is very close to expiry_date (within 7 days)
        # This is a fallback for edge cases, but we prefer cycle count
        if (
            not is_last_cycle
            and subscription.expiry_date
            and subscription.next_billing_date
        ):
            days_until_expiry = (
                subscription.expiry_date - subscription.next_billing_date
            ).days
            # Only consider it last cycle if very close (within 7 days, not 30)
            # This prevents false positives for early cycles
            if 0 <= days_until_expiry <= 7:
                is_last_cycle = True
                logger.info(
                    f"[SUBSCRIPTION-FEE-TASK] Monthly billing/yearly payment plan - "
                    f"Determined last cycle by expiry date proximity: "
                    f"days_until_expiry={days_until_expiry}, business {business.id}"
                )

        if not is_last_cycle:
            # Not the last cycle - generate invoice only, NO payment, NO receipt
            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] Generating invoice only (NO PAYMENT) for monthly billing/yearly payment plan "
                f"(cycle {subscription.billing_cycle_count + 1} of {duration_months or 'unknown'}): business {business.id}. "
                f"Payment will be processed on last cycle only."
            )
            _generate_invoice_only(subscription, today)
            # CRITICAL: Return here to prevent any payment processing
            return
        else:
            # Last cycle - process payment with FULL yearly amount
            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] Processing FINAL payment (FULL YEARLY AMOUNT) for monthly billing/yearly payment plan "
                f"(last cycle {subscription.billing_cycle_count + 1} of {duration_months or 'unknown'}): business {business.id}. "
                f"Charging full subscription amount, not divided amount."
            )
            # Mark subscription to indicate this is the last billing cycle
            # This will be used in calculate_base_amount to charge full yearly amount instead of divided amount
            subscription._is_last_billing_cycle = True
            # Continue with normal payment processing below

    # Initialize variables
    transaction_obj = None
    billing_details = None
    api_response = None
    payment_successful = False
    api_payload = None
    should_send_receipt = False
    should_send_failure_email = False
    failure_reason = None

    try:
        with transaction.atomic():
            # Calculate billing period based on payment type
            # PREPAID: Bill for future period (today to next month's billing date) - user pays in advance
            # POSTPAID: Bill for past period (last_billing_date to today) - user pays for period that just ended
            if payment_type == SubscriptionPaymentTypeChoices.PREPAID:
                # PREPAID: Bill from today to next month's billing date (future period)
                # User pays in advance for the upcoming period
                # For first billing: today = start_date, calculate next month from today
                # For recurring billing: today = billing date, calculate next month from today
                # IMPORTANT: Use today as start_date to ensure we bill from the actual billing date
                start_date = today
                # Calculate the next billing date from today (this will be the end of the period we're billing for)
                # Example: If today is Jan 21, 2026, end_date will be Feb 21, 2026
                end_date = subscription.calculate_next_billing_date(today) - timedelta(
                    days=1
                )
                logger.info(
                    f"[SUBSCRIPTION-FEE-TASK] PREPAID billing period: {start_date} to {end_date} "
                    f"(future period, cycle {subscription.billing_cycle_count + 1}) for business {business.id}. "
                    f"Today: {today}, Next billing date from DB: {subscription.next_billing_date}"
                )
            else:  # POSTPAID
                # POSTPAID: Bill from last_billing_date to today (past period that just ended)
                # User pays for the period that just completed
                # For first billing: last_billing_date = None, so use start_date to today
                # For recurring billing: last_billing_date to today
                start_date = subscription.last_billing_date or subscription.start_date
                end_date = today - timedelta(days=1)
                logger.info(
                    f"[SUBSCRIPTION-FEE-TASK] POSTPAID billing period: {start_date} to {end_date} "
                    f"(past period, cycle {subscription.billing_cycle_count + 1}) for business {business.id}"
                )

            # Create billing details
            (
                billing_details,
                purchase_requests,
                invoice_numbers_display,
            ) = create_subscription_billing_details(subscription, start_date, end_date)

            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] business {business.id}: Created billing "
                f"base={billing_details.base_amount}, total={billing_details.total_amount}"
            )

            # Send invoice BEFORE payment
            try:
                send_subscription_invoice(
                    billing_details,
                    business,
                    subscription.subscription_plan,
                    business.organization_id,
                    invoice_numbers_display,
                    business_subscription_plan=subscription,
                )
            except Exception as invoice_error:
                logger.error(
                    f"[SUBSCRIPTION-FEE-TASK] Failed to send invoice: {invoice_error}"
                )

            # Skip payment for FREE_TRIAL
            if not requires_payment:
                billing_details.payment_status = PaymentStatus.COMPLETED
                billing_details.save()
                subscription.update_billing_after_success()
                return

            # CRITICAL SAFETY CHECK: For POSTPAID monthly billing/yearly payment plans,
            # ensure we only process payment on the last cycle
            # This is a defensive check in case the early return above didn't catch it
            is_postpaid_monthly_yearly = (
                payment_type == SubscriptionPaymentTypeChoices.POSTPAID
                and subscription.billing_frequency == "MONTHLY"
                and subscription.payment_interval == "YEARLY"
            )

            if is_postpaid_monthly_yearly:
                is_last_cycle_flag = getattr(
                    subscription, "_is_last_billing_cycle", False
                )
                if not is_last_cycle_flag:
                    # This should never happen - the early return should have caught this
                    # But if we get here, it's a bug - log error and skip payment
                    logger.error(
                        f"[SUBSCRIPTION-FEE-TASK] CRITICAL: Attempted to process payment for "
                        f"POSTPAID monthly/yearly plan (non-last cycle) - business {business.id}, "
                        f"cycle {subscription.billing_cycle_count + 1}. This should not happen. "
                        f"Skipping payment to prevent incorrect charge."
                    )
                    # Set billing status to PENDING (payment deferred)
                    billing_details.payment_status = PaymentStatus.PENDING
                    billing_details.save()
                    subscription.update_billing_after_success()
                    return
                else:
                    # Last cycle - verify we're charging full amount
                    logger.info(
                        f"[SUBSCRIPTION-FEE-TASK] Processing payment for POSTPAID monthly/yearly plan "
                        f"(LAST CYCLE) - business {business.id}. "
                        f"Charging FULL yearly amount: {billing_details.base_amount}"
                    )

            # Process payment
            amount = billing_details.total_amount
            vat_rate = billing_details.vat_rate or Decimal("0.0000")
            vat_amount = billing_details.vat_amount or Decimal("0.00")

            # Create transaction record (store total amount including VAT)
            transaction_obj = Transaction.objects.create(
                from_business=business,
                to_business=business,
                amount=amount,
                vat_rate=vat_rate,
                vat=vat_amount,
                transaction_type=TransactionType.PAYMENT,
                transfer_via=TransferVia.CREDIMAX,
                status=TransactionStatus.PENDING,
                log_details=f"Recurring subscription payment for plan {subscription.subscription_plan.name if subscription.subscription_plan else subscription.subscription_name or 'N/A'}",
                created_by=subscription.created_by,
                business_subscription=subscription,
            )

            # Perform recurring charge
            try:
                api_payload, api_response = client.charge_recurring(
                    token=token_obj.token,
                    order=transaction_obj,
                    agreement=subscription,
                )
            except Exception as api_error:
                logger.error(f"API call failed for business {business.id}: {api_error}")
                raise api_error

            # Determine payment success
            payment_successful = (
                api_response.get("result") == "SUCCESS"
                and api_response.get("order", {}).get("status") == "CAPTURED"
            )

            payment_details = extract_payment_details(api_response)

            if payment_successful:
                logger.info(
                    f"[SUBSCRIPTION-FEE-TASK] Payment successful: business {business.id} - {amount}"
                )
            else:
                failure_msg = payment_details.get(
                    "acquirer_message"
                ) or payment_details.get("gateway_code")
                logger.warning(
                    f"[SUBSCRIPTION-FEE-TASK] Payment failed: business {business.id} - {failure_msg}"
                )

            # Record webhook
            try:
                record_recurring_payment_webhook(
                    transaction_obj, api_response, payment_successful, api_payload
                )
            except Exception as webhook_error:
                logger.error(
                    f"[SUBSCRIPTION-FEE-TASK] Webhook error for business {business.id}: {webhook_error}"
                )

            # Update transaction and billing status
            if payment_successful:
                transaction_obj.status = TransactionStatus.SUCCESS
                billing_details.payment_status = PaymentStatus.COMPLETED
                billing_details.save()

                # Check if this is final billing (day after expiry_date)
                # CRITICAL: Check by dates, not status, because subscription might still be ACTIVE
                # when billing runs (expiration happens after billing)
                is_final_billing = (
                    subscription.expiry_date
                    and subscription.expiry_date < today  # Day after expiry_date
                    and subscription.next_billing_date
                    == subscription.expiry_date  # Final billing
                )

                if is_final_billing:
                    # For final billing (day after expiry_date), only update billing records
                    # Don't update next_billing_date or extend expiry_date
                    # The subscription will be expired in the next step
                    subscription.last_billing_date = today
                    subscription.billing_cycle_count += 1
                    subscription.retry_count = 0
                    subscription.save(
                        update_fields=[
                            "last_billing_date",
                            "billing_cycle_count",
                            "retry_count",
                            "updated_at",
                        ]
                    )
                    logger.info(
                        f"[SUBSCRIPTION-FEE-TASK] Final billing completed - "
                        f"business {business.id}, subscription {subscription.id}. "
                        f"expiry_date: {subscription.expiry_date}, today: {today}. "
                        f"Subscription will be expired in next step."
                    )
                else:
                    # Normal billing update (for ACTIVE subscriptions that are not final billing)
                    # This extends expiry_date and updates next_billing_date
                    subscription.update_billing_after_success()

                # If auto-renew is disabled and this is POSTPAID, cancel subscription after successful payment
                if (
                    not subscription.is_auto_renew
                    and payment_type == SubscriptionPaymentTypeChoices.POSTPAID
                ):
                    subscription.status = SubscriptionStatusChoices.CANCELLED
                    subscription.cancelled_date = today
                    subscription.save(
                        update_fields=["status", "cancelled_date", "updated_at"]
                    )
                    logger.info(
                        f"[SUBSCRIPTION-FEE-TASK] Subscription cancelled for business {business.id} "
                        f"after final POSTPAID billing (is_auto_renew=False)"
                    )

                    # Send cancellation notification to all users in the business
                    # This must be outside the atomic transaction to avoid database connection issues
                    try:
                        _send_subscription_cancellation_notification(subscription)
                    except Exception as notification_error:
                        logger.error(
                            f"[SUBSCRIPTION-FEE-TASK] Failed to send cancellation notification "
                            f"for business {business.id}: {notification_error}",
                            exc_info=True,
                        )
                        # Don't fail the payment process if notification fails

                should_send_receipt = True
            else:
                transaction_obj.status = TransactionStatus.FAILED
                billing_details.payment_status = PaymentStatus.FAILED
                billing_details.save()

                failure_reason = (
                    payment_details.get("acquirer_message")
                    or payment_details.get("gateway_code")
                    or f"Payment declined (Status: {payment_details.get('order_status')})"
                )
                should_send_failure_email = True
                handle_payment_failure(
                    subscription, transaction_obj, api_response, api_payload
                )

            transaction_obj.save()

        # Send emails and notifications OUTSIDE atomic transaction
        if should_send_receipt and billing_details and transaction_obj:
            _send_receipt_email(
                billing_details, business, subscription, transaction_obj
            )

            # Send FCM notification to all users in the business about successful recurring payment
            # This must be outside the atomic transaction to avoid database connection issues
            try:
                users = User.objects.filter(
                    user_assigned_businesses__business=business,
                    user_preference__notifications_enabled=True,
                ).distinct()

                if users.exists():
                    plan_name = subscription.subscription_name or (
                        subscription.subscription_plan.name
                        if subscription.subscription_plan
                        else "Subscription Plan"
                    )

                    content_type = ContentType.objects.get_for_model(
                        BusinessSubscriptionPlan
                    )
                    send_notifications(
                        users=users,
                        title="Subscription Payment Processed",
                        message=f"Your recurring payment of BHD {billing_details.total_amount:.2f} for {plan_name} has been successfully processed.",
                        notification_type=NotificationTypes.BUSINESS_SUBSCRIPTION_PLAN,
                        content_type=content_type,
                        object_id=str(transaction_obj.id),
                    )

                    logger.info(
                        f"[SUBSCRIPTION-FEE-TASK] Sent recurring payment notification to {len(users)} users "
                        f"for business {business.id} (subscription {subscription.id})"
                    )
                else:
                    logger.warning(
                        f"[SUBSCRIPTION-FEE-TASK] No users with notifications enabled found "
                        f"for business {business.id} (subscription {subscription.id})"
                    )
            except Exception as notification_error:
                logger.error(
                    f"[SUBSCRIPTION-FEE-TASK] Failed to send recurring payment notification "
                    f"for business {business.id}: {notification_error}",
                    exc_info=True,
                )
                # Don't fail the payment process if notification fails

        if should_send_failure_email and billing_details and transaction_obj:
            _send_failure_email(business, subscription, transaction_obj, failure_reason)

    except Exception as e:
        logger.exception(
            f"[SUBSCRIPTION-FEE-TASK] Error processing business {business.id}: {e}"
        )

        # Preserve payment success if it occurred
        if payment_successful and transaction_obj:
            _preserve_payment_success(subscription, transaction_obj, billing_details)

        # Store error webhook
        if transaction_obj and api_payload:
            try:
                record_recurring_payment_webhook(
                    transaction_obj,
                    {"error": str(e), "result": "ERROR"},
                    False,
                    api_payload,
                )
            except Exception as error_webhook_error:
                logger.error(f"Failed to record error webhook: {error_webhook_error}")


def _process_prepaid_pro_rata_recalculation(subscription, client, today):
    """
    Process pro rata recalculation for PREPAID investors.

    Recalculates pro rata for remaining assets and deducts the updated amount.
    On January 1st, recalculates pro rata for ALL remaining assets (regardless of purchase date).
    """
    business = subscription.business
    pro_rata_rate = subscription.pro_rata_rate

    logger.info(f"[PRO-RATA-TASK] Processing PREPAID: business {business.id}")

    from sooq_althahab.enums.investor import RequestType

    # Get all purchase requests with remaining assets (not just from previous year)
    # On Jan 1st, we recalculate pro rata for ALL remaining assets
    purchase_requests = PurchaseRequest.objects.filter(
        business=business,
        request_type=RequestType.PURCHASE,
        status__in=[PurchaseRequestStatus.APPROVED, PurchaseRequestStatus.COMPLETED],
        pro_rata_mode=SubscriptionPaymentTypeChoices.PREPAID,
    ).select_related(
        "precious_item",
        "precious_item__precious_metal",
        "precious_item__precious_stone",
    )

    logger.info(
        f"[PRO-RATA-TASK] Found {purchase_requests.count()} purchase request(s) for business {business.id}"
    )

    total_pro_rata_amount = Decimal("0.00")
    processed_count = 0

    for purchase_request in purchase_requests:
        # Use remaining_quantity property (this is safe - it's a read-only property)
        remaining_qty = purchase_request.remaining_quantity

        if remaining_qty and remaining_qty > 0:
            processed_count += 1
            # Calculate pro rata for remaining quantity
            if purchase_request.precious_item.material_type == MaterialType.METAL:
                # For METAL: pro_rata = remaining_weight × price_locked × pro_rata_rate
                # Get remaining weight from units
                from investor.models import PreciousItemUnit

                available_units = PreciousItemUnit.objects.filter(
                    purchase_request=purchase_request,
                    sale_request__isnull=True,
                    pool__isnull=True,
                )

                # Sum remaining weights
                total_remaining_weight = Decimal("0.00")
                for unit in available_units:
                    total_remaining_weight += unit.remaining_weight or Decimal("0.00")

                # Calculate pro rata
                price_locked = purchase_request.price_locked or Decimal("0.00")
                pro_rata_amount = total_remaining_weight * price_locked * pro_rata_rate

                logger.debug(
                    f"[PRO-RATA-TASK] METAL purchase {purchase_request.id}: "
                    f"remaining_weight={total_remaining_weight}, price_locked={price_locked}, "
                    f"pro_rata_rate={pro_rata_rate}, amount={pro_rata_amount}"
                )

            else:  # STONE
                # For STONE: pro_rata = order_cost × pro_rata_rate
                # Calculate based on remaining quantity proportion
                order_cost = purchase_request.order_cost or Decimal("0.00")
                requested_qty = purchase_request.requested_quantity or Decimal("1.00")
                remaining_proportion = (
                    remaining_qty / requested_qty
                    if requested_qty > 0
                    else Decimal("0.00")
                )

                pro_rata_amount = order_cost * remaining_proportion * pro_rata_rate

                logger.debug(
                    f"[PRO-RATA-TASK] STONE purchase {purchase_request.id}: "
                    f"order_cost={order_cost}, remaining_qty={remaining_qty}, "
                    f"requested_qty={requested_qty}, proportion={remaining_proportion}, "
                    f"pro_rata_rate={pro_rata_rate}, amount={pro_rata_amount}"
                )

            total_pro_rata_amount += pro_rata_amount

    logger.info(
        f"[PRO-RATA-TASK] Processed {processed_count} purchase request(s) with remaining assets "
        f"for business {business.id}"
    )

    if total_pro_rata_amount > 0:
        logger.info(
            f"[PRO-RATA-TASK] PREPAID total: business {business.id} - {total_pro_rata_amount}"
        )
        # Process the payment
        _process_pro_rata_payment(subscription, total_pro_rata_amount, client, today)
    else:
        logger.info(
            f"[PRO-RATA-TASK] No pro rata amount: business {business.id} "
            f"(found {purchase_requests.count()} purchase requests, "
            f"{processed_count} with remaining assets)"
        )


def _process_postpaid_pro_rata_charge(subscription, client, today):
    """
    Process accumulated pro rata charge for POSTPAID investors.

    Charges the full accumulated pro rata from previous year.
    If assets were partially sold, calculates based on days held.
    """
    business = subscription.business
    pro_rata_rate = subscription.pro_rata_rate

    logger.info(f"[PRO-RATA-TASK] Processing POSTPAID: business {business.id}")

    # Get all purchase requests from previous year
    previous_year_start = datetime(today.year - 1, 1, 1).date()
    previous_year_end = datetime(today.year - 1, 12, 31).date()

    from sooq_althahab.enums.investor import RequestType

    purchase_requests = PurchaseRequest.objects.filter(
        business=business,
        request_type=RequestType.PURCHASE,
        status__in=[PurchaseRequestStatus.APPROVED, PurchaseRequestStatus.COMPLETED],
        pro_rata_mode=SubscriptionPaymentTypeChoices.POSTPAID,
        created_at__date__range=(previous_year_start, previous_year_end),
    ).select_related("precious_item")

    total_pro_rata_amount = Decimal("0.00")

    for purchase_request in purchase_requests:
        requested_qty = Decimal(purchase_request.requested_quantity or 0)
        if requested_qty <= 0:
            continue

        purchase_date = (
            purchase_request.created_at.date()
            if purchase_request.created_at
            else previous_year_start
        )
        start_date = max(previous_year_start, purchase_date)

        # Determine base fee for the charged year:
        # - If the asset was purchased in this charged year, use the stored pro_rata_fee
        #   (already represents remaining months of that year).
        # - Otherwise, use the annual fee for a full year.
        purchased_this_year = purchase_date.year == previous_year_start.year
        if purchased_this_year:
            base_fee = purchase_request.pro_rata_fee or Decimal("0.00")
            period_end = previous_year_end
        else:
            base_fee = purchase_request.annual_pro_rata_fee or (
                (purchase_request.order_cost or Decimal("0.00")) * pro_rata_rate
            )
            period_end = previous_year_end

        period_days = Decimal((period_end - start_date).days + 1)
        if period_days <= 0:
            continue

        per_unit_base_fee = (
            base_fee / requested_qty if requested_qty else Decimal("0.00")
        )

        # Track sold quantity within the year with proportional charge by days held
        from sooq_althahab.enums.investor import RequestType as InvestorRequestType

        sales_in_year = purchase_request.sale_requests.filter(
            request_type=InvestorRequestType.SALE,
            status__in=[
                PurchaseRequestStatus.APPROVED,
                PurchaseRequestStatus.COMPLETED,
            ],
            approved_at__date__range=(previous_year_start, previous_year_end),
        )

        total_charge_for_request = Decimal("0.00")
        sold_qty = Decimal("0.00")

        for sale in sales_in_year:
            qty_sold = Decimal(sale.requested_quantity or 0)
            if qty_sold <= 0:
                continue

            sold_qty += qty_sold
            sale_date = sale.approved_at.date() if sale.approved_at else period_end
            sale_date = max(start_date, sale_date)

            days_held = Decimal((sale_date - start_date).days + 1)
            proportion = min(
                max(days_held, Decimal("0.00")) / period_days, Decimal("1.00")
            )

            charge = per_unit_base_fee * qty_sold * proportion
            total_charge_for_request += charge

        # Remaining quantity (held through the year)
        remaining_qty = requested_qty - sold_qty
        if remaining_qty > 0:
            days_for_remaining = Decimal((period_end - start_date).days + 1)
            proportion_remaining = min(
                max(days_for_remaining, Decimal("0.00")) / period_days, Decimal("1.00")
            )
            total_charge_for_request += (
                per_unit_base_fee * remaining_qty * proportion_remaining
            )

        logger.debug(
            f"[PRO-RATA-TASK] POSTPAID pr {purchase_request.id}: "
            f"base_fee={base_fee}, per_unit={per_unit_base_fee}, "
            f"start_date={start_date}, sold_qty={sold_qty}, remaining_qty={remaining_qty}, "
            f"charge={total_charge_for_request}"
        )

        total_pro_rata_amount += total_charge_for_request

    if total_pro_rata_amount > 0:
        logger.info(
            f"[PRO-RATA-TASK] POSTPAID total: business {business.id} - {total_pro_rata_amount}"
        )
        # Process the payment
        _process_pro_rata_payment(subscription, total_pro_rata_amount, client, today)
    else:
        logger.info(f"[PRO-RATA-TASK] No pro rata amount: business {business.id}")


def _process_pro_rata_payment(subscription, amount, client, today):
    """
    Process payment for pro rata amount.

    Creates billing, processes payment, and sends receipts.
    """
    business = subscription.business
    token_obj = subscription.business_saved_card_token

    # Get default card if not set
    if not token_obj:
        token_obj = _get_default_card_for_business(business, subscription, client)
        if not token_obj:
            logger.warning(
                f"[PRO-RATA-TASK] Skipping business {business.id} - No payment token"
            )
            return

    # Create billing details for pro rata
    from sooq_althahab.billing.subscription.services import (
        monthly_subscription_calculation,
    )
    from sooq_althahab_admin.models import BillingDetails

    organization = business.organization_id
    organization_vat_rate = organization.vat_rate if organization else Decimal("0.00")
    organization_tax_rate = organization.tax_rate if organization else Decimal("0.00")

    # Calculate VAT and total
    vat_amount = amount * organization_vat_rate
    tax_amount = amount * organization_tax_rate
    total_amount = amount + vat_amount + tax_amount

    # Create billing record
    billing_details = BillingDetails.objects.create(
        business=business,
        period_start_date=datetime(today.year - 1, 1, 1).date(),
        period_end_date=datetime(today.year - 1, 12, 31).date(),
        base_amount=amount,
        commission_fee=Decimal("0.00"),
        service_fee=Decimal("0.00"),
        vat_rate=organization_vat_rate,
        vat_amount=vat_amount,
        tax_rate=organization_tax_rate,
        tax_amount=tax_amount,
        total_amount=total_amount,
        payment_status=PaymentStatus.PENDING,
        notes="Pro rata fee for previous year",
    )

    # Send invoice
    try:
        send_subscription_invoice(
            billing_details,
            business,
            subscription.subscription_plan,
            organization,
            "",
            business_subscription_plan=subscription,
        )
    except Exception as invoice_error:
        logger.error(f"[PRO-RATA-TASK] Failed to send invoice: {invoice_error}")

    # Process payment
    transaction_obj = None
    api_response = None
    payment_successful = False
    api_payload = None

    try:
        with transaction.atomic():
            # Create transaction
            transaction_obj = Transaction.objects.create(
                from_business=business,
                to_business=business,
                amount=total_amount,
                vat_rate=organization_vat_rate,
                vat=vat_amount,
                transaction_type=TransactionType.PAYMENT,
                transfer_via=TransferVia.CREDIMAX,
                status=TransactionStatus.PENDING,
                log_details=f"Pro rata payment for {today.year - 1}",
                created_by=subscription.created_by,
                business_subscription=subscription,
            )

            # Charge payment
            api_payload, api_response = client.charge_recurring(
                token=token_obj.token,
                order=transaction_obj,
                agreement=subscription,
            )

            # Check payment success
            payment_successful = (
                api_response.get("result") == "SUCCESS"
                and api_response.get("order", {}).get("status") == "CAPTURED"
            )

            # Record webhook
            record_recurring_payment_webhook(
                transaction_obj, api_response, payment_successful, api_payload
            )

            # Update status
            if payment_successful:
                transaction_obj.status = TransactionStatus.SUCCESS
                billing_details.payment_status = PaymentStatus.COMPLETED
                logger.info(
                    f"[PRO-RATA-TASK] Payment successful: business {business.id} - {total_amount}"
                )
            else:
                transaction_obj.status = TransactionStatus.FAILED
                billing_details.payment_status = PaymentStatus.FAILED
                handle_payment_failure(
                    subscription, transaction_obj, api_response, api_payload
                )
                logger.warning(
                    f"[PRO-RATA-TASK] Payment failed: business {business.id}"
                )

            transaction_obj.save()
            billing_details.save()

        # Send receipt if successful
        if payment_successful and transaction_obj:
            _send_receipt_email(
                billing_details, business, subscription, transaction_obj
            )
        elif not payment_successful and transaction_obj:
            _send_failure_email(
                business, subscription, transaction_obj, "Pro rata payment failed"
            )

    except Exception as e:
        logger.exception(
            f"[PRO-RATA-TASK] Error processing pro rata payment for business {business.id}: {e}"
        )


def _get_default_card_for_business(business, subscription, client):
    """Get default card for business and update subscription if needed."""
    default_card = BusinessSavedCardToken.objects.filter(
        business=business, is_used_for_subscription=True
    ).first()

    if default_card:
        logger.info(
            f"No card on subscription, using default card {default_card.id} "
            f"for business {business.id}"
        )

        # CRITICAL: Unassign card token from any existing subscription first
        # This prevents OneToOne constraint violation (one card can only be assigned to one subscription)
        existing_subscription = (
            BusinessSubscriptionPlan.objects.filter(
                business_saved_card_token=default_card
            )
            .exclude(id=subscription.id)
            .first()
        )

        if existing_subscription:
            # Unassign from previous subscription to avoid OneToOne constraint violation
            logger.info(
                f"Unassigning card {default_card.id} from existing subscription "
                f"{existing_subscription.id} before assigning to {subscription.id}"
            )
            existing_subscription.business_saved_card_token = None
            existing_subscription.save(update_fields=["business_saved_card_token"])

        # Now assign the card to the current subscription
        subscription.business_saved_card_token = default_card
        subscription.save(update_fields=["business_saved_card_token"])

        # Update Credimax agreement
        try:
            client.update_agreement_with_card(
                agreement=subscription,
                token=default_card.token,
            )
        except Exception as update_error:
            logger.error(
                f"Failed to update agreement {subscription.id} with default card: {str(update_error)}"
            )

    return default_card


def _generate_invoice_only(subscription, today):
    """
    Generate invoice only without payment.

    Used for:
    1. Yearly PREPAID plans (payment already made at purchase)
    2. POSTPAID monthly billing/yearly payment plans (non-last cycles)

    IMPORTANT: No transaction is created, no payment is processed, no receipt is sent.
    """
    business = subscription.business
    start_date = subscription.last_billing_date or subscription.start_date
    end_date = subscription.next_billing_date

    try:
        # Determine payment status based on plan type
        # For POSTPAID monthly/yearly plans, payment is deferred until last cycle
        is_postpaid_monthly_yearly = (
            subscription.payment_type == SubscriptionPaymentTypeChoices.POSTPAID
            and subscription.billing_frequency == "MONTHLY"
            and subscription.payment_interval == "YEARLY"
        )

        if is_postpaid_monthly_yearly:
            # For POSTPAID monthly/yearly (non-last cycle), payment is deferred
            # Use PENDING status to indicate payment will be processed later
            payment_status = PaymentStatus.PENDING
            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] Generating invoice for POSTPAID monthly/yearly plan "
                f"(non-last cycle) - business {business.id}. Payment deferred until last cycle."
            )
        else:
            # For yearly PREPAID plans, payment was already made at purchase
            payment_status = PaymentStatus.COMPLETED
            logger.info(
                f"[SUBSCRIPTION-FEE-TASK] Generating invoice for yearly PREPAID plan "
                f"- business {business.id}. Payment already made at purchase."
            )

        (
            billing_details,
            purchase_requests,
            invoice_numbers_display,
        ) = create_subscription_billing_details(subscription, start_date, end_date)

        # CRITICAL: Set payment status (PENDING for POSTPAID deferred, COMPLETED for PREPAID)
        billing_details.payment_status = payment_status
        billing_details.save()

        # Send invoice only (no payment, no receipt)
        send_subscription_invoice(
            billing_details,
            business,
            subscription.subscription_plan,
            business.organization_id,
            invoice_numbers_display,
            business_subscription_plan=subscription,
        )

        # Update billing cycle (increment cycle count, update dates)
        subscription.update_billing_after_success()

        logger.info(
            f"[SUBSCRIPTION-FEE-TASK] Invoice generated (invoice only, no payment): business {business.id}"
        )
    except Exception as e:
        logger.error(
            f"[SUBSCRIPTION-FEE-TASK] Failed to generate invoice for business {business.id}: {e}",
            exc_info=True,
        )


def _send_receipt_email(billing_details, business, subscription, transaction_obj):
    """Send receipt email after successful payment."""
    try:
        import time

        time.sleep(2)  # Delay between invoice and receipt emails

        send_subscription_receipt_after_payment(
            billing_details,
            business,
            subscription.subscription_plan,
            business.organization_id,
            transaction_obj,
            business_subscription_plan=subscription,
        )
        logger.info(f"[SUBSCRIPTION-FEE-TASK] Receipt sent: business {business.id}")
    except Exception as email_error:
        logger.error(f"Failed to send receipt: {email_error}")


def _send_failure_email(business, subscription, transaction_obj, failure_reason):
    """Send failure email for failed payment."""
    try:
        owner_assignment = business.user_assigned_businesses.filter(
            is_owner=True
        ).first()

        if not owner_assignment or not owner_assignment.user:
            logger.warning(f"No owner found for business {business.id}")
            return

        user = owner_assignment.user
        organization = getattr(business, "organization_id", None)

        if not organization or not getattr(user, "email", None):
            logger.warning(
                f"Cannot send failure email for business {business.id} - missing organization or email"
            )
            return

        user_email = user.email
        business_display_name = _get_business_display_name(business)
        user_fullname = getattr(user, "fullname", None) or ""
        display_name = (
            business_display_name or user_fullname or user_email or "Customer"
        )

        subscription_plan = getattr(subscription, "subscription_plan", None)
        plan_name = (
            getattr(subscription_plan, "name", None)
            if subscription_plan
            else "Subscription Plan"
        )

        try:
            amount = (
                Decimal(str(transaction_obj.amount))
                if transaction_obj.amount
                else Decimal("0.00")
            )
            vat = (
                Decimal(str(transaction_obj.vat))
                if transaction_obj.vat
                else Decimal("0.00")
            )
            subscription_amount = amount + vat
        except (ValueError, TypeError, AttributeError):
            subscription_amount = Decimal("0.00")

        try:
            organization_logo_url = get_organization_logo_url(organization)
        except Exception:
            organization_logo_url = ""

        email_context = {
            "organization_name": getattr(organization, "name", None) or "Organization",
            "business_name": business_display_name,
            "user_fullname": user_fullname,
            "display_name": display_name,
            "plan_name": plan_name,
            "plan_start_date": getattr(subscription, "start_date", None) or "N/A",
            "plan_end_date": getattr(subscription, "next_billing_date", None) or "N/A",
            "subscription_plan_duration": (
                getattr(subscription_plan, "duration", None)
                if subscription_plan
                else "N/A"
            ),
            "subscription_amount": subscription_amount,
            "organization_logo_url": organization_logo_url,
            "status": getattr(transaction_obj, "status", None) or "FAILED",
            "failure_reason": failure_reason or "Payment declined",
            "is_debit_card_failure": (
                bool(failure_reason and "DEBIT" in str(failure_reason).upper())
                if failure_reason
                else False
            ),
        }

        organization_name = getattr(organization, "name", None) or "Organization"
        failed_transaction_send_mail(
            [user_email],
            email_context,
            organization_name=organization_name,
        )
        logger.info(f"Failure email sent to business {business.id}")
    except Exception as email_error:
        logger.error(f"Failed to send failure email: {email_error}")


def _preserve_payment_success(subscription, transaction_obj, billing_details):
    """Preserve payment success status if error occurred after payment."""
    try:
        if transaction_obj.status != TransactionStatus.SUCCESS:
            transaction_obj.status = TransactionStatus.SUCCESS
            transaction_obj.save()

        if billing_details:
            billing_details.payment_status = PaymentStatus.COMPLETED
            billing_details.save()

        if subscription.retry_count > 0:
            subscription.update_billing_after_success()

        logger.info(
            f"[SUBSCRIPTION-FEE-TASK] Payment success preserved: business {subscription.business.id}"
        )
    except Exception as recovery_error:
        logger.error(f"Failed to preserve payment success: {recovery_error}")


def create_subscription_billing_details(subscription, start_date, end_date):
    """
    Create BillingDetails record for a subscription billing cycle.

    This function is kept for backward compatibility and is used by all tasks.
    """
    business = subscription.business

    (
        billing_details,
        purchase_requests,
        invoice_numbers_display,
    ) = monthly_subscription_calculation(
        start_date=start_date,
        end_date=end_date,
        business=business,
        business_subscription=subscription,
    )

    return billing_details, purchase_requests, invoice_numbers_display


def record_recurring_payment_webhook(
    transaction_obj, api_response, payment_successful, api_payload=None
):
    """
    Record the recurring payment API response as a webhook call.
    """
    try:
        webhook_status = (
            WebhookCallStatus.SUCCESS
            if payment_successful
            else WebhookCallStatus.FAILURE
        )

        webhook_call = WebhookCall.objects.create(
            transaction=transaction_obj,
            transfer_via=TransferVia.CREDIMAX,
            event_type=WebhookEventType.PAYMENT,
            status=webhook_status,
            request_body=api_payload,
            response_body=api_response or {},
            response_status_code=200 if payment_successful else 402,
        )

        if payment_successful and api_response:
            payment_details = extract_payment_details(api_response)
            # Use transaction amount from database (actual processed amount) instead of API response amount
            # API response amount may differ due to rounding or API-specific formatting
            transaction_amount = transaction_obj.amount or Decimal("0.00")
            logger.info(
                f"Webhook recorded: Transaction {transaction_obj.id} - "
                f"Amount: {transaction_amount} "
                f"AuthCode: {payment_details.get('authorization_code')}"
            )

        return webhook_call

    except Exception as e:
        logger.error(
            f"Failed to record webhook call for transaction {transaction_obj.id}: {e}"
        )
        raise


def handle_payment_failure(subscription, transaction, response, api_payload=None):
    """
    Handle failed payment with retry logic.
    """
    try:
        try:
            record_recurring_payment_webhook(transaction, response, False, api_payload)
        except Exception as webhook_error:
            logger.error(
                f"Failed to record failure webhook for transaction {transaction.id}: {webhook_error}"
            )

        subscription.update_billing_after_failure()

        if subscription.retry_count >= subscription.max_retry_attempts:
            subscription.status = SubscriptionStatusChoices.FAILED
            subscription.save()
            logger.error(
                f"Subscription {subscription.id} marked as failed after {subscription.max_retry_attempts} retries"
            )
        else:
            subscription.save()
            logger.info(
                f"Retry {subscription.retry_count} scheduled for subscription {subscription.id}"
            )

    except Exception as e:
        logger.error(
            f"Error in handle_payment_failure for subscription {subscription.id}: {e}"
        )
        try:
            subscription.update_billing_after_failure()
            subscription.save()
        except Exception as update_error:
            logger.error(
                f"Failed to update subscription {subscription.id} after error: {update_error}"
            )


def extract_payment_details(api_response):
    """
    Extract key payment details from Credimax API response.
    """
    if not api_response:
        return {}

    order_info = api_response.get("order", {})
    transaction_info = api_response.get("transaction", {})
    response_info = api_response.get("response", {})

    return {
        "result": api_response.get("result"),
        "order_status": order_info.get("status"),
        "amount": order_info.get("amount"),
        "currency": order_info.get("currency"),
        "authorization_code": transaction_info.get("authorizationCode"),
        "receipt": transaction_info.get("receipt"),
        "stan": transaction_info.get("stan"),
        "gateway_code": response_info.get("gatewayCode"),
        "acquirer_message": response_info.get("acquirerMessage"),
        "acquirer_code": response_info.get("acquirerCode"),
    }
