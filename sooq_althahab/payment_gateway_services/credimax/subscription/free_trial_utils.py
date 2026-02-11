"""
Free Trial Subscription Utilities
================================

This module provides utilities for handling free trial subscription limitations
for different user types in the Sooq Al Thahab platform.
"""

from decimal import ROUND_HALF_UP
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum

from account.models import BusinessAccount
from jeweler.message import MESSAGES as JEWELER_MESSAGES
from jeweler.models import JewelryDesign
from jeweler.models import MusharakahContractRequest
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.sooq_althahab_admin import SubscriptionPaymentTypeChoices


class FreeTrialLimitationError(ValidationError):
    """Custom exception for free trial limitation violations."""

    pass


def is_free_trial_subscription(business: BusinessAccount) -> bool:
    """
    Check if a business has an active free trial subscription.

    Args:
        business: The business account to check

    Returns:
        bool: True if the business has an active free trial subscription
    """
    from sooq_althahab.billing.subscription.helpers import get_active_subscription

    active_subscription = get_active_subscription(business)
    if not active_subscription:
        return False

    return (
        active_subscription.subscription_plan.payment_type
        == SubscriptionPaymentTypeChoices.FREE_TRIAL
    )


def get_designer_subscription_limitations(business: BusinessAccount) -> dict:
    """
    Get the free trial limitations for a business.

    Args:
        business: The business account to get limitations for

    Returns:
        dict: Dictionary containing limitation values for the business
    """
    from sooq_althahab.billing.subscription.helpers import get_active_subscription

    # if not is_free_trial_subscription(business):
    #     return {}

    active_subscription = get_active_subscription(business)

    if not active_subscription:
        return {}

    subscription_plan = active_subscription.subscription_plan
    limitations = {}

    # Only apply limitations for JEWELER role
    if subscription_plan.role == UserRoleBusinessChoices.JEWELER:
        limitations.update(
            {
                "musharakah_request_max_weight": subscription_plan.musharakah_request_max_weight,
                "metal_purchase_max_weight": subscription_plan.metal_purchase_max_weight,
                "max_design_count": subscription_plan.max_design_count,
            }
        )

    return limitations


def check_jeweler_musharakah_weight_limit(
    business: BusinessAccount, requested_weight: Decimal
) -> None:
    """Check if a jeweler's total musharakah weight exceeds the free trial weight limit."""
    # if not is_free_trial_subscription(business):
    #     return

    if not isinstance(requested_weight, Decimal):
        requested_weight = Decimal(str(requested_weight))

    limitations = get_designer_subscription_limitations(business)
    max_weight = limitations.get("musharakah_request_max_weight")

    if max_weight is not None:
        if not isinstance(max_weight, Decimal):
            max_weight = Decimal(str(max_weight))

        # Get total weight of all existing active musharakah contracts
        existing_total_weight = MusharakahContractRequest.objects.filter(
            jeweler=business,
            deleted_at__isnull=True,
            status__in=["PENDING", "APPROVED"],
        ).aggregate(total_weight=Sum("target"))["total_weight"] or Decimal("0.00")

        # Calculate total weight including the new request
        total_weight_with_new_request = existing_total_weight + requested_weight

        if total_weight_with_new_request > max_weight:
            # Format weights to 2 decimal places for display
            max_weight_formatted = max_weight.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            existing_weight_formatted = existing_total_weight.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            requested_weight_formatted = requested_weight.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            total_weight_formatted = total_weight_with_new_request.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            raise FreeTrialLimitationError(
                JEWELER_MESSAGES["free_trial_musharakah_total_weight_limit"].format(
                    max_weight=max_weight_formatted,
                    existing_weight=existing_weight_formatted,
                    requested_weight=requested_weight_formatted,
                    total_weight=total_weight_formatted,
                )
            )


def check_jeweler_metal_purchase_weight_limit(
    business: BusinessAccount, purchase_weight: Decimal
) -> None:
    """Check if a jeweler's metal purchase exceeds the free trial weight limit."""
    # if not is_free_trial_subscription(business):
    #     return

    if not isinstance(purchase_weight, Decimal):
        purchase_weight = Decimal(str(purchase_weight))

    limitations = get_designer_subscription_limitations(business)
    max_weight = limitations.get("metal_purchase_max_weight")

    if max_weight is not None:
        if not isinstance(max_weight, Decimal):
            max_weight = Decimal(str(max_weight))
        if purchase_weight > max_weight:
            # Format weights to 2 decimal places for display
            max_weight_formatted = max_weight.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            purchase_weight_formatted = purchase_weight.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            raise FreeTrialLimitationError(
                JEWELER_MESSAGES["free_trial_metal_purchase_weight_limit"].format(
                    max_weight=max_weight_formatted,
                    purchase_weight=purchase_weight_formatted,
                )
            )


def check_jeweler_design_count_limit(business: BusinessAccount) -> None:
    """Check if a jeweler's design count exceeds the free trial limit."""
    # if not is_free_trial_subscription(business):
    #     return

    limitations = get_designer_subscription_limitations(business)
    max_designs = limitations.get("max_design_count")

    if max_designs is not None:
        current_design_count = JewelryDesign.objects.filter(
            business=business, deleted_at__isnull=True
        ).count()

        if current_design_count >= max_designs:
            raise FreeTrialLimitationError(
                JEWELER_MESSAGES["free_trial_jeweler_design_limit"].format(
                    max_designs=max_designs, current_design_count=current_design_count
                )
            )


def get_jeweler_current_usage(business: BusinessAccount) -> dict:
    """
    Get the current usage statistics for a jeweler on free trial.

    Args:
        business: The business account to get usage for

    Returns:
        dict: Dictionary containing current usage statistics
    """
    # if not is_free_trial_subscription(business):
    #     return {}

    limitations = get_designer_subscription_limitations(business)
    if not limitations:
        return {}

    usage = {}

    # Current design count
    if limitations.get("max_design_count"):
        usage["current_design_count"] = JewelryDesign.objects.filter(
            business=business, deleted_at__isnull=True
        ).count()
        usage["max_design_count"] = limitations["max_design_count"]

    # Current musharakah request weight (total from all active requests)
    if limitations.get("musharakah_request_max_weight"):
        total_musharakah_weight = MusharakahContractRequest.objects.filter(
            jeweler=business,
            deleted_at__isnull=True,
            status__in=["PENDING", "APPROVED"],
        ).aggregate(total_weight=Sum("target"))["total_weight"] or Decimal("0.00")

        usage["current_musharakah_weight"] = total_musharakah_weight
        usage["max_musharakah_weight"] = limitations["musharakah_request_max_weight"]

    # Note: Metal purchase tracking would need to be implemented based on the specific
    # purchase flow in the application

    return usage


def validate_business_action_limits(
    business: BusinessAccount, action: str, **kwargs
) -> None:
    """
    Validate free trial limitations for a specific action.

    Args:
        business: The business account performing the action
        action: The action being performed ('musharakah_request', 'metal_purchase', 'design_creation')
        **kwargs: Additional parameters specific to the action

    Raises:
        FreeTrialLimitationError: If the action violates free trial limitations
    """
    # if not is_free_trial_subscription(business):
    #     return

    if action == "musharakah_request":
        requested_weight = Decimal(str(kwargs.get("weight")))

        # Get subscription plan limits
        limitations = get_designer_subscription_limitations(business)
        max_weight_per_musharakah = limitations.get("musharakah_request_max_weight")

        # Check single request weight limit from subscription plan
        if max_weight_per_musharakah is not None:
            if not isinstance(max_weight_per_musharakah, Decimal):
                max_weight_per_musharakah = Decimal(str(max_weight_per_musharakah))

            if requested_weight > max_weight_per_musharakah:
                # Format weights to 2 decimal places for display
                max_weight_formatted = max_weight_per_musharakah.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                requested_weight_formatted = requested_weight.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

                raise FreeTrialLimitationError(
                    JEWELER_MESSAGES["musharakah_single_request_weight_limit"].format(
                        max_weight=max_weight_formatted,
                        requested_weight=requested_weight_formatted,
                    )
                )

        # Check total musharakah weight limit
        check_jeweler_musharakah_weight_limit(business, requested_weight)

    elif action == "metal_purchase":
        purchase_weight = Decimal(str(kwargs.get("weight")))
        if purchase_weight:
            check_jeweler_metal_purchase_weight_limit(business, purchase_weight)

    elif action == "design_creation":
        check_jeweler_design_count_limit(business)

    else:
        raise ValueError(f"Unknown action: {action}")
