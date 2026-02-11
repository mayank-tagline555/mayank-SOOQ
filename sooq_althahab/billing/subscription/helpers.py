from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db.models import Sum

from investor.message import MESSAGES as INVESTOR_MESSAGES
from investor.models import PurchaseRequest
from sooq_althahab.enums.account import SubscriptionFeatureChoices
from sooq_althahab.enums.account import SubscriptionStatusChoices
from sooq_althahab.enums.account import TransferVia
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.payment_gateway_services.credimax.subscription.free_trial_utils import (
    get_jeweler_current_usage,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.free_trial_utils import (
    is_free_trial_subscription,
)
from sooq_althahab_admin.models import BusinessSubscriptionPlan


def get_active_subscription(business):
    business_subscription_plan = (
        BusinessSubscriptionPlan.objects.filter(
            business=business,
            status__in=[
                SubscriptionStatusChoices.ACTIVE,
                SubscriptionStatusChoices.TRIALING,
            ],
        )
        .select_related("subscription_plan")
        .order_by("-start_date")
    )

    return business_subscription_plan.first()


def resolve_subscription_transaction_identifier(transaction):
    """
    Return the transaction identifier that should appear on subscription
    invoices/receipts. For Credimax payments we surface the same identifier used
    during the gateway interaction; for other payment methods we stick with the
    generated receipt number.
    """

    if not transaction:
        return ""

    if transaction.transfer_via == TransferVia.CREDIMAX:
        subscription = getattr(transaction, "business_subscription", None)
        credimax_reference = getattr(subscription, "credimax_3ds_transaction_id", None)
        if credimax_reference:
            return credimax_reference
        if getattr(transaction, "reference_number", None):
            return str(transaction.reference_number)
        return str(transaction.id)

    return transaction.receipt_number


def get_subscription_usage_info(business):
    """
    Get comprehensive subscription usage information including free trial limitations.

    Args:
        business: The business account to get usage info for

    Returns:
        dict: Dictionary containing subscription and usage information
    """
    active_subscription = get_active_subscription(business)

    if not active_subscription:
        return {
            "has_active_subscription": False,
            "subscription_info": None,
            "usage_info": None,
        }

    subscription_info = {
        "id": active_subscription.id,
        "name": active_subscription.subscription_plan.name,
        "role": active_subscription.subscription_plan.role,
        "payment_type": active_subscription.subscription_plan.payment_type,
        "status": active_subscription.status,
        "start_date": active_subscription.start_date,
        "expiry_date": active_subscription.expiry_date,
        "is_free_trial": active_subscription.subscription_plan.payment_type
        == "FREE_TRIAL",
    }

    usage_info = None

    usage_info = get_jeweler_current_usage(business)
    # # Get free trial usage if applicable
    # if is_free_trial_subscription(business):
    #     usage_info = get_jeweler_current_usage(business)

    return {
        "has_active_subscription": True,
        "subscription_info": subscription_info,
        "usage_info": usage_info,
    }


def calculate_base_amount(subscription, start_date, end_date):
    """
    Calculate the base billing amount for a subscription.

    BUSINESS LOGIC:
    1. If pending_subscription_plan exists → Use PENDING plan fee (admin wants immediate change)
    2. If no pending plan → Use current subscription_fee
    3. For POSTPAID with pro_rata → Calculate from purchase requests

    SPECIAL CASE: POSTPAID → PREPAID Transition
    - If current subscription is POSTPAID and pending plan is PREPAID:
      - Charge POSTPAID amount for the period that just ended (using current subscription)
      - Charge PREPAID amount for the new plan (using pending subscription)
      - Both amounts are combined in a single transaction

    Args:
        subscription: BusinessSubscriptionPlan object
        start_date: Billing period start date
        end_date: Billing period end date

    Returns:
        tuple: (base_amount: Decimal, invoice_numbers: str, purchase_requests: QuerySet)
    """
    import logging

    logger = logging.getLogger(__name__)

    # Case 1: Pro-rata billing (POSTPAID - charge based on usage/purchase requests)
    if subscription.pro_rata_rate and subscription.payment_type == "POSTPAID":
        purchase_requests = calculate_billing_amount(
            start_date, end_date, subscription.business
        )

        total_pro_rata_fee = purchase_requests.aggregate(total=Sum("pro_rata_fee"))[
            "total"
        ] or Decimal("0.00")

        invoice_numbers = ", ".join(
            purchase_requests.order_by("invoice_number").values_list(
                "invoice_number", flat=True
            )
        )

        return total_pro_rata_fee, invoice_numbers, purchase_requests

    # Case 2: Fixed subscription fee (PREPAID - fixed monthly/yearly amount)
    # CRITICAL: Check for pending plan changes first
    if subscription.subscription_fee or subscription.pending_subscription_plan:
        if subscription.pending_subscription_plan:
            # Check if this is a POSTPAID → PREPAID transition
            # If current subscription is POSTPAID and pending is PREPAID, we need to charge both
            is_postpaid_to_prepaid = (
                subscription.payment_type == "POSTPAID"
                and subscription.pending_subscription_plan.payment_type == "PREPAID"
            )

            if is_postpaid_to_prepaid:
                # Calculate POSTPAID amount from current subscription (for period that just ended)
                # Use subscription_fee from BusinessSubscriptionPlan (already has the correct fee)
                postpaid_fee = subscription.subscription_fee or Decimal("0.00")

                # Apply yearly/monthly division if needed for current subscription
                if (
                    subscription.payment_interval == "YEARLY"
                    and subscription.billing_frequency == "MONTHLY"
                ):
                    postpaid_fee = postpaid_fee / Decimal("12")

                # Calculate PREPAID amount from pending subscription (for new plan)
                # Use discounted_fee if available, otherwise use subscription_fee
                pending_plan = subscription.pending_subscription_plan
                if pending_plan and pending_plan.discounted_fee:
                    prepaid_fee = pending_plan.discounted_fee or Decimal("0.00")
                else:
                    prepaid_fee = pending_plan.subscription_fee or Decimal("0.00")

                # Apply yearly/monthly division if needed for pending subscription
                # Use pending plan's payment_interval and billing_frequency
                pending_payment_interval = pending_plan.payment_interval
                pending_billing_frequency = pending_plan.billing_frequency
                if (
                    pending_payment_interval == "YEARLY"
                    and pending_billing_frequency == "MONTHLY"
                ):
                    prepaid_fee = prepaid_fee / Decimal("12")

                # Combine both amounts
                total_fee = postpaid_fee + prepaid_fee

                logger.info(
                    f"[BILLING] POSTPAID→PREPAID transition for {subscription.business.name}: "
                    f"POSTPAID={postpaid_fee}, PREPAID={prepaid_fee}, TOTAL={total_fee}"
                )

                return total_fee, "", PurchaseRequest.objects.none()
            else:
                # Regular pending plan change - use PENDING plan fee only
                # Use discounted_fee if available, otherwise use subscription_fee
                pending_plan = subscription.pending_subscription_plan
                if pending_plan and pending_plan.discounted_fee:
                    pending_fee = pending_plan.discounted_fee or Decimal("0.00")
                else:
                    pending_fee = pending_plan.subscription_fee or Decimal("0.00")

                # Use pending plan's payment_interval and billing_frequency for division
                pending_payment_interval = (
                    subscription.pending_subscription_plan.payment_interval
                )
                pending_billing_frequency = (
                    subscription.pending_subscription_plan.billing_frequency
                )

                # If payment_interval is YEARLY and billing_frequency is MONTHLY,
                # divide the yearly fee by 12 to get monthly amount
                if (
                    pending_payment_interval == "YEARLY"
                    and pending_billing_frequency == "MONTHLY"
                ):
                    pending_fee = pending_fee / Decimal("12")
                    logger.info(
                        f"[BILLING] Using pending plan fee (yearly/monthly): "
                        f"{subscription.business.name}: {pending_fee} (yearly fee divided by 12)"
                    )
                else:
                    logger.info(
                        f"[BILLING] Using pending plan fee for {subscription.business.name}: {pending_fee}"
                    )
                return pending_fee, "", PurchaseRequest.objects.none()
        else:
            # No pending plan - use current subscription_fee from BusinessSubscriptionPlan
            # (already has the correct fee stored)
            current_fee = subscription.subscription_fee

            # If payment_interval is YEARLY and billing_frequency is MONTHLY,
            # divide the yearly fee by 12 to get monthly amount
            # EXCEPTION: For POSTPAID plans on the last billing cycle, charge full yearly amount
            is_last_cycle = getattr(subscription, "_is_last_billing_cycle", False)
            is_postpaid_last_cycle = (
                is_last_cycle
                and subscription.payment_type == "POSTPAID"
                and subscription.payment_interval == "YEARLY"
                and subscription.billing_frequency == "MONTHLY"
            )

            if (
                subscription.payment_interval == "YEARLY"
                and subscription.billing_frequency == "MONTHLY"
                and not is_postpaid_last_cycle
            ):
                # Not the last cycle - divide by 12 for monthly billing
                current_fee = current_fee / Decimal("12")
                logger.info(
                    f"[BILLING] Using current fee (yearly/monthly): "
                    f"{subscription.business.name}: {current_fee} (yearly fee divided by 12)"
                )
            elif is_postpaid_last_cycle:
                # Last cycle - use full yearly amount
                logger.info(
                    f"[BILLING] Using full yearly fee for last cycle: "
                    f"{subscription.business.name}: {current_fee} (full yearly amount, not divided)"
                )
            else:
                logger.info(
                    f"[BILLING] Using current fee for {subscription.business.name}: {current_fee}"
                )
            return current_fee, "", PurchaseRequest.objects.none()

    # Case 3: Commission-based subscription (rare case)
    if subscription.commission_rate:
        # TODO: Implement commission-based billing logic
        # return subscription.commission_rate, "", PurchaseRequest.objects.none()
        return Decimal("0.00"), "", PurchaseRequest.objects.none()

    # Default: No billing method configured
    return Decimal("0.00"), "", PurchaseRequest.objects.none()


def calculate_tax_and_total(
    base_amount,
    vat_rate,
    tax_rate,
    commission_rate,
):
    commission_fee = base_amount * commission_rate
    amount_for_tax = base_amount + commission_fee
    vat_amount = amount_for_tax * vat_rate
    tax_amount = amount_for_tax * tax_rate
    total_amount = amount_for_tax + vat_amount + tax_amount
    return commission_fee, vat_amount, tax_amount, total_amount


def calculate_billing_amount(start_date, end_date, business):
    return PurchaseRequest.objects.filter(
        business=business,
        approved_at__date__range=(start_date, end_date),
        status__in=[PurchaseRequestStatus.APPROVED, PurchaseRequestStatus.COMPLETED],
    )


def get_file_url(relative_path):
    file_path = Path(settings.BASE_DIR) / relative_path
    return f"file://{file_path}" if file_path.exists() else ""


def prepare_organization_details(organization):
    return {
        "name": organization.name,
        "arabic_name": organization.arabic_name or organization.name,
        "address": organization.address,
        "country": organization.country.title() if organization.country else "",
        "commercial_registration_number": organization.commercial_registration_number,
        "vat_account_number": organization.vat_account_number,
        "watermark_url": get_file_url("static/images/invoice_bg.png"),
        "musharakah_bg": get_file_url("static/images/musharakah_bg.png"),
    }


def has_subscription_feature(business, feature):
    """
    Check if a business has access to a specific subscription feature.

    Args:
        business: BusinessAccount instance
        feature: One of SubscriptionFeatureChoices values (e.g., 'PURCHASE_ASSETS')

    Returns:
        tuple: (has_access: bool, subscription_plan: BusinessSubscriptionPlan or None)
    """
    active_subscription = get_active_subscription(business)

    if not active_subscription:
        return False, None

    # CRITICAL: Check features from BusinessSubscriptionPlan, not SubscriptionPlan
    # This ensures users keep their original features even if admin updates the plan
    #
    # Feature access logic:
    # - Always use features stored in BusinessSubscriptionPlan
    # - When user purchases plan: features are copied from SubscriptionPlan to BusinessSubscriptionPlan
    # - When admin updates plan: features are updated immediately in BusinessSubscriptionPlan
    #   (similar to commission_rate and pro_rata_rate behavior)
    # - This ensures features are independent of SubscriptionPlan updates
    features = active_subscription.features or []

    # Check if feature is in the enabled features list
    # Empty list [] = no features enabled
    # List with items = only those features enabled
    has_access = feature in features

    return has_access, active_subscription


def check_subscription_feature_access(business, feature):
    """
    Check if a business has access to a specific subscription feature.
    Raises ValidationError if access is denied.

    Args:
        business: BusinessAccount instance
        feature: One of SubscriptionFeatureChoices values

    Returns:
        BusinessSubscriptionPlan: The active subscription if access is granted

    Raises:
        ValidationError: If the business doesn't have access to the feature
    """
    from rest_framework.validators import ValidationError

    has_access, subscription = has_subscription_feature(business, feature)

    if not has_access:
        feature_name = dict(SubscriptionFeatureChoices.choices).get(
            feature, feature.replace("_", " ").title()
        )
        error_message = INVESTOR_MESSAGES["subscription_feature_access_denied"].format(
            feature_name=feature_name
        )
        raise ValidationError(error_message)

    return subscription
