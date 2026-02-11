import calendar
import logging
import time
from datetime import datetime
from datetime import timedelta
from decimal import ROUND_HALF_UP
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.contrib.contenttypes.models import ContentType
from django.db import transaction as db_transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework import status

from account.models import Transaction
from account.models import User
from account.models import UserAssignedBusiness
from account.models import WebhookCall
from sooq_althahab.billing.subscription.email_utils import send_mail_to_business_owner
from sooq_althahab.billing.subscription.email_utils import (
    send_postpaid_subscription_activation_email,
)
from sooq_althahab.billing.subscription.helpers import calculate_tax_and_total
from sooq_althahab.billing.subscription.pdf_utils import render_subscription_invoice_pdf
from sooq_althahab.billing.transaction.helpers import get_organization_logo_url
from sooq_althahab.enums.account import SubscriptionBillingFrequencyChoices
from sooq_althahab.enums.account import SubscriptionStatusChoices
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.account import TransferVia
from sooq_althahab.enums.account import WebhookCallStatus
from sooq_althahab.enums.account import WebhookEventType
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.enums.sooq_althahab_admin import PaymentStatus
from sooq_althahab.enums.sooq_althahab_admin import SubscriptionPaymentIntervalChoices
from sooq_althahab.enums.sooq_althahab_admin import SubscriptionPaymentTypeChoices
from sooq_althahab.payment_gateway_services.credimax.subscription.credimax_client import (
    CredimaxClient,
)
from sooq_althahab.payment_gateway_services.payment_logger import get_credimax_logger
from sooq_althahab.utils import send_notifications
from sooq_althahab.utils import validate_card_expiry_date
from sooq_althahab_admin.models import BillingDetails
from sooq_althahab_admin.models import BusinessSavedCardToken
from sooq_althahab_admin.models import BusinessSubscriptionPlan
from sooq_althahab_admin.models import SubscriptionPlan

logger = logging.getLogger(__name__)


class CreateSubscriptionSessionSerializer(serializers.Serializer):
    """
    Serializer to:
    - Validate business and subscription plan input.
    - Create a new Credimax session.
    - Reuse existing PENDING subscription or create new one if none exists.
    - Record/update pending transaction and business subscription plan.

    Fields:
        - subscription_plan_id (str)
        - is_auto_renew (bool)

    Returns:
        - session_id: ID from Credimax
        - order_id: Internal transaction ID
        - transaction_id: Shortened 3DS transaction ID
    """

    subscription_plan_id = serializers.CharField()
    is_auto_renew = serializers.BooleanField()

    def validate(self, data):
        request = self.context["request"]
        current_business_id = request.auth.get("current_business")

        if not current_business_id:
            raise serializers.ValidationError("Invalid user business.")

        try:
            subscription_plan = SubscriptionPlan.objects.get(
                id=data.get("subscription_plan_id")
            )
        except SubscriptionPlan.DoesNotExist:
            raise serializers.ValidationError("Invalid subscription plan.")

        # Check if this is a free trial plan - handle it differently
        is_free_trial = (
            subscription_plan.payment_type == SubscriptionPaymentTypeChoices.FREE_TRIAL
        )

        try:
            user_business = UserAssignedBusiness.objects.get(id=current_business_id)
        except UserAssignedBusiness.DoesNotExist:
            raise serializers.ValidationError("Associated business not found.")

        data["is_free_trial"] = is_free_trial
        data["subscription_plan"] = subscription_plan
        data["business"] = user_business.business

        return data

    def create(self, validated_data):
        request = self.context["request"]
        business = validated_data["business"]
        subscription_plan = validated_data["subscription_plan"]
        is_auto_renew = validated_data["is_auto_renew"]
        is_free_trial = validated_data.get("is_free_trial", False)
        intro_grace_days = self._get_intro_grace_days(business, subscription_plan)

        # Check if this is a POSTPAID subscription - no transaction should be created at purchase time
        is_postpaid = (
            subscription_plan.payment_type == SubscriptionPaymentTypeChoices.POSTPAID
        )

        vat_rate = getattr(request.user.organization_id, "vat_rate", 0)

        # Initialize payment logger
        payment_logger = get_credimax_logger(business_id=str(business.id))

        # Log transaction start
        payment_logger.log_transaction_start(
            transaction_type="SUBSCRIPTION_CREATION",
            business_id=str(business.id),
            amount=float(subscription_plan.subscription_fee or 0),
            additional_data={
                "subscription_plan_id": str(subscription_plan.id),
                "subscription_plan_name": subscription_plan.name,
                "is_auto_renew": is_auto_renew,
                "is_free_trial": is_free_trial,
                "vat_rate": float(vat_rate),
                "business_name": business.name,
                "user_id": str(request.user.id),
            },
        )

        # Handle free trial subscriptions differently
        if is_free_trial:
            try:
                result = self._create_free_trial_subscription(
                    request,
                    business,
                    subscription_plan,
                    is_auto_renew,
                    vat_rate,
                    payment_logger,
                    intro_grace_days,
                )
                payment_logger.log_transaction_completion(
                    final_status=result.get("status") or "SUCCESS",
                    summary={
                        "type": "free_trial",
                        "subscription_id": result.get("subscription_id"),
                    },
                )
                return result
            except Exception as e:
                payment_logger.log_error(
                    error_type="FREE_TRIAL_CREATION_ERROR",
                    error_message=str(e),
                    context={
                        "business_id": str(business.id),
                        "subscription_plan_id": str(subscription_plan.id),
                    },
                )
                raise

        # Regular paid subscription flow
        try:
            client = CredimaxClient()
            session_start_time = time.time()

            payment_logger.log_api_request(
                endpoint="session",
                method="POST",
                payload={"apiOperation": "CREATE_CHECKOUT_SESSION"},
            )

            session_response = client.create_session()
            session_response_time = (time.time() - session_start_time) * 1000

            payment_logger.log_api_response(
                status_code=200,
                response_data=session_response,
                response_time_ms=session_response_time,
            )

            print("FLAG-1")
            session_id = session_response.get("session", {}).get("id")

            if not session_id:
                payment_logger.log_error(
                    error_type="SESSION_CREATION_FAILED",
                    error_message="Failed to create Credimax session - no session ID in response",
                    context={"response": session_response},
                )
                raise serializers.ValidationError("Failed to create Credimax session.")

        except Exception as e:
            payment_logger.log_error(
                error_type="CREDIMAX_SESSION_ERROR",
                error_message=str(e),
                context={
                    "business_id": str(business.id),
                    "subscription_plan_id": str(subscription_plan.id),
                },
            )
            raise serializers.ValidationError(
                f"Failed to create Credimax session: {str(e)}"
            )

        with db_transaction.atomic():
            try:
                if subscription_plan.discounted_fee is not None:
                    amount = subscription_plan.discounted_fee
                elif subscription_plan.subscription_fee is not None:
                    amount = subscription_plan.subscription_fee
                else:
                    amount = Decimal("0.00")

                payment_logger.log_business_logic(
                    action="CALCULATE_AMOUNT",
                    data={
                        "discounted_fee": (
                            float(subscription_plan.discounted_fee)
                            if subscription_plan.discounted_fee
                            else None
                        ),
                        "subscription_fee": (
                            float(subscription_plan.subscription_fee)
                            if subscription_plan.subscription_fee
                            else None
                        ),
                        "final_amount": float(amount),
                    },
                )

                # IMPORTANT: Always create a NEW subscription for each purchase attempt
                # Do NOT reuse existing PENDING or FAILED subscriptions
                # This ensures each attempt gets fresh dates calculated from the current attempt date
                # If payment succeeds, the subscription will be activated with those new dates
                # Old FAILED records remain as historical records

                # Step 1: Create BusinessSubscriptionPlan with fresh dates
                (
                    start_date,
                    expiry_date,
                    next_billing_date,
                ) = self._compute_initial_subscription_dates(
                    subscription_plan, intro_grace_days
                )

                payment_logger.log_business_logic(
                    action="CREATE_NEW_SUBSCRIPTION",
                    data={
                        "subscription_plan_id": str(subscription_plan.id),
                        "start_date": start_date.isoformat(),
                        "expiry_date": expiry_date.isoformat(),
                        "duration_months": subscription_plan.duration,
                        "amount": float(amount),
                        "is_auto_renew": is_auto_renew,
                        "intro_grace_days": intro_grace_days,
                        "next_billing_date": next_billing_date.isoformat()
                        if next_billing_date
                        else None,
                    },
                )
                logger.info(
                    f"[GRACE_PERIOD] Creating subscription with grace_days={intro_grace_days}, "
                    f"expiry_date={expiry_date}, next_billing_date={next_billing_date}, "
                    f"business_id={business.id}, business_has_received_grace={getattr(business, 'has_received_intro_grace', False)}"
                )

                business_subscription_plan = BusinessSubscriptionPlan.objects.create(
                    business=business,
                    subscription_plan=subscription_plan,
                    subscription_name=subscription_plan.name,
                    start_date=start_date,
                    expiry_date=expiry_date,
                    billing_frequency=subscription_plan.billing_frequency,
                    payment_interval=subscription_plan.payment_interval,
                    payment_amount_variability=subscription_plan.payment_amount_variability,
                    subscription_fee=amount,
                    next_billing_date=next_billing_date,
                    intro_grace_period_days=intro_grace_days,
                    intro_grace_applied=bool(intro_grace_days),
                    status=SubscriptionStatusChoices.PENDING,
                    payment_type=subscription_plan.payment_type,
                    pro_rata_rate=subscription_plan.pro_rata_rate,
                    commission_rate=subscription_plan.commission_rate,
                    features=subscription_plan.features or [],
                    is_auto_renew=is_auto_renew,
                    created_by=request.user,
                )
                print("FLAG-CREATED-BUSINESS-SUBSCRIPTION")

                # Verify grace period was set correctly
                if intro_grace_days > 0:
                    logger.info(
                        f"[GRACE_PERIOD] Subscription created - id={business_subscription_plan.id}, "
                        f"intro_grace_period_days={business_subscription_plan.intro_grace_period_days}, "
                        f"intro_grace_applied={business_subscription_plan.intro_grace_applied}, "
                        f"expiry_date={business_subscription_plan.expiry_date}, "
                        f"next_billing_date={business_subscription_plan.next_billing_date}"
                    )
                else:
                    logger.info(
                        f"[GRACE_PERIOD] Subscription created without grace - id={business_subscription_plan.id}, "
                        f"plan_grace_days={getattr(subscription_plan, 'intro_grace_period_days', 0)}, "
                        f"business_has_received_grace={getattr(business, 'has_received_intro_grace', False)}"
                    )

                # IMPORTANT: Do NOT mark business as having received grace here!
                # The subscription is still PENDING - payment hasn't succeeded yet.
                # If payment fails, the subscription won't be activated, but we would have
                # incorrectly marked the business as having received grace.
                # Grace period will be marked as consumed only when subscription is activated
                # (status changes to ACTIVE) in CustomerInitiatedPaymentSerializer.save()
                logger.info(
                    f"[GRACE_PERIOD] Subscription created with grace period configured: "
                    f"id={business_subscription_plan.id}, grace_days={intro_grace_days}, "
                    f"status=PENDING. Business will be marked as having received grace only after successful payment activation."
                )

                payment_logger.log_business_logic(
                    action="SUBSCRIPTION_CREATED",
                    data={
                        "subscription_id": str(business_subscription_plan.id),
                        "subscription_name": business_subscription_plan.subscription_name,
                        "status": business_subscription_plan.status,
                        "start_date": business_subscription_plan.start_date.isoformat(),
                        "expiry_date": business_subscription_plan.expiry_date.isoformat(),
                    },
                )

                # Step 2: Create Transaction only for PREPAID subscriptions
                # POSTPAID subscriptions do not create transactions at purchase time
                if is_postpaid:
                    payment_logger.log_business_logic(
                        action="SKIP_TRANSACTION_FOR_POSTPAID_NEW_SUBSCRIPTION",
                        data={
                            "subscription_id": str(business_subscription_plan.id),
                            "reason": "POSTPAID subscriptions do not create transactions at purchase time. Transaction will be created during recurring payment.",
                        },
                    )
                    logger.info(
                        f"[CREATE_SESSION] POSTPAID subscription - skipping transaction creation: "
                        f"subscription_id={business_subscription_plan.id}"
                    )
                    transaction = None
                    # Use subscription ID for 3DS transaction ID for POSTPAID
                    credimax_3ds_transaction_id = (
                        business_subscription_plan.id[:8]
                        if business_subscription_plan.id
                        else "POSTPAID"
                    )
                else:
                    # Calculate VAT and total amount
                    vat_amount = (amount * vat_rate).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    total_amount = (amount + vat_amount).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )

                    transaction = Transaction.objects.create(
                        from_business=business,
                        to_business=business,
                        amount=total_amount,  # Store total amount (base + VAT) in transaction
                        vat_rate=vat_rate,
                        vat=vat_amount,
                        transaction_type=TransactionType.PAYMENT,
                        transfer_via=TransferVia.CREDIMAX,
                        status=TransactionStatus.PENDING,
                        log_details=f"Subscription payment by {business.name} for plan {subscription_plan.name} with ID {subscription_plan.id}",
                        created_by=request.user,
                        business_subscription=business_subscription_plan,
                    )
                    print("FLAG-CREATED-TRANSACTION")

                    payment_logger.log_business_logic(
                        action="TRANSACTION_CREATED_FOR_NEW_SUBSCRIPTION",
                        data={
                            "transaction_id": str(transaction.id),
                            "subscription_id": str(business_subscription_plan.id),
                            "amount": float(amount),
                            "vat_amount": float(transaction.vat),
                            "status": transaction.status,
                        },
                    )

                    # Step 3: Update subscription with 3DS transaction ID
                    credimax_3ds_transaction_id = transaction.id[:8]
                    business_subscription_plan.credimax_3ds_transaction_id = (
                        credimax_3ds_transaction_id
                    )
                    business_subscription_plan.save(
                        update_fields=["credimax_3ds_transaction_id"]
                    )
                    print("FLAG-UPDATED-SUBSCRIPTION-WITH-3DS-ID")

                    payment_logger.log_business_logic(
                        action="SUBSCRIPTION_UPDATED_WITH_3DS_ID",
                        data={
                            "subscription_id": str(business_subscription_plan.id),
                            "credimax_3ds_transaction_id": credimax_3ds_transaction_id,
                        },
                    )

                # For POSTPAID: Set 3DS transaction ID from subscription ID
                if is_postpaid:
                    business_subscription_plan.credimax_3ds_transaction_id = (
                        credimax_3ds_transaction_id
                    )
                    business_subscription_plan.save(
                        update_fields=["credimax_3ds_transaction_id"]
                    )
                    logger.info(
                        f"[CREATE_SESSION] POSTPAID subscription - set 3DS ID from subscription: "
                        f"subscription_id={business_subscription_plan.id}, "
                        f"credimax_3ds_transaction_id={credimax_3ds_transaction_id}"
                    )

            except Exception as e:
                payment_logger.log_error(
                    error_type="DATABASE_OPERATION_ERROR",
                    error_message=str(e),
                    context={
                        "business_id": str(business.id),
                        "subscription_plan_id": str(subscription_plan.id),
                    },
                )
                raise

        try:
            print("FLAG-4")
            session_update_start_time = time.time()

            # For POSTPAID: Create a minimal transaction with amount=0 for session update
            # This transaction is only for Credimax session update, not for actual payment
            if is_postpaid and transaction is None:
                payment_logger.log_business_logic(
                    action="CREATE_DUMMY_TRANSACTION_FOR_POSTPAID_SESSION",
                    data={
                        "subscription_id": str(business_subscription_plan.id),
                        "reason": "POSTPAID subscriptions need a transaction object for Credimax session update, but with amount=0",
                    },
                )
                logger.info(
                    f"[CREATE_SESSION] Creating dummy transaction (amount=0) for POSTPAID session update: "
                    f"subscription_id={business_subscription_plan.id}"
                )
                # Create a minimal transaction with amount=0 for POSTPAID
                # This is only used for Credimax session update, not for actual payment
                transaction = Transaction.objects.create(
                    from_business=business,
                    to_business=business,
                    amount=Decimal("0.00"),  # Zero amount for POSTPAID
                    vat_rate=vat_rate,
                    vat=Decimal("0.00"),
                    transaction_type=TransactionType.PAYMENT,
                    transfer_via=TransferVia.CREDIMAX,
                    status=TransactionStatus.PENDING,
                    log_details=f"POSTPAID subscription session setup - no payment at purchase. Subscription: {business_subscription_plan.subscription_name} (ID: {subscription_plan.id})",
                    created_by=request.user,
                    business_subscription=business_subscription_plan,
                    remark="POSTPAID subscription - transaction created for session update only. Actual payment will be processed during recurring billing.",
                )
                credimax_3ds_transaction_id = transaction.id[:8]
                business_subscription_plan.credimax_3ds_transaction_id = (
                    credimax_3ds_transaction_id
                )
                business_subscription_plan.save(
                    update_fields=["credimax_3ds_transaction_id"]
                )
                logger.info(
                    f"[CREATE_SESSION] Created dummy transaction for POSTPAID: "
                    f"transaction_id={transaction.id}, subscription_id={business_subscription_plan.id}"
                )

            payment_logger.log_api_request(
                endpoint="session/update",
                method="PUT",
                payload={
                    "session_id": session_id,
                    "transaction_id": str(transaction.id) if transaction else None,
                    "credimax_3ds_transaction_id": credimax_3ds_transaction_id,
                    "subscription_id": str(business_subscription_plan.id),
                    "is_postpaid": is_postpaid,
                    "transaction_amount": float(transaction.amount)
                    if transaction
                    else 0,
                },
            )

            client.update_session(
                session_id,
                transaction,
                credimax_3ds_transaction_id,
                agreement=business_subscription_plan,
            )

            session_update_response_time = (
                time.time() - session_update_start_time
            ) * 1000

            payment_logger.log_api_response(
                status_code=200,
                response_data={"status": "session_updated"},
                response_time_ms=session_update_response_time,
            )

            print("FLAG-5")

            result = {
                "session_id": session_id,
                "order_id": transaction.id if transaction else None,
                "transaction_id": credimax_3ds_transaction_id,
            }

            if transaction:
                payment_logger.log_transaction_completion(
                    final_status=transaction.status,
                    summary={
                        "type": "subscription_session_creation",
                        "session_id": session_id,
                        "transaction_id": str(transaction.id),
                        "subscription_id": str(business_subscription_plan.id),
                        "amount": float(transaction.amount),
                        "is_postpaid": is_postpaid,
                        "business_id": str(business.id),
                    },
                )
            else:
                payment_logger.log_transaction_completion(
                    final_status="NO_TRANSACTION",
                    summary={
                        "type": "subscription_session_creation",
                        "session_id": session_id,
                        "subscription_id": str(business_subscription_plan.id),
                        "is_postpaid": is_postpaid,
                        "business_id": str(business.id),
                    },
                )

            return result

        except Exception as e:
            payment_logger.log_error(
                error_type="SESSION_UPDATE_ERROR",
                error_message=str(e),
                context={
                    "session_id": session_id,
                    "transaction_id": str(transaction.id),
                    "subscription_id": str(business_subscription_plan.id),
                },
            )
            raise serializers.ValidationError(
                f"Failed to update Credimax session: {str(e)}"
            )

    def _create_free_trial_subscription(
        self,
        request,
        business,
        subscription_plan,
        is_auto_renew,
        vat_rate,
        payment_logger,
        intro_grace_days,
    ):
        """Create a free trial subscription without payment processing."""

        payment_logger.log_business_logic(
            action="CREATE_FREE_TRIAL_SUBSCRIPTION",
            data={
                "business_id": str(business.id),
                "subscription_plan_id": str(subscription_plan.id),
                "is_auto_renew": is_auto_renew,
                "vat_rate": float(vat_rate),
            },
        )

        with db_transaction.atomic():
            # Validate subscription plan is active
            if not subscription_plan.is_active:
                payment_logger.log_error(
                    error_type="INACTIVE_SUBSCRIPTION_PLAN",
                    error_message="Subscription plan is not active",
                    context={"subscription_plan_id": str(subscription_plan.id)},
                )
                raise serializers.ValidationError(
                    "This subscription plan is not active."
                )

            # Check if business already has an active subscription
            existing_active_subscription = BusinessSubscriptionPlan.objects.filter(
                business=business,
                status=SubscriptionStatusChoices.ACTIVE,
            ).first()

            if existing_active_subscription:
                payment_logger.log_error(
                    error_type="BUSINESS_ALREADY_HAS_ACTIVE_SUBSCRIPTION",
                    error_message="Business already has an active subscription",
                    context={
                        "business_id": str(business.id),
                        "existing_subscription_id": str(
                            existing_active_subscription.id
                        ),
                        "existing_subscription_name": existing_active_subscription.subscription_plan.name,
                    },
                )
                raise serializers.ValidationError(
                    f"Business already has an active subscription: {existing_active_subscription.subscription_plan.name}"
                )

            (
                start_date,
                expiry_date,
                next_billing_date,
            ) = self._compute_initial_subscription_dates(
                subscription_plan, intro_grace_days
            )

            payment_logger.log_business_logic(
                action="CALCULATE_FREE_TRIAL_DATES",
                data={
                    "start_date": start_date.isoformat(),
                    "expiry_date": expiry_date.isoformat(),
                    "duration_months": subscription_plan.duration,
                    "intro_grace_days": intro_grace_days,
                    "next_billing_date": next_billing_date.isoformat()
                    if next_billing_date
                    else None,
                },
            )
            logger.info(
                f"[GRACE_PERIOD] Free trial dates calculated: grace_days={intro_grace_days}, "
                f"expiry_date={expiry_date}, next_billing_date={next_billing_date}"
            )

            # Create the business subscription plan
            business_subscription_plan = BusinessSubscriptionPlan.objects.create(
                business=business,
                subscription_plan=subscription_plan,
                subscription_name=subscription_plan.name,
                start_date=start_date,
                expiry_date=expiry_date,
                billing_frequency=subscription_plan.billing_frequency,
                payment_interval=subscription_plan.payment_interval,
                payment_amount_variability=subscription_plan.payment_amount_variability,
                subscription_fee=Decimal("0.00"),  # Free trial has no fee
                next_billing_date=next_billing_date,
                intro_grace_period_days=intro_grace_days,
                intro_grace_applied=bool(intro_grace_days),
                status=SubscriptionStatusChoices.TRIALING,
                payment_type=SubscriptionPaymentTypeChoices.FREE_TRIAL,
                pro_rata_rate=subscription_plan.pro_rata_rate,
                commission_rate=subscription_plan.commission_rate,
                features=subscription_plan.features or [],
                is_auto_renew=is_auto_renew,
                created_by=request.user,
            )
            print("FLAG-CREATED-FREE-TRIAL-BUSINESS-SUBSCRIPTION")

            # IMPORTANT: For FREE_TRIAL subscriptions, mark grace immediately since they don't require payment
            # Free trial subscriptions are activated immediately upon creation (status = TRIALING)
            # So it's safe to mark business as having received grace here
            if intro_grace_days:
                business.has_received_intro_grace = True
                if hasattr(business, "intro_grace_consumed_on"):
                    business.intro_grace_consumed_on = timezone.now().date()
                    business.save(
                        update_fields=[
                            "has_received_intro_grace",
                            "intro_grace_consumed_on",
                        ]
                    )
                else:
                    business.save(update_fields=["has_received_intro_grace"])

                logger.info(
                    f"[GRACE_PERIOD] Free trial subscription - marked business as having received grace: "
                    f"business_id={business.id}, grace_days={intro_grace_days}"
                )

                logger.info(
                    f"[GRACE_PERIOD] Free trial subscription created with grace: id={business_subscription_plan.id}, "
                    f"grace_days={intro_grace_days}, expiry_date={expiry_date}"
                )

            payment_logger.log_business_logic(
                action="FREE_TRIAL_SUBSCRIPTION_CREATED",
                data={
                    "subscription_id": str(business_subscription_plan.id),
                    "subscription_name": business_subscription_plan.subscription_name,
                    "status": business_subscription_plan.status,
                    "payment_type": business_subscription_plan.payment_type,
                    "start_date": business_subscription_plan.start_date.isoformat(),
                    "expiry_date": business_subscription_plan.expiry_date.isoformat(),
                },
            )

            # Create a zero-amount transaction record for audit purposes
            transaction = Transaction.objects.create(
                from_business=business,
                to_business=business,
                amount=Decimal("0.00"),
                additional_fee=Decimal("0.00"),
                transaction_type=TransactionType.PAYMENT,
                transfer_via=TransferVia.ORGANIZATION_ADMIN,  # Mark as admin-initiated
                status=TransactionStatus.SUCCESS,  # Directly mark as successful
                log_details=f"Free trial subscription activated for {business.name} - Plan: {subscription_plan.name}",
                created_by=request.user,
                business_subscription=business_subscription_plan,
            )
            print("FLAG-CREATED-FREE-TRIAL-TRANSACTION")

            payment_logger.log_business_logic(
                action="FREE_TRIAL_TRANSACTION_CREATED",
                data={
                    "transaction_id": str(transaction.id),
                    "subscription_id": str(business_subscription_plan.id),
                    "amount": float(transaction.amount),
                    "status": transaction.status,
                    "transfer_via": transaction.transfer_via,
                },
            )

            result = {
                "subscription_id": business_subscription_plan.id,
                "transaction_id": transaction.id,
                "message": f"Free trial subscription '{subscription_plan.name}' activated successfully",
                "expiry_date": business_subscription_plan.expiry_date,
                "is_auto_renew": business_subscription_plan.is_auto_renew,
                "is_free_trial": True,
            }

            payment_logger.log_transaction_completion(
                final_status=transaction.status,
                summary={
                    "type": "free_trial_subscription",
                    "subscription_id": str(business_subscription_plan.id),
                    "transaction_id": str(transaction.id),
                    "business_id": str(business.id),
                },
            )

            return result

    def _get_intro_grace_days(
        self, business, subscription_plan, refresh_business=False
    ):
        """
        Return grace days to apply for the first billing cycle.

        Rules:
        - Admin sets grace on the subscription plan.
        - Applied only if the business has never received it before.

        Args:
            business: BusinessAccount instance
            subscription_plan: SubscriptionPlan instance
            refresh_business: If True, refresh business from DB (default: False for performance)
        """
        # Fast check: subscription plan grace days first (no DB query)
        grace_days = getattr(subscription_plan, "intro_grace_period_days", 0) or 0
        if grace_days <= 0:
            return 0

        # IMPORTANT: Always refresh business from DB to get the latest has_received_intro_grace value
        # This ensures we don't use stale data, especially important for new subscriptions
        # where the business object might have been loaded before grace was applied elsewhere
        try:
            business.refresh_from_db(fields=["has_received_intro_grace"])
        except Exception:
            # If refresh fails (e.g., business not saved yet), use in-memory value
            pass

        # Check business state - ensure we have the latest value from DB
        if getattr(business, "has_received_intro_grace", False):
            logger.info(
                f"[GRACE_PERIOD] Business {business.id} already received grace period, skipping"
            )
            return 0

        logger.info(
            f"[GRACE_PERIOD] Business {business.id} eligible for grace period: {grace_days} days"
        )
        return grace_days

    def _compute_initial_subscription_dates(self, subscription_plan, intro_grace_days):
        """
        Calculate start, expiry, and first billing date with optional grace days.

        Expiry date calculation:
        - Monthly plans (duration=1): start_date + 30 days - 1 day = 30 days of access
          Example: Nov 18, 2025 → Dec 17, 2025 (user can access until Dec 17, 11:59 PM)
        - Yearly plans (duration=12): start_date + 365 days - 1 day = 365 days of access
          Example: Nov 18, 2025 → Nov 17, 2026 (user can access until Nov 17, 11:59 PM)
        - Other durations: duration * 30 days - 1 day

        The expiry_date is set to the last day the user can access the service.
        On the day after expiry_date, the subscription expires.

        Args:
            subscription_plan: SubscriptionPlan instance with duration in months
            intro_grace_days: Optional grace days to add to expiry

        Returns:
            tuple: (start_date, expiry_date, next_billing_date)
        """
        start_date = timezone.now().date()

        # Calculate duration in days based on subscription plan duration
        # Monthly plans get exactly 30 days, yearly plans get exactly 365 days
        if subscription_plan.duration == 1:
            # Monthly subscription: 30 days
            duration_in_days = 30
        elif subscription_plan.duration == 12:
            # Yearly subscription: 365 days
            duration_in_days = 365
        else:
            # For other durations, calculate as 30 days per month
            duration_in_days = subscription_plan.duration * 30

        # Calculate expiry date: start_date + duration - 1 day
        # This ensures users get exactly duration_in_days of access (from start_date to expiry_date inclusive)
        # The subscription expires on the day after expiry_date
        expiry_date = start_date + timedelta(days=duration_in_days - 1)

        # Add intro grace days if provided
        if intro_grace_days:
            expiry_date = expiry_date + timedelta(days=intro_grace_days)

        # Calculate next_billing_date based on billing frequency
        # IMPORTANT: next_billing_date should be the LAST DAY of access for the first billing cycle
        if (
            subscription_plan.billing_frequency
            == SubscriptionBillingFrequencyChoices.MONTHLY
        ):
            # For monthly billing with grace period:
            # First month ends: start_date + 30 days = last day of first month (day 30)
            # With grace: add grace days to get the last day of access for first billing cycle
            # Example: start_date = 2025-12-30, grace_days = 5
            # First month end: Dec 30 + 30 days = Jan 29, 2026 (day 30 from start)
            # With grace: Jan 29 + 5 days = Feb 3, 2026 (last day of access for first month)
            first_month_end = start_date + timedelta(
                days=30
            )  # Last day of first month (day 30)
            next_billing_date = first_month_end + timedelta(days=intro_grace_days or 0)
        else:
            # For yearly billing, billing happens on expiry date
            next_billing_date = expiry_date

        return start_date, expiry_date, next_billing_date

    def _mark_intro_grace_consumed(self, business):
        """
        Persist that this business already consumed the introductory grace days.
        """
        if getattr(business, "has_received_intro_grace", False):
            return

        business.has_received_intro_grace = True
        if hasattr(business, "intro_grace_consumed_on"):
            business.intro_grace_consumed_on = timezone.now().date()
            business.save(
                update_fields=["has_received_intro_grace", "intro_grace_consumed_on"]
            )
        else:
            business.save(update_fields=["has_received_intro_grace"])


class TokenizeCardSerializer(serializers.Serializer):
    """
    Serializer to:
    - Validate that the business has a pending subscription.
    - Retrieve and store the Credimax token.
    - Associate the token with the business subscription.

    Fields:
        - session_id (str): The Credimax session to retrieve token from.
    """

    session_id = serializers.CharField()

    def validate(self, data):
        request = self.context["request"]
        current_business_id = request.auth.get("current_business")
        logger.info(
            f"TOKENIZE_CARD_VALIDATE_START - business_id: {current_business_id}"
        )

        try:
            user_business = UserAssignedBusiness.objects.get(
                id=current_business_id
            ).business
            logger.info(
                f"TOKENIZE_CARD_VALIDATE_BUSINESS_FOUND - business_id: {current_business_id}"
            )
        except UserAssignedBusiness.DoesNotExist:
            logger.warning(
                f"TOKENIZE_CARD_VALIDATE_BUSINESS_NOT_FOUND - business_id: {current_business_id}"
            )
            raise serializers.ValidationError("Associated business not found.")

        # Get the most recent pending subscription for this business
        subscription = (
            BusinessSubscriptionPlan.objects.filter(
                business=user_business,
                status=SubscriptionStatusChoices.PENDING,
            )
            .order_by("-created_at")
            .first()
        )

        if not subscription:
            logger.warning(
                f"TOKENIZE_CARD_VALIDATE_NO_PENDING_SUBSCRIPTION - business_id: {current_business_id}"
            )
            raise serializers.ValidationError(
                "No subscription with pending payment found for this business."
            )

        logger.info(
            f"TOKENIZE_CARD_VALIDATE_SUBSCRIPTION_FOUND"
            f"business_id: {current_business_id}, subscription_id: {subscription.id}"
        )

        data["business"] = user_business
        data["subscription"] = subscription
        return data

    def save(self):
        request = self.context["request"]
        session_id = self.validated_data["session_id"]
        business = self.validated_data["business"]
        subscription = self.validated_data["subscription"]

        logger.info(
            f"TOKENIZE_CARD_SAVE_START - session_id: {session_id}, "
            f"business_id: {business.id}, subscription_id: {subscription.id}"
        )

        client = CredimaxClient()

        try:
            logger.info(f"TOKENIZE_CARD_CREDIMAX_CALL_START - session_id: {session_id}")
            response = client.tokenize_card(session_id)
            logger.info(
                f"TOKENIZE_CARD_CREDIMAX_CALL_SUCCESS - session_id: {session_id}, "
                f"response_keys: {list(response.keys()) if response else 'None'}"
            )
        except Exception as e:
            logger.warning(
                f"TOKENIZE_CARD_CREDIMAX_CALL_FAILED - session_id: {session_id}, "
                f"business_id: {business.id}, subscription_id: {subscription.id}, error: {str(e)}"
            )
            # Mark subscription and transaction as failed when tokenization fails
            self._mark_subscription_payment_failed(
                subscription, f"Tokenization failed: {str(e)}"
            )
            raise serializers.ValidationError(f"Tokenization failed: {str(e)}")

        # Check for errors in Credimax response (even if HTTP status was 200)
        if "error" in response:
            error_info = response.get("error", {})
            error_message = error_info.get(
                "explanation", error_info.get("message", "Tokenization failed")
            )
            logger.warning(
                f"TOKENIZE_CARD_CREDIMAX_RESPONSE_ERROR - session_id: {session_id}, "
                f"business_id: {business.id}, subscription_id: {subscription.id}, error: {error_message}"
            )
            self._mark_subscription_payment_failed(
                subscription, f"Tokenization failed: {error_message}"
            )
            raise serializers.ValidationError(f"Tokenization failed: {error_message}")

        token = response.get("token")
        card = response.get("sourceOfFunds", {}).get("provided", {}).get("card", {})

        logger.info(
            f"TOKENIZE_CARD_RESPONSE_PARSED - session_id: {session_id}, "
            f"token_present: {bool(token)}, card_brand: {card.get('brand', 'unknown')}"
        )

        # Validate card expiry date
        expiry = card.get("expiry", "")
        expiry_month = expiry[:2] if len(expiry) >= 2 else ""
        expiry_year = expiry[2:] if len(expiry) >= 4 else ""

        if expiry_month and expiry_year:
            is_valid, error_message = validate_card_expiry_date(
                expiry_month, expiry_year
            )
            if not is_valid:
                logger.warning(
                    f"TOKENIZE_CARD_EXPIRY_VALIDATION_FAILED - session_id: {session_id}, "
                    f"expiry: {expiry_month}/{expiry_year}, error: {error_message}"
                )
                self._mark_subscription_payment_failed(subscription, error_message)
                raise serializers.ValidationError({"session_id": error_message})

        if not token:
            logger.warning(
                f"TOKENIZE_CARD_NO_TOKEN_RECEIVED - session_id: {session_id}, "
                f"business_id: {business.id}, subscription_id: {subscription.id}"
            )
            # Mark subscription and transaction as failed when tokenization returns no token
            self._mark_subscription_payment_failed(
                subscription, "Tokenization failed: Unable to tokenize details."
            )
            raise serializers.ValidationError(
                "Tokenization failed: Unable to tokenize details."
            )

        # Extract card details (expiry_month and expiry_year already extracted above during validation)
        card_number = card.get("number")

        with db_transaction.atomic():
            # CRITICAL: Check for existing card by TOKEN first (token is globally unique)
            # This prevents duplicate entries even if card number format differs slightly
            existing_card_by_token = (
                BusinessSavedCardToken.objects.select_for_update()
                .filter(token=token)
                .first()
            )

            saved_card = None

            if existing_card_by_token:
                # Token already exists - check if it belongs to the same business
                if existing_card_by_token.business != business:
                    raise serializers.ValidationError(
                        {
                            "session_id": "This card token is already registered with another business."
                        }
                    )

                # Token exists for same business - update it instead of creating duplicate
                saved_card = existing_card_by_token
                saved_card.number = card_number or saved_card.number
                saved_card.expiry_month = expiry_month or saved_card.expiry_month
                saved_card.expiry_year = expiry_year or saved_card.expiry_year
                saved_card.card_type = card.get("fundingMethod", saved_card.card_type)
                saved_card.card_brand = card.get("brand", saved_card.card_brand)
                # Update updated_by if available
                if hasattr(saved_card, "updated_by"):
                    saved_card.updated_by = request.user
                saved_card.save()
            else:
                # Token doesn't exist - check for duplicate by card number
                existing_card_by_number = None
                if card_number:
                    existing_card_by_number = (
                        BusinessSavedCardToken.objects.select_for_update()
                        .filter(
                            business=business,
                            number=card_number,
                        )
                        .first()
                    )

                if existing_card_by_number:
                    # Card number already exists for this business - update it with new token
                    saved_card = existing_card_by_number

                    # Only update token if it's different and not used by another card
                    if existing_card_by_number.token != token:
                        # Double-check token is not used elsewhere (race condition protection)
                        token_conflict = (
                            BusinessSavedCardToken.objects.filter(token=token)
                            .exclude(id=existing_card_by_number.id)
                            .exists()
                        )
                        if token_conflict:
                            raise serializers.ValidationError(
                                {
                                    "session_id": "This card token is already registered with another card."
                                }
                            )
                        saved_card.token = token

                    # Update card metadata from Credimax response
                    saved_card.number = card_number or saved_card.number
                    saved_card.expiry_month = expiry_month or saved_card.expiry_month
                    saved_card.expiry_year = expiry_year or saved_card.expiry_year
                    saved_card.card_type = card.get(
                        "fundingMethod", saved_card.card_type
                    )
                    saved_card.card_brand = card.get("brand", saved_card.card_brand)
                    # Update updated_by if available
                    if hasattr(saved_card, "updated_by"):
                        saved_card.updated_by = request.user
                    saved_card.save()
                else:
                    # New card - ensure token is not used elsewhere (final safety check)
                    token_conflict = BusinessSavedCardToken.objects.filter(
                        token=token
                    ).exists()
                    if token_conflict:
                        raise serializers.ValidationError(
                            {
                                "session_id": "This card has already been added. Please refresh and try again."
                            }
                        )

                    # Create new card entry
                    try:
                        saved_card = BusinessSavedCardToken.objects.create(
                            business=business,
                            token=token,
                            number=card_number,
                            expiry_month=expiry_month,
                            expiry_year=expiry_year,
                            card_type=card.get("fundingMethod"),
                            card_brand=card.get("brand"),
                            is_used_for_subscription=True,
                            created_by=request.user,
                            updated_by=request.user,
                        )
                    except Exception as e:
                        # Handle database integrity errors (e.g., unique constraint violation)
                        if "token" in str(e).lower() or "unique" in str(e).lower():
                            raise serializers.ValidationError(
                                {
                                    "session_id": "This card has already been added. Please refresh and try again."
                                }
                            )
                        raise

            # CRITICAL: Unassign card token from any existing subscription first
            # This prevents OneToOne constraint violation (one card can only be assigned to one subscription)
            existing_subscription = (
                BusinessSubscriptionPlan.objects.filter(
                    business_saved_card_token=saved_card
                )
                .exclude(id=subscription.id)
                .first()
            )

            if existing_subscription:
                # Unassign from previous subscription to avoid OneToOne constraint violation
                existing_subscription.business_saved_card_token = None
                existing_subscription.save(update_fields=["business_saved_card_token"])

            # Deactivate old subscription tokens for this business (except the one we're using)
            BusinessSavedCardToken.objects.filter(
                business=business, is_used_for_subscription=True
            ).exclude(id=saved_card.id).update(is_used_for_subscription=False)

            # Ensure this card is marked as used for subscription
            if not saved_card.is_used_for_subscription:
                saved_card.is_used_for_subscription = True
                saved_card.save(update_fields=["is_used_for_subscription"])

            # Assign the card to the subscription
            try:
                subscription.business_saved_card_token = saved_card
                subscription.save(update_fields=["business_saved_card_token"])
            except Exception as e:
                # Handle database integrity errors (OneToOne constraint violation)
                if "unique" in str(e).lower() or "constraint" in str(e).lower():
                    # If still getting constraint error, try to refresh and check again
                    subscription.refresh_from_db()
                    existing_subscription = (
                        BusinessSubscriptionPlan.objects.filter(
                            business_saved_card_token=saved_card
                        )
                        .exclude(id=subscription.id)
                        .first()
                    )
                    if existing_subscription:
                        existing_subscription.business_saved_card_token = None
                        existing_subscription.save(
                            update_fields=["business_saved_card_token"]
                        )
                    # Retry assignment
                    subscription.business_saved_card_token = saved_card
                    subscription.save(update_fields=["business_saved_card_token"])
                else:
                    raise

        try:
            client.update_session_with_token(session_id, token)
        except Exception as e:
            # Mark subscription and transaction as failed when session update fails
            self._mark_subscription_payment_failed(
                subscription, f"Failed to update session with token: {str(e)}"
            )
            raise serializers.ValidationError(
                f"Failed to update session with token: {str(e)}"
            )

    def _mark_subscription_payment_failed(self, subscription, error_message):
        """
        Mark subscription and associated transaction as failed when tokenization fails.

        Args:
            subscription: BusinessSubscriptionPlan instance
            error_message: Error message describing the failure
        """
        logger.info(
            f"TOKENIZE_CARD_MARK_FAILED_START - subscription_id: {subscription.id}, "
            f"business_id: {subscription.business.id}, error: {error_message}"
        )

        try:
            with db_transaction.atomic():
                # Mark subscription as failed
                subscription.status = SubscriptionStatusChoices.FAILED
                subscription.save(update_fields=["status"])
                logger.info(
                    f"TOKENIZE_CARD_SUBSCRIPTION_MARKED_FAILED - subscription_id: {subscription.id}"
                )

                # Find and mark associated pending transaction as failed
                pending_transaction = Transaction.objects.filter(
                    business_subscription=subscription, status=TransactionStatus.PENDING
                ).first()

                if pending_transaction:
                    pending_transaction.status = TransactionStatus.FAILED
                    pending_transaction.remark = error_message
                    pending_transaction.save(update_fields=["status", "remark"])
                    logger.info(
                        f"TOKENIZE_CARD_TRANSACTION_MARKED_FAILED - subscription_id: {subscription.id}, "
                        f"transaction_id: {pending_transaction.id}"
                    )
                else:
                    logger.warning(
                        f"TOKENIZE_CARD_NO_PENDING_TRANSACTION - subscription_id: {subscription.id}"
                    )

                # If the subscription has a BusinessSavedCardToken and payment failed,
                # mark the card as not used for subscription
                if subscription.business_saved_card_token:
                    card_token = subscription.business_saved_card_token
                    if card_token.is_used_for_subscription:
                        card_token.is_used_for_subscription = False
                        card_token.save(update_fields=["is_used_for_subscription"])
                        logger.info(
                            f"TOKENIZE_CARD_TOKEN_DEACTIVATED - subscription_id: {subscription.id}, "
                            f"token_id: {card_token.id}"
                        )
                    else:
                        logger.info(
                            f"TOKENIZE_CARD_TOKEN_ALREADY_INACTIVE - subscription_id: {subscription.id}, "
                            f"token_id: {card_token.id}"
                        )
                else:
                    logger.info(
                        f"TOKENIZE_CARD_NO_TOKEN_TO_DEACTIVATE - subscription_id: {subscription.id}"
                    )

                logger.warning(
                    f"TOKENIZE_CARD_PAYMENT_FAILED_COMPLETE - subscription_id: {subscription.id}, "
                    f"business_id: {subscription.business.id}, "
                    f"transaction_id: {pending_transaction.id if pending_transaction else 'None'}, "
                    f"error: {error_message}"
                )

        except Exception as e:
            logger.exception(
                f"TOKENIZE_CARD_MARK_FAILED_ERROR - subscription_id: {subscription.id}, "
                f"business_id: {subscription.business.id}, "
                f"marking_error: {str(e)}, original_error: {error_message}"
            )


class CustomerInitiatedPaymentSerializer(serializers.Serializer):
    """
    Serializer to:
    - Validate the transaction and business.
    - Execute the payment via Credimax using saved token.
    - Update subscription and transaction statuses.

    Fields:
        - session_id (str): Credimax session ID.
        - order_id (UUID): Internal transaction ID.

    Returns:
        - detail (str): Human-readable result.
        - status_code (int): HTTP status to return.
    """

    session_id = serializers.CharField()
    order_id = serializers.CharField()

    def validate(self, data):
        request = self.context["request"]
        current_business_id = request.auth.get("current_business")
        try:
            user_business = UserAssignedBusiness.objects.get(id=current_business_id)
        except UserAssignedBusiness.DoesNotExist:
            raise serializers.ValidationError("Associated business not found.")

        order_id = data.get("order_id")
        try:
            transaction_obj = Transaction.objects.get(id=order_id)
        except Transaction.DoesNotExist:
            raise serializers.ValidationError("Transaction not found.")

        data["business"] = user_business
        data["transaction"] = transaction_obj
        return data

    def save(self):
        business = self.validated_data["business"]
        session_id = self.validated_data["session_id"]
        transaction = self.validated_data["transaction"]
        organization = business.business.organization_id

        # Initialize payment logger with transaction ID
        payment_logger = get_credimax_logger(
            str(transaction.id), business_id=str(business.business.id)
        )

        payment_logger.log_transaction_start(
            transaction_type="CUSTOMER_INITIATED_PAYMENT",
            business_id=str(business.business.id),
            amount=float(transaction.amount),
            additional_data={
                "session_id": session_id,
                "transaction_id": str(transaction.id),
                "subscription_id": (
                    str(transaction.business_subscription.id)
                    if transaction.business_subscription
                    else None
                ),
                "business_name": business.business.name,
                "user_id": str(self.context["request"].user.id),
            },
        )

        business_subscription_plan = self.get_business_subscription_details(business)
        print("--> business_subscription_plan", business_subscription_plan)

        payment_logger.log_business_logic(
            action="GET_BUSINESS_SUBSCRIPTION_DETAILS",
            data={
                "business_id": str(business.business.id),
                "subscription_found": business_subscription_plan is not None,
                "subscription_id": (
                    str(business_subscription_plan.id)
                    if business_subscription_plan
                    else None
                ),
                "subscription_status": (
                    business_subscription_plan.status
                    if business_subscription_plan
                    else None
                ),
            },
        )

        client = CredimaxClient()
        # Calculate total amount: base amount + VAT amount
        total_amount = Decimal(transaction.amount) + Decimal(transaction.vat or 0)

        payment_logger.log_business_logic(
            action="CALCULATE_TOTAL_AMOUNT",
            data={
                "base_amount": float(transaction.amount),
                "vat_amount": float(transaction.vat or 0),
                "total_amount": float(total_amount),
            },
        )

        if (
            not business_subscription_plan
            or not business_subscription_plan.business_saved_card_token
        ):
            payment_logger.log_error(
                error_type="MISSING_SUBSCRIPTION_OR_TOKEN",
                error_message="No active subscription or saved card token found",
                context={
                    "business_id": str(business.business.id),
                    "subscription_exists": business_subscription_plan is not None,
                    "token_exists": (
                        business_subscription_plan.business_saved_card_token is not None
                        if business_subscription_plan
                        else False
                    ),
                },
            )
            raise serializers.ValidationError(
                "No active subscription or saved card token found."
            )

        # Check payment type: POSTPAID subscriptions should go through full Credimax process
        # but with amount = 0 to store card details and agreement without charging
        try:
            payment_type = business_subscription_plan.payment_type
            is_postpaid = payment_type == SubscriptionPaymentTypeChoices.POSTPAID

            payment_logger.log_business_logic(
                action="CHECK_PAYMENT_TYPE",
                data={
                    "payment_type": payment_type,
                    "is_postpaid": is_postpaid,
                    "subscription_id": str(business_subscription_plan.id),
                },
            )
            logger.info(
                f"[CUSTOMER_INITIATED_PAYMENT] Payment type check: "
                f"subscription_id={business_subscription_plan.id}, "
                f"payment_type={payment_type}, is_postpaid={is_postpaid}"
            )
        except Exception as e:
            logger.error(
                f"[CUSTOMER_INITIATED_PAYMENT] Error checking payment type: {e}",
                exc_info=True,
            )
            # Default to PREPAID if error occurs
            payment_type = SubscriptionPaymentTypeChoices.PREPAID
            is_postpaid = False

        # For POSTPAID: Process payment with amount = 0 to go through Credimax flow
        # This allows Credimax to store card details and create agreement
        # Actual payment will be processed later during recurring payment task
        try:
            payment_amount = Decimal("0.00") if is_postpaid else total_amount

            if is_postpaid:
                payment_logger.log_business_logic(
                    action="PROCESS_POSTPAID_WITH_ZERO_AMOUNT",
                    data={
                        "subscription_id": str(business_subscription_plan.id),
                        "business_id": str(business.business.id),
                        "original_amount": float(total_amount),
                        "payment_amount": float(payment_amount),
                        "reason": "POSTPAID subscriptions go through Credimax with 0 amount to store card and agreement. Payment will be processed during recurring payment.",
                    },
                )
                logger.info(
                    f"[CUSTOMER_INITIATED_PAYMENT] POSTPAID subscription detected: "
                    f"subscription_id={business_subscription_plan.id}, "
                    f"original_amount={total_amount}, payment_amount={payment_amount}"
                )
            else:
                logger.info(
                    f"[CUSTOMER_INITIATED_PAYMENT] PREPAID subscription: "
                    f"subscription_id={business_subscription_plan.id}, "
                    f"payment_amount={payment_amount}"
                )
        except Exception as e:
            logger.error(
                f"[CUSTOMER_INITIATED_PAYMENT] Error calculating payment amount: {e}",
                exc_info=True,
            )
            # Fallback to total_amount if error occurs
            payment_amount = total_amount
            is_postpaid = False

        # Execute payment for all payment types (POSTPAID uses amount = 0)
        # This ensures Credimax processes the payment, stores card details, and creates agreement
        try:
            payment_start_time = time.time()

            payment_logger.log_api_request(
                endpoint="payment/cit",
                method="POST",
                payload={
                    "session_id": session_id,
                    "amount": float(payment_amount),
                    "original_amount": float(total_amount) if is_postpaid else None,
                    "transaction_id": str(transaction.id),
                    "subscription_id": str(business_subscription_plan.id),
                    "token_exists": True,
                    "payment_type": payment_type,
                    "is_postpaid": is_postpaid,
                },
            )

            cit_payload, cit_payment_response = client.make_cit_payment(
                session_id=session_id,
                agreement=business_subscription_plan,
                order=transaction,
                amount=payment_amount,  # Use 0.00 for POSTPAID, total_amount for PREPAID
                token=business_subscription_plan.business_saved_card_token.token,
            )

            payment_response_time = (time.time() - payment_start_time) * 1000

            payment_logger.log_api_response(
                status_code=200,
                response_data=cit_payment_response,
                response_time_ms=payment_response_time,
            )

            logger.debug(f"Payment response received for transaction {transaction.id}")
            logger.info(
                f"[CUSTOMER_INITIATED_PAYMENT] Credimax API response received: "
                f"transaction_id={transaction.id}, "
                f"subscription_id={business_subscription_plan.id}, "
                f"is_postpaid={is_postpaid}, "
                f"payment_amount={payment_amount}, "
                f"result={cit_payment_response.get('result')}"
            )

            # Check for error in response even if HTTP status was 200
            if "error" in cit_payment_response:
                error_info = cit_payment_response.get("error", {})
                error_message = error_info.get(
                    "explanation",
                    error_info.get("message", "Payment processing error"),
                )
                error_cause = error_info.get("cause", "UNKNOWN_ERROR")

                # Mark transaction and subscription as failed
                transaction.status = TransactionStatus.FAILED
                business_subscription_plan.status = SubscriptionStatusChoices.FAILED
                transaction.remark = f"Credimax Error: {error_message}"
                transaction.save()
                business_subscription_plan.save()

                payment_logger.log_error(
                    error_type="CREDIMAX_API_ERROR",
                    error_message=error_message,
                    context={
                        "transaction_id": str(transaction.id),
                        "subscription_id": str(business_subscription_plan.id),
                        "error_cause": error_cause,
                        "session_id": session_id,
                    },
                )

                payment_logger.log_transaction_update(
                    old_status=TransactionStatus.PENDING,
                    new_status=TransactionStatus.FAILED,
                    reason=f"Credimax API error: {error_message}",
                )

                logger.error(
                    f"[CUSTOMER_INITIATED_PAYMENT] Credimax API error: "
                    f"transaction_id={transaction.id}, "
                    f"subscription_id={business_subscription_plan.id}, "
                    f"is_postpaid={is_postpaid}, "
                    f"error_message={error_message}, "
                    f"error_cause={error_cause}"
                )

                raise serializers.ValidationError(f"Payment failed: {error_message}")

        except serializers.ValidationError:
            # Re-raise validation errors as-is
            raise
        except Exception as e:
            try:
                payment_logger.log_error(
                    error_type="PAYMENT_EXECUTION_ERROR",
                    error_message=str(e),
                    context={
                        "session_id": session_id,
                        "transaction_id": str(transaction.id),
                        "subscription_id": (
                            str(business_subscription_plan.id)
                            if business_subscription_plan
                            else None
                        ),
                        "amount": float(total_amount),
                        "payment_amount": float(payment_amount)
                        if "payment_amount" in locals()
                        else None,
                        "is_postpaid": is_postpaid
                        if "is_postpaid" in locals()
                        else False,
                    },
                )
            except Exception as log_error:
                logger.error(
                    f"[CUSTOMER_INITIATED_PAYMENT] Failed to log payment error: {log_error}",
                    exc_info=True,
                )

            logger.error(
                f"[CUSTOMER_INITIATED_PAYMENT] Payment execution error: "
                f"transaction_id={transaction.id}, "
                f"subscription_id={business_subscription_plan.id if business_subscription_plan else None}, "
                f"is_postpaid={is_postpaid if 'is_postpaid' in locals() else False}, "
                f"error={str(e)}",
                exc_info=True,
            )

            try:
                transaction.status = TransactionStatus.FAILED
                business_subscription_plan.status = SubscriptionStatusChoices.FAILED
                transaction.remark = f"Payment processing error: {str(e)}"
                transaction.save()
                business_subscription_plan.save()
            except Exception as save_error:
                logger.error(
                    f"[CUSTOMER_INITIATED_PAYMENT] Failed to save transaction/subscription status: {save_error}",
                    exc_info=True,
                )

            try:
                payment_logger.log_transaction_update(
                    old_status=TransactionStatus.PENDING,
                    new_status=TransactionStatus.FAILED,
                    reason=f"Payment execution failed: {str(e)}",
                )
            except Exception as log_error:
                logger.error(
                    f"[CUSTOMER_INITIATED_PAYMENT] Failed to log transaction update: {log_error}",
                    exc_info=True,
                )

            raise serializers.ValidationError(f"Payment failed: {str(e)}")

        # Process payment response for all payment types
        try:
            is_successful = None
            api_operation = cit_payload.get("apiOperation") if cit_payload else None

            payment_logger.log_business_logic(
                action="PROCESS_PAYMENT_RESPONSE",
                data={
                    "api_operation": api_operation,
                    "payment_result": cit_payment_response.get("result"),
                    "order_status": cit_payment_response.get("order", {}).get("status"),
                    "is_postpaid": is_postpaid,
                    "payment_amount": float(payment_amount),
                },
            )
            logger.info(
                f"[CUSTOMER_INITIATED_PAYMENT] Processing payment response: "
                f"transaction_id={transaction.id}, "
                f"api_operation={api_operation}, "
                f"is_postpaid={is_postpaid}, "
                f"payment_amount={payment_amount}"
            )

            failure_reason = None
            card_type = None

            # Extract card information for better error handling
            try:
                source_of_funds = cit_payment_response.get("sourceOfFunds", {})
                if source_of_funds.get("provided", {}).get("card"):
                    card_info = source_of_funds["provided"]["card"]
                    card_type = card_info.get("fundingMethod", "UNKNOWN")
            except Exception as card_error:
                logger.warning(
                    f"[CUSTOMER_INITIATED_PAYMENT] Failed to extract card info: {card_error}"
                )
                card_type = "UNKNOWN"

            if api_operation == "VERIFY":
                is_successful = (
                    cit_payment_response.get("result") == "SUCCESS"
                    and cit_payment_response.get("order", {}).get("status")
                    == "VERIFIED"
                )
            elif api_operation == "PAY":
                is_successful = (
                    cit_payment_response.get("result") == "SUCCESS"
                    and cit_payment_response.get("order", {}).get("status")
                    == "CAPTURED"
                )
            else:
                logger.warning(
                    f"[CUSTOMER_INITIATED_PAYMENT] Unknown API operation: {api_operation}"
                )
                is_successful = False

            logger.info(
                f"[CUSTOMER_INITIATED_PAYMENT] Payment success determination: "
                f"transaction_id={transaction.id}, "
                f"is_successful={is_successful}, "
                f"api_operation={api_operation}, "
                f"is_postpaid={is_postpaid}"
            )
        except Exception as e:
            logger.error(
                f"[CUSTOMER_INITIATED_PAYMENT] Error processing payment response: {e}",
                exc_info=True,
            )
            is_successful = False
            failure_reason = f"Error processing payment response: {str(e)}"
            card_type = None
            api_operation = None

        # Enhanced failure analysis for DEBIT cards
        if not is_successful:
            failure_reason = self._analyze_payment_failure(
                cit_payment_response, card_type
            )
        else:
            print(
                f"FLAG - Payment response status: {is_successful} received for apiOperation{api_operation}, card_type: {card_type}, failure_reason: {failure_reason}"
            )

        payment_logger.log_business_logic(
            action="DETERMINE_PAYMENT_SUCCESS",
            data={
                "is_successful": is_successful,
                "api_operation": api_operation,
                "payment_result": cit_payment_response.get("result"),
                "order_status": cit_payment_response.get("order", {}).get("status"),
            },
        )

        # Handle success or failure update and logging
        try:
            if is_successful:
                old_transaction_status = transaction.status
                old_subscription_status = business_subscription_plan.status

                # Apply grace period if not already applied and business is eligible
                # OPTIMIZED: Fast path - check subscription plan grace days first (no DB query)
                subscription_plan = business_subscription_plan.subscription_plan
                plan_grace_days = (
                    (getattr(subscription_plan, "intro_grace_period_days", 0) or 0)
                    if subscription_plan
                    else 0
                )

                if (
                    not business_subscription_plan.intro_grace_applied
                    and subscription_plan
                    and plan_grace_days > 0
                ):
                    # CRITICAL: Check business.has_received_intro_grace, not subscription.intro_grace_applied
                    # The business flag indicates if the business has EVER received grace period
                    # This prevents applying grace period multiple times when buying new plans
                    business_obj = business.business
                    # Refresh business to get latest has_received_intro_grace value from DB
                    try:
                        business_obj.refresh_from_db(
                            fields=["has_received_intro_grace"]
                        )
                    except Exception:
                        pass

                    business_has_received_grace = getattr(
                        business_obj, "has_received_intro_grace", False
                    )

                    logger.info(
                        f"[GRACE_PERIOD] Checking grace eligibility during activation: "
                        f"subscription_id={business_subscription_plan.id}, "
                        f"plan_grace_days={plan_grace_days}, "
                        f"business_has_received_grace={business_has_received_grace}, "
                        f"subscription_grace_applied={business_subscription_plan.intro_grace_applied}"
                    )

                    if not business_has_received_grace:
                        # Calculate grace days - refresh business to get latest has_received_intro_grace value
                        intro_grace_days = self._get_intro_grace_days(
                            business_obj, subscription_plan, refresh_business=True
                        )
                        if intro_grace_days > 0:
                            # Calculate new expiry date with grace days from existing start_date
                            start_date = business_subscription_plan.start_date
                            base_expiry = start_date + relativedelta(
                                months=subscription_plan.duration
                            )
                            # Subtract 1 day so expiry_date is the last day user can use the app
                            base_expiry = base_expiry - timedelta(days=1)
                            expiry_date = base_expiry + relativedelta(
                                days=intro_grace_days
                            )

                            # Calculate next_billing_date based on billing frequency
                            # IMPORTANT: next_billing_date should be the LAST DAY of access for the first billing cycle
                            if (
                                subscription_plan.billing_frequency
                                == SubscriptionBillingFrequencyChoices.MONTHLY
                            ):
                                # For monthly billing with grace period:
                                # First month ends: start_date + 30 days = last day of first month (day 30)
                                # With grace: add grace days to get the last day of access for first billing cycle
                                # Example: start_date = 2025-12-30, grace_days = 5
                                # First month end: Dec 30 + 30 days = Jan 29, 2026 (day 30 from start)
                                # With grace: Jan 29 + 5 days = Feb 3, 2026 (last day of access for first month)
                                start_date = business_subscription_plan.start_date
                                first_month_end = start_date + timedelta(
                                    days=30
                                )  # Last day of first month (day 30)
                                next_billing_date = first_month_end + timedelta(
                                    days=intro_grace_days or 0
                                )
                            else:
                                # For yearly billing, billing happens on expiry date
                                next_billing_date = expiry_date

                            # Batch updates: update subscription and mark business in one go
                            business_subscription_plan.expiry_date = expiry_date
                            business_subscription_plan.next_billing_date = (
                                next_billing_date
                            )
                            business_subscription_plan.intro_grace_period_days = (
                                intro_grace_days
                            )
                            business_subscription_plan.intro_grace_applied = True

                            # IMPORTANT: Mark business grace as consumed ONLY when subscription is activated
                            # This ensures grace is only marked after successful payment
                            # Save business grace status immediately
                            business_obj.has_received_intro_grace = True
                            if hasattr(business_obj, "intro_grace_consumed_on"):
                                business_obj.intro_grace_consumed_on = (
                                    timezone.now().date()
                                )
                                business_obj.save(
                                    update_fields=[
                                        "has_received_intro_grace",
                                        "intro_grace_consumed_on",
                                    ]
                                )
                            else:
                                business_obj.save(
                                    update_fields=["has_received_intro_grace"]
                                )

                            logger.info(
                                f"[GRACE_PERIOD] Applied grace during activation: "
                                f"subscription_id={business_subscription_plan.id}, "
                                f"grace_days={intro_grace_days}, "
                                f"expiry_date={expiry_date}, "
                                f"next_billing_date={next_billing_date}, "
                                f"business_id={business_obj.id}, "
                                f"business_marked_as_received_grace=True"
                            )
                        else:
                            logger.info(
                                f"[GRACE_PERIOD] Grace not applied: intro_grace_days={intro_grace_days} "
                                f"for subscription_id={business_subscription_plan.id}"
                            )
                    else:
                        # Business already received grace (has_received_intro_grace = True)
                        # But check if subscription has grace applied - if so, log it
                        if (
                            business_subscription_plan.intro_grace_applied
                            and business_subscription_plan.intro_grace_period_days
                            and business_subscription_plan.intro_grace_period_days > 0
                        ):
                            logger.info(
                                f"[GRACE_PERIOD] Business already received grace, subscription has grace applied: "
                                f"subscription_id={business_subscription_plan.id}, "
                                f"grace_days={business_subscription_plan.intro_grace_period_days}"
                            )
                        else:
                            logger.info(
                                f"[GRACE_PERIOD] Business already received grace, skipping for "
                                f"subscription_id={business_subscription_plan.id}"
                            )

                elif subscription_plan and plan_grace_days == 0:
                    logger.info(
                        f"[GRACE_PERIOD] Plan has no grace days configured: "
                        f"subscription_id={business_subscription_plan.id}, plan_id={subscription_plan.id}"
                    )
                elif business_subscription_plan.intro_grace_applied:
                    logger.info(
                        f"[GRACE_PERIOD] Grace already applied to subscription: "
                        f"subscription_id={business_subscription_plan.id}"
                    )

                # CRITICAL: Always check if subscription has grace applied but business flag wasn't set
                # This handles the case where grace was applied during creation but business flag wasn't updated
                # This check runs AFTER all grace application logic, regardless of which path was taken
                # Get business object and refresh to get latest has_received_intro_grace value
                business_obj = business.business
                try:
                    business_obj.refresh_from_db(fields=["has_received_intro_grace"])
                except Exception:
                    pass

                if (
                    business_subscription_plan.intro_grace_applied
                    and business_subscription_plan.intro_grace_period_days
                    and business_subscription_plan.intro_grace_period_days > 0
                    and not business_obj.has_received_intro_grace
                ):
                    # Grace was applied to subscription but business flag wasn't set - fix it now
                    business_obj.has_received_intro_grace = True
                    if hasattr(business_obj, "intro_grace_consumed_on"):
                        business_obj.intro_grace_consumed_on = timezone.now().date()
                        business_obj.save(
                            update_fields=[
                                "has_received_intro_grace",
                                "intro_grace_consumed_on",
                            ]
                        )
                    else:
                        business_obj.save(update_fields=["has_received_intro_grace"])
                    logger.info(
                        f"[GRACE_PERIOD] Fixed missing business grace flag during activation: "
                        f"subscription_id={business_subscription_plan.id}, "
                        f"business_id={business_obj.id}, "
                        f"grace_days={business_subscription_plan.intro_grace_period_days}"
                    )

                transaction.status = TransactionStatus.SUCCESS
                business_subscription_plan.status = SubscriptionStatusChoices.ACTIVE
                payment_status = WebhookCallStatus.SUCCESS
                status_code = status.HTTP_200_OK

                # For POSTPAID: Add remark indicating no payment was made at purchase
                if is_postpaid:
                    transaction.remark = "POSTPAID subscription activated. Payment will be processed during recurring billing cycle."
                    title = "Subscription activated successfully. Invoice sent. Payment will be processed during recurring billing."
                    logger.info(
                        f"[CUSTOMER_INITIATED_PAYMENT] POSTPAID subscription activated successfully: "
                        f"transaction_id={transaction.id}, "
                        f"subscription_id={business_subscription_plan.id}, "
                        f"payment_amount={payment_amount}"
                    )
                else:
                    title = "Subscription payment successful."
                    logger.info(
                        f"[CUSTOMER_INITIATED_PAYMENT] PREPAID subscription payment successful: "
                        f"transaction_id={transaction.id}, "
                        f"subscription_id={business_subscription_plan.id}, "
                        f"payment_amount={payment_amount}"
                    )

                payment_logger.log_transaction_update(
                    old_status=old_transaction_status,
                    new_status=TransactionStatus.SUCCESS,
                    reason="Payment successful",
                    additional_data={
                        "subscription_old_status": old_subscription_status,
                        "subscription_new_status": SubscriptionStatusChoices.ACTIVE,
                        "api_operation": api_operation,
                    },
                )
            else:
                old_transaction_status = transaction.status
                old_subscription_status = business_subscription_plan.status

                transaction.status = TransactionStatus.FAILED
                business_subscription_plan.status = SubscriptionStatusChoices.FAILED
                payment_status = WebhookCallStatus.FAILURE
                status_code = status.HTTP_402_PAYMENT_REQUIRED

                # Enhanced error message based on failure analysis
                if failure_reason:
                    title = failure_reason
                    # Store failure reason in transaction remark
                    transaction.remark = failure_reason
                    # Add retry suggestion for DEBIT card failures
                    if card_type == "DEBIT" and self._should_retry_with_different_card(
                        cit_payment_response, card_type
                    ):
                        title += " We recommend trying with a CREDIT card for better success rates."
                else:
                    title = (
                        cit_payment_response.get("response", {}).get("acquirerMessage")
                        or "Subscription payment failed. Please try again, or contact our support team for further assistance."
                    )
                    # Store generic failure reason in transaction remark
                    transaction.remark = title

                payment_logger.log_transaction_update(
                    old_status=old_transaction_status,
                    new_status=TransactionStatus.FAILED,
                    reason="Payment failed",
                    additional_data={
                        "subscription_old_status": old_subscription_status,
                        "subscription_new_status": SubscriptionStatusChoices.FAILED,
                        "api_operation": api_operation,
                        "acquirer_message": cit_payment_response.get(
                            "response", {}
                        ).get("acquirerMessage"),
                    },
                )

            # Batch save: transaction and subscription together for better performance
            transaction.save()

            # Save subscription (business grace status is already saved above when grace was applied)
            subscription_update_fields = ["status"]
            if business_subscription_plan.intro_grace_applied:
                subscription_update_fields.extend(
                    [
                        "expiry_date",
                        "next_billing_date",
                        "intro_grace_period_days",
                        "intro_grace_applied",
                    ]
                )
                # Note: Business grace status was already saved when grace was applied above
                # No need to save again here

            business_subscription_plan.save(update_fields=subscription_update_fields)

            # Record webhook for all payment types (POSTPAID goes through Credimax with 0 amount)
            try:
                payment_logger.log_business_logic(
                    action="RECORD_WEBHOOK_CALL",
                    data={
                        "transaction_id": str(transaction.id),
                        "webhook_status": payment_status,
                        "event_type": WebhookEventType.PAYMENT,
                        "is_postpaid": is_postpaid,
                        "payment_amount": float(payment_amount),
                    },
                )

                self.record_cit_payment_response(
                    transaction_obj=transaction,
                    transfer_via=TransferVia.CREDIMAX,
                    event_type=WebhookEventType.PAYMENT,
                    request_body=cit_payload,
                    response_body=cit_payment_response,
                    webhook_status=payment_status,
                    response_status_code=cit_payment_response.get(
                        "http_status_code", status.HTTP_200_OK
                    ),
                )
                logger.info(
                    f"[CUSTOMER_INITIATED_PAYMENT] Webhook recorded: "
                    f"transaction_id={transaction.id}, "
                    f"is_postpaid={is_postpaid}, "
                    f"payment_status={payment_status}"
                )
            except Exception as webhook_error:
                logger.error(
                    f"[CUSTOMER_INITIATED_PAYMENT] Failed to record webhook: {webhook_error}",
                    exc_info=True,
                )
                # Don't fail the entire process if webhook recording fails

            logger.info("Flag 1111: Start")
            # For POSTPAID: Skip billing details creation if transaction amount is 0
            # POSTPAID subscriptions don't create billing details at purchase time
            # Billing details will be created during recurring payment task
            if transaction.status == TransactionStatus.SUCCESS:
                # Check if this is a POSTPAID subscription with zero-amount transaction (session-only)
                # POSTPAID transactions created during session setup have amount=0.00
                is_postpaid_zero_amount = is_postpaid and transaction.amount == Decimal(
                    "0.00"
                )

                if is_postpaid_zero_amount:
                    payment_logger.log_business_logic(
                        action="SKIP_BILLING_DETAILS_FOR_POSTPAID_SESSION_TRANSACTION",
                        data={
                            "transaction_id": str(transaction.id),
                            "subscription_id": str(business_subscription_plan.id),
                            "transaction_amount": float(transaction.amount),
                            "reason": "POSTPAID session-only transaction (amount=0). Billing details will be created during recurring payment.",
                        },
                    )
                    logger.info(
                        f"[CUSTOMER_INITIATED_PAYMENT] Skipping billing details for POSTPAID session transaction: "
                        f"transaction_id={transaction.id}, "
                        f"subscription_id={business_subscription_plan.id}, "
                        f"transaction_amount={transaction.amount}, "
                        f"is_postpaid={is_postpaid}"
                    )
                    billing_details = None
                else:
                    payment_logger.log_business_logic(
                        action="CREATE_BILLING_DETAILS",
                        data={
                            "transaction_id": str(transaction.id),
                            "subscription_id": str(business_subscription_plan.id),
                            "business_id": str(business.business.id),
                            "is_postpaid": is_postpaid,
                            "transaction_amount": float(transaction.amount),
                        },
                    )

                    billing_details = self.create_billing_details(
                        business=business.business,
                        business_subscription_plan=business_subscription_plan,
                        transaction=transaction,
                    )

                payment_logger.log_business_logic(
                    action="BILLING_DETAILS_CREATED",
                    data={
                        "billing_details_id": (
                            str(billing_details.id) if billing_details else None
                        ),
                        "total_amount": (
                            float(billing_details.total_amount)
                            if billing_details
                            else None
                        ),
                    },
                )
            else:
                billing_details = None
                payment_logger.log_business_logic(
                    action="SKIP_BILLING_DETAILS",
                    data={
                        "reason": "Transaction not successful",
                        "transaction_status": transaction.status,
                    },
                )

            logger.info("Flag 2222: Send mail")
            request = self.context["request"]

            # For POSTPAID: Skip both invoice and receipt at purchase time
            # No billing details are created, so no invoice is sent
            # Send POSTPAID activation email with upcoming payment details
            # Invoice and receipt will be sent during recurring payment task when actual payment is processed
            # For PREPAID: Send both invoice and receipt
            if is_postpaid:
                # Check if billing details were created (should be None for POSTPAID with amount=0)
                if billing_details is None:
                    try:
                        payment_logger.log_business_logic(
                            action="SKIP_INVOICE_AND_RECEIPT_FOR_POSTPAID",
                            data={
                                "subscription_id": str(business_subscription_plan.id),
                                "business_id": str(business.business.id),
                                "transaction_id": str(transaction.id),
                                "transaction_amount": float(transaction.amount),
                                "reason": "POSTPAID subscriptions do not send invoice or receipt at purchase time. Both will be sent during recurring payment when actual payment is processed.",
                            },
                        )
                    except Exception as log_error:
                        logger.warning(
                            f"[CUSTOMER_INITIATED_PAYMENT] Failed to log skip invoice/receipt: {log_error}"
                        )
                    logger.info(
                        f"[CUSTOMER_INITIATED_PAYMENT] POSTPAID subscription: "
                        f"No invoice or receipt sent at purchase. "
                        f"Transaction (amount=0) created for session only. "
                        f"Invoice and receipt will be sent during recurring payment. "
                        f"transaction_id={transaction.id}, "
                        f"subscription_id={business_subscription_plan.id}"
                    )

                    # Send POSTPAID activation email with upcoming payment details
                    if transaction.status == TransactionStatus.SUCCESS:
                        try:
                            # Get business owner
                            owner_user = User.objects.filter(
                                user_assigned_businesses__business=business.business,
                                user_assigned_businesses__is_owner=True,
                            ).first()

                            if owner_user and owner_user.email:
                                # Format dates for email display
                                from django.utils import formats

                                plan_start_date_str = (
                                    formats.date_format(
                                        business_subscription_plan.start_date, "M. d, Y"
                                    )
                                    if business_subscription_plan.start_date
                                    else "N/A"
                                )
                                plan_end_date_str = (
                                    formats.date_format(
                                        business_subscription_plan.expiry_date,
                                        "M. d, Y",
                                    )
                                    if business_subscription_plan.expiry_date
                                    else "N/A"
                                )
                                next_billing_date_str = (
                                    formats.date_format(
                                        business_subscription_plan.next_billing_date,
                                        "M. d, Y",
                                    )
                                    if business_subscription_plan.next_billing_date
                                    else "N/A"
                                )

                                # Get billing frequency display name
                                billing_frequency_display = (
                                    business_subscription_plan.get_billing_frequency_display()
                                    if business_subscription_plan.billing_frequency
                                    else "Monthly"
                                )

                                # Determine first payment date based on payment interval
                                # If payment interval is YEARLY, show plan_end_date (expiry_date)
                                # Otherwise (MONTHLY, QUARTERLY), show next_billing_date
                                payment_interval = (
                                    business_subscription_plan.payment_interval
                                    or SubscriptionPaymentIntervalChoices.MONTHLY
                                )
                                if (
                                    payment_interval
                                    == SubscriptionPaymentIntervalChoices.YEARLY
                                ):
                                    first_payment_date_str = plan_end_date_str
                                else:
                                    first_payment_date_str = next_billing_date_str

                                # Get business and user names
                                business_name = business.business.name or ""
                                user_fullname = owner_user.fullname or ""
                                display_name = (
                                    business_name
                                    or user_fullname
                                    or owner_user.email
                                    or "Customer"
                                )

                                # Get subscription plan name
                                plan_name = business_subscription_plan.subscription_name or (
                                    business_subscription_plan.subscription_plan.name
                                    if business_subscription_plan.subscription_plan
                                    else "Subscription Plan"
                                )

                                # Get organization logo
                                organization_logo_url = get_organization_logo_url(
                                    organization
                                )

                                # Calculate subscription amount with VAT for email
                                # For POSTPAID, use the subscription fee from business_subscription_plan
                                # and calculate VAT based on organization VAT rate
                                subscription_base_amount = (
                                    business_subscription_plan.subscription_fee
                                    or Decimal("0.00")
                                )
                                vat_rate = getattr(organization, "vat_rate", 0) or 0
                                vat_amount = subscription_base_amount * Decimal(
                                    str(vat_rate)
                                )
                                subscription_total_amount = (
                                    subscription_base_amount + vat_amount
                                )

                                # Prepare email context
                                email_context = {
                                    "organization_name": organization.name,
                                    "business_name": business_name,
                                    "user_fullname": user_fullname,
                                    "display_name": display_name,
                                    "plan_name": plan_name,
                                    "plan_start_date": plan_start_date_str,
                                    "plan_end_date": plan_end_date_str,
                                    "next_billing_date": next_billing_date_str,
                                    "first_payment_date": first_payment_date_str,
                                    "billing_frequency": billing_frequency_display,
                                    "subscription_amount": subscription_total_amount,
                                    "organization_logo_url": organization_logo_url,
                                }

                                # Send POSTPAID activation email
                                send_postpaid_subscription_activation_email(
                                    recipient_list=[owner_user.email],
                                    context=email_context,
                                    organization_name=organization.name,
                                )

                                payment_logger.log_business_logic(
                                    action="SEND_POSTPAID_ACTIVATION_EMAIL",
                                    data={
                                        "subscription_id": str(
                                            business_subscription_plan.id
                                        ),
                                        "business_id": str(business.business.id),
                                        "transaction_id": str(transaction.id),
                                        "recipient_email": owner_user.email,
                                        "next_billing_date": next_billing_date_str,
                                        "subscription_amount": float(
                                            subscription_total_amount
                                        ),
                                        "subscription_base_amount": float(
                                            subscription_base_amount
                                        ),
                                        "vat_rate": float(vat_rate),
                                        "vat_amount": float(vat_amount),
                                    },
                                )
                                logger.info(
                                    f"[CUSTOMER_INITIATED_PAYMENT] POSTPAID activation email sent: "
                                    f"subscription_id={business_subscription_plan.id}, "
                                    f"recipient={owner_user.email}, "
                                    f"next_billing_date={next_billing_date_str}, "
                                    f"amount={subscription_total_amount} (base: {subscription_base_amount}, VAT: {vat_amount})"
                                )
                            else:
                                logger.warning(
                                    f"[CUSTOMER_INITIATED_PAYMENT] Cannot send POSTPAID activation email: "
                                    f"No owner user or email found for business_id={business.business.id}"
                                )
                        except Exception as email_error:
                            logger.error(
                                f"[CUSTOMER_INITIATED_PAYMENT] Failed to send POSTPAID activation email: {email_error}",
                                exc_info=True,
                            )
                            # Don't fail the entire process if email sending fails
                else:
                    # This shouldn't happen, but log it if it does
                    logger.warning(
                        f"[CUSTOMER_INITIATED_PAYMENT] POSTPAID subscription has billing details: "
                        f"transaction_id={transaction.id}, "
                        f"billing_details_id={billing_details.id if billing_details else None}"
                    )
            else:
                # Add delay before sending receipt email (invoice was already sent during billing details creation)
                if transaction.status == TransactionStatus.SUCCESS and billing_details:
                    delay_seconds = (
                        2  # 2 second delay between invoice and receipt emails
                    )
                    payment_logger.log_business_logic(
                        action="EMAIL_DELAY",
                        data={
                            "delay_seconds": delay_seconds,
                            "reason": "Delay between invoice and receipt emails",
                        },
                    )

                    logger.info(
                        f"Waiting {delay_seconds} seconds before sending receipt email..."
                    )
                    time.sleep(delay_seconds)

                payment_logger.log_business_logic(
                    action="SEND_EMAIL_NOTIFICATION",
                    data={
                        "transaction_id": str(transaction.id),
                        "subscription_id": str(business_subscription_plan.id),
                        "business_id": str(business.business.id),
                        "billing_details_exists": billing_details is not None,
                        "payment_type": payment_type,
                    },
                )

                send_mail_to_business_owner(
                    request.user,
                    organization=organization,
                    business=business.business,
                    business_subscription_plan=business_subscription_plan,
                    billing_details=billing_details,
                    transaction=transaction,
                    failure_reason=failure_reason if not is_successful else None,
                )
            logger.info("Flag 3333: Completed")

            payment_logger.log_transaction_completion(
                final_status=str(transaction.status),
                summary={
                    "type": "customer_initiated_payment",
                    "transaction_id": str(transaction.id),
                    "subscription_id": str(business_subscription_plan.id),
                    "business_id": str(business.business.id),
                    "amount": float(total_amount),
                    "payment_successful": is_successful,
                    "api_operation": api_operation,
                },
            )

            # Check if still processing (no DB refresh needed - status was just updated above)
            is_processing = (
                business_subscription_plan.status
                == SubscriptionStatusChoices.PENDING  # still waiting for gateway/webhook
            )

            response_data = {
                "detail": title,
                "status_code": status_code,
                "transaction_id": transaction.id,
                "transaction_status": transaction.status,
                "subscription_status": business_subscription_plan.status,
                "is_processing": is_processing,
                "remark": transaction.remark,
            }

            # Include additional details for failed transactions
            if not is_successful:
                response_data["card_type"] = card_type

            return response_data

        except Exception as e:
            # If payment was successful but later steps failed, still report success
            # but log/raise appropriate warnings for debugging
            try:
                is_postpaid_check = is_postpaid if "is_postpaid" in locals() else False
                payment_amount_check = (
                    payment_amount if "payment_amount" in locals() else None
                )

                if is_successful:
                    try:
                        payment_logger.log_error(
                            error_type="POST_PROCESSING_ERROR",
                            error_message=f"Payment succeeded but post-processing failed: {str(e)}",
                            context={
                                "transaction_id": str(transaction.id),
                                "subscription_id": str(business_subscription_plan.id),
                                "payment_successful": True,
                                "is_postpaid": is_postpaid_check,
                                "payment_amount": float(payment_amount_check)
                                if payment_amount_check
                                else None,
                            },
                        )
                    except Exception as log_error:
                        logger.error(
                            f"[CUSTOMER_INITIATED_PAYMENT] Failed to log post-processing error: {log_error}",
                            exc_info=True,
                        )

                    logger.error(
                        f"[CUSTOMER_INITIATED_PAYMENT] Payment succeeded but post-processing failed: "
                        f"transaction_id={transaction.id}, "
                        f"subscription_id={business_subscription_plan.id}, "
                        f"is_postpaid={is_postpaid_check}, "
                        f"error={str(e)}",
                        exc_info=True,
                    )
                    return {
                        "detail": "Payment succeeded, but system encountered a follow-up error.",
                        "status_code": status.HTTP_200_OK,
                        "transaction_id": transaction.id,
                        "transaction_status": transaction.status,
                        "remark": transaction.remark,
                    }
                else:
                    try:
                        payment_logger.log_error(
                            error_type="PAYMENT_AND_POST_PROCESSING_ERROR",
                            error_message=f"Payment failed and post-processing also failed: {str(e)}",
                            context={
                                "transaction_id": str(transaction.id),
                                "subscription_id": str(business_subscription_plan.id),
                                "payment_successful": False,
                                "is_postpaid": is_postpaid_check,
                                "payment_amount": float(payment_amount_check)
                                if payment_amount_check
                                else None,
                            },
                        )
                    except Exception as log_error:
                        logger.error(
                            f"[CUSTOMER_INITIATED_PAYMENT] Failed to log payment/post-processing error: {log_error}",
                            exc_info=True,
                        )

                    logger.error(
                        f"[CUSTOMER_INITIATED_PAYMENT] Payment failed and post-processing also failed: "
                        f"transaction_id={transaction.id}, "
                        f"subscription_id={business_subscription_plan.id}, "
                        f"is_postpaid={is_postpaid_check}, "
                        f"error={str(e)}",
                        exc_info=True,
                    )
                    raise serializers.ValidationError(
                        f"Payment failed (follow-up error): {str(e)}"
                    )
            except serializers.ValidationError:
                raise
            except Exception as final_error:
                logger.error(
                    f"[CUSTOMER_INITIATED_PAYMENT] Critical error in exception handler: {final_error}",
                    exc_info=True,
                )
                raise serializers.ValidationError(f"Payment processing error: {str(e)}")

    def _analyze_payment_failure(self, response, card_type):
        """
        Analyze payment failure response to provide specific error messages
        for different failure scenarios, especially DEBIT card issues.
        """
        result = response.get("result", "").upper()
        gateway_code = response.get("response", {}).get("gatewayCode", "").upper()

        # Check for risk management rejections
        risk_response = response.get("risk", {}).get("response", {})
        risk_gateway_code = risk_response.get("gatewayCode", "").upper()

        # Check for MSO_BIN_RANGE rejections (common with DEBIT cards)
        rules = risk_response.get("rule", [])
        bin_range_rejection = False
        for rule in rules:
            if (
                rule.get("name") == "MSO_BIN_RANGE"
                and rule.get("recommendation") == "REJECT"
            ):
                bin_range_rejection = True
                break

        # DEBIT card specific handling
        if card_type == "DEBIT":
            if bin_range_rejection:
                return (
                    "Unfortunately, DEBIT cards are not currently accepted for subscription payments. "
                    "Please use a CREDIT card. "
                    "You can also contact our support team for alternative payment methods."
                )
            elif risk_gateway_code == "REJECTED":
                return (
                    "Your DEBIT card was declined due to risk management policies. "
                    "This may be due to your bank's restrictions on recurring payments. "
                    "Please try with a CREDIT card or contact our support team for assistance."
                )
            elif gateway_code == "BLOCKED":
                return (
                    "Your DEBIT card payment was blocked. This is often due to bank restrictions on recurring payments. "
                    "Please use a CREDIT card or contact our support team for assistance."
                )

        # General failure handling
        if result == "FAILURE":
            if gateway_code == "BLOCKED":
                return (
                    "Payment was blocked by the payment gateway. "
                    "This may be due to your bank's security policies or card restrictions. "
                    "Please try with a different CREDIT card or contact our support team for assistance."
                )
            elif risk_gateway_code == "REJECTED":
                return (
                    "Payment was declined due to risk management policies. "
                    "Please try with a different CREDIT card or contact our support team for assistance."
                )

        # Default message for unhandled cases
        return None

    def _should_retry_with_different_card(self, response, card_type):
        """
        Determine if the payment should be retried with a different card type
        based on the failure reason.
        """
        if card_type != "DEBIT":
            return False

        # Check for specific DEBIT card rejection patterns
        risk_response = response.get("risk", {}).get("response", {})
        rules = risk_response.get("rule", [])

        for rule in rules:
            if (
                rule.get("name") == "MSO_BIN_RANGE"
                and rule.get("recommendation") == "REJECT"
            ):
                return True

        # Check for other DEBIT-specific rejections
        gateway_code = response.get("response", {}).get("gatewayCode", "").upper()
        risk_gateway_code = risk_response.get("gatewayCode", "").upper()

        if gateway_code == "BLOCKED" or risk_gateway_code == "REJECTED":
            return True

        return False

    # Method 3: Get all subscription details (if you need more info)
    def get_business_subscription_details(self, user_assigned_business):
        """
        Returns the BusinessSubscriptionPlan instance with full details.
        Looks for PENDING subscriptions first, then ACTIVE, then SUSPENDED.
        This ensures we can process payments for recurring subscriptions.
        """
        try:
            # Priority order: PENDING > ACTIVE > SUSPENDED
            # First try to get PENDING subscription (for initial payments)
            business_subscription = (
                user_assigned_business.business.business_subscription_plan.select_related(
                    "subscription_plan", "business_saved_card_token"
                )
                .filter(status=SubscriptionStatusChoices.PENDING)
                .order_by("-created_at")
                .first()
            )

            # If no PENDING, try ACTIVE (for recurring payments)
            if not business_subscription:
                business_subscription = (
                    user_assigned_business.business.business_subscription_plan.select_related(
                        "subscription_plan", "business_saved_card_token"
                    )
                    .filter(status=SubscriptionStatusChoices.ACTIVE)
                    .order_by("-created_at")
                    .first()
                )

            # If no ACTIVE, try SUSPENDED (for reactivation)
            if not business_subscription:
                business_subscription = (
                    user_assigned_business.business.business_subscription_plan.select_related(
                        "subscription_plan", "business_saved_card_token"
                    )
                    .filter(status=SubscriptionStatusChoices.SUSPENDED)
                    .order_by("-created_at")
                    .first()
                )

            return business_subscription

        except UserAssignedBusiness.DoesNotExist:
            return None
        except Exception as e:
            print(f"Error getting subscription details: {e}")
            return None

    def record_cit_payment_response(
        self,
        transaction_obj={},
        transfer_via=TransferVia.CREDIMAX,
        event_type=WebhookEventType.PAYMENT,
        request_body=dict(),
        response_body=dict(),
        webhook_status=WebhookCallStatus.SUCCESS,
        response_status_code=status.HTTP_200_OK,
    ):
        WebhookCall.objects.create(
            transaction=transaction_obj,
            transfer_via=transfer_via,
            event_type=event_type,
            status=webhook_status,
            request_body=request_body,
            response_body=response_body,
            response_status_code=response_status_code,
        )

    def create_billing_details(
        self,
        business,
        business_subscription_plan,
        transaction,
    ):
        # Get payment logger for this transaction
        payment_logger = get_credimax_logger(
            str(transaction.id), business_id=str(business.id)
        )

        # Calculate base amount from transaction
        # transaction.amount is the TOTAL amount (base + VAT)
        # transaction.vat is the VAT amount
        # So base_amount = transaction.amount - transaction.vat
        base_amount = transaction.amount - (transaction.vat or Decimal("0.00"))

        payment_logger.log_business_logic(
            action="CALCULATE_BILLING_DETAILS",
            data={
                "transaction_id": str(transaction.id),
                "subscription_id": str(business_subscription_plan.id),
                "transaction_total_amount": float(transaction.amount),
                "transaction_vat": float(transaction.vat or 0),
                "calculated_base_amount": float(base_amount),
                "vat_rate": float(transaction.vat_rate or 0),
                "tax_rate": float(transaction.tax_rate or 0),
                "commission_rate": float(
                    business_subscription_plan.commission_rate or 0
                ),
            },
        )

        (
            commission_fee,
            vat_amount,
            tax_amount,
            total_amount,
        ) = calculate_tax_and_total(
            base_amount,
            transaction.vat_rate or Decimal(0.0),
            transaction.tax_rate or Decimal(0.0),
            business_subscription_plan.commission_rate or Decimal(0.0),
        )

        payment_logger.log_business_logic(
            action="BILLING_CALCULATIONS_COMPLETED",
            data={
                "commission_fee": float(commission_fee),
                "vat_amount": float(vat_amount),
                "tax_amount": float(tax_amount),
                "total_amount": float(total_amount),
            },
        )

        logging.info(f"Flag 5555: Commission fee {commission_fee}")
        if transaction.status == TransactionStatus.SUCCESS:
            payment_status = PaymentStatus.COMPLETED
        else:
            payment_status = PaymentStatus.FAILED

        period_start_date = (
            business_subscription_plan.last_billing_date
            or business_subscription_plan.start_date
        )

        if not period_start_date:
            period_start_date = timezone.now().date()

        period_end_date = (
            business_subscription_plan.next_billing_date
            or business_subscription_plan.calculate_next_billing_date(period_start_date)
        )

        billing_details = BillingDetails.objects.create(
            business=business,
            period_start_date=period_start_date,
            period_end_date=period_end_date,
            base_amount=base_amount,
            commission_fee=commission_fee or Decimal(0.0),
            vat_rate=transaction.vat_rate or Decimal(0.0),
            vat_amount=vat_amount,
            tax_rate=transaction.tax_rate or Decimal(0.0),
            tax_amount=tax_amount,
            total_amount=total_amount,
            payment_status=payment_status,
        )

        payment_logger.log_business_logic(
            action="BILLING_DETAILS_SAVED",
            data={
                "billing_details_id": str(billing_details.id),
                "payment_status": payment_status,
                "period_start_date": billing_details.period_start_date.isoformat(),
                "period_end_date": billing_details.period_end_date.isoformat(),
            },
        )

        # Send invoice email after creating billing details
        if transaction.status == TransactionStatus.SUCCESS:
            payment_logger.log_business_logic(
                action="SEND_INVOICE_EMAIL",
                data={
                    "billing_details_id": str(billing_details.id),
                    "business_id": str(business.id),
                    "subscription_plan_id": str(
                        business_subscription_plan.subscription_plan.id
                    ),
                },
            )

            from sooq_althahab.billing.subscription.services import (
                send_subscription_invoice,
            )

            try:
                send_subscription_invoice(
                    billing_details=billing_details,
                    business=business,
                    subscription_plan=business_subscription_plan.subscription_plan,
                    organization=business.organization_id,
                    business_subscription_plan=business_subscription_plan,  # Pass BusinessSubscriptionPlan for accurate pricing info
                )

                payment_logger.log_business_logic(
                    action="INVOICE_EMAIL_SENT",
                    data={
                        "billing_details_id": str(billing_details.id),
                        "status": "success",
                    },
                )
            except Exception as e:
                payment_logger.log_error(
                    error_type="INVOICE_EMAIL_FAILED",
                    error_message=str(e),
                    context={
                        "billing_details_id": str(billing_details.id),
                        "business_id": str(business.id),
                    },
                )
                # Don't fail the entire process for email issues
                pass

        return billing_details


class MarkTransactionAsFailedSerializer(serializers.Serializer):
    order_id = serializers.CharField(required=True)
    remark = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        request = self.context["request"]
        current_business_id = request.auth.get("current_business")
        try:
            user_business = UserAssignedBusiness.objects.get(id=current_business_id)
        except UserAssignedBusiness.DoesNotExist:
            raise serializers.ValidationError("Associated business not found.")

        try:
            transaction = Transaction.objects.select_related(
                "business_subscription"
            ).get(id=data.get("order_id"), from_business=user_business.business)
        except Transaction.DoesNotExist:
            raise serializers.ValidationError("Order not found.")

        data["user_business"] = user_business
        data["transaction"] = transaction
        return data

    @db_transaction.atomic
    def save(self):
        transaction = self.validated_data["transaction"]
        remark = self.validated_data.get("remark", "")
        user_business = self.validated_data["user_business"]
        organization = user_business.business.organization_id

        # 1. Update transaction
        transaction.status = TransactionStatus.FAILED
        transaction.remark = remark
        transaction.save()

        # 2. Update subscription + token if applicable
        subscription = transaction.business_subscription
        if subscription:
            subscription.status = SubscriptionStatusChoices.FAILED
            subscription.save()

            token = subscription.business_saved_card_token
            if token and token.is_used_for_subscription:
                token.is_used_for_subscription = False
                token.save()

        request = self.context["request"]
        send_mail_to_business_owner(
            request.user,
            organization=organization,
            business=user_business.business,
            business_subscription_plan=subscription,
            transaction=transaction,
            failure_reason=remark,
        )
        return transaction


class Credimax3DSCallbackSerializer(serializers.Serializer):
    order_id = serializers.CharField(required=True)
    result = serializers.CharField(required=True)

    def save(self):
        data = self.validated_data
        result = data.get("result")
        order_id = data.get("order_id")

        if result != "SUCCESS":
            try:
                transaction = Transaction.objects.select_related(
                    "business_subscription"
                ).get(id=order_id)
            except Transaction.DoesNotExist:
                raise serializers.ValidationError("Order not found.")

            with db_transaction.atomic():
                transaction.status = TransactionStatus.FAILED
                transaction.remark = "3DS Authentication Failed"
                transaction.save()

                subscription = transaction.business_subscription
                if subscription:
                    subscription.status = SubscriptionStatusChoices.FAILED
                    subscription.save()

                    token = subscription.business_saved_card_token
                    if token and token.is_used_for_subscription:
                        token.is_used_for_subscription = False
                        token.save()

            return {"status": "failed", "transaction_id": order_id}

        # Success case
        return {"status": "success", "transaction_id": order_id}


class Credimax3DSCardAdditionCallbackSerializer(serializers.Serializer):
    """
    Serializer for handling 3DS callbacks specifically for card addition flow.
    Card addition transactions have order_id starting with "card_add_".
    """

    order_id = serializers.CharField(required=True)
    result = serializers.CharField(required=True)

    def validate_order_id(self, value):
        """Ensure this is a card addition transaction."""
        if not value.startswith("card_add_"):
            raise serializers.ValidationError(
                "This endpoint is only for card addition transactions. "
                "Order ID must start with 'card_add_'."
            )
        return value

    def save(self):
        """
        Handle card addition 3DS callback.
        For card addition, we don't need to update transaction/subscription status
        as the frontend handles the final card save. We just need to return the status.
        """
        data = self.validated_data
        result = data.get("result")
        order_id = data.get("order_id")

        if result != "SUCCESS":
            logger.warning(
                f"Card addition 3DS authentication failed for order {order_id}"
            )
            return {"status": "failed", "order_id": order_id}

        logger.info(f"Card addition 3DS authentication successful for order {order_id}")
        return {"status": "success", "order_id": order_id}


class UpdateBusinessSubscriptionPlanSerializer(serializers.Serializer):
    """
    Serializer to update business subscription plan by admin.

    Takes business_id and subscription_plan_id in payload and updates the
    business subscription plan with all necessary changes to handle the update
    of subscription plan in business subscription plan like in billing cycle
    of that business, changes required in musharakah, jewelry design or any other.

    Key Behaviors:
        - Updates start_date to current date (marks new plan period start)
        - Calculates new expiry_date based on subscription plan duration
        - Recalculates next_billing_date based on new billing frequency
        - Updates all plan-specific fields (fees, commission, limitations)
        - Warns if billing_frequency and payment_interval are inconsistent

    Fields:
        - business_id (str): The ID of the business to update subscription for
        - subscription_plan_id (str): The ID of the new subscription plan to assign

    Returns:
        - subscription_id: The updated business subscription plan ID
        - business_name: Name of the business
        - old_plan_name: Previous subscription plan name
        - new_plan_name: New subscription plan name
        - updated_fields: List of fields that were updated
        - subscription_dates: Object containing start_date, expiry_date, next_billing_date, duration
        - billing_details_impact: Impact on billing configuration
        - limitations_impact: Impact on business limitations (for JEWELER role)
    """

    business_id = serializers.CharField()
    subscription_plan_id = serializers.CharField()

    def validate(self, data):
        request = self.context["request"]

        # Validate business exists
        business_id = data.get("business_id")

        user_business = (
            UserAssignedBusiness.objects.select_related("business")
            .filter(business_id=business_id, is_owner=True)
            .first()
        )

        if not user_business:
            raise serializers.ValidationError("Business not found.")

        # Validate subscription plan exists and is active
        subscription_plan_id = data.get("subscription_plan_id")

        # First check if plan exists (without is_active filter to get better error messages)
        try:
            subscription_plan = SubscriptionPlan.objects.get(id=subscription_plan_id)
        except SubscriptionPlan.DoesNotExist:
            raise serializers.ValidationError(
                f"Subscription plan with ID '{subscription_plan_id}' not found."
            )

        # Check if plan is active
        if not subscription_plan.is_active:
            raise serializers.ValidationError(
                f"Subscription plan '{subscription_plan.name}' is inactive. "
                "Please activate the plan before assigning it to a business."
            )

        # Check if business has an active subscription
        active_subscription = BusinessSubscriptionPlan.objects.filter(
            business=user_business.business,
            status__in=[
                SubscriptionStatusChoices.ACTIVE,
                SubscriptionStatusChoices.TRIALING,
            ],
        ).first()

        if not active_subscription:
            raise serializers.ValidationError(
                "Business does not have an active subscription to update."
            )

        # Validate subscription plan role matches business role
        if subscription_plan.role != user_business.business.business_account_type:
            raise serializers.ValidationError(
                f"Subscription plan role '{subscription_plan.role}' does not match "
                f"business role '{user_business.business.business_account_type}'."
            )

        data["user_business"] = user_business
        data["subscription_plan"] = subscription_plan
        data["active_subscription"] = active_subscription

        return data

    @db_transaction.atomic
    def save(self):
        user_business = self.validated_data["user_business"]
        subscription_plan = self.validated_data["subscription_plan"]
        active_subscription = self.validated_data["active_subscription"]

        previous_commission_rate = active_subscription.commission_rate
        previous_pro_rata_rate = active_subscription.pro_rata_rate
        new_commission_rate = subscription_plan.commission_rate or Decimal("0.0000")
        new_pro_rata_rate = subscription_plan.pro_rata_rate or Decimal("0.0000")

        # CRITICAL: Store the new plan as PENDING instead of applying immediately
        # This ensures the current billing cycle uses the original plan rates
        # NOTE: active_subscription fields are NOT modified, so they retain current values

        # Ensure next_billing_date is set
        if not active_subscription.next_billing_date:
            active_subscription.next_billing_date = (
                active_subscription.calculate_next_billing_date()
            )

        # Store the pending plan and effective date
        active_subscription.pending_subscription_plan = subscription_plan
        active_subscription.pending_plan_effective_date = (
            active_subscription.next_billing_date
        )

        rates_updated_immediately = False
        if (
            previous_commission_rate != new_commission_rate
            or previous_pro_rata_rate != new_pro_rata_rate
        ):
            active_subscription.commission_rate = new_commission_rate
            active_subscription.pro_rata_rate = new_pro_rata_rate
            rates_updated_immediately = True

        # Update features immediately when admin updates plan (similar to commission_rate/pro_rata_rate)
        previous_features = active_subscription.features or []
        new_features = subscription_plan.features or []
        features_updated_immediately = False
        if previous_features != new_features:
            active_subscription.features = new_features
            features_updated_immediately = True

        # Handle billing details updates
        billing_details_impact = self._handle_billing_details_updates(
            user_business.business,
            active_subscription,
            active_subscription.subscription_plan,  # Current plan
            subscription_plan,  # New pending plan
        )

        # Handle business-specific limitations for JEWELER role
        limitations_impact = self._handle_business_limitations(
            user_business.business,
            active_subscription.subscription_plan,  # Current plan
            subscription_plan,  # New pending plan
        )

        # Save the subscription with pending changes
        active_subscription.save()

        # Calculate new fee for response
        new_fee = (
            subscription_plan.discounted_fee
            or subscription_plan.subscription_fee
            or Decimal("0.00")
        )

        # Log the update
        logger.info(
            f"✅ PENDING PLAN CHANGE STORED: Business subscription {active_subscription.id} "
            f"for {user_business.business.name} will change from '{active_subscription.subscription_name}' "
            f"to '{subscription_plan.name}' on {active_subscription.pending_plan_effective_date}"
        )

        logger.info(
            f"📊 Current Cycle: Uses {active_subscription.subscription_name} "
            f"(Fee: {active_subscription.subscription_fee}, Commission: {active_subscription.commission_rate}) | "
            f"Next Cycle (from {active_subscription.pending_plan_effective_date}): "
            f"Will use {subscription_plan.name} (Fee: {new_fee}, Commission: {subscription_plan.commission_rate})"
        )

        return {
            "subscription_id": active_subscription.id,
            "business_name": user_business.business.name,
            "current_plan_name": active_subscription.subscription_name,
            "pending_plan_name": subscription_plan.name,
            "current_billing_cycle": {
                "uses_plan": active_subscription.subscription_name,
                "subscription_fee": str(active_subscription.subscription_fee),
                "commission_rate": str(active_subscription.commission_rate),
                "billing_period": f"{active_subscription.last_billing_date or active_subscription.start_date} to {active_subscription.next_billing_date}",
            },
            "pending_changes": {
                "effective_date": (
                    active_subscription.pending_plan_effective_date.isoformat()
                    if active_subscription.pending_plan_effective_date
                    else None
                ),
                "new_plan_name": subscription_plan.name,
                "new_subscription_fee": str(new_fee),
                "new_commission_rate": str(subscription_plan.commission_rate),
                "will_apply_on_next_billing": True,
            },
            "subscription_dates": {
                "start_date": active_subscription.start_date.isoformat(),
                "expiry_date": (
                    active_subscription.expiry_date.isoformat()
                    if active_subscription.expiry_date
                    else None
                ),
                "next_billing_date": (
                    active_subscription.next_billing_date.isoformat()
                    if active_subscription.next_billing_date
                    else None
                ),
                "duration_months": subscription_plan.duration,
            },
            "billing_details_impact": billing_details_impact,
            "limitations_impact": limitations_impact,
            "immediate_rate_updates": {
                "applied": rates_updated_immediately,
                "commission_rate": {
                    "previous": str(previous_commission_rate),
                    "current": str(active_subscription.commission_rate),
                },
                "pro_rata_rate": {
                    "previous": str(previous_pro_rata_rate),
                    "current": str(active_subscription.pro_rata_rate),
                },
            },
        }

    def _handle_business_limitations(self, business, old_plan, new_plan):
        """
        Handle business-specific limitations when updating subscription plan.
        This includes musharakah weight limits, jewelry design limits, etc.
        """
        limitations_impact = {}

        # Only process limitations for JEWELER role
        if business.business_account_type == "JEWELER":
            # Handle musharakah weight limitations
            musharakah_impact = self._handle_musharakah_limitations(
                business, old_plan, new_plan
            )
            if musharakah_impact:
                limitations_impact["musharakah"] = musharakah_impact

            # Handle jewelry design limitations
            design_impact = self._handle_design_limitations(
                business, old_plan, new_plan
            )
            if design_impact:
                limitations_impact["design"] = design_impact

        return limitations_impact

    def _handle_billing_details_updates(
        self, business, subscription, old_plan, new_plan
    ):
        """
        Handle billing details updates when subscription plan changes.

        IMPORTANT FINANCIAL PRINCIPLE:
        - We do NOT update existing billing details (preserves financial integrity)
        - We only ensure future billing cycles use the new subscription plan
        - Billing cycle continues from the last payment date (industry standard)
        - Plan changes take effect from the next billing cycle
        """
        from sooq_althahab.enums.sooq_althahab_admin import PaymentStatus

        billing_details_impact = {
            "next_billing_info": {},
            "plan_change_effective_date": None,
        }

        # Check if subscription fee or commission rate changed
        old_fee = old_plan.subscription_fee if old_plan else Decimal("0.00")
        old_commission = old_plan.commission_rate if old_plan else Decimal("0.00")
        new_fee = (
            new_plan.discounted_fee or new_plan.subscription_fee or Decimal("0.00")
        )
        new_commission = new_plan.commission_rate

        if old_fee != new_fee or old_commission != new_commission:
            # Get the last successful billing date
            last_billing_date = (
                subscription.last_billing_date or subscription.start_date
            )
            next_billing_date = subscription.next_billing_date

            if next_billing_date:
                billing_details_impact[
                    "plan_change_effective_date"
                ] = next_billing_date.isoformat()
                billing_details_impact["next_billing_info"] = {
                    "next_billing_date": next_billing_date.isoformat(),
                    "will_use_new_rates": True,
                    "billing_cycle_preserved": True,
                    "last_billing_date": last_billing_date.isoformat(),
                }

                logger.info(
                    f"Subscription plan change for business {business.name} will take effect "
                    f"from next billing cycle on {next_billing_date}. "
                    f"Current billing cycle (from {last_billing_date} to {next_billing_date}) "
                    f"remains unchanged to preserve financial integrity."
                )
            else:
                # If no next billing date, calculate it and update the subscription
                next_billing_date = subscription.calculate_next_billing_date(
                    timezone.now().date()
                )
                subscription.next_billing_date = next_billing_date

                billing_details_impact[
                    "plan_change_effective_date"
                ] = next_billing_date.isoformat()
                billing_details_impact["next_billing_info"] = {
                    "next_billing_date": next_billing_date.isoformat(),
                    "will_use_new_rates": True,
                    "billing_cycle_preserved": True,
                    "last_billing_date": last_billing_date.isoformat(),
                }

                logger.info(
                    f"Calculated and set next billing date for business {business.name} "
                    f"to {next_billing_date} due to subscription plan change"
                )

            # Log the financial integrity preservation
            logger.info(
                f"Financial Integrity Preserved: Existing billing details for business {business.name} "
                f"remain unchanged. New subscription plan rates will apply from next billing cycle "
                f"starting {billing_details_impact['plan_change_effective_date']}"
            )

        return billing_details_impact

    def _handle_musharakah_limitations(self, business, old_plan, new_plan):
        """Handle musharakah weight limitations changes."""
        musharakah_impact = {}

        # Check if musharakah weight limits changed
        old_musharakah_weight = (
            old_plan.musharakah_request_max_weight if old_plan else None
        )
        new_musharakah_weight = new_plan.musharakah_request_max_weight

        if old_musharakah_weight != new_musharakah_weight:
            musharakah_impact["musharakah_request_max_weight"] = {
                "old_limit": (
                    str(old_musharakah_weight) if old_musharakah_weight else "No limit"
                ),
                "new_limit": (
                    str(new_musharakah_weight) if new_musharakah_weight else "No limit"
                ),
            }

            # Check if new limit is lower than current usage
            if new_musharakah_weight is not None:
                current_usage = self._get_current_musharakah_usage(business)
                if current_usage > new_musharakah_weight:
                    musharakah_impact["warning"] = (
                        f"Current musharakah usage ({current_usage}g) exceeds new limit ({new_musharakah_weight}g). "
                        "Existing contracts may need to be reviewed."
                    )

        # Check metal purchase weight limits
        old_metal_weight = old_plan.metal_purchase_max_weight if old_plan else None
        new_metal_weight = new_plan.metal_purchase_max_weight

        if old_metal_weight != new_metal_weight:
            musharakah_impact["metal_purchase_max_weight"] = {
                "old_limit": str(old_metal_weight) if old_metal_weight else "No limit",
                "new_limit": str(new_metal_weight) if new_metal_weight else "No limit",
            }

        return musharakah_impact

    def _handle_design_limitations(self, business, old_plan, new_plan):
        """Handle jewelry design count limitations changes."""
        design_impact = {}

        # Check if design count limits changed
        old_design_count = old_plan.max_design_count if old_plan else None
        new_design_count = new_plan.max_design_count

        if old_design_count != new_design_count:
            design_impact["max_design_count"] = {
                "old_limit": old_design_count if old_design_count else "No limit",
                "new_limit": new_design_count if new_design_count else "No limit",
            }

            # Check if new limit is lower than current usage
            if new_design_count is not None:
                current_design_count = self._get_current_design_count(business)
                if current_design_count > new_design_count:
                    design_impact["warning"] = (
                        f"Current design count ({current_design_count}) exceeds new limit ({new_design_count}). "
                        "No new designs can be uploaded until some are removed."
                    )

        return design_impact

    def _get_current_musharakah_usage(self, business):
        """Get current musharakah weight usage for the business."""
        from django.db.models import Sum

        from jeweler.models import MusharakahContractRequest

        total_weight = MusharakahContractRequest.objects.filter(
            jeweler=business,
            deleted_at__isnull=True,
            status__in=["PENDING", "APPROVED"],
        ).aggregate(total_weight=Sum("target"))["total_weight"] or Decimal("0.00")

        return total_weight

    def _get_current_design_count(self, business):
        """Get current jewelry design count for the business."""
        from jeweler.models import JewelryDesign

        design_count = JewelryDesign.objects.filter(
            business=business,
            deleted_at__isnull=True,
        ).count()

        return design_count


class SuspendBusinessSubscriptionPlanSerializer(serializers.Serializer):
    """
    Serializer to suspend business subscription plan by admin.

    This API allows admin to suspend a business subscription, preventing the business
    from logging in. This is particularly useful for businesses on free trial plans
    that need to be forced to upgrade to a paid plan (which requires card details).

    Key Behaviors:
        - Changes subscription status to SUSPENDED
        - Prevents business users from logging in
        - Business can purchase a paid plan after suspension
        - Preserves subscription data for audit purposes

    Fields:
        - business_id (str): The ID of the business to suspend subscription for

    Returns:
        - subscription_id: The suspended business subscription plan ID
        - business_name: Name of the business
        - subscription_status: New status (SUSPENDED)
        - previous_status: Previous subscription status
        - suspended_at: Timestamp when suspension was applied
        - message: Confirmation message
    """

    business_id = serializers.CharField()

    def validate(self, data):
        request = self.context["request"]

        # Validate business exists
        business_id = data.get("business_id")
        assignments = UserAssignedBusiness.objects.select_related("business").filter(
            business_id=business_id
        )

        if not assignments.exists():
            raise serializers.ValidationError("Business not found.")

        user_business = assignments.filter(is_owner=True).first() or assignments.first()

        # Check if business has an active or trialing subscription
        active_subscription = BusinessSubscriptionPlan.objects.filter(
            business=user_business.business,
            status__in=[
                SubscriptionStatusChoices.ACTIVE,
                SubscriptionStatusChoices.TRIALING,
            ],
        ).first()

        if not active_subscription:
            raise serializers.ValidationError(
                "Business does not have an active or trialing subscription to suspend."
            )

        # Check if subscription is already suspended
        if active_subscription.status == SubscriptionStatusChoices.SUSPENDED:
            raise serializers.ValidationError(
                "Business subscription is already suspended."
            )

        data["user_business"] = user_business
        data["active_subscription"] = active_subscription
        data["previous_status"] = active_subscription.status

        return data

    @db_transaction.atomic
    def save(self):
        user_business = self.validated_data["user_business"]
        active_subscription = self.validated_data["active_subscription"]
        previous_status = self.validated_data["previous_status"]
        business = user_business.business

        # Get business name or user name (for individual businesses)
        business_name = business.name or ""
        owner_user = User.objects.filter(
            user_assigned_businesses__business=business,
            user_assigned_businesses__is_owner=True,
        ).first()

        user_fullname = owner_user.fullname if owner_user else ""
        display_name = (
            business_name
            or user_fullname
            or (owner_user.email if owner_user else "")
            or "Customer"
        )

        # Update subscription status to SUSPENDED
        active_subscription.status = SubscriptionStatusChoices.SUSPENDED
        active_subscription.save()

        # Get all users in the business (for critical suspension notification, notify all users)
        all_users_in_business = User.objects.filter(
            user_assigned_businesses__business=business,
        ).distinct()

        # Send FCM push notifications to all business users
        if all_users_in_business.exists():
            try:
                plan_name = (
                    active_subscription.subscription_plan.name
                    if active_subscription.subscription_plan
                    else active_subscription.subscription_name or "Free Trial"
                )

                title = "Subscription Suspended"
                message = (
                    f"Your {plan_name} subscription has been suspended. "
                    f"Please upgrade to a paid plan to continue using the application."
                )

                send_notifications(
                    all_users_in_business,
                    title,
                    message,
                    NotificationTypes.BUSINESS_SUBSCRIPTION_SUSPENDED,
                    ContentType.objects.get_for_model(BusinessSubscriptionPlan),
                    active_subscription.id,
                )

                logger.info(
                    f"FCM notifications sent to {all_users_in_business.count()} users "
                    f"for business {display_name} subscription suspension"
                )
            except Exception as e:
                logger.error(
                    f"Failed to send FCM notifications for subscription suspension: {str(e)}"
                )

        # Send email notification to business owner
        if owner_user and owner_user.email:
            try:
                self._send_suspension_email(
                    owner_user=owner_user,
                    business=business,
                    business_name=business_name,
                    user_fullname=user_fullname,
                    display_name=display_name,
                    subscription_plan=active_subscription.subscription_plan,
                    subscription_name=active_subscription.subscription_name,
                    organization=business.organization_id,
                )
            except Exception as e:
                logger.error(
                    f"Failed to send suspension email to {owner_user.email}: {str(e)}"
                )

        # Log the suspension
        logger.info(
            f"✅ SUBSCRIPTION SUSPENDED: Business subscription {active_subscription.id} "
            f"for {display_name} has been suspended. "
            f"Previous status: {previous_status}"
        )

        return {
            "subscription_id": active_subscription.id,
            "business_name": display_name,
            "subscription_status": active_subscription.status,
            "previous_status": previous_status,
            "suspended_at": (
                active_subscription.updated_at.isoformat()
                if active_subscription.updated_at
                else timezone.now().isoformat()
            ),
            "message": (
                f"Business subscription for '{display_name}' "
                f"has been suspended successfully. The business will not be able to login "
                f"until they purchase a paid subscription plan."
            ),
        }

    def _send_suspension_email(
        self,
        owner_user,
        business,
        business_name,
        user_fullname,
        display_name,
        subscription_plan,
        subscription_name,
        organization,
    ):
        """Send email notification when subscription is suspended."""
        from django.conf import settings

        from sooq_althahab.billing.transaction.helpers import get_organization_logo_url
        from sooq_althahab.tasks import send_mail

        plan_name = (
            subscription_plan.name
            if subscription_plan
            else subscription_name or "Free Trial"
        )

        email_context = {
            "organization_name": organization.name
            if organization
            else "Sooq Al Thahab",
            "business_name": business_name,
            "user_fullname": user_fullname,
            "display_name": display_name,
            "plan_name": plan_name,
            "organization_logo_url": (
                get_organization_logo_url(organization) if organization else ""
            ),
            "support_email": settings.CONTACT_SUPPORT_EMAIL,
            "support_contact_number": settings.SUPPORT_CONTACT_NUMBER,
        }

        subject = f"Free Trial Subscription Suspended - {plan_name}"

        send_mail.delay(
            subject=subject,
            template_name="templates/subscription-suspended.html",
            context=email_context,
            to_emails=[owner_user.email],
            from_email=settings.ORGANIZATION_BILLING_EMAIL,
            bcc_emails=settings.ORGANIZATION_ACCOUNTS_EMAIL,
        )

        logger.info(
            f"📧 Suspension email sent to {owner_user.email} for business {display_name}"
        )


class CancelBusinessSubscriptionPlanSerializer(serializers.Serializer):
    """
    Serializer to cancel business subscription plan by admin.

    This API allows admin to cancel a business subscription at the end of the current billing cycle.
    The subscription will remain active until the expiry_date, then it will be automatically
    cancelled and marked as CANCELLED status. This prevents auto-renewal.

    Key Behaviors:
        - Sets is_auto_renew flag to False to prevent auto-renewal
        - Subscription remains ACTIVE until expiry_date
        - At expiry_date, subscription will expire and not renew
        - No further billing cycles will occur
        - Preserves subscription data for audit purposes

    Fields:
        - business_id (str): The ID of the business to cancel subscription for

    Returns:
        - subscription_id: The business subscription plan ID
        - business_name: Name of the business
        - subscription_status: Current status (still ACTIVE until expiry)
        - is_auto_renew: False (auto-renewal disabled)
        - expiry_date: Date when subscription will expire
        - message: Confirmation message
    """

    business_id = serializers.CharField()

    def validate(self, data):
        request = self.context["request"]

        # Validate business exists
        business_id = data.get("business_id")
        assignments = UserAssignedBusiness.objects.select_related("business").filter(
            business_id=business_id
        )

        if not assignments.exists():
            raise serializers.ValidationError("Business not found.")

        user_business = assignments.filter(is_owner=True).first() or assignments.first()

        # Check if business has an active or trialing subscription
        active_subscription = BusinessSubscriptionPlan.objects.filter(
            business=user_business.business,
            status__in=[
                SubscriptionStatusChoices.ACTIVE,
                SubscriptionStatusChoices.TRIALING,
            ],
        ).first()

        if not active_subscription:
            raise serializers.ValidationError(
                "Business does not have an active or trialing subscription to cancel."
            )

        # Check if subscription is already cancelled or expired
        if active_subscription.status in [
            SubscriptionStatusChoices.CANCELLED,
            SubscriptionStatusChoices.EXPIRED,
            SubscriptionStatusChoices.TERMINATED,
        ]:
            raise serializers.ValidationError(
                f"Business subscription is already {active_subscription.status.lower()}."
            )

        # Check if auto-renewal is already disabled
        if not active_subscription.is_auto_renew:
            raise serializers.ValidationError(
                "Subscription auto-renewal is already disabled for this business."
            )

        data["user_business"] = user_business
        data["active_subscription"] = active_subscription

        return data

    @db_transaction.atomic
    def save(self):
        user_business = self.validated_data["user_business"]
        active_subscription = self.validated_data["active_subscription"]
        business = user_business.business

        # Get business name or user name (for individual businesses)
        business_name = business.name or ""
        owner_user = User.objects.filter(
            user_assigned_businesses__business=business,
            user_assigned_businesses__is_owner=True,
        ).first()

        user_fullname = owner_user.fullname if owner_user else ""
        display_name = (
            business_name
            or user_fullname
            or (owner_user.email if owner_user else "")
            or "Customer"
        )

        # Disable auto-renewal - subscription will not renew after expiry
        active_subscription.is_auto_renew = False
        active_subscription.save(update_fields=["is_auto_renew"])

        # Get expiry date (when subscription will expire)
        expiry_date = active_subscription.expiry_date

        return {
            "subscription_id": str(active_subscription.id),
            "business_name": display_name,
            "subscription_status": active_subscription.status,
            "is_auto_renew": active_subscription.is_auto_renew,
            "expiry_date": expiry_date.isoformat() if expiry_date else None,
            "message": (
                f"Subscription auto-renewal has been disabled for {display_name}. "
                f"The subscription will remain active until {expiry_date.strftime('%B %d, %Y') if expiry_date else 'the end of the billing period'}, "
                f"after which it will expire and not renew."
            ),
        }
