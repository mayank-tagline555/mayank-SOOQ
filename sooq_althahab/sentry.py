import os

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration


def before_send_transaction(event, hint):
    """Ignore traces from specific Celery tasks."""
    transaction_name = event.get("transaction", "")
    if "fetch_live_metal_prices" in transaction_name:
        return None
    return event


def before_send(event, hint):
    """Optional: Suppress specific exceptions here if needed."""
    # Ignore webhook status mismatch warnings - these are expected duplicate/delayed webhooks
    # that are handled correctly by the system
    if event.get("level") in ("error", "warning"):
        # Check top-level message
        message = event.get("message", "")
        if isinstance(message, str):
            if "WEBHOOK_STATUS_MISMATCH" in message:
                return None
            if "Webhook shows FAILURE but subscription is already ACTIVE" in message:
                return None

        # Check breadcrumbs (can be list or dict with 'values' key)
        breadcrumbs = event.get("breadcrumbs")
        if breadcrumbs:
            # Handle list format
            if isinstance(breadcrumbs, list):
                for crumb in breadcrumbs:
                    if isinstance(crumb, dict):
                        crumb_message = crumb.get("message", "")
                        if isinstance(crumb_message, str):
                            if "WEBHOOK_STATUS_MISMATCH" in crumb_message:
                                return None
                            if (
                                "Webhook shows FAILURE but subscription is already ACTIVE"
                                in crumb_message
                            ):
                                return None
            # Handle dict format with 'values' key
            elif isinstance(breadcrumbs, dict):
                values = breadcrumbs.get("values", [])
                if isinstance(values, list):
                    for crumb in values:
                        if isinstance(crumb, dict):
                            crumb_message = crumb.get("message", "")
                            if isinstance(crumb_message, str):
                                if "WEBHOOK_STATUS_MISMATCH" in crumb_message:
                                    return None
                                if (
                                    "Webhook shows FAILURE but subscription is already ACTIVE"
                                    in crumb_message
                                ):
                                    return None

        # Check log entry messages
        logentry = event.get("logentry", {})
        if isinstance(logentry, dict):
            formatted = logentry.get("formatted", "")
            if isinstance(formatted, str):
                if "WEBHOOK_STATUS_MISMATCH" in formatted:
                    return None
                if (
                    "Webhook shows FAILURE but subscription is already ACTIVE"
                    in formatted
                ):
                    return None

            # Check message field in logentry
            log_message = logentry.get("message", "")
            if isinstance(log_message, str):
                if "WEBHOOK_STATUS_MISMATCH" in log_message:
                    return None
                if (
                    "Webhook shows FAILURE but subscription is already ACTIVE"
                    in log_message
                ):
                    return None

    return event


def init_sentry():
    """Initialize Sentry if enabled."""
    if os.getenv("SENTRY_ENABLED", "0").lower() != "1":
        return

    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        raise RuntimeError(
            "SENTRY is enabled, but SENTRY_DSN is not set. Please provide a valid DSN URL."
        )

    sentry_sdk.init(
        dsn=dsn,
        integrations=[DjangoIntegration()],
        send_default_pii=True,
        traces_sample_rate=1.0,
        _experiments={"continuous_profiling_auto_start": True},
        before_send_transaction=before_send_transaction,
        before_send=before_send,
    )
