"""
API view to suspend business subscription plan by admin.
Allows admin to suspend subscription for a given business.
"""

import logging

from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from sooq_althahab.constants import BUSINESS_SUBSCRIPTION_CHANGE_PERMISSION
from sooq_althahab.helper import PermissionManager
from sooq_althahab.payment_gateway_services.credimax.subscription.serializers import (
    SuspendBusinessSubscriptionPlanSerializer,
)
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab_admin.message import MESSAGES

logger = logging.getLogger(__name__)


class SuspendBusinessSubscriptionPlanAPIView(APIView):
    """
    POST API for business subscription plan that will allow the admin to suspend
    the subscription plan for a given business.

    This API suspends a business subscription, preventing the business from logging in.
    This is particularly useful for businesses on free trial plans that need to be
    forced to upgrade to a paid plan (which requires card details).

    Takes business_id in payload and suspends the subscription.

    Expected payload:
    {
        "business_id": "bus_123456789"
    }

    Returns:
    {
        "success": true,
        "message": "Business subscription suspended successfully",
        "data": {
            "subscription_id": "bsp_123456789",
            "business_name": "Business Name",
            "subscription_status": "SUSPENDED",
            "previous_status": "TRIALING",
            "suspended_at": "2024-01-15T10:30:00Z",
            "message": "Business subscription for 'Business Name' has been suspended successfully..."
        }
    }
    """

    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Suspend business subscription plan for a given business. This API suspends a business subscription, preventing the business from logging in.",
        request_body=SuspendBusinessSubscriptionPlanSerializer,
    )
    @PermissionManager(BUSINESS_SUBSCRIPTION_CHANGE_PERMISSION)
    def post(self, request):
        """
        Suspend business subscription plan for a given business.

        Expected payload:
        {
            "business_id": "bus_123456789"
        }

        Returns:
        {
            "success": true,
            "message": "Business subscription suspended successfully",
            "data": {
                "subscription_id": "bsp_123456789",
                "business_name": "Business Name",
                "subscription_status": "SUSPENDED",
                "previous_status": "TRIALING",
                "suspended_at": "2024-01-15T10:30:00Z",
                "message": "..."
            }
        }
        """
        serializer = SuspendBusinessSubscriptionPlanSerializer(
            data=request.data, context={"request": request}
        )

        if serializer.is_valid():
            try:
                result = serializer.save()

                # Log successful suspension
                logger.info(
                    f"✅ API SUCCESS: Subscription suspended successfully for business {result.get('business_name')}"
                )

                return generic_response(
                    data=result,
                    message=MESSAGES["business_subscription_suspended"],
                    status_code=status.HTTP_200_OK,
                )

            except Exception as e:
                logger.exception("❌ API ERROR: Error suspending business subscription")
                return generic_response(
                    error_message=f"Failed to suspend business subscription: {str(e)}",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return handle_serializer_errors(serializer)
