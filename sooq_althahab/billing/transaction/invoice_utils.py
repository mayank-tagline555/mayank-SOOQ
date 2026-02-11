import logging
from decimal import Decimal

from django.conf import settings

from account.models import OrganizationCurrency
from sooq_althahab.billing.transaction.helpers import generate_deposit_receipt_context
from sooq_althahab.billing.transaction.helpers import (
    generate_withdrawal_receipt_context,
)
from sooq_althahab.billing.transaction.helpers import get_organization_logo_url
from sooq_althahab.tasks import send_mail

logger = logging.getLogger(__name__)


def get_business_display_name(transaction):
    """
    Returns business name if available,
    otherwise falls back to business owner name,
    otherwise returns 'N/A'
    """
    business = getattr(transaction, "from_business", None)
    # If a serialized dict was passed instead of model instance
    if not business and isinstance(transaction, dict):
        fb = transaction.get("from_business") or transaction.get("fromBusiness")
        if fb:
            name = fb.get("name")
            if name and name.strip():
                return name.strip()
            owner = fb.get("owner") or {}
            owner_name = (
                owner.get("name") or owner.get("username") or owner.get("email")
            )
            return owner_name or "N/A"

    if not business:
        return "N/A"

    name = getattr(business, "name", None)
    if name and name.strip():
        return name.strip()

    # Business name missing — try to find owner via UserAssignedBusiness relation
    try:
        owner_uab = (
            business.user_assigned_businesses.filter(is_owner=True)
            .select_related("user")
            .first()
        )
        if owner_uab and getattr(owner_uab, "user", None):
            user = owner_uab.user
            parts = [
                getattr(user, "first_name", ""),
                getattr(user, "middle_name", ""),
                getattr(user, "last_name", ""),
            ]
            owner_name = " ".join([p for p in parts if p]).strip()
            if owner_name:
                return owner_name
            return (
                getattr(user, "username", None) or getattr(user, "email", None) or "N/A"
            )
    except Exception:
        pass

    return "N/A"


def format_transfer_via(transfer_via):
    if transfer_via == "ORGANIZATION_ADMIN":
        return "Organization Admin"
    return str(transfer_via).replace("_", " ").title()


def format_status(status):
    if status in ["APPROVED", "SUCCESS"]:
        return "Completed"
    if status in ["REJECTED", "FAILED"]:
        return "Rejected"
    return str(status)


def get_currency_code(organization):
    default_currency = (
        OrganizationCurrency.objects.filter(
            organization=organization, is_default=True
        ).first()
        or OrganizationCurrency.objects.filter(organization=organization).first()
    )
    return default_currency.currency_code if default_currency else "BHD"


def send_topup_invoice_to_accounts(transaction, organization):
    """
    Send top-up details email with PDF attachment to accounts email
    """
    try:
        accounts_email = settings.ORGANIZATION_ACCOUNTS_EMAIL
        if not accounts_email:
            logger.warning(
                f"[Accounting] ORGANIZATION_ACCOUNTS_EMAIL not configured. Skipping top-up details email for transaction {transaction.id}."
            )
            return

        logger.info(
            f"[Accounting] Preparing to send top-up details email for transaction {transaction.id} to {accounts_email}"
        )

        from investor.serializers import TransactionResponseSerializer

        transaction_data = TransactionResponseSerializer(transaction).data

        pdf_context = generate_deposit_receipt_context(
            transaction, transaction_data, organization
        )
        pdf_context["organization_logo_url"] = get_organization_logo_url(organization)

        currency_code = get_currency_code(organization)
        pdf_context["billing"] = {"currency": currency_code}

        email_context = {
            "organization_name": organization.name,
            "transaction_number": transaction.receipt_number or str(transaction.id),
            "business_name": get_business_display_name(transaction),
            "transfer_via": format_transfer_via(transaction.transfer_via),
            "transaction_date": (
                transaction.created_at.date() if transaction.created_at else "N/A"
            ),
            "amount": Decimal(transaction.amount or 0),
            "platform_fee": Decimal(transaction.additional_fee or 0),
            "total_amount": Decimal(transaction.amount or 0)
            + Decimal(transaction.additional_fee or 0),
            "currency": currency_code,
            "status": format_status(transaction.status),
            "organization_logo_url": get_organization_logo_url(organization),
        }

        combined_context = {**pdf_context, **email_context}

        subject = (
            f"{organization.name} Top-Up Details - "
            f"Transaction {transaction.receipt_number or transaction.id}"
        )

        send_mail.delay(
            subject=subject,
            template_name="templates/top-up-invoice-email.html",
            context=combined_context,
            to_emails=[accounts_email],
            from_email=settings.ORGANIZATION_BILLING_EMAIL,
        )

        logger.info(
            f"[Accounting] Top-up invoice email sent successfully to {accounts_email} for transaction {transaction.id}"
        )

    except Exception as e:
        logger.error(
            f"[Accounting] Failed to send top-up invoice email for transaction {transaction.id}: {str(e)}",
            exc_info=True,
        )


def send_withdrawal_invoice_to_accounts(transaction, organization):
    """
    Send withdrawal details email to accounts email
    """
    try:
        accounts_email = settings.ORGANIZATION_ACCOUNTS_EMAIL
        if not accounts_email:
            logger.warning(
                f"[Accounting] ORGANIZATION_ACCOUNTS_EMAIL not configured. "
                f"Skipping withdrawal details email for transaction {transaction.id}."
            )
            return

        logger.info(
            f"[Accounting] Preparing to send withdrawal details email "
            f"for transaction {transaction.id} to {accounts_email}"
        )

        from investor.serializers import TransactionResponseSerializer

        transaction_data = TransactionResponseSerializer(transaction).data

        pdf_context = generate_withdrawal_receipt_context(
            transaction, transaction_data, organization
        )
        pdf_context["organization_logo_url"] = get_organization_logo_url(organization)

        currency_code = get_currency_code(organization)

        email_context = {
            "organization_name": organization.name,
            "transaction_number": transaction.receipt_number or str(transaction.id),
            "business_name": get_business_display_name(transaction),
            "transfer_via": format_transfer_via(transaction.transfer_via),
            "transaction_date": (
                transaction.created_at.date() if transaction.created_at else "N/A"
            ),
            "amount": Decimal(transaction.amount or 0),
            "platform_fee": Decimal(transaction.additional_fee or 0),
            "total_amount": Decimal(transaction.amount or 0)
            + Decimal(transaction.additional_fee or 0),
            "currency": currency_code,
            "status": format_status(transaction.status),
            "organization_logo_url": get_organization_logo_url(organization),
        }

        combined_context = {**pdf_context, **email_context}

        subject = (
            f"{organization.name} Withdrawal Details - "
            f"Transaction {transaction.receipt_number or transaction.id}"
        )

        send_mail.delay(
            subject=subject,
            template_name="templates/withdrawal-invoice-email.html",
            context=combined_context,
            to_emails=[accounts_email],
            from_email=settings.ORGANIZATION_BILLING_EMAIL,
        )
        logger.info(
            f"[Accounting] Withdrawal details email sent successfully to {accounts_email} for transaction {transaction.id}"
        )

    except Exception as e:
        logger.error(
            f"[Accounting] Failed to send withdrawal details email for transaction {transaction.id}: {str(e)}",
            exc_info=True,
        )
