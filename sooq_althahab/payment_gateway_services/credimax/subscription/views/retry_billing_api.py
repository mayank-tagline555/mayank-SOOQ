"""
API view to retry billing details creation and send mail for a specific subscription and transaction.
"""

import logging
from decimal import Decimal

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from account.models import Transaction
from account.models import TransactionStatus
from sooq_althahab.billing.subscription.helpers import calculate_tax_and_total
from sooq_althahab.billing.subscription.services import (
    send_subscription_receipt_after_payment,
)
from sooq_althahab.enums.account import TransactionStatus as TransactionStatusEnum
from sooq_althahab.enums.sooq_althahab_admin import PaymentStatus
from sooq_althahab_admin.models import BillingDetails
from sooq_althahab_admin.models import BusinessSubscriptionPlan

logger = logging.getLogger(__name__)


class RetryBillingDetailsAndMailAPIView(APIView):
    """
    Retry billing details creation and send both receipt and invoice emails for a specific subscription and transaction.
    """

    permission_classes = [AllowAny]
    authentication_classes = []  # Explicitly disable authentication

    def post(self, request):
        """
        Retry billing details creation and send both invoice and receipt emails for a specific subscription and transaction.

        Email sending order:
        1. Invoice email sent first
        2. 2-second delay
        3. Receipt email sent second

        Expected payload:
        {
            "subscription_id": "bsp_5F220925f5233a",
            "transaction_id": "txn_5F220925a1747a"
        }
        Returns:
        {
            "success": true,
            "message": "Successfully created billing details and sent both invoice and receipt emails",
            "data": {
                "billing_details_id": "bd_123",
                "business_name": "Business Name",
                "subscription_name": "Subscription Plan Name",
                "total_amount": "120.00",
                "receipt_email_sent": true,
                "invoice_email_sent": true,
                "emails_sent": true,
                "was_existing": false
            }
        }
        """
        try:
            # Extract data from request
            subscription_id = request.data.get("subscription_id")
            transaction_id = request.data.get("transaction_id")

            # Validate required fields
            if not subscription_id:
                return Response(
                    {"success": False, "error": "subscription_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not transaction_id:
                return Response(
                    {"success": False, "error": "transaction_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get the business subscription plan
            try:
                business_subscription_plan = (
                    BusinessSubscriptionPlan.objects.select_related(
                        "business", "subscription_plan", "created_by"
                    ).get(id=subscription_id)
                )
            except BusinessSubscriptionPlan.DoesNotExist:
                return Response(
                    {
                        "success": False,
                        "error": f"Business subscription plan with ID '{subscription_id}' not found",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Get the transaction
            try:
                transaction_obj = Transaction.objects.select_related(
                    "from_business", "to_business", "business_subscription"
                ).get(id=transaction_id)
            except Transaction.DoesNotExist:
                return Response(
                    {
                        "success": False,
                        "error": f"Transaction with ID '{transaction_id}' not found",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Verify the transaction belongs to the subscription
            if transaction_obj.business_subscription != business_subscription_plan:
                return Response(
                    {
                        "success": False,
                        "error": f"Transaction {transaction_id} does not belong to subscription {subscription_id}",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Check if transaction is successful
            if transaction_obj.status != TransactionStatusEnum.SUCCESS:
                return Response(
                    {
                        "success": False,
                        "error": f"Transaction {transaction_id} is not successful (Status: {transaction_obj.status}). Cannot create billing details for non-successful transactions.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Check if billing details already exist
            existing_billing = BillingDetails.objects.filter(
                business=business_subscription_plan.business,
                period_start_date__lte=transaction_obj.created_at.date(),
                period_end_date__gte=transaction_obj.created_at.date(),
            ).first()

            # Execute the billing details creation and mail sending
            with transaction.atomic():
                # Create/update billing details
                billing_details = self._create_billing_details(
                    business_subscription_plan, transaction_obj, existing_billing
                )

                # Send notification emails (both receipt and invoice)
                email_results = self._send_notification_email(
                    business_subscription_plan, transaction_obj, billing_details
                )

            # Prepare response data
            response_data = {
                "billing_details_id": billing_details.id,
                "business_name": business_subscription_plan.business.name,
                "subscription_name": business_subscription_plan.subscription_name,
                "total_amount": str(billing_details.total_amount),
                "payment_status": billing_details.payment_status,
                "receipt_email_sent": email_results.get("receipt_sent", False),
                "invoice_email_sent": email_results.get("invoice_sent", False),
                "emails_sent": email_results.get("success", False),
                "was_existing": existing_billing is not None,
            }

            # Determine success message based on email results
            receipt_sent = email_results.get("receipt_sent", False)
            invoice_sent = email_results.get("invoice_sent", False)

            if receipt_sent and invoice_sent:
                message = "Successfully created billing details and sent both receipt and invoice emails"
            elif receipt_sent:
                message = "Successfully created billing details and sent receipt email (invoice email failed)"
            elif invoice_sent:
                message = "Successfully created billing details and sent invoice email (receipt email failed)"
            else:
                message = "Successfully created billing details but failed to send both emails"

            return Response(
                {
                    "success": True,
                    "message": message,
                    "data": response_data,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Error in retry_billing_details_and_mail API: {str(e)}")
            return Response(
                {"success": False, "error": f"Internal server error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _create_billing_details(
        self, business_subscription_plan, transaction_obj, existing_billing=None
    ):
        """Create or update billing details for the subscription and transaction."""
        business = business_subscription_plan.business

        # Calculate base amount from transaction
        # transaction_obj.amount is the TOTAL amount (base + VAT)
        # transaction_obj.vat is the VAT amount
        # So base_amount = transaction_obj.amount - transaction_obj.vat
        base_amount = transaction_obj.amount - (transaction_obj.vat or Decimal("0.00"))

        # Calculate tax and total amounts
        (
            commission_fee,
            vat_amount,
            tax_amount,
            total_amount,
        ) = calculate_tax_and_total(
            base_amount,
            transaction_obj.vat_rate or Decimal(0.0),
            transaction_obj.tax_rate or Decimal(0.0),
            business_subscription_plan.commission_rate or Decimal(0.0),
        )

        if existing_billing:
            # Update existing billing details
            existing_billing.base_amount = base_amount
            existing_billing.commission_fee = commission_fee or Decimal(0.0)
            existing_billing.vat_rate = transaction_obj.vat_rate or Decimal(0.0)
            existing_billing.vat_amount = vat_amount
            existing_billing.tax_rate = transaction_obj.tax_rate or Decimal(0.0)
            existing_billing.tax_amount = tax_amount
            existing_billing.total_amount = total_amount
            existing_billing.payment_status = PaymentStatus.COMPLETED
            existing_billing.notes = "Updated billing details via retry API"
            existing_billing.save()

            logger.info(f"Updated existing billing details (ID: {existing_billing.id})")
            return existing_billing
        else:
            # Create new billing details
            billing_details = BillingDetails.objects.create(
                business=business,
                period_start_date=business_subscription_plan.start_date,
                period_end_date=business_subscription_plan.next_billing_date,
                base_amount=base_amount,
                commission_fee=commission_fee or Decimal(0.0),
                vat_rate=transaction_obj.vat_rate or Decimal(0.0),
                vat_amount=vat_amount,
                tax_rate=transaction_obj.tax_rate or Decimal(0.0),
                tax_amount=tax_amount,
                total_amount=total_amount,
                payment_status=PaymentStatus.COMPLETED,
                notes="Created billing details via retry API",
            )

            logger.info(f"Created new billing details (ID: {billing_details.id})")
            return billing_details

    def _send_notification_email(
        self, business_subscription_plan, transaction_obj, billing_details
    ):
        """Send both subscription invoice and receipt emails to business owner with PDF attachments.

        Sends invoice email first, then waits 2 seconds before sending receipt email.
        This ensures proper sequencing for subscription billing emails.
        """
        try:
            business = business_subscription_plan.business
            organization = business.organization_id
            subscription_plan = business_subscription_plan.subscription_plan

            # Log email details for debugging
            logger.info(
                f"Attempting to send receipt and invoice emails for transaction {transaction_obj.id}"
            )
            logger.info(f"Business: {business.name}")
            logger.info(
                f"Organization: {organization.name if organization else 'No organization'}"
            )

            # Try to get business owner email as well
            try:
                owner_assignment = business.user_assigned_businesses.filter(
                    is_owner=True
                ).first()
                if owner_assignment:
                    logger.info(f"Business owner email: {owner_assignment.user.email}")
                else:
                    logger.info("No business owner found")
            except Exception as owner_error:
                logger.warning(f"Could not get business owner email: {owner_error}")

            # Track email sending results
            receipt_sent = False
            invoice_sent = False

            # Send subscription invoice first with PDF attachment
            try:
                from sooq_althahab.billing.subscription.services import (
                    send_subscription_invoice,
                )

                send_subscription_invoice(
                    billing_details=billing_details,
                    business=business,
                    subscription_plan=subscription_plan,
                    organization=organization,
                    business_subscription_plan=business_subscription_plan,  # Pass BusinessSubscriptionPlan for accurate pricing info
                )
                invoice_sent = True
                logger.info(
                    f"Invoice email sent successfully for transaction {transaction_obj.id}"
                )
            except Exception as invoice_error:
                logger.error(
                    f"Failed to send invoice email for transaction {transaction_obj.id}: {str(invoice_error)}"
                )

            # Add delay between invoice and receipt emails
            import time

            delay_seconds = 2  # 2 second delay between emails
            logger.info(
                f"Waiting {delay_seconds} seconds before sending receipt email..."
            )
            time.sleep(delay_seconds)

            # Send subscription receipt with PDF attachment after delay
            try:
                send_subscription_receipt_after_payment(
                    billing_details=billing_details,
                    business=business,
                    subscription_plan=subscription_plan,
                    organization=organization,
                    transaction=transaction_obj,
                    business_subscription_plan=business_subscription_plan,  # Pass BusinessSubscriptionPlan for accurate pricing info
                )
                receipt_sent = True
                logger.info(
                    f"Receipt email sent successfully for transaction {transaction_obj.id}"
                )
            except Exception as receipt_error:
                logger.error(
                    f"Failed to send receipt email for transaction {transaction_obj.id}: {str(receipt_error)}"
                )

            # Return success if at least one email was sent
            return {
                "receipt_sent": receipt_sent,
                "invoice_sent": invoice_sent,
                "success": receipt_sent or invoice_sent,
            }

        except Exception as e:
            logger.error(
                f"Failed to send emails for transaction {transaction_obj.id}: {str(e)}"
            )
            import traceback

            logger.error(f"Email error traceback: {traceback.format_exc()}")
            return {"receipt_sent": False, "invoice_sent": False, "success": False}
