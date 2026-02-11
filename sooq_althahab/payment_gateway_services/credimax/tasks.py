import logging
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.db import close_old_connections
from django.db import transaction
from django.db.utils import OperationalError
from django.utils import timezone

from account.models import Transaction
from account.models import WebhookCall
from sooq_althahab.enums.account import SubscriptionStatusChoices
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransferVia
from sooq_althahab.enums.account import WebhookCallStatus
from sooq_althahab.enums.account import WebhookEventType

logger = logging.getLogger(__name__)


def extract_credimax_status(order_data):
    """
    Extracts the most relevant status and result from a Credimax Retrieve Order API response.
    Returns (status_code, result, error_info, total_authorized, total_captured)
    """
    # 1. Handle error response
    if "error" in order_data:
        error_info = order_data["error"]
        result = order_data.get("result", "ERROR")

        # Check if it's an invalid request error - this means session expired, never created, or invalid
        error_cause = error_info.get("cause", "")
        error_explanation = error_info.get("explanation", "")

        if error_cause == "INVALID_REQUEST":
            # This is a session that was never completed or invalid request - mark as failed
            logger.info(
                f"[Credimax-Task] Invalid request error detected: {error_explanation}"
            )
            return "FAILED", "FAILURE", error_info, 0, 0

        return None, result, error_info, 0, 0

    # 2. Try top-level fields
    status_code = order_data.get("status")
    result = order_data.get("result")
    total_authorized = order_data.get("totalAuthorizedAmount", 0)
    total_captured = order_data.get("totalCapturedAmount", 0)

    # 3. Try top-level order object
    if not status_code or not result or not total_authorized or not total_captured:
        order_obj = order_data.get("order", {})
        if not status_code:
            status_code = order_obj.get("status")
        if not result:
            result = order_obj.get("result")
        if not total_authorized:
            total_authorized = order_obj.get("totalAuthorizedAmount", total_authorized)
        if not total_captured:
            total_captured = order_obj.get("totalCapturedAmount", total_captured)

    # 4. Try nested transaction array (iterate all, prefer 'PAYMENT' type if present)
    txns = order_data.get("transaction")
    if isinstance(txns, list) and txns:
        # Prefer a transaction with type PAYMENT, else use the first
        payment_txn = next(
            (t for t in txns if t.get("transaction", {}).get("type") == "PAYMENT"), None
        )

        # If we found a payment transaction, use its status
        if payment_txn:
            txn_order = payment_txn.get("order", {})
            txn_response = payment_txn.get("response", {})

            # Use payment transaction status if available
            if not status_code:
                status_code = txn_order.get("status") or payment_txn.get("status")
            if not result:
                result = payment_txn.get("result")
            if not total_authorized:
                total_authorized = txn_order.get(
                    "totalAuthorizedAmount", total_authorized
                )
            if not total_captured:
                total_captured = txn_order.get("totalCapturedAmount", total_captured)

            # Check if payment transaction failed
            if (
                payment_txn.get("result", "").upper() == "FAILURE"
                or txn_response.get("gatewayCode", "").upper() == "DECLINED"
            ):
                # Override result to FAILURE if payment failed
                result = "FAILURE"

        # If no payment transaction found, use the first transaction
        if not payment_txn and txns:
            txn = txns[0]
            txn_order = txn.get("order", {})

            if not status_code:
                status_code = txn_order.get("status") or txn.get("status")
            if not result:
                result = txn.get("result")
            if not total_authorized:
                total_authorized = txn_order.get(
                    "totalAuthorizedAmount", total_authorized
                )
            if not total_captured:
                total_captured = txn_order.get("totalCapturedAmount", total_captured)

    # 5. Final fallback: try to find any status/result in the dict
    if not status_code:
        status_code = order_data.get("authenticationStatus")
    if not result:
        result = order_data.get("authenticationResult")

    return status_code, result, None, total_authorized, total_captured


def map_credimax_to_internal_status(
    order_data,
    status_code,
    result,
    error_info=None,
    total_authorized=0,
    total_captured=0,
):
    """
    Maps Credimax status/result to internal TransactionStatus.
    Handles edge cases where payment is only authenticated but not captured.
    """
    # Normalize for safety
    status_code = (status_code or "").upper()
    result = (result or "").upper()

    # Error or explicit failure
    if error_info or result == "ERROR":
        return TransactionStatus.FAILED

    # If status_code is explicitly FAILED (from extract_credimax_status), return failed
    if status_code == "FAILED":
        return TransactionStatus.FAILED

    # Check for payment failures in transaction array
    # Even if main order shows SUCCESS, check if any payment transaction failed
    txns = order_data.get("transaction", [])
    if isinstance(txns, list) and txns:
        # Look for PAYMENT type transactions that failed
        payment_txns = [
            t for t in txns if t.get("transaction", {}).get("type") == "PAYMENT"
        ]
        if payment_txns:
            # Check if any payment transaction failed
            for payment_txn in payment_txns:
                txn_result = payment_txn.get("result", "").upper()
                txn_response = payment_txn.get("response", {})
                gateway_code = txn_response.get("gatewayCode", "").upper()
                acquirer_code = txn_response.get("acquirerCode")

                # If any payment transaction failed, mark as failed
                if (
                    txn_result == "FAILURE"
                    or gateway_code == "DECLINED"
                    or (acquirer_code and acquirer_code not in ["00", "000"])
                ):
                    return TransactionStatus.FAILED

    # Check for authentication timeout
    # If authentication is pending for more than 2 days, mark as failed
    creation_time = order_data.get("creationTime")
    if creation_time and status_code in [
        "AUTHENTICATION_PENDING",
        "AUTHENTICATION_INITIATED",
    ]:
        try:
            from datetime import datetime
            from datetime import timezone

            # Parse creation time
            if creation_time.endswith("Z"):
                creation_time = creation_time[:-1] + "+00:00"
            creation_dt = datetime.fromisoformat(creation_time)

            # Get current time in UTC
            current_dt = datetime.now(timezone.utc)

            # Calculate time difference
            time_diff = current_dt - creation_dt

            # If more than 2 days (48 hours), mark as failed
            if time_diff.total_seconds() > 48 * 3600:  # 48 hours in seconds
                return TransactionStatus.FAILED
        except Exception as e:
            # If we can't parse the time, continue with normal logic
            logger.warning(f"Could not parse creation time for timeout check: {e}")

    # If status is AUTHENTICATED/AUTHORIZED/INITIATED/PENDING/UNSUCCESSFUL/FAILED and no money moved, treat as failed or pending
    failed_statuses = [
        "AUTHENTICATION_UNSUCCESSFUL",
        "AUTHENTICATION_FAILED",
        "AUTHENTICATION_DECLINED",
        "AUTHENTICATION_REJECTED",
        "DECLINED",
        "CANCELLED",
        "EXPIRED",
        "FAILED",
    ]
    pending_statuses = [
        "AUTHORIZED",
        "PENDING",
        "AUTHENTICATION_INITIATED",
        "AUTHENTICATION_PENDING",
    ]

    # If status is in failed_statuses, always failed
    if status_code in failed_statuses:
        return TransactionStatus.FAILED

    # If status is in pending_statuses and no money moved, pending
    if status_code in pending_statuses and (
        not total_authorized and not total_captured
    ):
        return TransactionStatus.PENDING

    # If status is AUTHENTICATED but no money moved, treat as failed
    if status_code == "AUTHENTICATED" and (not total_authorized and not total_captured):
        return TransactionStatus.FAILED

    # Handle VERIFIED status with SUCCESS result - this is used for subscription setup
    # where card is verified and subscription agreement is created (postpaid subscriptions)
    # For subscription transactions, VERIFIED with SUCCESS means the setup was successful
    # This status is returned when the card is verified and the subscription agreement is created
    # even though no payment has been captured yet (postpaid subscriptions)
    if status_code == "VERIFIED" and result == "SUCCESS":
        return TransactionStatus.SUCCESS

    # Standard success/failure logic
    if result == "SUCCESS" and status_code == "CAPTURED":
        return TransactionStatus.SUCCESS
    if result == "FAILURE" or status_code in failed_statuses:
        return TransactionStatus.FAILED
    if status_code in pending_statuses:
        return TransactionStatus.PENDING

    # Default fallback
    return TransactionStatus.PENDING


@shared_task(bind=True, max_retries=1)
def check_pending_credimax_transactions(self):
    """
    Task to check all pending Credimax transactions and update their status
    by calling the Credimax API. This is a fallback mechanism in case webhooks
    are missed or fail to process.

    Handles all pending Credimax transactions (wallet top-ups and subscriptions):
    - Checks all pending transactions every 5 minutes
    - Calls Credimax API to get current transaction status
    - Updates transaction status based on API response
    - For subscription transactions older than timeout threshold (>30 min) and still pending, marks as FAILED
    - Timeout threshold is configurable via CREDIMAX_STALE_TRANSACTION_TIMEOUT_MINUTES (default: 30 minutes)
    """
    try:
        # Close any stale database connections before querying
        close_old_connections()

        # Single query to fetch all pending Credimax transactions
        pending_transaction_ids = list(
            Transaction.objects.filter(
                status=TransactionStatus.PENDING,
                transfer_via=TransferVia.CREDIMAX,
            ).values_list("id", flat=True)
        )

        # Connection is automatically closed after the list() conversion
        close_old_connections()

        processed_count = 0
        failed_count = 0

        # Iterate over transaction IDs instead of full objects
        for transaction_id in pending_transaction_ids:
            try:
                # Close connections periodically to prevent connection exhaustion
                if processed_count % 50 == 0 and processed_count > 0:
                    close_old_connections()

                check_single_credimax_transaction.delay(transaction_id)
                processed_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(
                    f"[Credimax-Task] Failed to queue transaction {transaction_id}: {str(e)}"
                )

        return {
            "processed_count": processed_count,
            "failed_count": failed_count,
            "message": f"Queued {processed_count} transactions for status check",
        }

    except OperationalError as e:
        logger.error(f"[Credimax-Task] Database connection error: {e}")
        close_old_connections()
        raise
    except Exception as e:
        logger.exception(f"[Credimax-Task] Unexpected error: {e}")
        close_old_connections()
        raise


@shared_task(bind=True, max_retries=1)
def check_single_credimax_transaction(self, transaction_id):
    """
    Check the status of a single Credimax transaction by calling the Credimax API.

    Args:
        transaction_id: The ID of the transaction to check
    """
    try:
        # Close any stale database connections before querying
        close_old_connections()

        # Wrap select_for_update in a transaction block
        # select_for_update requires an active database transaction
        with transaction.atomic():
            # Get the transaction with select_for_update to prevent race conditions
            transaction_obj = Transaction.objects.select_for_update().get(
                id=transaction_id
            )

            # CRITICAL: Only process transactions that are still PENDING
            # This prevents the task from incorrectly updating SUCCESS/FAILED transactions
            # that may have been processed by webhooks or other processes
            if transaction_obj.status != TransactionStatus.PENDING:
                logger.info(
                    f"[Credimax-Task] Skipping transaction {transaction_id} - status is {transaction_obj.status}, not PENDING"
                )
                close_old_connections()
                return {
                    "status": "skipped",
                    "reason": f"transaction_not_pending",
                    "current_status": transaction_obj.status,
                }

        logger.info(f"[Credimax-Task] Checking status for transaction {transaction_id}")

        # Construct the API URL for checking order status
        # The order_id is the transaction.id as per the checkout.py implementation
        order_id = transaction_obj.id
        api_url = f"{settings.CREDIMAX_BASE_URL}order/{order_id}"

        # Prepare authentication
        auth = (settings.CREDIMAX_API_USERNAME, settings.CREDIMAX_API_PASSWORD)

        # Make the API call to check order status
        response = requests.get(api_url, auth=auth, timeout=30)

        logger.info(
            f"[Credimax-Task] API response status: {response.status_code} for transaction {transaction_id}"
        )

        if response.status_code == 200:
            order_data = response.json()
            logger.info(
                f"[Credimax-Task] Order data for transaction {transaction_id}: {order_data}"
            )

            # Process the response and update transaction status
            update_transaction_status_from_credimax_response(
                transaction_obj, order_data
            )

        elif response.status_code == 404:
            logger.warning(
                f"[Credimax-Task] Order not found in Credimax for transaction {transaction_id}"
            )
            # Order not found in Credimax - might be too old or invalid
            # We could mark it as failed or leave it pending based on business logic
            return

        elif response.status_code == 400:
            # Parse the error response and update transaction status
            try:
                error_data = response.json()
                error_info = error_data.get("error", {})
                error_explanation = error_info.get("explanation", "Unknown error")
                error_cause = error_info.get("cause", "UNKNOWN")

                # Log as warning instead of error - this is expected for orders that don't exist in Credimax
                logger.warning(
                    f"[Credimax-Task] Order not found in Credimax for transaction {transaction_id}: "
                    f"{error_explanation} (Cause: {error_cause})"
                )

                # Update transaction and subscription status based on error
                update_transaction_status_from_credimax_response(
                    transaction_obj, error_data
                )
            except Exception as e:
                logger.error(
                    f"[Credimax-Task] Error parsing 400 response for transaction {transaction_id}: {str(e)}"
                )
            return

        else:
            logger.error(
                f"[Credimax-Task] Unexpected response from Credimax API: {response.status_code} for transaction {transaction_id}"
            )
            # Only retry for other errors
            raise self.retry(
                countdown=300, exc=Exception(f"API returned {response.status_code}")
            )

    except Transaction.DoesNotExist:
        logger.error(f"[Credimax-Task] Transaction {transaction_id} not found")
        close_old_connections()
        return {"status": "error", "reason": "transaction_not_found"}

    except OperationalError as e:
        # Handle database connection errors
        logger.error(
            f"[Credimax-Task] Database connection error for transaction {transaction_id}: {e}"
        )
        # Close connections before retrying
        close_old_connections()
        raise  # Re-raise to trigger Celery retry if configured

    except requests.RequestException as e:
        logger.error(
            f"[Credimax-Task] Request error for transaction {transaction_id}: {str(e)}"
        )
        # Close connections before retrying
        close_old_connections()
        # Retry the task
        raise self.retry(countdown=300, exc=e)

    except Exception as e:
        # Only retry for non-400 errors
        if hasattr(e, "args") and "API returned 400" in str(e.args):
            logger.error(f"[Credimax-Task] Not retrying for 400 error: {e}")
            close_old_connections()
            return
        logger.error(
            f"[Credimax-Task] Error processing transaction {transaction_id}: {str(e)}"
        )
        # Close connections before retrying
        close_old_connections()
        # Retry the task
        raise self.retry(countdown=300, exc=e)


def update_transaction_status_from_credimax_response(transaction, order_data):
    """
    Update transaction status based on Credimax API response.
    """
    logger.info(
        f"[Credimax-Task] Starting update_transaction_status_from_credimax_response for transaction {transaction.id}"
    )
    logger.info(f"[Credimax-Task] Order data: {order_data}")

    try:
        (
            status_code,
            result,
            error_info,
            total_authorized,
            total_captured,
        ) = extract_credimax_status(order_data)

        # Log the extracted information
        if error_info:
            logger.info(
                f"[Credimax-Task] Processing error response for transaction {transaction.id}: {error_info}"
            )
        else:
            logger.info(
                f"[Credimax-Task] Processing order status: {status_code}, result: {result}, total_authorized: {total_authorized}, total_captured: {total_captured} for transaction {transaction.id}"
            )

        new_status = map_credimax_to_internal_status(
            order_data,
            status_code,
            result,
            error_info,
            total_authorized,
            total_captured,
        )

        # For subscription transactions, if still pending after timeout threshold, mark as failed
        # This handles abandoned payment sessions that have been pending for too long
        if (
            transaction.business_subscription
            and new_status == TransactionStatus.PENDING
        ):
            transaction_age = timezone.now() - transaction.created_at
            transaction_age_minutes = transaction_age.total_seconds() / 60
            stale_timeout_minutes = settings.CREDIMAX_STALE_TRANSACTION_TIMEOUT_MINUTES

            # If transaction is older than timeout threshold (>30 min) and still pending, mark as failed
            if transaction_age_minutes >= stale_timeout_minutes:
                new_status = TransactionStatus.FAILED
                error_info = error_info or {}
                error_info["explanation"] = (
                    f"Payment session abandoned - no activity after {transaction_age_minutes:.1f} minutes "
                    f"(timeout threshold: {stale_timeout_minutes} minutes)"
                )
                logger.warning(
                    f"[Credimax-Task] Marking subscription transaction {transaction.id} as FAILED "
                    f"(pending for {transaction_age_minutes:.1f} minutes, API still returned pending, "
                    f"timeout threshold: {stale_timeout_minutes} minutes)"
                )
            # If transaction is < 30 minutes old and still pending, keep it as pending
            # (payment is still in progress, don't mark as failed yet)

        logger.info(
            f"[Credimax-Task] Mapped status for transaction {transaction.id}: "
            f"extracted_status={status_code}, extracted_result={result}, "
            f"mapped_status={new_status}, current_status={transaction.status}"
        )

        # CRITICAL SAFETY CHECK: Refresh transaction from DB to ensure we have latest status
        # This prevents race conditions where transaction was updated by webhook between query and update
        transaction.refresh_from_db()
        if transaction.status != TransactionStatus.PENDING:
            logger.warning(
                f"[Credimax-Task] Transaction {transaction.id} status changed to {transaction.status} "
                f"during processing - skipping update to prevent overwriting final status"
            )
            close_old_connections()
            return

        # Only update if status changed and we have a valid new status
        if new_status and new_status != transaction.status:
            old_status = transaction.status
            transaction.status = new_status

            # Update transaction log details with error explanation if there's an error
            if error_info and new_status == TransactionStatus.FAILED:
                error_explanation = error_info.get("explanation", "")
                if error_explanation:
                    # Append error explanation to existing log details or create new log details
                    current_notes = transaction.log_details or ""
                    error_note = f"Credimax Error: {error_explanation}"
                    if current_notes:
                        transaction.log_details = f"{current_notes}\n{error_note}"
                    else:
                        transaction.log_details = error_note

            # If transaction is successful and it's a deposit, update wallet balance
            if (
                new_status == TransactionStatus.SUCCESS
                and transaction.transaction_type == "DEPOSIT"
            ):
                update_wallet_balance_for_successful_deposit(transaction)
                # Send invoice email to accounts for successful top-up transactions
                try:
                    from sooq_althahab.billing.transaction.invoice_utils import (
                        send_topup_invoice_to_accounts,
                    )

                    organization = transaction.from_business.organization_id
                    if organization:
                        send_topup_invoice_to_accounts(transaction, organization)
                except Exception as invoice_error:
                    logger.error(
                        f"[Credimax-Task] Failed to send top-up invoice email for transaction {transaction.id}: {str(invoice_error)}"
                    )

            # If transaction is for a business subscription, update subscription status
            if transaction.business_subscription:
                update_subscription_status_from_transaction(
                    transaction, new_status, error_info
                )

            try:
                transaction.save()
                logger.info(
                    f"[Credimax-Task] Updated transaction {transaction.id} status from {old_status} to {new_status}"
                )
            except Exception as save_error:
                logger.error(
                    f"[Credimax-Task] Error saving transaction {transaction.id}: {str(save_error)}"
                )
                raise
        else:
            logger.info(
                f"[Credimax-Task] No status change for transaction {transaction.id}: "
                f"new_status={new_status}, current_status={transaction.status}"
            )

            # Log the webhook call for audit purposes
            WebhookCall.objects.create(
                transaction=transaction,
                transfer_via=TransferVia.CREDIMAX,
                event_type=WebhookEventType.PAYMENT,
                status=(
                    WebhookCallStatus.SUCCESS
                    if new_status == TransactionStatus.SUCCESS
                    else WebhookCallStatus.FAILURE
                ),
                request_body={},  # No request body for this type of call
                response_body=order_data,
                response_status_code=200,
            )

    except Exception as e:
        logger.error(
            f"[Credimax-Task] Error updating transaction {transaction.id}: {str(e)}"
        )
        raise

    logger.info(
        f"[Credimax-Task] Completed update_transaction_status_from_credimax_response for transaction {transaction.id}"
    )


def update_wallet_balance_for_successful_deposit(transaction):
    """
    Update wallet balance for a successful deposit transaction.

    Args:
        transaction: Transaction object that was successful
    """
    try:
        from account.models import Wallet

        business_id = transaction.from_business.id
        business_wallet = Wallet.objects.get(business=business_id)

        # Update wallet balance
        transaction.previous_balance = business_wallet.balance
        business_wallet.balance += transaction.amount
        transaction.current_balance = business_wallet.balance

        business_wallet.save()
        transaction.save()

        logger.info(
            f"[Credimax-Task] Updated wallet balance for business {transaction.from_business.name}: "
            f"Previous: {transaction.previous_balance}, Current: {transaction.current_balance}"
        )

    except Wallet.DoesNotExist:
        logger.error(
            f"[Credimax-Task] Wallet not found for business {transaction.from_business.id}"
        )
        raise
    except Exception as e:
        logger.error(
            f"[Credimax-Task] Error updating wallet balance for transaction {transaction.id}: {str(e)}"
        )
        raise


def update_subscription_status_from_transaction(
    transaction, new_status, error_info=None
):
    """
    Update business subscription status based on transaction status change.
    This function is called for all subscription transactions checked by the task.

    Args:
        transaction: Transaction object with business_subscription
        new_status: The new transaction status (SUCCESS, FAILED, or PENDING)
        error_info: Optional error information from Credimax response
    """
    try:
        if not transaction.business_subscription:
            return

        subscription = transaction.business_subscription
        old_subscription_status = subscription.status

        # Update subscription status based on transaction status
        # Note: If transaction is older than timeout threshold and still pending,
        # it is already marked as FAILED in update_transaction_status_from_credimax_response
        # before this function is called
        if new_status == TransactionStatus.SUCCESS:
            # Payment succeeded - activate subscription
            if subscription.status == SubscriptionStatusChoices.PENDING:
                # Apply grace period if not already applied and business is eligible
                # OPTIMIZED: Fast path - check subscription plan grace days first (no DB query)
                subscription_plan = subscription.subscription_plan
                if (
                    not subscription.intro_grace_applied
                    and subscription_plan
                    and (getattr(subscription_plan, "intro_grace_period_days", 0) or 0)
                    > 0
                ):
                    business = subscription.business
                    # Only refresh if needed (for async task context)
                    business.refresh_from_db()

                    # Check if business already received grace
                    if not getattr(business, "has_received_intro_grace", False):
                        from dateutil.relativedelta import relativedelta

                        from sooq_althahab.enums.account import (
                            SubscriptionBillingFrequencyChoices,
                        )

                        grace_days = (
                            getattr(subscription_plan, "intro_grace_period_days", 0)
                            or 0
                        )
                        # Calculate new expiry date with grace days from existing start_date
                        from datetime import timedelta

                        start_date = subscription.start_date
                        base_expiry = start_date + relativedelta(
                            months=subscription_plan.duration
                        )
                        # Subtract 1 day so expiry_date is the last day user can use the app
                        base_expiry = base_expiry - timedelta(days=1)
                        expiry_date = base_expiry + relativedelta(days=grace_days)

                        # Calculate next_billing_date based on billing frequency and grace period
                        # IMPORTANT: next_billing_date should equal expiry_date for the first billing cycle
                        # This ensures billing happens on the last day of access, not the day after
                        # For POSTPAID: Billing happens on expiry_date (last day of access)
                        # For PREPAID: Billing happens on expiry_date (last day of current period)
                        # After successful billing, update_billing_after_success will calculate the next billing date
                        next_billing_date = expiry_date

                        subscription.expiry_date = expiry_date
                        subscription.next_billing_date = next_billing_date
                        subscription.intro_grace_period_days = grace_days
                        subscription.intro_grace_applied = True

                        # Mark grace as consumed (will be saved with subscription)
                        business.has_received_intro_grace = True
                        if hasattr(business, "intro_grace_consumed_on"):
                            business.intro_grace_consumed_on = timezone.now().date()

                subscription.status = SubscriptionStatusChoices.ACTIVE
                logger.info(
                    f"[Credimax-Task] Activating subscription {subscription.id} "
                    f"for transaction {transaction.id}"
                )
        elif new_status == TransactionStatus.FAILED:
            # Payment failed - mark subscription as failed
            # Update subscription if it's in PENDING state (don't override if already FAILED or ACTIVE)
            if subscription.status == SubscriptionStatusChoices.PENDING:
                subscription.status = SubscriptionStatusChoices.FAILED
                # Store error information if available
                if error_info:
                    error_explanation = error_info.get("explanation", "")
                    if error_explanation:
                        # Update transaction remark with error message
                        transaction.remark = (
                            "Transaction could not be verified with Credimax.\n\n"
                            "The payment gateway was unable to locate this order during verification. "
                            "This usually indicates an expired session or an order creation failure.\n\n"
                            "Status: Not Charged\n"
                            "Action: User should retry the payment with a new session."
                        )
                        transaction.save(update_fields=["remark"])
                logger.info(
                    f"[Credimax-Task] Marking subscription {subscription.id} as FAILED "
                    f"for transaction {transaction.id}. Error: {error_info.get('explanation', 'Unknown error') if error_info else 'N/A'}"
                )
        # If transaction is still PENDING and not older than timeout threshold,
        # we don't change subscription status (transaction is still in progress)

        # Save subscription if status changed or grace was applied
        update_fields = []
        if subscription.status != old_subscription_status:
            update_fields.append("status")
        if (
            subscription.intro_grace_applied
            and subscription.intro_grace_period_days > 0
        ):
            if "expiry_date" not in update_fields:
                update_fields.extend(
                    [
                        "expiry_date",
                        "next_billing_date",
                        "intro_grace_period_days",
                        "intro_grace_applied",
                    ]
                )
                # Save business grace status (only if grace was just applied)
                business = subscription.business
                if (
                    hasattr(business, "intro_grace_consumed_on")
                    and business.intro_grace_consumed_on
                ):
                    business.save(
                        update_fields=[
                            "has_received_intro_grace",
                            "intro_grace_consumed_on",
                        ]
                    )
                else:
                    business.save(update_fields=["has_received_intro_grace"])

        if update_fields:
            subscription.save(update_fields=update_fields)
            if subscription.status != old_subscription_status:
                logger.info(
                    f"[Credimax-Task] Updated subscription {subscription.id} status "
                    f"from {old_subscription_status} to {subscription.status} "
                    f"for transaction {transaction.id}"
                )
        else:
            logger.info(
                f"[Credimax-Task] Subscription {subscription.id} status unchanged "
                f"({subscription.status}) for transaction {transaction.id}"
            )

    except Exception as e:
        logger.error(
            f"[Credimax-Task] Error updating subscription status for transaction {transaction.id}: {str(e)}"
        )
        # Don't raise - we don't want subscription update failures to block transaction updates
        pass
