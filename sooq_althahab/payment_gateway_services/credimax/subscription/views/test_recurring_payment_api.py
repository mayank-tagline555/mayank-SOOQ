"""
API view to test recurring payment tasks for subscription fee and pro-rata billing.
This allows frontend team to test recurring payments via API instead of server console.
"""

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from account.models import BusinessAccount
from sooq_althahab.payment_gateway_services.credimax.subscription.tasks import (
    process_pro_rata_recurring_payment,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.tasks import (
    process_subscription_fee_recurring_payment,
)

logger = logging.getLogger(__name__)


class TestSubscriptionFeeRecurringPaymentAPIView(APIView):
    """
    API endpoint to test subscription fee recurring payment task for a specific business.

    This endpoint triggers the process_subscription_fee_recurring_payment task,
    which handles fixed subscription fees for:
    - Sellers
    - Manufacturers
    - Jewelers (subscription fee part only, not commission)
    - Investors (non-pro-rata plans only)

    Expected payload:
    {
        "business_id": "bus_311225d1294a"
    }

    Returns:
    {
        "success": true,
        "message": "Subscription fee recurring payment task initiated successfully",
        "data": {
            "business_id": "bus_311225d1294a",
            "business_name": "Business Name",
            "task": "process_subscription_fee_recurring_payment"
        }
    }
    """

    permission_classes = [AllowAny]
    authentication_classes = []  # Explicitly disable authentication

    def post(self, request):
        """
        Trigger subscription fee recurring payment task for a specific business.
        """
        try:
            # Extract business_id from request
            business_id = request.data.get("business_id")

            # Validate required fields
            if not business_id:
                return Response(
                    {"success": False, "error": "business_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Validate business exists
            try:
                business = BusinessAccount.objects.get(id=business_id)
            except BusinessAccount.DoesNotExist:
                return Response(
                    {
                        "success": False,
                        "error": f"Business with ID '{business_id}' not found",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Call the task function synchronously (not as a Celery task)
            # This allows us to execute it immediately and get the result
            logger.info(
                f"[TEST-API] Triggering subscription fee recurring payment for business: {business_id}"
            )

            # Call the task function directly (it's decorated with @shared_task but can be called directly)
            process_subscription_fee_recurring_payment(business_id=business_id)

            return Response(
                {
                    "success": True,
                    "message": "Subscription fee recurring payment task completed successfully",
                    "data": {
                        "business_id": business_id,
                        "business_name": business.name,
                        "task": "process_subscription_fee_recurring_payment",
                    },
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(
                f"Error in test subscription fee recurring payment API: {str(e)}"
            )
            import traceback

            logger.error(f"Error traceback: {traceback.format_exc()}")
            return Response(
                {"success": False, "error": f"Internal server error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class TestProRataRecurringPaymentAPIView(APIView):
    """
    API endpoint to test pro-rata recurring payment task for a specific business.

    This endpoint triggers the process_pro_rata_recurring_payment task,
    which handles investor pro-rata fees:
    - PREPAID Investors: Recalculate and deduct for remaining assets
    - POSTPAID Investors: Charge accumulated pro-rata from previous year

    Expected payload:
    {
        "business_id": "bus_311225d1294a"
    }

    Returns:
    {
        "success": true,
        "message": "Pro-rata recurring payment task initiated successfully",
        "data": {
            "business_id": "bus_311225d1294a",
            "business_name": "Business Name",
            "task": "process_pro_rata_recurring_payment"
        }
    }
    """

    permission_classes = [AllowAny]
    authentication_classes = []  # Explicitly disable authentication

    def post(self, request):
        """
        Trigger pro-rata recurring payment task for a specific business.
        """
        try:
            # Extract business_id from request
            business_id = request.data.get("business_id")

            # Validate required fields
            if not business_id:
                return Response(
                    {"success": False, "error": "business_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Validate business exists
            try:
                business = BusinessAccount.objects.get(id=business_id)
            except BusinessAccount.DoesNotExist:
                return Response(
                    {
                        "success": False,
                        "error": f"Business with ID '{business_id}' not found",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Call the task function synchronously (not as a Celery task)
            logger.info(
                f"[TEST-API] Triggering pro-rata recurring payment for business: {business_id}"
            )

            # Call the task function directly (it's decorated with @shared_task but can be called directly)
            process_pro_rata_recurring_payment(business_id=business_id)

            return Response(
                {
                    "success": True,
                    "message": "Pro-rata recurring payment task completed successfully",
                    "data": {
                        "business_id": business_id,
                        "business_name": business.name,
                        "task": "process_pro_rata_recurring_payment",
                    },
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Error in test pro-rata recurring payment API: {str(e)}")
            import traceback

            logger.error(f"Error traceback: {traceback.format_exc()}")
            return Response(
                {"success": False, "error": f"Internal server error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
