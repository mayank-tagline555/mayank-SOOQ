import logging
from decimal import ROUND_HALF_UP
from decimal import Decimal

import requests
from django.conf import settings
from requests.auth import HTTPBasicAuth

from sooq_althahab.enums.sooq_althahab_admin import SubscriptionPaymentTypeChoices

logger = logging.getLogger(__name__)


class CredimaxClient:
    DEFAULT_TXN_ID = "1"
    AUTH_3DS_CHANNEL = "PAYER_BROWSER"
    BASE_URL = settings.CREDIMAX_BASE_URL
    MERCHANT_ID = settings.CREDIMAX_MERCHANT_ID
    CREDIMAX_CURRENCY = settings.CREDIMAX_CURRENCY

    def __init__(self):
        self.auth = HTTPBasicAuth(
            settings.CREDIMAX_API_USERNAME, settings.CREDIMAX_API_PASSWORD
        )

    def _get_url(self, *args):
        """Helper method to construct the URL with base and endpoints."""
        return f"{self.BASE_URL}" + "/".join(args)

    def _send_request(self, method, url, payload=None):
        """Helper method to send the HTTP request."""
        if method.lower() == "post":
            response = requests.post(url, json=payload, auth=self.auth)
        elif method.lower() == "put":
            response = requests.put(url, json=payload, auth=self.auth)
        elif method.lower() == "get":
            response = requests.get(url, auth=self.auth)
        else:
            raise ValueError(f"Unsupported method {method}")

        # Check for HTTP errors and log them
        # 4xx errors are client errors (validation issues) - log as warning
        # 5xx errors are server errors - log as error
        if response.status_code >= 400:
            try:
                error_data = response.json()
                error_info = error_data.get("error", {})
                error_message = error_info.get(
                    "explanation", error_info.get("message", response.text)
                )
                if response.status_code < 500:
                    # 4xx errors are client validation errors - don't trigger Sentry
                    logger.warning(
                        f"Credimax API validation error: HTTP {response.status_code} - {error_message}"
                    )
                else:
                    # 5xx errors are server errors - should trigger Sentry
                    logger.error(
                        f"Credimax API error: HTTP {response.status_code} - {error_message}"
                    )
            except Exception:
                if response.status_code < 500:
                    logger.warning(
                        f"Credimax API validation error: HTTP {response.status_code} - {response.text}"
                    )
                else:
                    logger.error(
                        f"Credimax API error: HTTP {response.status_code} - {response.text}"
                    )

        return response

    def create_session(self):
        """Create a new session."""
        url = self._get_url("session")
        response = self._send_request("post", url)
        return response.json()

    def tokenize_card(self, session_id):
        """Tokenize a card based on the session ID."""
        url = self._get_url("token")
        payload = {"session": {"id": session_id}}
        response = self._send_request("post", url, payload)
        return response.json()

    def make_cit_payment(self, session_id, agreement, order, amount, token):
        """Make a payment using the tokenized card."""

        payload = {
            "apiOperation": "PAY",
            "agreement": {
                "id": agreement.id,
                "type": "RECURRING",
                "amountVariability": agreement.payment_amount_variability,
            },
            "order": {"amount": str(amount), "currency": order.currency},
            "session": {"id": session_id},
            "sourceOfFunds": {
                "type": "CARD",
                "token": token,
                "provided": {"card": {"storedOnFile": "TO_BE_STORED"}},
            },
            "transaction": {
                "reference": order.reference_number,
                "source": "INTERNET",
            },
            "authentication": {"transactionId": agreement.credimax_3ds_transaction_id},
        }
        if (
            amount == 0
            or agreement.payment_type == SubscriptionPaymentTypeChoices.POSTPAID
        ):
            payload["apiOperation"] = "VERIFY"

        logger.debug(f"make_cit_payment: payload for order {order.id}")
        url = self._get_url("order", order.id, "transaction", self.DEFAULT_TXN_ID)
        response = self._send_request("put", url, payload)
        return payload, response.json()

    def update_session(self, session_id, order, txn_id, agreement=None):
        """Update an existing session with payment and agreement information."""

        url = self._get_url("session", session_id)
        # Use order.amount as the total amount (order.amount already includes VAT)
        total_amount = Decimal(order.amount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        payload = {
            "order": {
                "id": order.id,
                "currency": order.currency or "BHD",
                "amount": str(total_amount),  # Total amount including VAT
            },
            "transaction": {"id": txn_id},
            "authentication": {
                "channel": self.AUTH_3DS_CHANNEL,
                "redirectResponseUrl": settings.CREDIMAX_3DS_REDIRECT_RESPONSE_URL,
            },
        }
        if agreement:
            payload["agreement"] = {
                "id": agreement.id,
                "type": "RECURRING",
                "amountVariability": agreement.payment_amount_variability,
                "expiryDate": agreement.expiry_date.strftime("%Y-%m-%d"),
                "paymentFrequency": agreement.payment_interval,
                "minimumDaysBetweenPayments": "28",
            }
            if (
                order.amount == 0
                or agreement.payment_type == SubscriptionPaymentTypeChoices.POSTPAID
            ):
                payload["authentication"]["purpose"] = "ADD_CARD"

        print("update_session: payload", payload)
        x = self._send_request("put", url, payload)
        print("update_session: response", x.json())

    def update_session_for_card_addition(self, session_id, order_id, transaction_id):
        """
        Update session with a zero-amount order and transaction for card addition flow.
        This is required by Credimax when adding a card without making a payment.

        Args:
            session_id (str): The Credimax session ID
            order_id (str): The order ID for this card addition
            transaction_id (str): The transaction ID for authentication

        Returns:
            dict: Response from Credimax
        """
        url = self._get_url("session", session_id)
        payload = {
            "order": {
                "id": str(order_id),
                "currency": self.CREDIMAX_CURRENCY,
                "amount": "0.00",
            },
            "transaction": {
                "id": str(transaction_id),
            },
            "authentication": {
                "channel": self.AUTH_3DS_CHANNEL,
                "purpose": "ADD_CARD",
                "redirectResponseUrl": settings.CREDIMAX_CARD_ADDITION_3DS_REDIRECT_RESPONSE_URL,
            },
        }
        response = self._send_request("put", url, payload)
        return response.json()

    def update_session_with_token(self, session_id, token):
        """Update an existing session with saved business card token details."""

        url = self._get_url("session", session_id)
        payload = {"sourceOfFunds": {"type": "SCHEME_TOKEN", "token": token}}
        self._send_request("put", url, payload)

    def verify_card_with_agreement(self, agreement, token, session_id=None):
        """
        Verify a card with Credimax using VERIFY operation for an existing agreement.
        This verifies the card works for future payments without charging it.
        After verification, the agreement is updated with the new card token.

        Args:
            agreement: BusinessSubscriptionPlan instance (Credimax agreement)
            token: Card token to verify and update in agreement
            session_id: Optional session ID (if not provided, creates a new session)

        Returns:
            tuple: (payload, response) - The payload sent and response received
        """
        # Generate a temporary order ID for agreement update verification
        # Credimax requires order IDs to be less than 41 characters
        # Format: UPD_{agreement_id_last_12}_{random_6}
        import uuid

        agreement_id_short = (
            agreement.id[-12:] if len(agreement.id) > 12 else agreement.id
        )
        random_suffix = uuid.uuid4().hex[:6]
        temp_order_id = f"UPD_{agreement_id_short}_{random_suffix}"

        # Use VERIFY operation (amount is 0, so it will verify only)
        payload = {
            "apiOperation": "VERIFY",
            "agreement": {
                "id": agreement.id,
                "type": "RECURRING",
                "amountVariability": agreement.payment_amount_variability,
            },
            "order": {
                "amount": "0.00",
                "currency": self.CREDIMAX_CURRENCY,
            },
            "sourceOfFunds": {
                "type": "CARD",
                "token": token,
                "provided": {"card": {"storedOnFile": "STORED"}},
            },
            "transaction": {
                "reference": f"UPDATE_AGREEMENT_{agreement.id}",
                "source": "MERCHANT",
            },
        }

        # If session_id is provided, include it
        if session_id:
            payload["session"] = {"id": session_id}

        # Use a temporary order ID for verification
        url = self._get_url("order", temp_order_id, "transaction", self.DEFAULT_TXN_ID)
        response = self._send_request("put", url, payload)
        return payload, response.json()

    def update_agreement_with_card(self, agreement, token):
        """
        Update a Credimax agreement with a new card token.
        This ensures future recurring payments use the new card.

        Args:
            agreement: BusinessSubscriptionPlan instance (Credimax agreement)
            token: New card token to associate with the agreement

        Returns:
            dict: Response from Credimax

        Raises:
            ValueError: If the response contains an error (validation error from Credimax)
        """
        url = self._get_url("agreement", agreement.id)
        payload = {
            "sourceOfFunds": {
                "type": "CARD",
                "token": token,
                "provided": {"card": {"storedOnFile": "STORED"}},
            }
        }
        response = self._send_request("put", url, payload)
        response_data = response.json()

        # Check for errors in response (even if HTTP status was 200)
        if "error" in response_data:
            error_info = response_data.get("error", {})
            error_message = error_info.get(
                "explanation", error_info.get("message", "Failed to update agreement")
            )
            # Raise ValueError for validation errors (4xx) - these should be handled gracefully
            raise ValueError(f"Credimax validation error: {error_message}")

        return response_data

    def get_agreement_details(self, agreement):
        """
        Retrieve agreement details from Credimax to verify the card token is stored.
        This allows us to confirm the agreement has been updated with the new card.

        Args:
            agreement: BusinessSubscriptionPlan instance (Credimax agreement)

        Returns:
            dict: Response from Credimax containing agreement details including sourceOfFunds
        """
        url = self._get_url("agreement", agreement.id)
        response = self._send_request("get", url)
        return response.json()

    def charge_recurring(self, token, order, agreement):
        """
        Charge for recurring payments using the stored token.

        Note: We explicitly pass the token in sourceOfFunds even though the agreement
        should have the card stored. This ensures we use the correct/updated card token
        and provides better control over which card is used for the payment.

        Args:
            token: Card token to use for payment (from subscription.business_saved_card_token)
            order: Transaction instance (order.amount already includes VAT)
            agreement: BusinessSubscriptionPlan instance (Credimax agreement)

        Returns:
            tuple: (payload, response) - The payload sent to Credimax and the response received
        """
        logger.info(
            f"Charging recurring payment for agreement {agreement.id} "
            f"using card token {token[:4]}...{token[-4:] if len(token) > 8 else '****'}"
        )

        # order.amount is expected to already be the total (base + VAT)
        total_amount = Decimal(order.amount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        payload = {
            "apiOperation": "PAY",
            "agreement": {
                "id": agreement.id,
                "type": "RECURRING",
                "amountVariability": agreement.payment_amount_variability,
            },
            "order": {
                "amount": str(total_amount),  # Total amount including VAT, 2 decimals
                "currency": order.currency or "BHD",
            },
            "sourceOfFunds": {
                "type": "CARD",
                "token": token,
                "provided": {"card": {"storedOnFile": "STORED"}},
            },
            "transaction": {
                "reference": str(order.reference_number),
                "source": "MERCHANT",
            },
        }

        url = self._get_url("order", str(order.id), "transaction", self.DEFAULT_TXN_ID)
        response = self._send_request("put", url, payload)
        return payload, response.json()
