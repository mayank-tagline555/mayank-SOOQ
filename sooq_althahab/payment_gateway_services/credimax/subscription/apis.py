"""
Credimax Subscription Payment Integration — API Views
------------------------------------------------------

This module handles subscription payments using the Credimax payment gateway.
It supports the full Customer-Initiated Transaction (CIT) flow for setting up
recurring business subscriptions.

📌 Flow Summary (Frontend-Driven):

1. CreateSessionView (POST /create-session/)
   - Frontend initiates this first.
   - Backend creates a Credimax payment session via API.
   - Backend prepares a pending `Transaction` and `BusinessSubscriptionPlan`.
   - Backend updates the Credimax session with transaction and subscription metadata.
   - Returns: `session_id`, `order_id`, `transaction_id`.

2. TokenizeCardView (POST /tokenize-card/)
   - Frontend collects card details via Credimax Session SDK using `session_id`.
   - Frontend sends only the `session_id` to this endpoint (card details remain with Credimax).
   - Backend calls Credimax to retrieve the card token and details.
   - Stores the token in `BusinessSavedCardToken` and links it to the subscription.
   - Updates the Credimax session with the token for use in the upcoming CIT payment.

3. (Frontend) Performs 3DS Authentication
   - Frontend uses the same `session_id` with the Credimax SDK to perform 3D Secure.
   - This step ensures cardholder authentication to reduce fraud risk.
   - Backend is **not involved** in this step directly.

4. CustomerInitiatedPaymentAPIView (POST /make-payment/)
   - Called by frontend *after* 3DS is completed.
   - Backend uses the stored token and `session_id` to perform the first CIT payment.
   - If payment is successful:
       - Marks `Transaction` as `SUCCESS`
       - Activates the `BusinessSubscriptionPlan`
     Otherwise:
       - Marks `Transaction` and subscription as `FAILED`.

🔒 Security & Validation:
- All API endpoints rely on `request.auth["current_business"]` to resolve business context.
- Token and card data are handled securely; raw card details never touch the backend.
- Only one card token is marked as active (`is_used_for_subscription=True`) per business.

Credimax Naming Mapping with Models:

Transaction -> Order
Transaction.id[:8] -> credimax_3ds_transaction_id
BusinessSubscriptionPlan -> Agreement
"""

import logging

from django.conf import settings
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from sooq_althahab.payment_gateway_services.credimax.subscription.serializers import (
    CreateSubscriptionSessionSerializer,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.serializers import (
    Credimax3DSCallbackSerializer,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.serializers import (
    Credimax3DSCardAdditionCallbackSerializer,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.serializers import (
    CustomerInitiatedPaymentSerializer,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.serializers import (
    MarkTransactionAsFailedSerializer,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.serializers import (
    TokenizeCardSerializer,
)

logger = logging.getLogger(__name__)


from rest_framework import serializers


class CreateSessionView(APIView):
    """
    Initiates a Credimax session and creates a pending business subscription transaction.

    Request Body:
        - subscription_plan_id (str): The ID of the selected subscription plan.
        - is_auto_renew (bool): Whether the subscription should auto-renew.

    Response:
        - session_id (str): The created Credimax session ID.
        - order_id (UUID): The transaction ID.
        - transaction_id (str): Shortened transaction ID for 3DS identification.
    """

    def post(self, request):
        serializer = CreateSubscriptionSessionSerializer(
            data=request.data, context={"request": request}
        )
        try:
            serializer.is_valid(raise_exception=True)
            result = serializer.save()
            return Response(result, status=status.HTTP_200_OK)
        except serializers.ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Error creating subscription session")
            return Response(
                {"detail": "Internal server error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class TokenizeCardView(APIView):
    """
    Tokenizes the customer's card using an active Credimax session.

    Request Body:
        - session_id (str): The active Credimax session ID.

    Response:
        - message (str): Confirmation that the card token was saved.
    """

    def post(self, request):
        serializer = TokenizeCardSerializer(
            data=request.data, context={"request": request}
        )
        try:
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response({"message": "Card token saved."}, status=status.HTTP_200_OK)
        except serializers.ValidationError as e:
            # Format error response to match project standards
            # Extract field errors and format as {field: "error_message"}
            error_response = {}
            if hasattr(e, "detail"):
                # If detail is a dict (field errors)
                if isinstance(e.detail, dict):
                    for field, messages in e.detail.items():
                        # Extract first message if it's a list
                        if isinstance(messages, list) and len(messages) > 0:
                            error_response[field] = str(messages[0])
                        else:
                            error_response[field] = str(messages)
                else:
                    error_response["detail"] = str(e.detail)
            else:
                # Fallback to string representation
                error_response["detail"] = str(e)
            return Response(error_response, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Unexpected error during tokenization.")
            return Response(
                {"detail": f"Tokenization failed. {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CustomerInitiatedPaymentAPIView(APIView):
    """
    Processes a customer-initiated payment (CIT) using a saved card token and session.

    Request Body:
        - session_id (str): The Credimax session ID.
        - order_id (UUID): The previously created transaction ID.

    Response:
        - detail (str): Success or failure message.
    """

    def post(self, request):
        serializer = CustomerInitiatedPaymentSerializer(
            data=request.data, context={"request": request}
        )
        try:
            serializer.is_valid(raise_exception=True)
            result = serializer.save()

            # Consistent response structure
            response_data = {
                "message": result["detail"],
                "status_code": result["status_code"],
                "data": {
                    "transaction_id": result.get("transaction_id"),
                    "transaction_status": result.get("transaction_status"),
                    "subscription_status": result.get("subscription_status"),
                    "is_processing": result.get("is_processing", False),
                    "remark": result.get("remark"),
                },
            }

            # Include additional details for failed transactions
            if result.get("card_type"):
                response_data["data"]["card_type"] = result.get("card_type")

            return Response(response_data, status=result["status_code"])
        except serializers.ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Payment processing failed.")
            return Response(
                {"detail": "Internal server error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class Credimax3DSWebCallbackAPIView(APIView):
    """
    Handles the POST callback from Credimax 3DS authentication process.

    This endpoint receives a `QueryDict` payload after the 3D Secure flow.
    It:
      - Extracts and normalizes the incoming data.
      - Validates the data using a serializer.
      - Marks the related transaction and subscription as FAILED if the result is not 'SUCCESS'.
      - Redirects the user to either a success or failure URL based on the transaction outcome.

    Expected POST data (as QueryDict with list values):
        - order.id: Unique transaction identifier
        - result: 'SUCCESS' or other failure indication

    Redirection URLs:
        - On success: settings.CREDIMAX_3DS_SUCCESS_WEB_CALLBACK_URL
        - On failure: settings.CREDIMAX_3DS_FAILURE_WEB_CALLBACK_URL
    """

    def post(self, request, *args, **kwargs):
        # Convert QueryDict values from list to single values (take first element)
        data = {
            k: v[0] if isinstance(v, (list, tuple)) else v
            for k, v in request.data.lists()
        }

        # Map 'order.id' to 'order_id'
        if "order.id" in data:
            data["order_id"] = data.pop("order.id")

        # Reject card addition transactions - they should use the card addition callback endpoint
        order_id = data.get("order_id", "")
        if order_id.startswith("card_add_"):
            logger.warning(
                "Credimax3DSWebCallbackAPIView: Received card addition transaction %s. "
                "Card addition transactions should use Credimax3DSCardAdditionCallbackAPIView",
                order_id,
            )
            # Redirect to card addition failure URL since this is the wrong endpoint
            callback_url = settings.CREDIMAX_CARD_ADDITION_FAILURE_REDIRECT_URL
            return redirect(callback_url)

        serializer = Credimax3DSCallbackSerializer(data=data)
        if not serializer.is_valid():
            logger.warning(
                "Invalid data in Credimax3DSWebCallbackAPIView: %s", serializer.errors
            )
            callback_url = settings.CREDIMAX_3DS_FAILURE_WEB_CALLBACK_URL
            return redirect(callback_url)

        callback_result = serializer.save()

        if callback_result["status"] == "failed":
            logger.warning(
                "Credimax3DSWebCallbackAPIView: Transaction and related subscription marked as failed"
            )
            callback_url = settings.CREDIMAX_3DS_FAILURE_WEB_CALLBACK_URL
            return redirect(callback_url)
        else:
            callback_url = settings.CREDIMAX_3DS_SUCCESS_WEB_CALLBACK_URL

        logger.info("Redirecting to callback URL: %s", callback_url)
        return redirect(callback_url)


class Credimax3DSCardAdditionCallbackAPIView(APIView):
    """
    Handles the POST callback from Credimax 3DS authentication process for CARD ADDITION ONLY.

    This endpoint is specifically for card addition flow (order_id starts with "card_add_").
    It redirects to card addition success/failure URLs, not subscription URLs.

    This endpoint receives a `QueryDict` payload after the 3D Secure flow.
    It:
      - Validates that the order_id starts with "card_add_" (card addition only)
      - Validates the data using a serializer
      - Redirects the user to card addition success or failure URL based on the result

    Expected POST data (as QueryDict with list values):
        - order.id: Unique transaction identifier (must start with "card_add_")
        - result: 'SUCCESS' or other failure indication

    Redirection URLs:
        - On success: settings.CREDIMAX_CARD_ADDITION_SUCCESS_REDIRECT_URL
        - On failure: settings.CREDIMAX_CARD_ADDITION_FAILURE_REDIRECT_URL
    """

    def post(self, request, *args, **kwargs):
        # Convert QueryDict values from list to single values (take first element)
        data = {
            k: v[0] if isinstance(v, (list, tuple)) else v
            for k, v in request.data.lists()
        }

        # Map 'order.id' to 'order_id'
        if "order.id" in data:
            data["order_id"] = data.pop("order.id")

        serializer = Credimax3DSCardAdditionCallbackSerializer(data=data)
        if not serializer.is_valid():
            logger.warning(
                "Invalid data in Credimax3DSCardAdditionCallbackAPIView: %s",
                serializer.errors,
            )
            # Redirect to card addition failure URL
            callback_url = settings.CREDIMAX_CARD_ADDITION_FAILURE_REDIRECT_URL
            logger.info("Redirecting to card addition failure URL: %s", callback_url)
            return redirect(callback_url)

        callback_result = serializer.save()

        if callback_result["status"] == "failed":
            logger.warning(
                "Credimax3DSCardAdditionCallbackAPIView: Card addition 3DS authentication failed "
                "for order %s",
                callback_result.get("order_id"),
            )
            callback_url = settings.CREDIMAX_CARD_ADDITION_FAILURE_REDIRECT_URL
        else:
            logger.info(
                "Credimax3DSCardAdditionCallbackAPIView: Card addition 3DS authentication "
                "successful for order %s",
                callback_result.get("order_id"),
            )
            callback_url = settings.CREDIMAX_CARD_ADDITION_SUCCESS_REDIRECT_URL

        logger.info("Redirecting to card addition callback URL: %s", callback_url)
        return redirect(callback_url)


class MarkTransactionAsFailedAPIView(APIView):
    """
    Receives a transaction ID as order ID, marks the transaction as FAILED,
    and updates any related subscription and saved card token.
    """

    def post(self, request):
        serializer = MarkTransactionAsFailedSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {"detail": "Transaction and related subscription marked as failed."},
            status=status.HTTP_200_OK,
        )
