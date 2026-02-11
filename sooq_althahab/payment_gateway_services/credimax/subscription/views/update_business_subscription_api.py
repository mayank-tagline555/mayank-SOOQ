"""
API view to update business subscription plan by admin.
Allows admin to update subscription plan for a given business.
"""

import logging
from datetime import datetime
from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from account.models import UserAssignedBusiness
from sooq_althahab.enums.account import SubscriptionStatusChoices
from sooq_althahab.payment_gateway_services.credimax.subscription.serializers import (
    UpdateBusinessSubscriptionPlanSerializer,
)
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab_admin.message import MESSAGES
from sooq_althahab_admin.models import BusinessSubscriptionPlan
from sooq_althahab_admin.models import SubscriptionPlan

logger = logging.getLogger(__name__)


class UpdateBusinessSubscriptionPlanAPIView(APIView):
    """
    PATCH API for business subscription plan that will allow the admin to update
    the subscription plan for a given business.

    Takes subscription_id in payload admin wants to update for a given business
    and then updates it with all necessary changes to handle the update of
    subscription plan in business subscription plan like in billing cycle of
    that business, changes required in musharakah, jewelry design or any other.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request):
        """
        Update business subscription plan for a given business.

        Expected payload:
        {
            "business_id": "bus_123456789",
            "subscription_plan_id": "sp_987654321"
        }

        Returns:
        {
            "success": true,
            "message": "Business subscription plan updated successfully",
            "data": {
                "subscription_id": "bsp_123456789",
                "business_name": "Business Name",
                "old_plan_name": "Old Plan Name",
                "new_plan_name": "New Plan Name",
                "updated_fields": [...],
                "billing_impact": {
                    "old_billing_frequency": "MONTHLY",
                    "new_billing_frequency": "YEARLY",
                    "old_subscription_fee": "100.00",
                    "new_subscription_fee": "1200.00"
                }
            }
        }
        """
        serializer = UpdateBusinessSubscriptionPlanSerializer(
            data=request.data, context={"request": request}
        )

        if serializer.is_valid():
            try:
                result = serializer.save()

                # Log successful database update
                logger.info(
                    f"✅ API SUCCESS: Subscription plan updated successfully for business {result.get('business_name')}"
                )

                return generic_response(
                    data=result,
                    message=MESSAGES["business_subscription_plan_updated"],
                    status_code=status.HTTP_200_OK,
                )

            except Exception as e:
                logger.exception(
                    "❌ API ERROR: Error updating business subscription plan"
                )
                return generic_response(
                    error_message=f"Failed to update business subscription plan: {str(e)}",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return handle_serializer_errors(serializer)
