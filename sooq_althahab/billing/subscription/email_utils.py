import logging
from decimal import Decimal

from django.conf import settings

from sooq_althahab.billing.subscription.helpers import prepare_organization_details
from sooq_althahab.billing.subscription.helpers import (
    resolve_subscription_transaction_identifier,
)
from sooq_althahab.billing.subscription.pdf_utils import render_subscription_invoice_pdf
from sooq_althahab.billing.transaction.helpers import get_organization_logo_url

logger = logging.getLogger(__name__)


def send_subscription_invoice_email(recipient_list, context, pdf_io, organization_name):
    from sooq_althahab.tasks import send_mail

    subject = f"{organization_name} Subscription Payment Receipt"
    pdf_io.seek(0)
    attachment = [("subscription_receipt.pdf", pdf_io.read(), "application/pdf")]
    send_mail.delay(
        subject=subject,
        template_name="templates/subscription-receipt-email.html",
        context=context,
        to_emails=recipient_list,
        attachments=attachment,
        from_email=settings.ORGANIZATION_BILLING_EMAIL,
        bcc_emails=settings.ORGANIZATION_ACCOUNTS_EMAIL,
    )


def send_subscription_invoice_only_email(
    recipient_list, context, pdf_io, organization_name
):
    """Send invoice email before payment completion"""
    from sooq_althahab.tasks import send_mail

    subject = f"{organization_name} Subscription Invoice"
    pdf_io.seek(0)
    attachment = [("subscription_invoice.pdf", pdf_io.read(), "application/pdf")]
    send_mail.delay(
        subject=subject,
        template_name="templates/subscription-invoice.html",
        context=context,
        to_emails=recipient_list,
        attachments=attachment,
        from_email=settings.ORGANIZATION_BILLING_EMAIL,
        bcc_emails=settings.ORGANIZATION_ACCOUNTS_EMAIL,
    )


def failed_transaction_send_mail(recipient_list, context, organization_name):
    from sooq_althahab.tasks import send_mail

    subject = f"{organization_name} Subscription Payment Failed"

    send_mail.delay(
        subject=subject,
        template_name="templates/subscription-failed.html",
        context=context,
        to_emails=recipient_list,
        from_email=settings.ORGANIZATION_BILLING_EMAIL,
        bcc_emails=settings.ORGANIZATION_ACCOUNTS_EMAIL,
    )


def send_postpaid_subscription_activation_email(
    recipient_list, context, organization_name
):
    """Send POSTPAID subscription activation email with upcoming payment details"""
    from sooq_althahab.tasks import send_mail

    subject = f"{organization_name} POSTPAID Subscription Activated"

    send_mail.delay(
        subject=subject,
        template_name="templates/subscription-postpaid-activation.html",
        context=context,
        to_emails=recipient_list,
        from_email=settings.ORGANIZATION_BILLING_EMAIL,
        bcc_emails=settings.ORGANIZATION_ACCOUNTS_EMAIL,
    )


def send_mail_to_business_owner(
    user,
    organization,
    business,
    business_subscription_plan,
    transaction,
    billing_details=None,
    failure_reason=None,
):
    organization_details = prepare_organization_details(organization)

    # Ensure we have a proper name for the email greeting
    business_name = business.name or ""
    user_fullname = user.fullname or ""
    display_name = business_name or user_fullname or user.email or "Customer"

    # Use failure_reason if provided, otherwise fall back to transaction remark
    effective_failure_reason = failure_reason or transaction.remark

    # Calculate subscription_amount correctly
    # If billing_details exists, use its total_amount (most accurate)
    # Otherwise, use transaction.amount (which already includes VAT)
    if billing_details:
        subscription_amount = billing_details.total_amount
    else:
        # transaction.amount is already the total (base + VAT), don't add VAT again
        subscription_amount = Decimal(transaction.amount)

    email_context = {
        "organization_name": organization.name,
        "business_name": business_name,
        "user_fullname": user_fullname,
        "display_name": display_name,
        "plan_name": business_subscription_plan.subscription_plan.name,
        "plan_start_date": business_subscription_plan.start_date,
        "plan_end_date": "N/A",
        "subscription_plan_duration": business_subscription_plan.subscription_plan.duration
        or "N/A",
        "subscription_amount": subscription_amount,
        "organization_logo_url": get_organization_logo_url(organization),
        "status": transaction.status,
        "failure_reason": effective_failure_reason,
        "is_debit_card_failure": (
            effective_failure_reason and "DEBIT" in effective_failure_reason.upper()
            if effective_failure_reason
            else False
        ),
    }

    if billing_details:
        email_context["plan_end_date"] = (
            business_subscription_plan.next_billing_date or "N/A"
        )
        # Get business owner user safely
        owner_assignment = business.user_assigned_businesses.filter(
            is_owner=True
        ).first()
        business_user_email = owner_assignment.user.email if owner_assignment else ""
        try:
            card_token = transaction.from_business.business_saved_card_tokens.filter(
                is_used_for_subscription=True
            ).first()
            payment_card_number = card_token.number if card_token else ""
        except AttributeError:
            payment_card_number = ""

        # Prepare PDF context
        pdf_context = {
            "user_fullname": user_fullname,
            "display_name": display_name,
            "billing": billing_details,
            "business": business,
            "business_user": {"email": business_user_email},
            "subscription_plan": business_subscription_plan.subscription_plan,
            "organization_details": organization_details,
            "payment_method": transaction.transfer_via,
            "transaction_id": resolve_subscription_transaction_identifier(transaction),
            "transaction_date": transaction.created_at,
            "payment_card_number": payment_card_number,
            "invoice_number": billing_details.invoice_number,
            "organization_logo_url": get_organization_logo_url(organization),
        }
        template_name = "invoice/subscription-receipt.html"
        pdf_io = render_subscription_invoice_pdf(template_name, pdf_context)
        send_subscription_invoice_email(
            [user.email],
            email_context,
            pdf_io,
            organization_name=organization.name,
        )
    else:
        failed_transaction_send_mail(
            [user.email],
            email_context,
            organization_name=organization.name,
        )
