import logging
import mimetypes

import boto3
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.http import Http404
from django.http import JsonResponse
from django.utils.encoding import force_str
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import exception_handler
from rest_framework.viewsets import ModelViewSet

from account.models import Organization
from account.models import User
from seller.utils import get_fcm_tokens_for_users
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab_admin.models import Notification

from .messages import MESSAGES

logger = logging.getLogger(__name__)

# Create an S3 client
s3 = boto3.client(
    "s3",
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name=settings.AWS_S3_REGION_NAME,
)


def build_error_response(error_type, detail, status_code, use_drf=True):
    payload = {
        "success": False,
        "error": {
            "type": error_type,
            "detail": detail,
            "status_code": status_code,
        },
    }
    if use_drf:
        return Response(payload, status=status_code)
    return JsonResponse(payload, status=status_code)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        return build_error_response(
            exc.__class__.__name__, response.data, response.status_code
        )

    return build_error_response(
        "ServerError",
        "Something went wrong on the server.",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


class CommonPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"


class CustomModelViewSet(ModelViewSet):
    def get_object(self):
        try:
            get_object = super().get_object()
        except Http404:
            raise Http404(
                generic_response(
                    status.HTTP_404_NOT_FOUND, MESSAGES["not_found_error"]
                ).data
            )
        return get_object


def generic_response(
    data=None, message=None, error_message=None, status_code=status.HTTP_200_OK
):
    """
    Generates a standardized HTTP response with a given status code, message, optional data, and
    optional developer-specific error message.

    Args:
        status_code (int, optional): HTTP status code for the response. Defaults to 200 (OK).
        message (str, optional): Message to include in the response body. Defaults to None.
        data (any, optional): Additional data to include in the response body. Defaults to None.
        dev_error_message (str, optional): A developer-specific error message for debugging.
                                           Defaults to None.

    Returns:
        Response: A DRF (Django Rest Framework) Response object with 'statusCode', 'message',
        'data', and optionally 'dev_error' fields.
    """
    response_body = {
        "status_code": status_code,
        "message": message,
        "data": data,
    }
    # Only include the dev_error field if a message is provided
    if error_message:
        response_body["error"] = error_message
    return Response(response_body, status=status_code)


def handle_serializer_errors(serializer):
    """
    Helper function to handle serializer validation errors.
    Returns a dictionary with the error message and status code.
    """
    errors = serializer.errors
    error_messages = []

    # Collecting all error messages
    for field, messages in errors.items():
        if isinstance(messages, list):
            error_messages.append(
                f"{field}: {', '.join(force_str(msg) for msg in messages)}"
                if field != "non_field_errors"
                else f"{', '.join(force_str(msg) for msg in messages)}"
            )
        else:
            error_messages.append(
                f"{field}: {force_str(messages)}"
                if field != "non_field_errors"
                else force_str(messages)
            )

    error_message = " | ".join(error_messages)
    return generic_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        error_message=error_message,
    )


def handle_validation_error(validation_error):
    """
    Helper function to handle ValidationError exceptions raised in serializer create/update methods.
    Extracts error message consistently and returns a formatted generic_response.

    Args:
        validation_error: ValidationError exception instance

    Returns:
        Response: A DRF Response object with standardized error format
    """
    ve = validation_error

    # Handle different ValidationError detail formats
    if isinstance(ve.detail, list):
        error_message = (
            ", ".join(str(msg) for msg in ve.detail) if ve.detail else str(ve)
        )
    elif isinstance(ve.detail, dict):
        # If it's a dict, format it similar to handle_serializer_errors
        error_messages = []
        for field, messages in ve.detail.items():
            if isinstance(messages, list):
                error_messages.append(
                    f"{field}: {', '.join(str(msg) for msg in messages)}"
                    if field != "non_field_errors"
                    else f"{', '.join(str(msg) for msg in messages)}"
                )
            else:
                error_messages.append(
                    f"{field}: {str(messages)}"
                    if field != "non_field_errors"
                    else str(messages)
                )
        error_message = " | ".join(error_messages)
    else:
        error_message = str(ve.detail) if ve.detail else str(ve)

    return generic_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        error_message=error_message,
    )


def get_presigned_url_from_s3(object_name):
    """Generate a presigned URL for an S3 object with inferred file type."""
    if not object_name:
        return None

    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": object_name},
            ExpiresIn=settings.S3_FILE_EXPIRATION_DURATION,
        )

        # Infer file type based on filename extension
        file_type, _ = mimetypes.guess_type(object_name)
        file_type = file_type or "application/octet-stream"

        return {"url": url, "file_type": file_type}

    except Exception:
        logger.error(f"Error generating presigned URL for object {object_name}")
        return None


def send_notification_to_group(org_code, data={}, message=""):
    """
    Utility function to send notifications to a WebSocket group.
    Args:
        org_id (str): The group name to which the message will be sent.
        message (str): The message content to send.
    """
    channel_layer = get_channel_layer()

    # Send a message to the group
    async_to_sync(channel_layer.group_send)(
        f"notifications_{org_code}",  # The group name (e.g., 'notifications_org_code')
        {"type": "notification_message", "data": data, "message": message},
    )


def send_notification_count_to_users(users):
    """
    Utility function to send notifications to a WebSocket group.
    Args:
        org_id (str): The group name to which the message will be sent.
        message (str): The message content to send.
    """
    channel_layer = get_channel_layer()
    for user in users:
        count = Notification.objects.filter(user=user, is_read=False).count()
        # Send a message to the group
        async_to_sync(channel_layer.group_send)(
            f"notifications_{user.pk}",  # The group name (e.g., 'notifications_user_id')
            {"type": "notification_count", "count": count},
        )


def send_notifications_to_organization_admins(
    org_code,
    title,
    body,
    notification_type,
    content_type,
    object_id,
    sub_admin,
):
    """Send notifications to all admins (and optionally sub-admins) of a specific organization."""

    # Try to fetch the organization by its unique code
    try:
        organization = Organization.objects.get(code=org_code)
    except Organization.DoesNotExist:
        # If the organization doesn't exist, exit early
        return

    # Use the helper function with the organization object
    return send_notifications_to_organization_admins_with_org(
        organization, title, body, notification_type, content_type, object_id, sub_admin
    )


def send_notifications_to_organization_admins_with_org(
    organization,
    title,
    body,
    notification_type,
    content_type,
    object_id,
    sub_admin,
):
    """Send notifications to all admins (and optionally sub-admins) of a specific organization.

    This version accepts an organization object directly to avoid N+1 queries.
    Use this when you already have the organization object loaded.
    """

    # Start with the base role: ADMIN
    role = [UserRoleChoices.ADMIN]

    # If sub_admin is provided, extend the roles list accordingly
    if sub_admin and sub_admin == UserRoleChoices.TAQABETH_ENFORCER:
        role.append(UserRoleChoices.TAQABETH_ENFORCER)
    elif sub_admin and sub_admin == UserRoleChoices.JEWELLERY_INSPECTOR:
        role.append(UserRoleChoices.JEWELLERY_INSPECTOR)
    elif sub_admin and sub_admin == UserRoleChoices.JEWELLERY_BUYER:
        role.append(UserRoleChoices.JEWELLERY_BUYER)

    # Fetch users who belong to the given organization
    # and match any of the specified roles (ADMIN + optional sub-admin roles)
    admin_users = User.objects.filter(
        organization_id=organization,
        user_roles__role__in=role,
    )

    # Create notification objects for each matched user
    notifications = [
        Notification(
            user=user,
            title=title,
            message=body,
            notification_type=notification_type,
            content_type=content_type,
            object_id=object_id,
        )
        for user in admin_users
    ]

    # Bulk insert all notifications into the database for efficiency
    # Use ignore_conflicts=True to handle potential duplicate IDs from concurrent operations
    Notification.objects.bulk_create(notifications, ignore_conflicts=True)

    # Trigger sending of real-time notifications (e.g., via WebSocket, push, etc.)
    send_notification_to_group(
        organization.code,
        data={
            "title": title,
            "body": body,
            "object_id": object_id,
            "notification_type": notification_type,
        },
        message="Success",
    )

    # Return the list of admin users who received notifications
    return admin_users


def send_notifications(
    users,
    title,
    message,
    notification_type,
    content_type,
    object_id,
):
    """
    Sends notifications to specified users.

    This method retrieves the FCM tokens for the given users and sends push notifications asynchronously.
    Additionally, it creates in-app notification records for each user.
    """
    from sooq_althahab.tasks import send_notification

    tokens = get_fcm_tokens_for_users(list(users))

    if not tokens:
        return

    notifications = [
        Notification(
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
            content_type=content_type,
            object_id=object_id,
        )
        for user in users
    ]
    # Bulk insert all notifications, ignoring conflicts from concurrent operations
    Notification.objects.bulk_create(notifications, ignore_conflicts=True)

    # Serialize just **one** notification (since all are identical)
    notification_data = {
        "notification_type": notification_type,
        "id": str(object_id),
    }

    # Send a bulk push notification asynchronously
    send_notification_count_to_users(users)
    send_notification.delay(tokens, title, message, notification_data)


def validate_card_expiry_date(expiry_month, expiry_year):
    """
    Validate that a card expiry date is not in the past.

    Args:
        expiry_month (str): Two-digit month (e.g., "12" for December)
        expiry_year (str): Two-digit year (e.g., "25" for 2025) or four-digit year

    Returns:
        tuple: (is_valid: bool, error_message: str or None)

    Raises:
        ValueError: If expiry_month or expiry_year format is invalid
    """
    from datetime import datetime

    if not expiry_month or not expiry_year:
        return False, "Please enter your card's expiry date."

    try:
        # Convert to integers
        month = int(expiry_month)
        year = int(expiry_year)

        # Validate month range
        if month < 1 or month > 12:
            return (
                False,
                "Invalid card expiry date. Please check your card's expiry month and try again.",
            )

        # Handle two-digit years (assume 2000-2099)
        if year < 100:
            year += 2000

        # Get current date
        now = datetime.now()
        current_year = now.year
        current_month = now.month

        # Check if expiry date is in the past
        if year < current_year:
            return (
                False,
                "Your card has expired. Please use a card with a valid expiry date.",
            )

        if year == current_year and month < current_month:
            return (
                False,
                "Your card has expired. Please use a card with a valid expiry date.",
            )

        return True, None

    except ValueError:
        return (
            False,
            "Invalid card expiry date format. Please check your card's expiry date and try again.",
        )
