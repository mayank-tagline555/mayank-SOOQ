# sooq_althahab/billing/subscription/services.py

from decimal import Decimal

from django.utils import formats
from django.utils.translation import gettext_lazy as _

from account.models import User
from sooq_althahab.billing.subscription.email_utils import (
    send_subscription_invoice_email,
)
from sooq_althahab.billing.subscription.email_utils import (
    send_subscription_invoice_only_email,
)
from sooq_althahab.billing.subscription.helpers import calculate_base_amount
from sooq_althahab.billing.subscription.helpers import calculate_tax_and_total
from sooq_althahab.billing.subscription.helpers import prepare_organization_details
from sooq_althahab.billing.subscription.helpers import (
    resolve_subscription_transaction_identifier,
)
from sooq_althahab.billing.subscription.pdf_utils import render_subscription_invoice_pdf
from sooq_althahab.billing.transaction.helpers import get_organization_logo_url
from sooq_althahab.billing.transaction.helpers import get_user_contact_details
from sooq_althahab.enums.sooq_althahab_admin import PaymentStatus
from sooq_althahab_admin.models import BillingDetails


def monthly_subscription_calculation(
    start_date, end_date, business, business_subscription=None
):
    """
    Calculate and create billing details for a subscription period.

    BUSINESS LOGIC:
    - If pending_subscription_plan exists → Uses pending plan fee (admin wants immediate change)
    - If no pending plan → Uses current subscription_fee
    - Calculates VAT and total amounts
    - Creates BillingDetails record

    Args:
        start_date: Billing period start
        end_date: Billing period end
        business: BusinessAccount object
        business_subscription: BusinessSubscriptionPlan object

    Returns:
        tuple: (billing_details, purchase_requests, invoice_numbers_display)
    """
    organization = business.organization_id
    organization_tax_rate = organization.tax_rate
    organization_vat_rate = organization.vat_rate

    # Calculate base amount (handles pending plan logic internally)
    base_amount, invoice_numbers_display, purchase_requests = calculate_base_amount(
        business_subscription, start_date, end_date
    )

    commission_rate = business_subscription.commission_rate or Decimal("0.00")
    commission_fee = base_amount * commission_rate
    service_fee = Decimal("0.00")  # Reserved for future use

    # Calculate VAT, tax, and total
    (
        commission_fee,
        vat_amount,
        tax_amount,
        total_amount,
    ) = calculate_tax_and_total(
        base_amount,
        organization_vat_rate,
        organization_tax_rate,
        commission_fee,
    )

    # Create billing record
    billing_details = BillingDetails.objects.create(
        business=business,
        period_start_date=start_date,
        period_end_date=end_date,
        base_amount=base_amount,
        commission_fee=commission_fee,
        service_fee=service_fee,
        vat_rate=organization_vat_rate,
        vat_amount=vat_amount,
        tax_rate=organization_tax_rate,
        tax_amount=tax_amount,
        total_amount=total_amount,
        payment_status=PaymentStatus.PENDING,
        notes=_("Auto-generated subscription tax invoice"),
    )

    return billing_details, purchase_requests, invoice_numbers_display


def send_subscription_invoice(
    billing_details,
    business,
    subscription_plan,
    organization,
    invoice_numbers_display=None,
    business_subscription_plan=None,
):
    """
    Send subscription invoice email with PDF attachment BEFORE payment is processed.

    IMPORTANT: This shows what the user will be charged.
    - If pending_subscription_plan exists → Shows pending plan name and fee
    - Otherwise → Shows current plan name and fee

    Args:
        billing_details: BillingDetails with amounts (base, VAT, total)
        business: BusinessAccount being billed
        subscription_plan: Master SubscriptionPlan (reference only)
        organization: Organization for branding/VAT rates
        invoice_numbers_display: Purchase request invoice numbers (for POSTPAID)
        business_subscription_plan: BusinessSubscriptionPlan (contains current/pending plan info)
    """
    owner_user = User.objects.filter(
        user_assigned_businesses__business=business,
        user_assigned_businesses__is_owner=True,
    ).first()

    if not owner_user:
        return

    business_user_details = get_user_contact_details(owner_user.id)
    business_user_details = {
        "address": business_user_details["address"] or "N/A",
        "country": business_user_details["country"] or "N/A",
        "phone": str(owner_user.phone_number) if owner_user.phone_number else None,
    }

    organization_details = prepare_organization_details(organization)
    organization_logo_url = get_organization_logo_url(organization)

    # Ensure we have proper names for the PDF
    business_name = business.name or ""
    user_fullname = owner_user.fullname or ""
    display_name = business_name or user_fullname or owner_user.email or "Customer"

    # Use subscription details for accurate billing info
    # CRITICAL: If pending_subscription_plan exists, show PENDING plan name (what's being charged)
    # Otherwise show current plan name
    if business_subscription_plan:
        if business_subscription_plan.pending_subscription_plan:
            # Show pending plan name and type (this is what's being billed)
            plan_name = business_subscription_plan.pending_subscription_plan.name
            plan_business_type = (
                business_subscription_plan.pending_subscription_plan.business_type
            )
        else:
            # Show current plan name and type
            plan_name = business_subscription_plan.subscription_name or (
                subscription_plan.name if subscription_plan else "Subscription Plan"
            )
            plan_business_type = (
                subscription_plan.business_type if subscription_plan else "Business"
            )
    else:
        plan_name = subscription_plan.name if subscription_plan else "Subscription Plan"
        plan_business_type = (
            subscription_plan.business_type if subscription_plan else "Business"
        )

    pdf_context = {
        "billing": billing_details,
        "business": business,
        "business_user": owner_user,
        "business_user_details": business_user_details,
        "subscription_plan": subscription_plan,
        "business_subscription_plan": business_subscription_plan,
        "plan_name": plan_name,
        "plan_business_type": plan_business_type,
        "organization_details": organization_details,
        "payment_method": "Pending",
        "transaction_id": "Pending",
        "organization_logo_url": organization_logo_url,
        "purchase_request_invoice_number": invoice_numbers_display or "",
        "transaction_date": billing_details.created_at,
        "user_fullname": user_fullname,
        "display_name": display_name,
    }

    template_name = "invoice/subscription-invoice.html"
    pdf_io = render_subscription_invoice_pdf(template_name, pdf_context)

    recipient_list = list(
        User.objects.filter(
            user_assigned_businesses__business=business,
            user_assigned_businesses__is_owner=True,
            email__isnull=False,
        )
        .exclude(email__exact="")
        .values_list("email", flat=True)
    )

    if recipient_list:
        # Ensure we have a proper name for the email greeting
        business_name = business.name or ""
        user_fullname = owner_user.fullname or ""
        display_name = business_name or user_fullname or owner_user.email or "Customer"

        # Format dates for email display (M. d, Y format: Dec. 22, 2025)
        from django.utils import formats

        plan_start_date_str = (
            formats.date_format(billing_details.period_start_date, "M. d, Y")
            if billing_details.period_start_date
            else "N/A"
        )
        plan_end_date_str = (
            formats.date_format(billing_details.period_end_date, "M. d, Y")
            if billing_details.period_end_date
            else "N/A"
        )

        email_context = {
            "organization_name": organization.name,
            "business_name": business_name,
            "user_fullname": user_fullname,
            "display_name": display_name,
            "plan_name": plan_name,  # Use the correctly determined plan name
            "plan_start_date": plan_start_date_str,
            "plan_end_date": plan_end_date_str,
            "subscription_amount": billing_details.total_amount,
            "invoice_number": billing_details.invoice_number or "N/A",
            "organization_logo_url": organization_logo_url,
        }
        send_subscription_invoice_only_email(
            recipient_list, email_context, pdf_io, organization_name=organization.name
        )


def send_subscription_receipt_after_payment(
    billing_details,
    business,
    subscription_plan,
    organization,
    transaction,
    business_subscription_plan=None,
):
    """
    Send subscription receipt email with PDF attachment AFTER successful payment.

    NOTE: Pending plan changes (if any) have already been applied by this point.

    Args:
        billing_details: BillingDetails with final amounts
        business: BusinessAccount that made payment
        subscription_plan: Master SubscriptionPlan (reference only)
        organization: Organization for branding
        transaction: Transaction with payment confirmation
        business_subscription_plan: BusinessSubscriptionPlan (for plan name)
    """
    owner_user = User.objects.filter(
        user_assigned_businesses__business=business,
        user_assigned_businesses__is_owner=True,
    ).first()

    if not owner_user:
        return

    organization_details = prepare_organization_details(organization)
    organization_logo_url = get_organization_logo_url(organization)
    try:
        card_token = transaction.from_business.business_saved_card_tokens.filter(
            is_used_for_subscription=True
        ).first()
        payment_card_number = card_token.number if card_token else ""
    except AttributeError:
        payment_card_number = ""

    # Ensure we have proper names for the PDF
    business_name = business.name or ""
    user_fullname = owner_user.fullname or ""
    display_name = business_name or user_fullname or owner_user.email or "Customer"

    # Use subscription details for accurate billing info
    # CRITICAL: If pending_subscription_plan exists, show PENDING plan name (what was charged)
    # Otherwise show current plan name
    if business_subscription_plan:
        if business_subscription_plan.pending_subscription_plan:
            # Show pending plan name and type (this was what was billed)
            plan_name = business_subscription_plan.pending_subscription_plan.name
            plan_business_type = (
                business_subscription_plan.pending_subscription_plan.business_type
            )
        else:
            # Show current plan name and type
            plan_name = business_subscription_plan.subscription_name or (
                subscription_plan.name if subscription_plan else "Subscription Plan"
            )
            plan_business_type = (
                subscription_plan.business_type if subscription_plan else "Business"
            )
    else:
        plan_name = subscription_plan.name if subscription_plan else "Subscription Plan"
        plan_business_type = (
            subscription_plan.business_type if subscription_plan else "Business"
        )

    pdf_context = {
        "billing": billing_details,
        "business": business,
        "business_user": owner_user,
        "subscription_plan": subscription_plan,
        "business_subscription_plan": business_subscription_plan,
        "plan_name": plan_name,
        "plan_business_type": plan_business_type,
        "organization_details": organization_details,
        "payment_method": transaction.transfer_via if transaction else "Unknown",
        "transaction_id": resolve_subscription_transaction_identifier(transaction),
        "organization_logo_url": organization_logo_url,
        "purchase_request_invoice_number": "",
        "transaction_date": transaction.created_at,
        "payment_card_number": payment_card_number,
        "user_fullname": user_fullname,
        "display_name": display_name,
        "invoice_number": billing_details.invoice_number,
    }

    template_name = "invoice/subscription-receipt.html"
    pdf_io = render_subscription_invoice_pdf(template_name, pdf_context)

    recipient_list = list(
        User.objects.filter(
            user_assigned_businesses__business=business,
            user_assigned_businesses__is_owner=True,
            email__isnull=False,
        )
        .exclude(email__exact="")
        .values_list("email", flat=True)
    )

    if recipient_list:
        # Ensure we have a proper name for the email greeting
        business_name = business.name or ""
        user_fullname = owner_user.fullname or ""
        display_name = business_name or user_fullname or owner_user.email or "Customer"

        # Format dates for email display (M. d, Y format: Dec. 22, 2025)
        plan_start_date_str = (
            formats.date_format(billing_details.period_start_date, "M. d, Y")
            if billing_details.period_start_date
            else "N/A"
        )
        plan_end_date_str = (
            formats.date_format(billing_details.period_end_date, "M. d, Y")
            if billing_details.period_end_date
            else "N/A"
        )

        email_context = {
            "organization_name": organization.name,
            "business_name": business_name,
            "user_fullname": user_fullname,
            "display_name": display_name,
            "plan_name": plan_name,  # Use the correctly determined plan name
            "plan_start_date": plan_start_date_str,
            "plan_end_date": plan_end_date_str,
            "subscription_amount": billing_details.total_amount,
            "organization_logo_url": organization_logo_url,
        }
        send_subscription_invoice_email(
            recipient_list, email_context, pdf_io, organization_name=organization.name
        )
