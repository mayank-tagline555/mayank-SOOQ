"""
API view to disable auto-renewal for business subscription plan by admin.
Allows admin to disable auto-renewal for a given business subscription.
"""

import logging

from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from sooq_althahab.constants import BUSINESS_SUBSCRIPTION_CHANGE_PERMISSION
from sooq_althahab.helper import PermissionManager
from sooq_althahab.payment_gateway_services.credimax.subscription.serializers import (
    CancelBusinessSubscriptionPlanSerializer,
)
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab_admin.message import MESSAGES

logger = logging.getLogger(__name__)


class CancelBusinessSubscriptionPlanAPIView(APIView):
    """
    POST API for business subscription plan that will allow the admin to disable
    auto-renewal for a given business subscription.

    This API disables auto-renewal for a subscription. The subscription will remain active
    until the expiry_date (end of current billing cycle), then it will expire and not renew.
    This prevents auto-renewal.

    Takes business_id in payload and disables auto-renewal.

    Expected payload:
    {
        "business_id": "bus_123456789"
    }

    Returns:
    {
        "success": true,
        "message": "Business subscription auto-renewal disabled successfully",
        "data": {
            "subscription_id": "bsp_123456789",
            "business_name": "Business Name",
            "subscription_status": "ACTIVE",
            "is_auto_renew": false,
            "expiry_date": "2024-12-31",
            "message": "Subscription auto-renewal has been disabled for Business Name. The subscription will remain active until December 31, 2024, after which it will expire and not renew."
        }
    }
    """

    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Disable auto-renewal for a business subscription plan. The subscription will remain active until the expiry_date, then it will expire and not renew.",
        request_body=CancelBusinessSubscriptionPlanSerializer,
    )
    @PermissionManager(BUSINESS_SUBSCRIPTION_CHANGE_PERMISSION)
    def post(self, request):
        """
        Disable auto-renewal for a business subscription plan.

        Expected payload:
        {
            "business_id": "bus_123456789"
        }

        Returns:
        {
            "success": true,
            "message": "Business subscription auto-renewal disabled successfully",
            "data": {
                "subscription_id": "bsp_123456789",
                "business_name": "Business Name",
                "subscription_status": "ACTIVE",
                "is_auto_renew": false,
                "expiry_date": "2024-12-31",
                "message": "..."
            }
        }
        """
        serializer = CancelBusinessSubscriptionPlanSerializer(
            data=request.data, context={"request": request}
        )

        if serializer.is_valid():
            try:
                result = serializer.save()

                # Log successful auto-renewal disable
                logger.info(
                    f"✅ API SUCCESS: Subscription auto-renewal disabled successfully for business {result.get('business_name')}"
                )

                return generic_response(
                    data=result,
                    message=MESSAGES["business_subscription_auto_renewal_disabled"],
                    status_code=status.HTTP_200_OK,
                )

            except Exception as e:
                logger.exception(
                    "❌ API ERROR: Error disabling business subscription auto-renewal"
                )
                return generic_response(
                    error_message=f"Failed to disable business subscription auto-renewal: {str(e)}",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return handle_serializer_errors(serializer)
