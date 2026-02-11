import json
import logging
import mimetypes
import os
import time
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from datetime import timedelta
from email.mime.image import MIMEImage

import requests
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.mail import EmailMultiAlternatives
from django.db import close_old_connections
from django.db.models import DateTimeField
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import Func
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils import translation
from django.utils.html import strip_tags
from firebase_admin import messaging
from redis import RedisError
from redis import StrictRedis
from weasyprint import HTML

from account.models import FCMToken
from account.models import Organization
from account.models import Transaction
from account.models import User
from account.models import Wallet
from account.utils import get_business_display_name
from investor.serializers import TransactionResponseSerializer
from jeweler.models import MusharakahContractRequest
from jeweler.utils import send_termination_reciept_email
from sooq_althahab.billing.subscription.pdf_utils import render_subscription_invoice_pdf
from sooq_althahab.billing.subscription.services import send_subscription_invoice
from sooq_althahab.billing.transaction.helpers import generate_tax_invoice_context
from sooq_althahab.billing.transaction.helpers import get_organization_logo_url
from sooq_althahab.billing.transaction.helpers import get_user_contact_details
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.jeweler import MusharakahContractStatus
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.enums.sooq_althahab_admin import PoolStatus
from sooq_althahab.payment_gateway_services.credimax.subscription.tasks import (
    process_commission_recurring_payment,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.tasks import (
    process_pro_rata_recurring_payment,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.tasks import (
    process_subscription_fee_recurring_payment,
)
from sooq_althahab.utils import get_presigned_url_from_s3
from sooq_althahab.utils import send_notification_to_group
from sooq_althahab.utils import send_notifications_to_organization_admins
from sooq_althahab_admin.models import GlobalMetal
from sooq_althahab_admin.models import MetalPriceHistory
from sooq_althahab_admin.models import Notification
from sooq_althahab_admin.models import Pool

logger = logging.getLogger(__name__)


def get_redis_client():
    """Get a Redis client, raise exception if fails."""
    try:
        return StrictRedis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB
        )
    except RedisError as e:
        raise Exception("Failed to connect to Redis. Task cannot proceed.") from e


def acquire_lock(redis_client, lock_key, timeout=30):
    """
    Acquire a Redis lock to prevent concurrent execution.
    Timeout reduced to 30s since tasks now complete much faster (~2-3s).
    """
    return redis_client.set(lock_key, "locked", nx=True, ex=timeout)


def release_lock(redis_client, lock_key):
    """Release the Redis lock."""
    redis_client.delete(lock_key)


def check_circuit_breaker(redis_client, api_url, failure_window_seconds=300):
    """
    Check if the API endpoint should be skipped due to recent failures (circuit breaker).
    Returns True if the endpoint should be skipped, False otherwise.

    Args:
        redis_client: Redis client instance
        api_url: The API URL to check
        failure_window_seconds: Time window in seconds to track failures (default 5 minutes)

    Returns:
        True if circuit is open (skip request), False if circuit is closed (allow request)
    """
    try:
        circuit_key = f"circuit_breaker:goldapi:{api_url}"
        failure_count = redis_client.get(circuit_key)

        if failure_count:
            # Handle both bytes and string responses from Redis
            try:
                count = (
                    int(failure_count)
                    if isinstance(failure_count, (int, str))
                    else int(failure_count.decode("utf-8"))
                )
            except (ValueError, AttributeError):
                # If conversion fails, assume circuit is closed
                return False

            # If we have 3+ consecutive failures in the window, open the circuit
            if count >= 3:
                return True

        return False
    except Exception as e:
        # If Redis fails, log but don't block the request
        logger.debug(f"Error checking circuit breaker: {e}")
        return False


def record_circuit_breaker_failure(redis_client, api_url, failure_window_seconds=300):
    """
    Record a failure for circuit breaker tracking.

    Args:
        redis_client: Redis client instance
        api_url: The API URL that failed
        failure_window_seconds: Time window in seconds to track failures
    """
    try:
        circuit_key = f"circuit_breaker:goldapi:{api_url}"
        redis_client.incr(circuit_key)
        redis_client.expire(circuit_key, failure_window_seconds)
    except Exception as e:
        logger.debug(f"Error recording circuit breaker failure: {e}")


def reset_circuit_breaker(redis_client, api_url):
    """
    Reset the circuit breaker on successful request.

    Args:
        redis_client: Redis client instance
        api_url: The API URL that succeeded
    """
    try:
        circuit_key = f"circuit_breaker:goldapi:{api_url}"
        redis_client.delete(circuit_key)
    except Exception as e:
        logger.debug(f"Error resetting circuit breaker: {e}")


def fetch_gold_price_with_retry(
    session, api_url, headers, redis_client=None, retries=3, initial_delay=1, timeout=10
):
    """
    Fetch gold price with retries on various error conditions.
    Implements exponential backoff to prevent excessive requests and handles:
    - Timeout errors (with aggressive timeout)
    - 503 Service Unavailable errors
    - 429 Rate limit errors
    - Other HTTP errors

    Circuit Breaker: Skips requests if endpoint has 3+ failures in the last 5 minutes.

    Optimizations:
    - Reduced timeout from 30s to 10s to fail fast
    - Reduced initial delay from 3s to 1s for faster recovery
    - Shorter retry cycles to prevent task backlog
    - Circuit breaker to prevent hammering failing endpoints
    - Warning-level logging for expected failures (no Sentry errors)
    """
    # Check circuit breaker first (if Redis client provided)
    if redis_client:
        if check_circuit_breaker(redis_client, api_url):
            logger.warning(f"Circuit breaker OPEN: Skipping {api_url}")
            return None

    # Copy initial_delay to a local variable so we can modify it for exponential backoff
    # without changing the original parameter. This preserves the parameter for reference
    # and allows delay to increase (1s → 2s → 4s) with each retry attempt.
    delay = initial_delay

    for attempt in range(retries):
        try:
            response = session.get(api_url, headers=headers, timeout=timeout)

            # Handle rate limiting
            if response.status_code == 429:
                if attempt < retries - 1:  # Don't wait if this is the last attempt
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                    continue
                else:
                    logger.warning(
                        f"Rate limit exceeded after {retries} attempts: {api_url}"
                    )
                    if redis_client:
                        record_circuit_breaker_failure(redis_client, api_url)
                    return None

            # Handle service unavailable
            if response.status_code == 503:
                if attempt < retries - 1:  # Don't wait if this is the last attempt
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                    continue
                else:
                    logger.warning(
                        f"Service unavailable after {retries} attempts: {api_url}"
                    )
                    if redis_client:
                        record_circuit_breaker_failure(redis_client, api_url)
                    return None

            response.raise_for_status()

            # Success - reset circuit breaker if it exists
            if redis_client:
                reset_circuit_breaker(redis_client, api_url)

            return response.json()

        except requests.exceptions.Timeout:
            if attempt < retries - 1:  # Don't wait if this is the last attempt
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                logger.warning(f"All {retries} retry attempts timed out: {api_url}")
                if redis_client:
                    record_circuit_breaker_failure(redis_client, api_url)
                return None

        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:  # Don't wait if this is the last attempt
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                logger.warning(f"All {retries} retry attempts failed: {api_url} - {e}")
                if redis_client:
                    record_circuit_breaker_failure(redis_client, api_url)
                return None

    return None


def fetch_metal_price_data(metal, base_url, currency, headers, redis_client=None):
    """
    Fetch a single metal price from the external API.

    Args:
        metal: GlobalMetal instance
        base_url: Base URL for the gold API
        currency: Currency code (e.g., 'USD')
        headers: HTTP headers for the request
        redis_client: Optional Redis client for circuit breaker functionality
    """
    session = requests.Session()
    try:
        url = f"{base_url}/{metal.symbol}/{currency}"
        response = fetch_gold_price_with_retry(
            session, url, headers, redis_client=redis_client
        )

        if not response:
            return None, metal, False

        price_24k = response.get("price_gram_24k")
        price_22k = response.get("price_gram_22k")
        price_21k = response.get("price_gram_21k")
        price_20k = response.get("price_gram_20k")
        price_18k = response.get("price_gram_18k")
        price_16k = response.get("price_gram_16k")
        price_14k = response.get("price_gram_14k")
        price_10k = response.get("price_gram_10k")

        if price_24k is None:
            return None, metal, False

        fetched_at = timezone.now()

        payload = {
            "symbol": metal.symbol,
            "price_24k": price_24k,
            "price_22k": price_22k,
            "price_21k": price_21k,
            "price_20k": price_20k,
            "price_18k": price_18k,
            "price_16k": price_16k,
            "price_14k": price_14k,
            "price_10k": price_10k,
        }

        return (
            {
                "payload": payload,
                "price_24k": price_24k,
                "fetched_at": fetched_at,
            },
            metal,
            True,
        )
    except Exception as e:
        logger.warning(f"Error fetching price for {metal.name}: {e}")
        return None, metal, False
    finally:
        try:
            session.close()
        except Exception:
            pass


@shared_task(bind=True, max_retries=0, time_limit=120, soft_time_limit=90)
def fetch_live_metal_prices(self):
    """
    Task to fetch live metal prices, update the database, and publish to Redis.

    This task handles API timeouts gracefully with:
    - Retry logic with exponential backoff (3 attempts)
    - Circuit breaker to prevent hammering failing endpoints
    - Warning-level logging (no Sentry errors for expected failures)
    - Graceful degradation: continues even if some metals fail

    Time limits:
    - soft_time_limit=90s: Task will receive SoftTimeLimitExceeded and can handle gracefully
    - time_limit=120s: Task will be killed hard if it exceeds this limit
    """
    environment_key = settings.ENVIRONMENT
    lock_key = f"{environment_key}_fetch_live_metal_prices_lock"
    redis_client = None

    try:
        redis_client = get_redis_client()
    except Exception as e:
        logger.error(
            f"Failed to connect to Redis: {e}. "
            "This indicates a Redis server/infrastructure issue. "
            "Check: Redis service running, network connectivity, firewall rules, Redis config."
        )
        # Continue without Redis - circuit breaker and pub/sub will be disabled
        # but the task can still fetch prices (just won't publish to Redis)
        redis_client = None

    # Acquire the lock to prevent concurrent execution
    if redis_client:
        if not acquire_lock(redis_client, lock_key):
            logger.info(f"[{environment_key}] Another instance is already running.")
            return

    try:
        headers = {
            "x-access-token": settings.GOLD_API_ACCESS_KEY,
            "Content-Type": "application/json",
        }
        base_url = settings.GOLD_API_BASE_URL
        currency = settings.CURRENCY

        # Fetch metals and their latest price history
        time_threshold = timezone.now() - settings.METAL_PRICE_UPDATE_INTERVAL

        # Close any old/stale DB connections before heavy read workload
        close_old_connections()

        # Get all metals - we'll fetch prices in parallel
        metals = list(GlobalMetal.objects.all())

        if not metals:
            logger.warning("No metals found in database")
            return

        live_metal_prices = {}
        total_metals = len(metals)
        successful_fetches = 0
        failed_fetches = 0

        # Fetch all metal prices in parallel using ThreadPoolExecutor
        # This dramatically reduces the total time from ~20-30s to ~2-3s
        max_workers = getattr(settings, "METAL_PRICE_MAX_WORKERS", 5) or 5
        worker_count = max(1, min(len(metals), max_workers))
        successful_results = []
        db_failures = 0

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            # Submit all tasks
            future_to_metal = {
                executor.submit(
                    fetch_metal_price_data,
                    metal,
                    base_url,
                    currency,
                    headers,
                    redis_client,  # Pass Redis client for circuit breaker
                ): metal
                for metal in metals
            }

            # Process results as they complete
            for future in as_completed(future_to_metal):
                metal = future_to_metal[future]
                try:
                    result, metal_obj, success = future.result()
                    if success and result:
                        live_metal_prices[metal_obj.name] = result["payload"]
                        successful_results.append(
                            (metal_obj, result["price_24k"], result["fetched_at"])
                        )
                        successful_fetches += 1
                    else:
                        failed_fetches += 1
                except Exception as e:
                    failed_fetches += 1
                    logger.warning(f"Error processing result for {metal.name}: {e}")

        # Update price history sequentially to avoid connection leaks
        if successful_results:
            close_old_connections()
            for metal_obj, price_24k, fetched_at in successful_results:
                if price_24k is None:
                    continue
                try:
                    latest_entry = (
                        MetalPriceHistory.objects.filter(
                            global_metal=metal_obj,
                            created_at__gte=time_threshold,
                        )
                        .order_by("-created_at")
                        .first()
                    )

                    if latest_entry:
                        latest_entry.price = price_24k
                        latest_entry.price_on_date = fetched_at
                        latest_entry.save(
                            update_fields=["price", "price_on_date", "updated_at"]
                        )
                    else:
                        MetalPriceHistory.objects.create(
                            global_metal=metal_obj,
                            price=price_24k,
                            price_on_date=fetched_at,
                        )
                except Exception as db_error:
                    db_failures += 1
                    logger.warning(
                        f"Error updating price history for {metal_obj.name}: {db_error}"
                    )
            close_old_connections()

        # Log summary of fetch results
        if failed_fetches > 0:
            logger.warning(
                f"Metal price fetch: {successful_fetches}/{total_metals} successful, "
                f"{failed_fetches} failed"
            )
        if db_failures > 0:
            logger.warning(
                f"Metal price history updates failed for {db_failures} metals"
            )
        else:
            logger.info(
                f"Metal price fetch: {successful_fetches}/{total_metals} successful"
            )

        # Publish the live metal prices to Redis (only if we have some successful fetches)
        if live_metal_prices:
            try:
                if redis_client:
                    redis_client.publish(
                        settings.METAL_PRICE_PUBSUB_CHANNEL_NAME,
                        json.dumps(live_metal_prices),
                    )
                else:
                    logger.error(
                        "Redis not available - cannot publish metal prices. "
                        "This indicates a Redis connectivity issue."
                    )
            except Exception as e:
                logger.error(f"Failed to publish metal prices to Redis: {e}")

    except SoftTimeLimitExceeded:
        logger.warning("Metal price fetch task exceeded soft time limit (90s)")
        return
    except Exception as e:
        logger.warning(f"Unexpected error in fetch_live_metal_prices task: {e}")
    finally:
        # Always release the lock
        if redis_client:
            try:
                release_lock(redis_client, lock_key)
            except Exception as e:
                logger.debug(f"Error releasing lock: {e}")
        # Ensure DB connections from this task are closed
        close_old_connections()


@shared_task
def send_mail(
    subject,
    template_name,
    context,
    to_emails,
    language_code="en",
    attachments=None,
    organization_code=None,
    from_email=None,
    bcc_emails=None,
):
    # Close any stale database connections before starting
    close_old_connections()

    # Ensure to_emails is a list
    to_emails = to_emails if isinstance(to_emails, list) else [to_emails]
    # Use custom from_email if provided, otherwise use default
    from_email = from_email or settings.EMAIL_HOST_USER
    # Ensure bcc_emails is a list if provided
    bcc_emails = (
        bcc_emails
        if isinstance(bcc_emails, list)
        else ([bcc_emails] if bcc_emails else None)
    )

    # Activate translation
    translation.activate(language_code)

    # Render the HTML email template with context
    html_message = render_to_string(template_name, context)
    # Strip HTML tags to create a plain text version
    plain_message = strip_tags(html_message)

    try:
        # Create the email message
        email = EmailMultiAlternatives(
            subject=subject,
            body=plain_message,
            from_email=from_email,
            to=to_emails,
            bcc=bcc_emails,
        )

        image_attached = False

        # Attach organization logo from S3
        if organization_code:
            try:
                org = Organization.objects.filter(code=organization_code).first()
                if org and org.logo:
                    logo_url_data = get_presigned_url_from_s3(org.logo)
                    if logo_url_data and logo_url_data.get("url"):
                        try:
                            response = requests.get(logo_url_data["url"])
                            if response.status_code == 200:
                                mime_type, _ = mimetypes.guess_type(
                                    logo_url_data["url"]
                                )
                                subtype = (
                                    mime_type.split("/")[1] if mime_type else "png"
                                )
                                image = MIMEImage(response.content, _subtype=subtype)
                                image.add_header("Content-ID", "<sqagoldenlogo>")
                                image.add_header("Content-Disposition", "inline")
                                image.add_header("Content-Transfer-Encoding", "base64")
                                email.attach(image)
                                image_attached = True
                        except Exception:
                            pass  # Silently fail and fallback to static
            finally:
                # Close connections after database query
                close_old_connections()

        # Fallback to static image
        if not image_attached:
            static_logo_path = os.path.join(
                settings.BASE_DIR, "static", "images", "sqa_golden_logo.png"
            )
            if os.path.exists(static_logo_path):
                with open(static_logo_path, "rb") as img_file:
                    image = MIMEImage(img_file.read())
                    image.add_header("Content-ID", "<sqagoldenlogo>")
                    image.add_header("Content-Disposition", "inline")
                    image.add_header("Content-Transfer-Encoding", "base64")
                    email.attach(image)

        # Attach HTML alternative
        email.attach_alternative(html_message, "text/html")

        # Optional attachments
        if attachments:
            for filename, file_content, mime_type in attachments:
                email.attach(filename, file_content, mime_type)

        # Send email
        email.send()

    except Exception as e:
        logger.exception(f"Error sending email to {to_emails}: {str(e)}")
    finally:
        # Always close connections after task completion
        close_old_connections()


@shared_task
def send_notification(
    device_tokens,
    title,
    body,
    data=None,
    web_push_config: messaging.WebpushConfig = None,
):
    """Send FCM notification to a specific user."""
    # Check if the firebase app is enabled.
    if not settings.FIREBASE_APP:
        logger.warning("Firebase app is not enabled.")
        return
    # Send push notifications to all users using firebase cloud messaging.
    successful_tokens = []
    failed_tokens = {}
    for token in device_tokens:
        shortened_token = token
        try:
            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                token=token,
                webpush=web_push_config,
                android=messaging.AndroidConfig(
                    notification=messaging.AndroidNotification(
                        channel_id="default"  # Setting the channel_id for Android notifications
                    )
                ),
                apns=messaging.APNSConfig(
                    headers={"apns-priority": "10"},
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            sound="notification_sound.wav",  # iOS sound file
                            alert=messaging.ApsAlert(title=title, body=body),
                            badge=1,
                            content_available=True,
                        )
                    ),
                ),
                data=data,
            )
            messaging.send(message)
            successful_tokens.append(shortened_token)
        # Firebase raised an exception incase it fails to send the notification, so catch the error that is raised for token.
        except Exception as e:
            failed_tokens[shortened_token] = str(e)

    logger.info(
        f"Successfully sent out notifications to {len(successful_tokens)} devices: {successful_tokens}"
    )
    if failed_tokens:
        FCMToken.objects.filter(fcm_token__in=failed_tokens.keys()).delete()
        logger.info(f"Deleted {len(failed_tokens)} invalid FCM tokens.")


@shared_task
def generate_pdf_response(template_name, context, filename="document.pdf"):
    """Generates a PDF file from a template and context and returns it as a download response."""

    html_string = render_to_string(template_name, context)
    pdf_file = HTML(string=html_string).write_pdf()

    response = HttpResponse(pdf_file, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@shared_task
def send_notification_to_admin_for_no_investor_in_musharakah_contract_request():
    """
    Send notifications to admins for Musharakah Contract Requests with no investors assigned.

    This Celery task scans all MusharakahContractRequest records created more than 2 weeks ago
    that have not yet been assigned to any investor. For each of these, it sends a notification
    to the organization's administrators to inform them that the contract is still unassigned.
    """

    cutoff = timezone.now() - timedelta(days=14)
    musharakah_contract_requests = MusharakahContractRequest.objects.filter(
        created_at=cutoff,
        investor__isnull=True,
    )
    for musharakah_contract_request in musharakah_contract_requests:
        title = f"Action Required: Investor Not Assigned to Contract Request"
        message = f"The Musharakah Contract Request with ID {musharakah_contract_request.id} remains without an investor assignment."
        send_notifications_to_organization_admins(
            musharakah_contract_request.organization_id.code,
            title,
            message,
            NotificationTypes.NO_INVESTOR_ASSIGNED_TO_MUSHARAKAH_CONTRACT_REQUEST,
            ContentType.objects.get_for_model(MusharakahContractRequest),
            musharakah_contract_request.id,
            UserRoleChoices.TAQABETH_ENFORCER,
        )


@shared_task
def send_notification_to_admin_for_close_pool():
    """
    Send notifications to admins for Pools that were closed today.

    This task should to update status and notify admins that Pool has been closed.
    """
    now = timezone.now()
    pools = (
        Pool.objects.filter(status=PoolStatus.OPEN)
        .annotate(
            close_date=ExpressionWrapper(
                F("created_at")
                + Func(days=F("pool_duration"), function="make_interval"),
                output_field=DateTimeField(),
            )
        )
        .filter(close_date__lte=now)  # Pool duration expired
    )

    for pool in pools:
        pool.status = PoolStatus.CLOSED
        pool.save()
        title = f"Pool has been closed successfully."
        message = f"The pool with ID {pool.id} has been closed successfully."
        send_notifications_to_organization_admins(
            pool.organization_id.code,
            title,
            message,
            NotificationTypes.POOL_CLOSED_DATE_UPDATED,
            ContentType.objects.get_for_model(Pool),
            pool.id,
            UserRoleChoices.TAQABETH_ENFORCER,
        )


@shared_task(
    bind=True,
    autoretry_for=(Transaction.DoesNotExist,),
    retry_kwargs={"max_retries": 3, "countdown": 1},
)
def send_purchase_request_email(
    self, transaction_id, from_wallet_id, organization_id, recipients
):
    """This helper method sends an email for the tax invoice of a purchase request."""
    try:
        # Add a small delay to ensure the database transaction is committed
        import time

        time.sleep(0.1)

        # Retrieve necessary objects
        transaction = Transaction.objects.get(pk=transaction_id)
        from_wallet = Wallet.objects.get(pk=from_wallet_id)
        organization = Organization.objects.get(pk=organization_id)
    except Transaction.DoesNotExist as e:
        logger.warning(
            f"Transaction not found in send_purchase_request_email: {e}. "
            f"Transaction ID: {transaction_id}, Wallet ID: {from_wallet_id}, Organization ID: {organization_id}. "
            f"Retrying..."
        )
        raise  # Retry the task

    except (Wallet.DoesNotExist, Organization.DoesNotExist) as e:
        logger.exception(
            f"Error retrieving objects in send_purchase_request_email: {e}. "
            f"Transaction ID: {transaction_id}, Wallet ID: {from_wallet_id}, Organization ID: {organization_id}"
        )
        return

    try:
        # Prepare context for the email and PDF attachment
        serialized_transaction = TransactionResponseSerializer(transaction).data
        context = generate_tax_invoice_context(serialized_transaction, organization)
        context["organization_logo_url"] = get_organization_logo_url(organization)
        template_name = "invoice/tax-invoice.html"
        filename = "Tax-Invoice.pdf"

        # Generate PDF for tax invoice
        pdf_io = render_subscription_invoice_pdf(template_name, context)
        attachment = [(filename, pdf_io.read(), "application/pdf")]

        # Prepare email context
        email_context = {
            "business_name": get_business_display_name(from_wallet.business),
            "transaction_id": transaction.receipt_number,
            "date": transaction.created_at.date(),
            "amount": transaction.amount,
            "organization_logo_url": context["organization_logo_url"],
        }

        # Send the email with the PDF attachment
        send_mail.delay(
            subject="Transaction Details",
            template_name="templates/transaction-details.html",
            context=email_context,
            to_emails=recipients,
            attachments=attachment,
            from_email=settings.ORGANIZATION_BILLING_EMAIL,
            bcc_emails=settings.ORGANIZATION_ACCOUNTS_EMAIL,
        )

        logger.info("send_mail task dispatched successfully.")

    except Exception as e:
        logger.exception(f"Unexpected error in send_purchase_request_email: {e}")


@shared_task
def send_receipt_to_mail(
    recipient_email, email_context, pdf_context, template_name, filename
):
    pdf_io = render_subscription_invoice_pdf(template_name, pdf_context)
    attachment = [(filename, pdf_io.read(), "application/pdf")]

    send_mail.delay(
        subject="Transaction Details",
        template_name="templates/transaction-details.html",
        context=email_context,
        to_emails=[recipient_email],
        attachments=attachment,
        from_email=settings.ORGANIZATION_BILLING_EMAIL,
        bcc_emails=settings.ORGANIZATION_ACCOUNTS_EMAIL,
    )


@shared_task
def close_replacement_musharakah_contract_request():
    """
    Close replacement Musharakah contract requests that were created after
    an investor-terminated contract but have not attracted a new investor
    within 60 days. Sends notifications for each closed contract request.
    """
    from collections import defaultdict

    from django.db import transaction
    from django.db.utils import OperationalError

    try:
        cutoff_date = timezone.now() - timedelta(days=60)

        musharakah_contract_requests = MusharakahContractRequest.objects.select_related(
            "organization_id"
        ).filter(
            terminated_musharakah_contract__isnull=False,
            investor__isnull=True,
            created_at__lte=cutoff_date,
        )

        # Convert to list to avoid re-evaluating queryset
        contract_requests_list = list(musharakah_contract_requests)

        if not contract_requests_list:
            logger.info("No replacement musharakah contract requests to close.")
            return

        closed_count = 0
        notification_count = 0
        errors = []

        # Get ContentType once to avoid repeated queries
        content_type = ContentType.objects.get_for_model(MusharakahContractRequest)

        # Update all contract requests in bulk to avoid N+1 queries
        with transaction.atomic():
            for musharakah_contract_request in contract_requests_list:
                musharakah_contract_request.musharakah_contract_status = (
                    MusharakahContractStatus.CLOSED
                )

            # Bulk update all records at once
            MusharakahContractRequest.objects.bulk_update(
                contract_requests_list,
                ["musharakah_contract_status"],
                batch_size=100,
            )
            closed_count = len(contract_requests_list)

        # Group contract requests by organization to batch notifications
        # This avoids querying the same organization's admins multiple times
        org_contract_map = defaultdict(list)
        for musharakah_contract_request in contract_requests_list:
            organization = musharakah_contract_request.organization_id
            if not organization:
                logger.warning(
                    f"Organization not found for contract request {musharakah_contract_request.id}"
                )
                errors.append(
                    f"Organization not found for contract request {musharakah_contract_request.id}"
                )
                continue
            org_contract_map[organization].append(musharakah_contract_request)

        # Send notifications grouped by organization
        # Cache admin users per organization to avoid repeated queries
        title = "Musharakah Contract Requests Closed"
        message = "Musharakah contract requests have been closed as no investor joined within the 60-day period."
        notification_type = NotificationTypes.MUSHARAKAH_CONTRACT_REQUESTS_CLOSED

        # Get admin users role list once
        role = [UserRoleChoices.ADMIN, UserRoleChoices.TAQABETH_ENFORCER]

        for organization, org_contracts in org_contract_map.items():
            try:
                # Fetch admin users once per organization to avoid repeated queries
                admin_users = User.objects.filter(
                    organization_id=organization,
                    user_roles__role__in=role,
                ).distinct()

                if not admin_users.exists():
                    logger.warning(
                        f"No admin users found for organization {organization.id}"
                    )
                    continue

                # Create all notifications for this organization's contract requests at once
                all_notifications = []

                for musharakah_contract_request in org_contracts:
                    # Create notification for each admin user for this contract request
                    for user in admin_users:
                        all_notifications.append(
                            Notification(
                                user=user,
                                title=title,
                                message=message,
                                notification_type=notification_type,
                                content_type=content_type,
                                object_id=musharakah_contract_request.id,
                            )
                        )
                    notification_count += 1

                # Bulk create all notifications at once
                if all_notifications:
                    Notification.objects.bulk_create(
                        all_notifications, ignore_conflicts=True
                    )

                    # Send WebSocket notifications for each contract request
                    # (one per contract request to match original behavior)
                    for musharakah_contract_request in org_contracts:
                        try:
                            send_notification_to_group(
                                organization.code,
                                data={
                                    "title": title,
                                    "body": message,
                                    "object_id": musharakah_contract_request.id,
                                    "notification_type": notification_type,
                                },
                                message="Success",
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to send WebSocket notification for contract request {musharakah_contract_request.id}: {e}"
                            )

            except Exception as e:
                logger.error(
                    f"Error sending notifications for organization {organization.id}: {e}"
                )
                errors.append(f"Error for organization {organization.id}: {str(e)}")

        logger.info(
            f"Closed {closed_count} replacement musharakah contract requests. "
            f"Sent {notification_count} notifications. Errors: {len(errors)}"
        )

        if errors:
            logger.warning(
                f"Encountered {len(errors)} errors during processing: {errors[:5]}"
            )

    except OperationalError as e:
        # Handle database connection errors at the task level
        logger.error(
            f"Database connection error in close_replacement_musharakah_contract_request: {e}"
        )
        raise  # Re-raise to trigger Celery retry if configured
    except Exception as e:
        logger.exception(
            f"Unexpected error in close_replacement_musharakah_contract_request: {e}"
        )
        raise


@shared_task
def send_termination_reciept_mail(
    user_id,
    organization_id,
    business_id,
    transaction_id,
    musharakah_contract_termination_request_id,
    subject,
    sub_total,
    title,
):
    from account.models import BusinessAccount
    from account.models import Organization
    from account.models import Transaction
    from investor.serializers import TransactionResponseSerializer
    from jeweler.models import MusharakahContractTerminationRequest
    from sooq_althahab.billing.subscription.helpers import prepare_organization_details
    from sooq_althahab.billing.subscription.pdf_utils import (
        render_subscription_invoice_pdf,
    )
    from sooq_althahab.billing.transaction.helpers import get_organization_logo_url

    # Fetch model instances inside the task
    user = User.objects.get(pk=user_id)
    organization = Organization.objects.get(pk=organization_id)
    business = BusinessAccount.objects.get(pk=business_id)
    transaction = Transaction.objects.get(id=transaction_id)
    musharakah_contract_termination_request = (
        MusharakahContractTerminationRequest.objects.get(
            pk=musharakah_contract_termination_request_id
        )
    )
    if transaction.payment_completed_at:
        date = transaction.payment_completed_at.strftime("%d %B %Y")
    else:
        date = transaction.created_at.strftime("%d %B %Y")

    transaction_serializer = TransactionResponseSerializer(transaction).data
    organization_details = prepare_organization_details(organization)

    # Safe display name
    business_name = business.name or ""
    user_fullname = user.fullname or ""
    display_name = business_name or user_fullname or user.email or "Customer"
    user_details = get_user_contact_details(user.pk)
    user_details["user_fullname"] = user.fullname or ""
    user_details["id"] = user.personal_number or ""
    user_details["phone_number"] = user.phone_number or ""

    email_context = {
        "organization_name": organization.name,
        "business_name": business_name,
        "user_fullname": user.fullname or "",
        "display_name": display_name,
        "transaction_id": transaction.receipt_number,
        "date": date,
        "amount": transaction.amount,
        "organization_logo_url": get_organization_logo_url(organization),
    }

    # Get business owner email safely
    owner_assignment = business.user_assigned_businesses.filter(is_owner=True).first()
    business_user_email = owner_assignment.user.email if owner_assignment else ""

    pdf_context = {
        "user_details": user_details,
        "display_name": display_name,
        "business": business,
        "business_user": {"email": business_user_email},
        "organization_details": organization_details,
        "transaction": transaction_serializer,
        "organization_logo_url": get_organization_logo_url(organization),
        "termination_request": musharakah_contract_termination_request,
        "sub_total_amount": sub_total,
        "title": title,
        "penalty_amount": musharakah_contract_termination_request.musharakah_contract_request.penalty_amount,
        "date": date,
    }

    template_name = "musharakah_contract/tax-invoice.html"
    pdf_io = render_subscription_invoice_pdf(template_name, pdf_context)

    send_termination_reciept_email(
        [user.email],
        email_context,
        pdf_io,
        subject,
    )


@shared_task
def manage_subscription_expiration_notifications():
    """
    Comprehensive subscription expiration management task that handles:
    1. Sending notifications for subscriptions expiring in 3, 2, and 1 days
    2. Sending email notifications for subscriptions expiring today
    3. Sending both in-app and email notifications

    This task runs daily to check for subscriptions at various stages of expiration.
    Note: Subscription expiration (status change) is handled by process_subscription_fee_recurring_payment
    task. This task only handles notifications.
    """
    from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
    from sooq_althahab.subscription_notification_utils import (
        handle_expiring_subscriptions_today,
    )
    from sooq_althahab.subscription_notification_utils import (
        send_expiration_notifications,
    )

    today = timezone.now().date()
    tomorrow = today + timedelta(days=1)
    two_days_from_now = today + timedelta(days=2)
    three_days_from_now = today + timedelta(days=3)

    logger.info(
        f"Starting comprehensive subscription expiration management for {today}"
    )

    # Track statistics
    stats = {
        "notifications_sent": 0,
        "subscriptions_expired": 0,
        "errors": 0,
    }

    # 1. Send notifications for subscriptions expiring in 3 days
    send_expiration_notifications(
        expiring_date=three_days_from_now,
        notification_type=NotificationTypes.BUSINESS_SUBSCRIPTION_EXPIRING_IN_3_DAYS,
        days_until_expiry=3,
        stats=stats,
    )

    # 2. Send notifications for subscriptions expiring in 2 days
    send_expiration_notifications(
        expiring_date=two_days_from_now,
        notification_type=NotificationTypes.BUSINESS_SUBSCRIPTION_EXPIRING_SOON,
        days_until_expiry=2,
        stats=stats,
    )

    # 3. Send notifications for subscriptions expiring tomorrow (1 day)
    send_expiration_notifications(
        expiring_date=tomorrow,
        notification_type=NotificationTypes.BUSINESS_SUBSCRIPTION_EXPIRING_SOON,
        days_until_expiry=1,
        stats=stats,
    )

    # 4. Send email notifications for subscriptions expiring today
    # Note: Expiration (status change) is handled by process_subscription_fee_recurring_payment task
    handle_expiring_subscriptions_today(today, stats)

    logger.info(
        f"Completed subscription expiration management. "
        f"Notifications sent: {stats['notifications_sent']}, "
        f"Subscriptions expired: {stats['subscriptions_expired']}, "
        f"Errors: {stats['errors']}"
    )
