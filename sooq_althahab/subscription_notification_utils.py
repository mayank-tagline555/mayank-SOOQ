"""
Subscription notification utilities for handling subscription expiration notifications.

This module contains helper functions for managing subscription expiration notifications,
including sending notifications, handling grace periods, and managing subscription statuses.
"""

import logging
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils import timezone

from sooq_althahab.enums.account import SubscriptionStatusChoices
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.enums.sooq_althahab_admin import SubscriptionPaymentTypeChoices
from sooq_althahab.tasks import send_mail
from sooq_althahab.utils import send_notifications
from sooq_althahab_admin.models import BusinessSubscriptionPlan

logger = logging.getLogger(__name__)


def get_business_owner(business):
    """
    Get the business owner from the business account.

    Args:
        business: BusinessAccount instance

    Returns:
        User instance or None if no owner found
    """
    business_owner_assignment = (
        business.user_assigned_businesses.filter(is_owner=True)
        .select_related("user")
        .first()
    )
    return business_owner_assignment.user if business_owner_assignment else None


def get_plan_name(subscription):
    """
    Get the subscription plan name, with fallbacks.

    Args:
        subscription: BusinessSubscriptionPlan instance

    Returns:
        str: Plan name
    """
    if subscription.subscription_plan:
        return subscription.subscription_plan.name
    elif subscription.subscription_name:
        return subscription.subscription_name
    else:
        return "Subscription Plan"


def send_expiration_notifications(
    expiring_date, notification_type, days_until_expiry, stats
):
    """
    Send notifications for subscriptions expiring on a specific date.

    Args:
        expiring_date: Date when subscriptions expire
        notification_type: Type of notification to send
        days_until_expiry: Number of days until expiry
        stats: Dictionary to track statistics
    """
    logger.info(f"Checking for subscriptions expiring on {expiring_date}")

    # Get all active subscriptions expiring on the specified date
    # Include both ACTIVE and TRIALING statuses, and all payment types
    expiring_subscriptions = BusinessSubscriptionPlan.objects.filter(
        Q(status=SubscriptionStatusChoices.ACTIVE)
        | Q(status=SubscriptionStatusChoices.TRIALING),
        expiry_date=expiring_date,
    ).select_related("business", "subscription_plan")

    logger.info(
        f"Found {expiring_subscriptions.count()} subscriptions expiring on {expiring_date}"
    )

    for subscription in expiring_subscriptions:
        try:
            business_owner = get_business_owner(subscription.business)
            if not business_owner:
                continue

            # Prepare notification details
            plan_name = get_plan_name(subscription)

            # Create appropriate message based on days until expiry
            if days_until_expiry == 1:
                message = f"Your {plan_name} subscription expires tomorrow ({subscription.expiry_date.strftime('%B %d, %Y')}). Please renew to avoid service interruption."
            elif days_until_expiry == 2:
                message = f"Your {plan_name} subscription will expire in 2 days ({subscription.expiry_date.strftime('%B %d, %Y')}). Please renew to continue using our services."
            elif days_until_expiry == 3:
                message = f"Your {plan_name} subscription will expire in 3 days ({subscription.expiry_date.strftime('%B %d, %Y')}). Please renew to continue using our services."
            else:
                message = f"Your {plan_name} subscription will expire in {days_until_expiry} days ({subscription.expiry_date.strftime('%B %d, %Y')}). Please renew to continue using our services."

            # Send in-app notification
            content_type = ContentType.objects.get_for_model(BusinessSubscriptionPlan)
            send_notifications(
                users=[business_owner],
                title="Subscription Expiring Soon",
                message=message,
                notification_type=notification_type,
                content_type=content_type,
                object_id=str(subscription.id),
            )

            # Send email notification
            send_expiration_email_notification(
                business_owner, subscription, days_until_expiry
            )

            stats["notifications_sent"] += 1
            logger.info(
                f"Sent expiration notification to {subscription.business.name} ({business_owner.email})"
            )

        except Exception as e:
            stats["errors"] += 1
            logger.exception(
                f"Failed to send expiration notification for {subscription.business.name}: {e}"
            )


def handle_expiring_subscriptions_today(today, stats):
    """
    Send notifications (FCM and email) for subscriptions that are expiring today.

    Informs users that their subscription expires today at midnight, so they can use it
    until today (until 11:59 PM today).

    Note: This function only sends notifications. Subscription expiration (status change)
    is handled by _check_and_expire_subscriptions in the subscription fee recurring payment task.

    Args:
        today: Current date
        stats: Dictionary to track statistics
    """
    logger.info(f"Sending notifications for subscriptions expiring today: {today}")

    # Get all subscriptions expiring today
    # Check both ACTIVE/TRIALING (not yet expired - can still use today) and EXPIRED
    # (in case expiration task already ran - backup notification)
    expiring_today = BusinessSubscriptionPlan.objects.filter(
        Q(
            status__in=[
                SubscriptionStatusChoices.ACTIVE,
                SubscriptionStatusChoices.TRIALING,
                SubscriptionStatusChoices.EXPIRED,
            ]
        ),
        expiry_date=today,
    ).select_related("business", "subscription_plan")

    logger.info(f"Found {expiring_today.count()} subscriptions expiring today")

    for subscription in expiring_today:
        try:
            business_owner = get_business_owner(subscription.business)
            if not business_owner:
                continue

            plan_name = get_plan_name(subscription)

            # Determine if subscription is still active (can use until today) or already expired
            is_still_active = subscription.status in [
                SubscriptionStatusChoices.ACTIVE,
                SubscriptionStatusChoices.TRIALING,
            ]

            if is_still_active:
                # Subscription expires today at midnight - user can still use until today
                message = (
                    f"Your {plan_name} subscription expires today at midnight. "
                    f"You can continue using the service until 11:59 PM today. Please renew to avoid service interruption."
                )
                title = "Subscription Expires Today"
                # Send email with "expires today" message (not "has expired")
                send_expiration_email_notification(
                    business_owner, subscription, 0, is_expired=False
                )
            else:
                # Subscription already expired
                message = (
                    f"Your {plan_name} subscription has expired. "
                    f"Please renew to continue using our services."
                )
                title = "Subscription Expired"
                # Send email with "has expired" message
                send_expiration_email_notification(
                    business_owner, subscription, 0, is_expired=True
                )

            # Send FCM notification (in-app notification)
            # Notification Type: BUSINESS_SUBSCRIPTION_EXPIRING_TODAY
            # Frontend should redirect to: Subscription/Renewal page when user taps notification
            # The object_id contains the subscription ID that can be used to fetch subscription details
            content_type = ContentType.objects.get_for_model(BusinessSubscriptionPlan)
            send_notifications(
                users=[business_owner],
                title=title,
                message=message,
                notification_type=NotificationTypes.BUSINESS_SUBSCRIPTION_EXPIRING_TODAY,
                content_type=content_type,
                object_id=str(subscription.id),
            )

            stats["notifications_sent"] += 1
            logger.info(
                f"Sent expiration notifications (FCM and email) for {subscription.business.name}"
            )

        except Exception as e:
            stats["errors"] += 1
            logger.exception(
                f"Failed to send notification for expiring subscription {subscription.business.name}: {e}"
            )


def handle_grace_period_subscriptions(today, stats):
    """
    Handle subscriptions that are in grace period and may need to be expired.

    Args:
        today: Current date
        stats: Dictionary to track statistics
    """
    logger.info("Checking for subscriptions in grace period that should be expired")

    # Get all suspended subscriptions
    suspended_subscriptions = BusinessSubscriptionPlan.objects.filter(
        status=SubscriptionStatusChoices.SUSPENDED,
    ).select_related("business", "subscription_plan")

    # Filter those past their grace period (using each subscription's grace_period_days)
    grace_period_subscriptions = []
    for subscription in suspended_subscriptions:
        grace_period_days = (
            subscription.grace_period_days or 3
        )  # Default to 3 if not set
        grace_period_cutoff = today - timedelta(days=grace_period_days)

        if subscription.expiry_date and subscription.expiry_date <= grace_period_cutoff:
            grace_period_subscriptions.append(subscription)

    logger.info(
        f"Found {len(grace_period_subscriptions)} subscriptions past grace period"
    )

    for subscription in grace_period_subscriptions:
        try:
            business_owner = get_business_owner(subscription.business)
            if not business_owner:
                continue

            # Expire the subscription
            subscription.status = SubscriptionStatusChoices.EXPIRED
            subscription.save(update_fields=["status", "updated_at"])
            stats["subscriptions_expired"] += 1

            plan_name = get_plan_name(subscription)

            # Send final expiration notification
            content_type = ContentType.objects.get_for_model(BusinessSubscriptionPlan)
            send_notifications(
                users=[business_owner],
                title="Subscription Expired",
                message=f"Your {plan_name} subscription has expired after the grace period. Please renew to continue using our services.",
                notification_type=NotificationTypes.BUSINESS_SUBSCRIPTION_EXPIRED,
                content_type=content_type,
                object_id=str(subscription.id),
            )

            # Send email notification
            send_expiration_email_notification(
                business_owner, subscription, 0, is_expired=True
            )

            stats["notifications_sent"] += 1
            logger.info(
                f"Expired subscription after grace period for {subscription.business.name}"
            )

        except Exception as e:
            stats["errors"] += 1
            logger.exception(
                f"Failed to expire subscription after grace period for {subscription.business.name}: {e}"
            )


def send_expiration_email_notification(
    user, subscription, days_until_expiry, is_expired=False
):
    """
    Send email notification for subscription expiration.

    Args:
        user: User instance
        subscription: BusinessSubscriptionPlan instance
        days_until_expiry: Number of days until expiry (0 means expires today)
        is_expired: Whether the subscription has already expired
    """
    try:
        plan_name = get_plan_name(subscription)

        if is_expired:
            subject = f"Your {plan_name} Subscription Has Expired"
            template_name = "templates/subscription-expired.html"
            context = {
                "user_name": user.fullname or user.email,
                "plan_name": plan_name,
                "expiry_date": subscription.expiry_date.strftime("%B %d, %Y"),
                "business_name": subscription.business.name or user.fullname,
            }
        else:
            # Handle special case: expires today (days_until_expiry=0)
            if days_until_expiry == 0:
                subject = f"Your {plan_name} Subscription Expires Today"
            else:
                subject = f"Your {plan_name} Subscription Expires Soon"
            template_name = "templates/subscription-expiring.html"
            context = {
                "user_name": user.fullname or user.email,
                "plan_name": plan_name,
                "expiry_date": subscription.expiry_date.strftime("%B %d, %Y"),
                "days_until_expiry": days_until_expiry,
                "business_name": subscription.business.name,
            }

        send_mail.delay(
            subject=subject,
            template_name=template_name,
            context=context,
            to_emails=[user.email],
            language_code="en",
        )

        logger.info(f"Sent expiration email to {user.email}")

    except Exception as e:
        logger.exception(f"Failed to send expiration email to {user.email}: {e}")


def send_grace_period_email_notification(user, subscription):
    """
    Send email notification for grace period start.

    Args:
        user: User instance
        subscription: BusinessSubscriptionPlan instance
    """
    try:
        plan_name = get_plan_name(subscription)

        subject = f"Your {plan_name} Subscription Grace Period Started"
        template_name = "templates/subscription-grace-period.html"
        context = {
            "user_name": user.fullname or user.email,
            "plan_name": plan_name,
            "expiry_date": subscription.expiry_date.strftime("%B %d, %Y"),
            "grace_period_days": subscription.grace_period_days or 3,
            "business_name": subscription.business.name,
        }

        send_mail.delay(
            subject=subject,
            template_name=template_name,
            context=context,
            to_emails=[user.email],
            language_code="en",
        )

        logger.info(f"Sent grace period email to {user.email}")

    except Exception as e:
        logger.exception(f"Failed to send grace period email to {user.email}: {e}")


def send_cancellation_email_notification(user, subscription):
    """
    Send email notification for subscription cancellation.

    Args:
        user: User instance
        subscription: BusinessSubscriptionPlan instance
    """
    try:
        plan_name = get_plan_name(subscription)

        subject = f"Your {plan_name} Subscription Has Been Cancelled"
        template_name = "templates/subscription-cancelled.html"
        context = {
            "user_name": user.fullname or user.email,
            "plan_name": plan_name,
            "cancelled_date": subscription.cancelled_date.strftime("%B %d, %Y")
            if subscription.cancelled_date
            else subscription.expiry_date.strftime("%B %d, %Y"),
            "business_name": subscription.business.name,
        }

        send_mail.delay(
            subject=subject,
            template_name=template_name,
            context=context,
            to_emails=[user.email],
            language_code="en",
        )

        logger.info(f"Sent cancellation email to {user.email}")

    except Exception as e:
        logger.exception(f"Failed to send cancellation email to {user.email}: {e}")
