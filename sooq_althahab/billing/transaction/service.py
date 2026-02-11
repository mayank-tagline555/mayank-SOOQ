from django.conf import settings

from account.utils import get_business_display_name
from investor.serializers import TransactionResponseSerializer
from sooq_althahab.billing.subscription.pdf_utils import render_subscription_invoice_pdf
from sooq_althahab.billing.transaction.helpers import generate_transfer_receipt_context
from sooq_althahab.tasks import send_mail


# TODO This method is not in use but we need to add this in the wallet deduction process
def send_transaction_email(transaction, from_wallet, organization, recipients):
    """This helper method for sending transer receipt for transaction."""

    serialized_transaction = TransactionResponseSerializer(transaction).data
    context = generate_transfer_receipt_context(
        transaction, serialized_transaction, organization
    )
    template_name = "invoice/transfer-receipt.html"
    filename = "transfer-receipt.pdf"
    pdf_io = render_subscription_invoice_pdf(template_name, context)
    attachment = [(filename, pdf_io.read(), "application/pdf")]

    email_context = {
        "business_name": get_business_display_name(from_wallet.business),
        "transaction_id": transaction.receipt_number,
        "date": transaction.created_at.date(),
        "amount": transaction.amount,
        "organization_logo_url": context["organization_logo_url"],
    }

    send_mail.delay(
        subject="Transaction Details",
        template_name="templates/transaction-details.html",
        context=email_context,
        to_emails=recipients,
        attachments=attachment,
        from_email=settings.ORGANIZATION_BILLING_EMAIL,
        bcc_emails=settings.ORGANIZATION_ACCOUNTS_EMAIL,
    )
