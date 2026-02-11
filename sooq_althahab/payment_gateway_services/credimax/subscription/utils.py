"""
Credimax Subscription Utilities
================================

This module provides utility functions for handling subscription payments
and transaction management in the Credimax payment gateway integration.
"""

import logging

from django.db import transaction as db_transaction

from account.models import Transaction
from sooq_althahab.enums.account import SubscriptionStatusChoices
from sooq_althahab.enums.account import TransactionStatus

logger = logging.getLogger(__name__)


def _deactivate_card_token(subscription):
    """Deactivate the card token associated with a subscription."""
    if not subscription or not subscription.business_saved_card_token:
        return

    token = subscription.business_saved_card_token
    if token.is_used_for_subscription:
        token.is_used_for_subscription = False
        token.save(update_fields=["is_used_for_subscription"])
        logger.info(
            "Card token deactivated - token_id: %s, subscription_id: %s",
            token.id,
            subscription.id,
        )


def _mark_subscription_failed(subscription):
    """Mark a subscription as failed and deactivate its card token."""
    if not subscription:
        return

    subscription.status = SubscriptionStatusChoices.FAILED
    subscription.save(update_fields=["status"])
    logger.info("Subscription marked as failed - subscription_id: %s", subscription.id)

    _deactivate_card_token(subscription)


def _get_transaction(transaction_id=None, transaction=None, subscription=None):
    """
    Get transaction object from various inputs.

    Returns:
        Transaction object or None if not found
    """
    if transaction:
        return transaction

    if transaction_id:
        return Transaction.objects.select_related("business_subscription").get(
            id=transaction_id
        )

    if subscription:
        # Find pending transaction for this subscription
        return (
            Transaction.objects.filter(
                business_subscription=subscription,
                status=TransactionStatus.PENDING,
            )
            .select_related("business_subscription")
            .first()
        )

    return None


def mark_transaction_and_subscription_as_failed(
    transaction_id=None,
    transaction=None,
    subscription=None,
    reason="Payment failed",
):
    """
    Mark a transaction and its related subscription as failed.

    This utility function handles marking a subscription payment as failed:
    - Marks the transaction as FAILED with the given reason
    - Marks the subscription as FAILED
    - Deactivates the saved card token if it was used for subscription

    Args:
        transaction_id: The transaction ID (UUID)
        transaction: The transaction object
        subscription: The subscription object (will find its pending transaction)
        reason: The failure reason to store in transaction remark

    Returns:
        Transaction: The updated transaction object, or None if not found

    Note: At least one of the parameters must be provided.
          If only subscription is provided and no pending transaction exists,
          only the subscription will be marked as failed.
    """
    if not any([transaction_id, transaction, subscription]):
        logger.error("No transaction_id, transaction, or subscription provided")
        return None

    try:
        # Get the transaction
        txn = _get_transaction(transaction_id, transaction, subscription)

        # If no transaction found but subscription provided, mark subscription only
        if not txn and subscription:
            logger.warning(
                "No pending transaction found for subscription_id: %s",
                subscription.id,
            )
            with db_transaction.atomic():
                _mark_subscription_failed(subscription)
            return None

        if not txn:
            logger.error("Transaction not found")
            return None

        # Get subscription from parameter or transaction
        sub = subscription or txn.business_subscription

        # Mark everything as failed in a single transaction
        with db_transaction.atomic():
            # Mark transaction as failed
            txn.status = TransactionStatus.FAILED
            txn.remark = reason
            txn.save(update_fields=["status", "remark"])
            logger.info(
                "Transaction marked as failed - transaction_id: %s, reason: %s",
                txn.id,
                reason,
            )

            # Mark subscription as failed
            _mark_subscription_failed(sub)

        logger.info(
            "Payment marked as failed - transaction_id: %s, subscription_id: %s",
            txn.id,
            sub.id if sub else None,
        )
        return txn

    except Transaction.DoesNotExist:
        logger.error(
            "Transaction not found - transaction_id: %s",
            transaction_id,
        )
        return None
    except Exception as e:
        logger.error(
            "Error marking payment as failed - error: %s",
            str(e),
        )
        return None
