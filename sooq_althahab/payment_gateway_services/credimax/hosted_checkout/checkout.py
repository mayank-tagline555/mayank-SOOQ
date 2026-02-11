import logging
import time
from decimal import Decimal

import requests
from django.conf import settings
from django.db.models import Prefetch
from rest_framework import status
from rest_framework.response import Response
from rest_framework.serializers import ValidationError
from rest_framework.views import APIView

from account.models import Transaction
from account.models import UserAssignedBusiness
from account.models import Wallet
from account.models import WebhookCall
from investor.serializers import CreateCredimaxPaymentSessionSerializer
from sooq_althahab.enums.account import SubscriptionStatusChoices
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.account import TransferVia
from sooq_althahab.enums.account import WebhookCallStatus
from sooq_althahab.enums.account import WebhookEventType
from sooq_althahab.payment_gateway_services.payment_logger import get_credimax_logger

logger = logging.getLogger(__name__)


class CreatePaymentSessionAPIView(APIView):
    def post(self, request):
        """Create a payment session via Credimax for adding money to the wallet."""

        current_business_id = request.auth.get("current_business", None)

        payment_logger = None

        serializer = CreateCredimaxPaymentSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        original_amount = serializer.get_base_amount()
        fee = serializer.get_fee()
        total_amount = serializer.get_total_amount()

        logger.info(
            "[Credimax-Wlt] Received request to create payment session with amount: %s for business ID: %s",
            original_amount,
            current_business_id,
        )
        logger.info(
            "[Credimax-Wlt] Original amount: %s, Fee: %s, Total charged: %s",
            original_amount,
            fee,
            total_amount,
        )

        # Fetch the business associated with the current business ID
        try:
            business = (
                UserAssignedBusiness.objects.select_related("business")  # forward FK
                .prefetch_related(
                    Prefetch(
                        "business__wallets",
                        queryset=Wallet.objects.all(),
                        to_attr="prefetched_wallets",
                    )
                )
                .get(id=current_business_id)
            ).business
            wallet = business.wallets.first()

            payment_logger = get_credimax_logger(business_id=str(business.id))

            payment_logger.log_transaction_start(
                transaction_type="WALLET_TOPUP_SESSION_CREATION",
                business_id=str(business.id),
                amount=float(total_amount),
                additional_data={
                    "user_id": str(request.user.id) if request.user else None,
                    "request_data": request.data,
                },
            )

            payment_logger.log_business_logic(
                action="VALIDATE_PAYMENT_SESSION_DATA",
                data={
                    "original_amount": float(original_amount),
                    "fee": float(fee),
                    "total_amount": float(total_amount),
                    "business_id": str(business.id),
                },
            )

            payment_logger.log_business_logic(
                action="FETCH_BUSINESS_DETAILS",
                data={
                    "business_id": str(business.id),
                    "user_id": str(request.user.id) if request.user else None,
                },
            )

            payment_logger.log_business_logic(
                action="BUSINESS_FETCHED_SUCCESSFULLY",
                data={
                    "business_id": str(business.id),
                    "business_name": business.name,
                    "wallet_exists": wallet is not None,
                    "wallet_balance": float(wallet.balance) if wallet else None,
                },
            )

            logger.info(
                "[Credimax-Wlt] Found business: %s with ID: %s",
                business.name,
                business.id,
            )
        except UserAssignedBusiness.DoesNotExist:
            payment_logger = payment_logger or get_credimax_logger()
            payment_logger.log_error(
                error_type="BUSINESS_NOT_FOUND",
                error_message=f"Business with ID {current_business_id} not found",
                context={"business_id": str(current_business_id)},
            )
            logger.error(
                "[Credimax-Wlt] Business with ID %s not found.", current_business_id
            )
            return Response(
                {"message": "Wallet not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            payment_logger = payment_logger or get_credimax_logger()
            payment_logger.log_error(
                error_type="BUSINESS_FETCH_ERROR",
                error_message=str(e),
                context={"business_id": str(current_business_id)},
            )
            logger.exception("[Credimax-Wlt] Error fetching business: %s", str(e))
            return Response(
                {"message": "An error occurred while fetching business."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        trans_notes = f"Top-up to Business Wallet - BHD {original_amount} + BHD {fee} fee - Total: BHD {total_amount}"

        logger.info("[Credimax-Wlt] Transaction log details: %s", trans_notes)

        # Create a transaction
        try:
            payment_logger.log_business_logic(
                action="CREATE_WALLET_TRANSACTION",
                data={
                    "business_id": str(business.id),
                    "original_amount": float(original_amount),
                    "fee": float(fee),
                    "total_amount": float(total_amount),
                    "wallet_balance_before": float(wallet.balance) if wallet else None,
                    "transaction_type": TransactionType.DEPOSIT,
                    "transfer_via": TransferVia.CREDIMAX,
                },
            )

            transaction = Transaction.objects.create(
                from_business=business,
                to_business=business,
                amount=original_amount,
                additional_fee=fee,
                transaction_type=TransactionType.DEPOSIT,
                transfer_via=TransferVia.CREDIMAX,
                status=TransactionStatus.PENDING,
                log_details=trans_notes,
                created_by=request.user,
                previous_balance=wallet.balance,
                current_balance=wallet.balance,
            )

            # Update payment logger with transaction ID
            payment_logger = get_credimax_logger(
                str(transaction.id), business_id=str(business.id)
            )

            payment_logger.log_business_logic(
                action="TRANSACTION_CREATED_SUCCESSFULLY",
                data={
                    "transaction_id": str(transaction.id),
                    "status": transaction.status,
                    "amount": float(transaction.amount),
                    "additional_fee": float(transaction.additional_fee),
                },
            )

            logger.info(
                "[Credimax-Wlt] Created transaction with ID: %s", transaction.id
            )
        except Exception as e:
            payment_logger.log_error(
                error_type="TRANSACTION_CREATION_ERROR",
                error_message=str(e),
                context={
                    "business_id": str(business.id),
                    "amount": float(original_amount),
                    "fee": float(fee),
                },
            )
            logger.exception("[Credimax-Wlt] Error creating transaction: %s", str(e))
            return Response(
                {"message": "An error occurred while creating transaction."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        print(
            f"[Credimax-Wlt] Created transaction {transaction.id} for business {business.id}, name: {business.name}"
        )

        # Construct the payload for the Credimax API
        payload = {
            "apiOperation": "INITIATE_CHECKOUT",
            "interaction": {
                "operation": "PURCHASE",
                "timeout": settings.CREDIMAX_CHECKOUT_TIMEOUT_PERIOD_IN_SECONDS,
                "timeoutUrl": settings.CREDIMAX_CHECKOUT_TIMEOUT_RETURN_URL,
                "returnUrl": settings.CREDIMAX_CHECKOUT_RETURN_URL,
                "merchant": {"name": "Sooq Al Thahab"},
            },
            "order": {
                "id": transaction.id,
                "amount": str(total_amount),
                "currency": "BHD",
                "description": trans_notes,
            },
        }

        payment_logger.log_api_request(
            endpoint="session", method="POST", payload=payload
        )

        logger.info("[Credimax-Wlt] Prepared payload for Credimax API: %s", payload)

        # Send request to Credimax API
        try:
            AUTH = (settings.CREDIMAX_API_USERNAME, settings.CREDIMAX_API_PASSWORD)
            credimax_session_url = f"{settings.CREDIMAX_BASE_URL}session"

            payment_logger.log_business_logic(
                action="PREPARE_CREDIMAX_API_CALL",
                data={
                    "api_url": credimax_session_url,
                    "has_auth": bool(AUTH[0] and AUTH[1]),
                    "transaction_id": str(transaction.id),
                },
            )

            logger.info(
                "[Credimax-Wlt] Fetched AUTH %s settings.CREDIMAX_BASE_URL, %s",
                AUTH,
                credimax_session_url,
            )

            api_start_time = time.time()
            response = requests.post(credimax_session_url, json=payload, auth=AUTH)
            api_response_time = (time.time() - api_start_time) * 1000

            payment_logger.log_api_response(
                status_code=response.status_code,
                response_data=response.json() if response.content else {},
                response_time_ms=api_response_time,
            )

            logger.info(
                "[Credimax-Wlt] Credimax API response status: %s", response.status_code
            )
        except requests.RequestException as e:
            payment_logger.log_error(
                error_type="CREDIMAX_API_ERROR",
                error_message=str(e),
                context={
                    "api_url": credimax_session_url,
                    "transaction_id": str(transaction.id),
                    "payload": payload,
                },
            )
            logger.exception("Error while calling Credimax API: %s", str(e))
            return Response(
                {"message": "An error occurred while communicating with Credimax."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if response.status_code == 201:
            payment_session = response.json()
            session_id = payment_session.get("session", {}).get("id")

            payment_logger.log_business_logic(
                action="CREDIMAX_SESSION_CREATED",
                data={
                    "session_id": session_id,
                    "transaction_id": str(transaction.id),
                    "response_status": response.status_code,
                },
            )

            logger.info(
                "[Credimax-Wlt] Received session ID from Credimax: %s", session_id
            )

            # Construct hosted payment page URL
            hosted_url = f"{settings.CREDIMAX_HOSTED_CHECKOUT_PAGE_URL}{session_id}?checkoutVersion={settings.CREDIMAX_HOSTED_CHECKOUT_VERSION}"

            payment_logger.log_business_logic(
                action="GENERATE_HOSTED_PAYMENT_URL",
                data={
                    "hosted_url": hosted_url,
                    "session_id": session_id,
                    "checkout_version": settings.CREDIMAX_HOSTED_CHECKOUT_VERSION,
                },
            )

            logger.info(
                "[Credimax-Wlt] Generated hosted payment page URL: %s", hosted_url
            )

            result = {
                "payment_checkout_hosted_page_url": hosted_url,
                "session_id": session_id,
                "order_id": transaction.id,
                "original_amount": str(original_amount),
                "fee": str(fee),
                "total_amount": str(total_amount),
                "currency": "BHD",
                "description": trans_notes,
            }

            payment_logger.log_transaction_completion(
                final_status=transaction.status,
                summary={
                    "type": "wallet_topup_session_creation",
                    "transaction_id": str(transaction.id),
                    "session_id": session_id,
                    "business_id": str(business.id),
                    "amount": float(total_amount),
                    "hosted_url": hosted_url,
                },
            )

            return Response(result, status=status.HTTP_201_CREATED)
        else:
            payment_logger.log_error(
                error_type="CREDIMAX_SESSION_CREATION_FAILED",
                error_message=f"Failed to create payment session, received status: {response.status_code}",
                context={
                    "response_status": response.status_code,
                    "response_body": response.json() if response.content else {},
                    "transaction_id": str(transaction.id),
                },
            )

            logger.error(
                "[Credimax-Wlt] Failed to create payment session, received error: %s",
                response.json(),
            )
            return Response(response.json(), status=response.status_code)


class CredimaxWebhookAPIView(APIView):
    def post(self, request, *args, **kwargs):
        """Handle webhook notifications from Credimax and update the transaction status and wallet balance."""

        webhook_log = ""  # String to accumulate webhook processing logs
        transaction_obj = None
        webhook_processed = False
        payment_logger = None

        try:
            # Extract necessary fields from the webhook data
            data = request.data

            order = data.get("order", {})
            transaction = data.get("transaction", {})
            response = data.get("response", {})
            result = data.get("result", "")

            order_id = order.get("id")
            amount = order.get("amount")
            status_code = order.get("status")
            transaction_type = transaction.get("type")
            transaction_id = transaction.get("transactionId") or transaction.get("id")
            gateway_code = response.get("gatewayCode", "")
            gateway_message = response.get("acquirerMessage", "")

            # Log only essential webhook response details
            webhook_log += (
                f"Order ID: {order_id}, Amount: {amount}, Status: {status_code}, "
                f"Result: {result}, Gateway Code: {gateway_code}"
            )
            if gateway_message:
                webhook_log += f", Gateway Message: {gateway_message}"
            webhook_log += "\n"

            # Check if this is an authentication-only webhook (card addition flow)
            # Card addition is handled via the dedicated 3DS callback endpoint: /api/v1/card-addition/3ds-callback/
            # These webhooks are informational only and should not be processed as payment webhooks
            # Card addition webhooks have order_id starting with "card_add_" and transaction type "AUTHENTICATION"
            is_card_addition_webhook = (
                transaction_type == "AUTHENTICATION"
                and order_id
                and order_id.startswith("card_add_")
            )

            # Check if this is an agreement update webhook (card update for agreement)
            # Agreement update webhooks are informational only and should not be processed as payment webhooks
            # Agreement update webhooks have transaction type "VERIFICATION" and order_id starting with "UPDATE_AGREEMENT_"
            is_agreement_update_webhook = (
                transaction_type == "VERIFICATION"
                and order_id
                and order_id.startswith("UPDATE_AGREEMENT_")
            )

            if is_card_addition_webhook:
                if payment_logger:
                    payment_logger.log_webhook_processing(
                        "CARD_ADDITION_WEBHOOK_IGNORED",
                        {
                            "order_id": order_id,
                            "transaction_type": transaction_type,
                            "status": status_code,
                            "note": "Card addition webhooks are handled via 3DS callback endpoint",
                        },
                    )
                return Response(
                    {
                        "message": "Card addition webhook received (handled via 3DS callback endpoint)",
                        "log": webhook_log,
                    },
                    status=status.HTTP_200_OK,
                )

            if is_agreement_update_webhook:
                if payment_logger:
                    payment_logger.log_webhook_processing(
                        "AGREEMENT_UPDATE_WEBHOOK_IGNORED",
                        {
                            "order_id": order_id,
                            "transaction_type": transaction_type,
                            "status": status_code,
                            "agreement_id": data.get("agreement", {}).get("id"),
                            "note": "Agreement update webhooks are informational only for card updates during agreement modification",
                        },
                    )
                return Response(
                    {
                        "message": "Agreement update webhook received (informational only)"
                    },
                    status=status.HTTP_200_OK,
                )

            # Validate the required fields for regular payment webhooks
            # Note: For payment webhooks, amount must be present and > 0 (0.0 is not valid for payments)
            # Only card addition webhooks can have 0.0 amount, and those are handled above
            if not order_id or not amount or not status_code:
                if payment_logger:
                    payment_logger.log_error(
                        error_type="INVALID_WEBHOOK_DATA",
                        error_message="Missing required fields in webhook data",
                        context={
                            "order_id": order_id,
                            "amount": amount,
                            "status_code": status_code,
                            "webhook_data": data,
                        },
                    )
                return Response(
                    {"message": "Invalid webhook data"},
                    status=status.HTTP_200_OK,  # Always return 200 for webhooks
                )

            if payment_logger:
                payment_logger.log_webhook_processing(
                    "VALIDATE_WEBHOOK_DATA",
                    {
                        "order_id": order_id,
                        "amount": amount,
                        "status_code": status_code,
                        "result": result,
                    },
                )

            # Try to find the transaction by the order_id first (which should be our Django transaction ID)
            # If that fails, try to find it by the Credimax transaction ID
            transaction_obj = None
            try:
                transaction_obj = (
                    Transaction.objects.select_related(
                        "from_business", "business_subscription"
                    )
                    .prefetch_related(
                        Prefetch(
                            "from_business__wallets",
                            queryset=Wallet.objects.all(),
                            to_attr="prefetched_wallets",
                        )
                    )
                    .get(id=order_id)
                )

                payment_logger = get_credimax_logger(
                    str(order_id), business_id=str(transaction_obj.from_business.id)
                )
                payment_logger.log_webhook_received(data, "Credimax")
                payment_logger.log_webhook_processing(
                    "FETCH_TRANSACTION", {"order_id": order_id}
                )
                if payment_logger:
                    payment_logger.log_webhook_processing(
                        "TRANSACTION_FOUND",
                        {
                            "transaction_id": str(transaction_obj.id),
                            "status": transaction_obj.status,
                            "amount": float(transaction_obj.amount),
                            "business_id": str(transaction_obj.from_business.id),
                            "has_subscription": transaction_obj.business_subscription
                            is not None,
                        },
                    )

            except Transaction.DoesNotExist:
                if payment_logger:
                    payment_logger.log_error(
                        error_type="TRANSACTION_NOT_FOUND",
                        error_message=f"Transaction with ID {order_id} not found",
                        context={"order_id": order_id},
                    )
                webhook_log += f"Transaction not found by order_id {order_id}\n\n"
                return Response(
                    {"message": "Transaction not found", "log": webhook_log},
                    status=status.HTTP_200_OK,  # Always return 200 for webhooks
                )
            # Fetch business wallet
            business_wallet = transaction_obj.from_business.wallets.first()
            if not business_wallet:
                if payment_logger:
                    payment_logger.log_error(
                        error_type="WALLET_NOT_FOUND",
                        error_message=f"Wallet not found for business ID {transaction_obj.from_business.id}",
                        context={"business_id": str(transaction_obj.from_business.id)},
                    )
                webhook_log += f"Wallet not found for business ID {transaction_obj.from_business.id}.\n\n"
                return Response(
                    {"message": "Wallet not found", "log": webhook_log},
                    status=status.HTTP_200_OK,  # Always return 200 for webhooks
                )
            transaction_obj.previous_balance = business_wallet.balance

            if payment_logger:
                payment_logger.log_webhook_processing(
                    "WALLET_FETCHED",
                    {
                        "wallet_balance": float(business_wallet.balance),
                        "previous_balance": float(transaction_obj.previous_balance),
                    },
                )

            # Update transaction status based on Credimax response
            old_status = transaction_obj.status
            business_subscription = transaction_obj.business_subscription

            if result == "SUCCESS" and status_code == "CAPTURED":
                # For wallet top-up (no subscription), only set SUCCESS on PAYMENT webhook.
                # Credimax sends AUTHENTICATION first (3DS) then PAYMENT (capture). If we set
                # SUCCESS on AUTHENTICATION, we never credit the wallet (we only credit on
                # PAYMENT), and when PAYMENT arrives we skip credit because old_status is
                # already SUCCESS. So for wallet top-up, only set SUCCESS when we receive
                # PAYMENT; leave PENDING on AUTHENTICATION. For subscriptions we set SUCCESS
                # on either webhook (subscription status is updated, no wallet credit).
                set_success = transaction_obj.status != TransactionStatus.SUCCESS and (
                    business_subscription
                    or transaction_type == WebhookEventType.PAYMENT
                )
                if set_success:
                    transaction_obj.status = TransactionStatus.SUCCESS

                # Update subscription status if this is a subscription payment
                if business_subscription:
                    old_subscription_status = business_subscription.status
                    # Only update to ACTIVE if subscription is in PENDING or FAILED state
                    # Don't override if already ACTIVE (to avoid issues with recurring payments)
                    if business_subscription.status in [
                        SubscriptionStatusChoices.PENDING,
                        SubscriptionStatusChoices.FAILED,
                    ]:
                        business_subscription.status = SubscriptionStatusChoices.ACTIVE
                        business_subscription.save(update_fields=["status"])
                        if payment_logger:
                            payment_logger.log_webhook_processing(
                                "SUBSCRIPTION_STATUS_UPDATED",
                                {
                                    "subscription_id": str(business_subscription.id),
                                    "old_status": old_subscription_status,
                                    "new_status": SubscriptionStatusChoices.ACTIVE,
                                },
                            )

                if payment_logger:
                    payment_logger.log_transaction_update(
                        old_status=old_status,
                        new_status=transaction_obj.status,
                        reason="Payment successful - captured",
                        additional_data={
                            "result": result,
                            "status_code": status_code,
                            "transaction_type": transaction_type,
                            "subscription_updated": business_subscription is not None,
                            "status_updated": set_success,
                        },
                    )

                if transaction_type == WebhookEventType.PAYMENT:
                    # Only update wallet balance if we are the ones who just marked this
                    # transaction as SUCCESS. If it was already SUCCESS (e.g. updated by
                    # the periodic check_single_credimax_transaction task or by a
                    # previous webhook), skip to avoid double-crediting the wallet.
                    if (
                        not business_subscription
                        and old_status != TransactionStatus.SUCCESS
                    ):
                        self.update_wallet_balance(
                            transaction_obj, webhook_log, payment_logger
                        )
                        # Send invoice email to accounts for successful top-up transactions
                        if (
                            transaction_obj.transaction_type == TransactionType.DEPOSIT
                            and transaction_obj.status == TransactionStatus.SUCCESS
                        ):
                            try:
                                from sooq_althahab.billing.transaction.invoice_utils import (
                                    send_topup_invoice_to_accounts,
                                )

                                organization = (
                                    transaction_obj.from_business.organization_id
                                )
                                if organization:
                                    send_topup_invoice_to_accounts(
                                        transaction_obj, organization
                                    )
                            except Exception as invoice_error:
                                logger.error(
                                    f"Failed to send top-up invoice email for transaction {transaction_obj.id}: {str(invoice_error)}"
                                )
            elif result == "FAILURE":
                # Only update transaction to FAILED if it's not already SUCCESS
                # If webhook shows failure but transaction was already marked as SUCCESS,
                # we should investigate but not override (could be a webhook timing issue)
                if transaction_obj.status != TransactionStatus.SUCCESS:
                    transaction_obj.status = TransactionStatus.FAILED

                # Update subscription status if this is a subscription payment
                if business_subscription:
                    old_subscription_status = business_subscription.status
                    # Only update to FAILED if subscription is in PENDING state
                    # Don't override if already FAILED or ACTIVE (to avoid race conditions)
                    if (
                        business_subscription.status
                        == SubscriptionStatusChoices.PENDING
                    ):
                        business_subscription.status = SubscriptionStatusChoices.FAILED
                        business_subscription.save(update_fields=["status"])
                        if payment_logger:
                            payment_logger.log_webhook_processing(
                                "SUBSCRIPTION_STATUS_UPDATED",
                                {
                                    "subscription_id": str(business_subscription.id),
                                    "old_status": old_subscription_status,
                                    "new_status": SubscriptionStatusChoices.FAILED,
                                },
                            )
                    elif (
                        business_subscription.status == SubscriptionStatusChoices.ACTIVE
                    ):
                        # Log warning if webhook shows failure but subscription is already active
                        # This is a valid scenario (duplicate/delayed webhook) that we handle correctly
                        # by not changing the subscription status. Log as warning, not error.
                        if payment_logger:
                            is_duplicate_webhook = (
                                transaction_obj.status == TransactionStatus.SUCCESS
                            )
                            warning_message = (
                                "Webhook shows FAILURE but subscription is already ACTIVE. "
                                "This is likely a duplicate or delayed webhook from a previous payment attempt. "
                                "Subscription status correctly preserved."
                            )
                            if is_duplicate_webhook:
                                warning_message += " Transaction was already SUCCESS, confirming duplicate webhook."
                            payment_logger.log_warning(
                                warning_message=warning_message,
                                context={
                                    "subscription_id": str(business_subscription.id),
                                    "transaction_id": str(transaction_obj.id),
                                    "transaction_status": transaction_obj.status,
                                    "webhook_result": result,
                                    "webhook_status": status_code,
                                    "is_duplicate_webhook": is_duplicate_webhook,
                                },
                            )

                gateway_recommendation = response.get("gatewayRecommendation", "")

                failure_message = (
                    "Payment was not completed.\n\n"
                    f"Reason: {gateway_message}.\n"
                    f"Recommendation: "
                    f"{gateway_recommendation.replace('_', ' ').title() if gateway_recommendation else 'Please try again with a different payment method.'}"
                )

                if not transaction_obj.remark:
                    transaction_obj.remark = failure_message
                else:
                    transaction_obj.remark = (
                        f"{transaction_obj.remark}\n\n{failure_message}"
                    )

                if payment_logger:
                    payment_logger.log_transaction_update(
                        old_status=old_status,
                        new_status=TransactionStatus.FAILED,
                        reason="Payment failed",
                        additional_data={
                            "result": result,
                            "status_code": status_code,
                            "gateway_code": gateway_code,
                            "gateway_message": gateway_message,
                            "gateway_recommendation": gateway_recommendation,
                        },
                    )
            else:
                transaction_obj.status = TransactionStatus.PENDING

                if payment_logger:
                    payment_logger.log_transaction_update(
                        old_status=old_status,
                        new_status=TransactionStatus.PENDING,
                        reason="Payment status pending",
                        additional_data={"result": result, "status_code": status_code},
                    )

            # Update transaction log_details with essential webhook information
            existing_notes = transaction_obj.log_details or ""
            # Only append webhook details if they contain meaningful information
            if webhook_log.strip():
                transaction_obj.log_details = (
                    f"{existing_notes}\n\n--- Webhook Response ---\n{webhook_log}"
                )

            transaction_obj.save()
            webhook_processed = True

            # Handle the call_type to ensure only valid types are saved
            if transaction_type not in WebhookEventType.values:
                transaction_type = WebhookEventType.OTHERS

            # Log the webhook call in the WebhookCall model (separate from core logic)
            try:
                WebhookCall.objects.create(
                    transaction=transaction_obj,
                    transfer_via=TransferVia.CREDIMAX,
                    event_type=transaction_type,
                    status=WebhookCallStatus.SUCCESS,
                    request_body=request.POST.dict(),
                    response_body=data,
                    response_status_code=status.HTTP_200_OK,
                )

                if payment_logger:
                    payment_logger.log_webhook_processing(
                        "WEBHOOK_CALL_LOGGED",
                        {
                            "webhook_event_type": transaction_type,
                            "webhook_status": WebhookCallStatus.SUCCESS,
                        },
                    )

            except Exception as webhook_log_error:
                if payment_logger:
                    payment_logger.log_error(
                        error_type="WEBHOOK_CALL_LOGGING_ERROR",
                        error_message=str(webhook_log_error),
                        context={"transaction_id": str(transaction_obj.id)},
                    )
                # Don't fail the entire webhook if logging fails

            if payment_logger:
                payment_logger.log_transaction_completion(
                    final_status=transaction_obj.status,
                    summary={
                        "type": "credimax_webhook_processing",
                        "transaction_id": str(transaction_obj.id),
                        "business_id": str(transaction_obj.from_business.id),
                        "amount": float(transaction_obj.amount),
                        "webhook_result": result,
                        "webhook_status_code": status_code,
                        "webhook_processed": webhook_processed,
                    },
                )

            # Always return 200 for webhook endpoints
            return Response(
                {"message": "Webhook processed successfully"},
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            if payment_logger:
                payment_logger.log_error(
                    error_type="WEBHOOK_PROCESSING_ERROR",
                    error_message=str(e),
                    context={
                        "order_id": order_id if "order_id" in locals() else None,
                        "transaction_id": str(transaction_obj.id)
                        if transaction_obj
                        else None,
                    },
                )

            # Try to update transaction log_details even if processing failed
            if transaction_obj:
                try:
                    existing_notes = transaction_obj.log_details or ""
                    transaction_obj.log_details = (
                        f"{existing_notes}\n\n--- Webhook Error ---\nError: {str(e)}"
                    )
                    transaction_obj.save()
                except Exception:
                    pass  # Don't fail if we can't update notes

            # Always return 200 for webhook endpoints
            return Response(
                {"message": "An error occurred while processing the webhook"},
                status=status.HTTP_200_OK,  # Always return 200 for webhooks
            )

    def update_wallet_balance(self, transaction_obj, webhook_log, payment_logger=None):
        """Update the wallet balance based on the transaction type."""
        try:
            business_id = transaction_obj.from_business.id
            business_wallet = Wallet.objects.get(business=business_id)

            if payment_logger:
                payment_logger.log_webhook_processing(
                    "FETCH_BUSINESS_WALLET",
                    {
                        "business_id": str(business_id),
                        "wallet_balance_before": float(business_wallet.balance),
                        "transaction_type": transaction_obj.transaction_type,
                    },
                )

            # Adjust wallet balance based on the transaction type
            if transaction_obj.transaction_type == TransactionType.DEPOSIT:
                old_balance = business_wallet.balance
                business_wallet.balance += Decimal(transaction_obj.amount or 0)

                if payment_logger:
                    payment_logger.log_webhook_processing(
                        "UPDATE_WALLET_BALANCE",
                        {
                            "transaction_type": "DEPOSIT",
                            "old_balance": float(old_balance),
                            "deposit_amount": float(transaction_obj.amount or 0),
                            "new_balance": float(business_wallet.balance),
                        },
                    )

            transaction_obj.current_balance = business_wallet.balance
            transaction_obj.save()
            business_wallet.save()

            if payment_logger:
                payment_logger.log_webhook_processing(
                    "WALLET_BALANCE_SAVED",
                    {
                        "final_balance": float(business_wallet.balance),
                        "current_balance_recorded": float(
                            transaction_obj.current_balance
                        ),
                    },
                )

        except Wallet.DoesNotExist:
            if payment_logger:
                payment_logger.log_error(
                    error_type="WALLET_NOT_FOUND_IN_UPDATE",
                    error_message=f"Wallet for business ID {business_id} not found",
                    context={"business_id": str(business_id)},
                )
            raise ValidationError("Wallet not found")
        except ValidationError as ve:
            if payment_logger:
                payment_logger.log_error(
                    error_type="WALLET_UPDATE_VALIDATION_ERROR",
                    error_message=str(ve),
                    context={"business_id": str(business_id)},
                )
            raise ve
