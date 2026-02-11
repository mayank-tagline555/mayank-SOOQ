import json
import logging
import time
from decimal import Decimal

from django.conf import settings
from django.db.models import Prefetch
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from account.models import Transaction
from account.models import UserAssignedBusiness
from account.models import Wallet
from account.models import WebhookCall
from investor.serializers import CreateBenefitPaymentSessionSerializer
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.account import TransferVia
from sooq_althahab.enums.account import WebhookCallStatus
from sooq_althahab.enums.account import WebhookEventType
from sooq_althahab.payment_gateway_services.benefit.benefit_client import (
    BenefitPayClient,
)
from sooq_althahab.payment_gateway_services.payment_logger import get_benefit_pay_logger

logger = logging.getLogger(__name__)


class BenefitPaymentInitView(APIView):
    def post(self, request):
        """Create a payment session via Benefit Pay for adding money to the wallet."""

        current_business_id = request.auth.get("current_business", None)
        payment_logger = None

        serializer = CreateBenefitPaymentSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        original_amount = serializer.get_base_amount()
        fee = serializer.get_fee()
        total_amount = serializer.get_total_amount()

        logger.info(
            "[BenefitPay] Received request to create payment session with amount: %s for business ID: %s",
            original_amount,
            current_business_id,
        )
        logger.info(
            "[BenefitPay] Original amount: %s, Fee: %s, Total charged: %s",
            original_amount,
            fee,
            total_amount,
        )
        # Fetch the business associated with the current business ID
        try:
            business = (
                UserAssignedBusiness.objects.select_related("business")  # forward FK
                .prefetch_related(
                    Prefetch(
                        "business__wallets",
                        queryset=Wallet.objects.all(),
                        to_attr="prefetched_wallets",
                    )
                )
                .get(id=current_business_id)
            ).business
            wallet = business.wallets.first()

            payment_logger = get_benefit_pay_logger(business_id=str(business.id))

            payment_logger.log_transaction_start(
                transaction_type="BENEFIT_PAY_WALLET_TOPUP",
                business_id=str(business.id),
                amount=float(total_amount),
                additional_data={
                    "user_id": str(request.user.id) if request.user else None,
                    "request_data": request.data,
                },
            )

            payment_logger.log_business_logic(
                action="VALIDATE_BENEFIT_PAY_SESSION_DATA",
                data={
                    "original_amount": float(original_amount),
                    "fee": float(fee),
                    "total_amount": float(total_amount),
                    "business_id": str(business.id),
                },
            )

            payment_logger.log_business_logic(
                action="FETCH_BUSINESS_DETAILS",
                data={
                    "business_id": str(business.id),
                    "user_id": str(request.user.id) if request.user else None,
                },
            )

            payment_logger.log_business_logic(
                action="BUSINESS_FETCHED_SUCCESSFULLY",
                data={
                    "business_id": str(business.id),
                    "business_name": business.name,
                    "wallet_exists": wallet is not None,
                    "wallet_balance": float(wallet.balance) if wallet else None,
                },
            )

            logger.info(
                "[BenefitPay] Found business: %s with ID: %s",
                business.name,
                business.id,
            )
        except UserAssignedBusiness.DoesNotExist:
            payment_logger = payment_logger or get_benefit_pay_logger()
            payment_logger.log_error(
                error_type="BUSINESS_NOT_FOUND",
                error_message=f"Business with ID {current_business_id} not found",
                context={"business_id": str(current_business_id)},
            )
            logger.error(
                "[BenefitPay] Business with ID %s not found.", current_business_id
            )
            return Response(
                {"message": "Wallet not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            payment_logger = payment_logger or get_benefit_pay_logger()
            payment_logger.log_error(
                error_type="BUSINESS_FETCH_ERROR",
                error_message=str(e),
                context={"business_id": str(current_business_id)},
            )
            logger.exception("[BenefitPay] Error fetching business: %s", str(e))
            return Response(
                {"message": "An error occurred while fetching business."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        trans_notes = f"Top-up to Business Wallet - BHD {original_amount} + BHD {fee} fee - Total: BHD {total_amount}"
        logger.info("[BenefitPay] Transaction log details: %s", trans_notes)

        try:
            payment_logger.log_business_logic(
                action="CREATE_BENEFIT_PAY_TRANSACTION",
                data={
                    "business_id": str(business.id),
                    "original_amount": float(original_amount),
                    "fee": float(fee),
                    "total_amount": float(total_amount),
                    "wallet_balance_before": float(wallet.balance) if wallet else None,
                    "transaction_type": TransactionType.DEPOSIT,
                    "transfer_via": TransferVia.BENEFIT_PAY,
                },
            )

            txn = Transaction.objects.create(
                from_business=business,
                to_business=business,
                amount=original_amount,
                additional_fee=fee,
                transaction_type=TransactionType.DEPOSIT,
                transfer_via=TransferVia.BENEFIT_PAY,
                status=TransactionStatus.PENDING,
                log_details=trans_notes,
                created_by=request.user,
                previous_balance=wallet.balance,
                current_balance=wallet.balance,
            )

            # Update payment logger with transaction ID
            payment_logger = get_benefit_pay_logger(
                str(txn.id), business_id=str(business.id)
            )

            payment_logger.log_business_logic(
                action="TRANSACTION_CREATED_SUCCESSFULLY",
                data={
                    "transaction_id": str(txn.id),
                    "status": txn.status,
                    "amount": float(txn.amount),
                    "additional_fee": float(txn.additional_fee),
                },
            )

            logger.info("[BenefitPay] Transaction created with ID: %s", txn.id)

            payment_logger.log_api_request(
                endpoint="initiate_payment",
                method="POST",
                payload={"amount": float(total_amount), "transaction_id": str(txn.id)},
            )

            api_start_time = time.time()
            result = BenefitPayClient.initiate_payment(total_amount, txn.id)
            api_response_time = (time.time() - api_start_time) * 1000

            payment_logger.log_api_response(
                status_code=200,
                response_data=result,
                response_time_ms=api_response_time,
            )

            if result[0]["status"] == "1":
                payment_url = "https:" + result[0]["result"].split(":")[1]

                payment_logger.log_business_logic(
                    action="BENEFIT_PAY_SESSION_CREATED",
                    data={
                        "payment_url": payment_url,
                        "transaction_id": str(txn.id),
                        "benefit_status": result[0]["status"],
                    },
                )

                response_data = {
                    "payment_url": payment_url,
                    "track_id": txn.id,
                    "reference_number": txn.reference_number,
                    "amount": str(txn.amount),
                    "status": txn.status,
                }

                payment_logger.log_transaction_completion(
                    final_status=txn.status,
                    summary={
                        "type": "benefit_pay_wallet_topup",
                        "transaction_id": str(txn.id),
                        "payment_url": payment_url,
                        "business_id": str(business.id),
                        "amount": float(total_amount),
                    },
                )

                return Response(response_data)
            else:
                payment_logger.log_error(
                    error_type="BENEFIT_PAY_SESSION_FAILED",
                    error_message=result[0].get("errorText", "Unknown error"),
                    context={
                        "transaction_id": str(txn.id),
                        "benefit_status": result[0]["status"],
                        "benefit_response": result,
                    },
                )
                return Response(
                    {"error": result[0]["errorText"]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            payment_logger.log_error(
                error_type="BENEFIT_PAY_INITIATION_ERROR",
                error_message=str(e),
                context={
                    "business_id": str(business.id),
                    "amount": float(total_amount),
                },
            )
            logger.exception(
                "[BenefitPay] Exception while initiating Benefit Pay session"
            )
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@method_decorator(csrf_exempt, name="dispatch")
class BenefitSuccessView(APIView):
    """
    Handle successful payment notifications from Benefit Pay.

    This endpoint must return a plain text response in the format:
    REDIRECT=someURL

    No HTML, JavaScript, or CSS should be included in the response.
    """

    def post(self, request):
        """Handle successful payment notifications from Benefit Pay."""

        webhook_log = ""
        start = time.time()
        transaction_obj = None
        redirect_url = settings.BENEFIT_ERROR_RETURN_URL  # fallback
        payment_logger = None

        try:
            trandata = request.POST.get("trandata")
            error_text = request.POST.get("ErrorText")
            webhook_data = request.POST.dict()

            track_id = None
            webhook_log += f"[Success] Raw POST data: {webhook_data}\n"
            logger.info("[BenefitPay] Raw POST Data: %s", webhook_data)

            if not trandata and not error_text:
                if payment_logger:
                    payment_logger.log_error(
                        error_type="MISSING_WEBHOOK_DATA",
                        error_message="Missing both trandata and errorText",
                        context={"webhook_data": webhook_data},
                    )
                raise ValueError("Missing both trandata and errorText")

            if trandata:
                decrypted = BenefitPayClient.decrypt(trandata)
                decrypted_data = json.loads(decrypted)[0]
                webhook_log += f"[Success] Decrypted trandata: {decrypted_data}\n"
                logger.info("[BenefitPay] Decrypted Trandata: %s", decrypted_data)

                track_id = decrypted_data.get("trackId")
                result = decrypted_data.get("result")

                if not track_id:
                    raise ValueError("Missing trackId in decrypted trandata")

                transaction_obj = Transaction.objects.select_related(
                    "from_business"
                ).get(id=track_id)

                payment_logger = get_benefit_pay_logger(
                    str(track_id), business_id=str(transaction_obj.from_business.id)
                )
                payment_logger.log_webhook_received(webhook_data, "BenefitPay-Success")
                payment_logger.log_webhook_processing(
                    "DECRYPT_TRANDATA", {"decrypted_data": decrypted_data}
                )
                payment_logger.log_webhook_processing(
                    "FETCH_TRANSACTION", {"track_id": track_id, "result": result}
                )

                payment_logger.log_webhook_processing(
                    "TRANSACTION_FOUND",
                    {
                        "transaction_id": str(transaction_obj.id),
                        "status": transaction_obj.status,
                        "amount": float(transaction_obj.amount),
                        "business_id": str(transaction_obj.from_business.id),
                    },
                )

                # Skip if already success
                if transaction_obj.status == TransactionStatus.SUCCESS:
                    if payment_logger:
                        payment_logger.log_webhook_processing(
                            "TRANSACTION_ALREADY_SUCCESS",
                            {"transaction_id": str(transaction_obj.id)},
                        )
                    logger.info("[BenefitPay] Transaction already marked SUCCESS.")
                    redirect_url = settings.BENEFIT_SUCCESS_RETURN_URL
                else:
                    business_wallet = Wallet.objects.filter(
                        business=transaction_obj.from_business
                    ).first()
                    transaction_obj.previous_balance = (
                        business_wallet.balance if business_wallet else 0
                    )

                    old_status = transaction_obj.status

                    if result == "CAPTURED":
                        # Transaction successful
                        webhook_log += "Transaction status is SUCCESS (CAPTURED)\n\n"
                        transaction_obj.status = TransactionStatus.SUCCESS

                        if payment_logger:
                            payment_logger.log_transaction_update(
                                old_status=old_status,
                                new_status=TransactionStatus.SUCCESS,
                                reason="Payment successful - captured",
                                additional_data={"result": result},
                            )

                        self.update_wallet_balance(
                            transaction_obj, webhook_log, payment_logger
                        )
                        # Send invoice email to accounts for successful top-up transactions
                        if transaction_obj.transaction_type == TransactionType.DEPOSIT:
                            try:
                                from sooq_althahab.billing.transaction.invoice_utils import (
                                    send_topup_invoice_to_accounts,
                                )

                                organization = (
                                    transaction_obj.from_business.organization_id
                                )
                                if organization:
                                    send_topup_invoice_to_accounts(
                                        transaction_obj, organization
                                    )
                            except Exception as invoice_error:
                                logger.error(
                                    f"Failed to send top-up invoice email for transaction {transaction_obj.id}: {str(invoice_error)}"
                                )
                        redirect_url = f"{settings.BENEFIT_SUCCESS_RETURN_URL}?transaction_id={track_id}"
                        webhook_status = WebhookCallStatus.SUCCESS
                    elif result in [
                        "CANCELED",
                        "FAILED",
                        "NOT CAPTURED",
                        "DENIED BY RISK",
                        "HOST TIMEOUT",
                    ]:
                        webhook_log += f"Transaction status is FAILED ({result})\n\n"
                        transaction_obj.status = TransactionStatus.FAILED

                        if payment_logger:
                            payment_logger.log_transaction_update(
                                old_status=old_status,
                                new_status=TransactionStatus.FAILED,
                                reason="Payment failed",
                                additional_data={"result": result},
                            )

                        redirect_url = f"{settings.BENEFIT_FAILURE_RETURN_URL}?transaction_id={track_id}"
                        webhook_status = WebhookCallStatus.FAILURE
                    else:
                        webhook_log += f"Transaction status is PENDING ({result})\n\n"
                        transaction_obj.status = TransactionStatus.PENDING

                        if payment_logger:
                            payment_logger.log_transaction_update(
                                old_status=old_status,
                                new_status=TransactionStatus.PENDING,
                                reason="Payment status pending",
                                additional_data={"result": result},
                            )

                        redirect_url = f"{settings.BENEFIT_ERROR_RETURN_URL}?transaction_id={track_id}&status=pending"
                        webhook_status = WebhookCallStatus.RECEIVED

                    # Update log details and balances
                    existing_notes = transaction_obj.log_details or ""
                    transaction_obj.log_details = f"{existing_notes}\n\n--- Benefit Pay Success Webhook Log ---\n{webhook_log}"
                    transaction_obj.current_balance = (
                        business_wallet.balance if business_wallet else 0
                    )
                    transaction_obj.save()

                    webhook_log += (
                        f"Updated transaction status to {transaction_obj.status}\n\n"
                    )

                    # Log the webhook call in the WebhookCall model (separate from core logic)
                    try:
                        WebhookCall.objects.create(
                            transaction=transaction_obj,
                            transfer_via=TransferVia.BENEFIT_PAY,
                            event_type=WebhookEventType.PAYMENT,
                            status=webhook_status,
                            request_body=webhook_data,
                            response_body=decrypted_data,
                            response_status_code=status.HTTP_200_OK,
                        )

                        if payment_logger:
                            payment_logger.log_webhook_processing(
                                "WEBHOOK_CALL_LOGGED",
                                {
                                    "webhook_event_type": WebhookEventType.PAYMENT,
                                    "webhook_status": webhook_status,
                                },
                            )

                        webhook_log += "Webhook call logged successfully.\n\n"
                    except Exception as log_error:
                        if payment_logger:
                            payment_logger.log_error(
                                error_type="WEBHOOK_CALL_LOGGING_ERROR",
                                error_message=str(log_error),
                                context={"transaction_id": str(transaction_obj.id)},
                            )
                        logger.warning(
                            "[BenefitPay] Failed to log WebhookCall: %s", str(log_error)
                        )
                        webhook_log += (
                            f"Warning: Webhook logging failed: {str(log_error)}\n\n"
                        )

            elif error_text:
                if payment_logger:
                    payment_logger.log_error(
                        error_type="ERROR_TEXT_RECEIVED",
                        error_message=f"ErrorText received: {error_text}",
                        context={"error_text": error_text},
                    )
                webhook_log += f"[Success] ErrorText received: {error_text}\n"
                logger.warning("[BenefitPay] ErrorText on Success: %s", error_text)

            if payment_logger and transaction_obj:
                payment_logger.log_transaction_completion(
                    final_status=transaction_obj.status,
                    summary={
                        "type": "benefit_pay_success_webhook",
                        "transaction_id": str(transaction_obj.id),
                        "business_id": str(transaction_obj.from_business.id),
                        "amount": float(transaction_obj.amount),
                        "webhook_result": result if "result" in locals() else None,
                        "redirect_url": redirect_url,
                    },
                )

        except Exception as e:
            webhook_log += f"[Success] Exception: {str(e)}\n"
            logger.exception("[BenefitPay] Exception in success handler: %s", str(e))

            if payment_logger:
                payment_logger.log_error(
                    error_type="SUCCESS_WEBHOOK_EXCEPTION",
                    error_message=str(e),
                    context={"webhook_data": webhook_data},
                )

            track_id = webhook_data.get("trackid")

            if track_id:
                try:
                    transaction_obj = Transaction.objects.get(id=track_id)
                    transaction_obj.status = TransactionStatus.FAILED

                    existing_notes = transaction_obj.log_details or ""
                    transaction_obj.log_details = f"{existing_notes}\n\n--- Benefit Pay Error Log ---\n{webhook_log}"
                    transaction_obj.save()

                    try:
                        WebhookCall.objects.create(
                            transaction=transaction_obj,
                            transfer_via=TransferVia.BENEFIT_PAY,
                            event_type=WebhookEventType.PAYMENT,
                            status=WebhookCallStatus.FAILURE,
                            request_body=webhook_data,
                            response_body={"error_text": error_text},
                            response_status_code=status.HTTP_200_OK,
                        )
                    except Exception as webhook_log_error:
                        webhook_log += f"Warning: Failed to log webhook call: {str(webhook_log_error)}\n\n"

                except Transaction.DoesNotExist:
                    webhook_log += f"Transaction not found with ID {track_id}\n\n"
                    logger.error(
                        "[BenefitPay] No transaction found with ID = %s", track_id
                    )
            redirect_url = f"{settings.BENEFIT_ERROR_RETURN_URL}?message=error"

        finally:
            logger.info(
                f"[BenefitPay] Webhook execution time: {time.time() - start:.2f} sec"
            )
            logger.info(f"[BenefitPay][SUCCESS] REDIRECT={settings.BENEFIT_RETURN_URL}")
            return HttpResponse(
                f"REDIRECT={settings.BENEFIT_RETURN_URL}", content_type="text/plain"
            )

    def update_wallet_balance(self, transaction_obj, webhook_log, payment_logger=None):
        if transaction_obj.transaction_type == TransactionType.DEPOSIT:
            wallet = Wallet.objects.get(business=transaction_obj.from_business)

            if payment_logger:
                payment_logger.log_webhook_processing(
                    "FETCH_BUSINESS_WALLET",
                    {
                        "business_id": str(transaction_obj.from_business.id),
                        "wallet_balance_before": float(wallet.balance),
                        "transaction_type": "DEPOSIT",
                    },
                )

            webhook_log += (
                f"Wallet balance before update: {wallet.balance} (DEPOSIT)\n\n"
            )
            logger.info(
                "[BenefitPay]-[Success]: Wallet balance before updated (DEPOSIT): %s",
                str(wallet.balance),
            )

            old_balance = wallet.balance
            wallet.balance += Decimal(transaction_obj.amount or 0)
            wallet.save()

            if payment_logger:
                payment_logger.log_webhook_processing(
                    "UPDATE_WALLET_BALANCE",
                    {
                        "transaction_type": "DEPOSIT",
                        "old_balance": float(old_balance),
                        "deposit_amount": float(transaction_obj.amount or 0),
                        "new_balance": float(wallet.balance),
                    },
                )

            webhook_log += f"Wallet balance updated: {wallet.balance} (DEPOSIT)\n\n"
            transaction_obj.current_balance = wallet.balance
            transaction_obj.save()

            if payment_logger:
                payment_logger.log_webhook_processing(
                    "WALLET_BALANCE_SAVED",
                    {
                        "final_balance": float(wallet.balance),
                        "current_balance_recorded": float(
                            transaction_obj.current_balance
                        ),
                    },
                )

            logger.info(
                "[BenefitPay]-[Success]: Wallet balance after updated (DEPOSIT): %s",
                str(wallet.balance),
            )


@method_decorator(csrf_exempt, name="dispatch")
class BenefitFailView(APIView):
    """
    Handle failed payment notifications from Benefit Pay.

    This endpoint must return a plain text response in the format:
    REDIRECT=someURL

    No HTML, JavaScript, or CSS should be included in the response.
    """

    def post(self, request):
        """Handle failed payment notifications from Benefit Pay."""

        webhook_log = ""
        start = time.time()
        transaction_obj = None
        redirect_url = settings.BENEFIT_FAILURE_RETURN_URL

        try:
            trandata = request.POST.get("trandata")
            error_text = request.POST.get("ErrorText")
            webhook_data = request.POST.dict()

            webhook_log += f"[Fail] Raw POST data: {webhook_data}\n"
            logger.info("[BenefitPay] Raw POST Data on Fail: %s", webhook_data)

            decrypted_data = {}
            if trandata:
                try:
                    decrypted = BenefitPayClient.decrypt(trandata)
                    decrypted_data = json.loads(decrypted)[0]
                    webhook_log += f"[Fail] Decrypted trandata: {decrypted_data}\n"
                    logger.info(
                        "[BenefitPay] Decrypted Fail Trandata: %s", decrypted_data
                    )
                except Exception as e:
                    webhook_log += f"Decryption failed on fail: {str(e)}\n"
                    logger.error(
                        "[BenefitPay: Fail] Decryption Failed on Fail: %s", str(e)
                    )
            elif error_text:
                webhook_log += f"Received ErrorText on fail: {error_text}\n"
                logger.warning(
                    "[BenefitPay: Fail] Received ErrorText on Fail: %s", error_text
                )
            track_id = decrypted_data.get("trackId") or webhook_data.get("trackid")
            if track_id:
                webhook_log += (
                    f"Processing failed transaction with track ID: {track_id}\n\n"
                )
                try:
                    transaction_obj = Transaction.objects.get(id=track_id)

                    if transaction_obj.status == TransactionStatus.SUCCESS:
                        logger.info(
                            "[BenefitPay] Skipping Fail: Already marked SUCCESS"
                        )
                        redirect_url = settings.BENEFIT_SUCCESS_RETURN_URL
                    else:
                        transaction_obj.status = TransactionStatus.FAILED
                        transaction_obj.log_details = f"{transaction_obj.log_details or ''}\n\n--- Benefit Pay Fail Webhook Log ---\n{webhook_log}"
                        transaction_obj.save()

                        try:
                            WebhookCall.objects.create(
                                transaction=transaction_obj,
                                transfer_via=TransferVia.BENEFIT_PAY,
                                event_type=WebhookEventType.PAYMENT,
                                status=WebhookCallStatus.FAILURE,
                                request_body=webhook_data,
                                response_body=decrypted_data or {},
                                response_status_code=status.HTTP_200_OK,  # Always log as 200
                            )
                            webhook_log += "Webhook call logged successfully.\n\n"
                        except Exception as webhook_log_error:
                            webhook_log += f"Warning: Failed to log webhook call: {str(webhook_log_error)}\n\n"

                except Transaction.DoesNotExist:
                    webhook_log += f"Transaction not found with ID {track_id}\n\n"
                    logger.error(
                        "[BenefitPay] No transaction found with ID = %s", track_id
                    )

        except Exception as e:
            logger.exception("[BenefitPay] Fail webhook error: %s", str(e))
            webhook_log += f"Error processing fail webhook: {str(e)}\n\n"

            # Try to update transaction log details even if processing failed
            if transaction_obj:
                try:
                    existing_notes = transaction_obj.log_details or ""
                    transaction_obj.log_details = f"{existing_notes}\n\n--- Benefit Pay Fail Error Log ---\n{webhook_log}"
                    transaction_obj.save()
                except Exception as note_error:
                    webhook_log += f"Warning: Failed to update transaction log details: {str(note_error)}\n\n"

            redirect_url = (
                f"{settings.BENEFIT_ERROR_RETURN_URL}?message=processing+fail"
            )

        logger.info(
            f"[BenefitPay] Webhook execution time: {time.time() - start:.2f} sec"
        )
        logger.info(f"[BenefitPay][FAIL] REDIRECT={settings.BENEFIT_RETURN_URL}")
        return HttpResponse(
            f"REDIRECT={settings.BENEFIT_RETURN_URL}", content_type="text/plain"
        )


@method_decorator(csrf_exempt, name="dispatch")
class BenefitNotificationView(APIView):
    """
    Handle server-to-server notification from Benefit Pay.

    This endpoint processes the encrypted notification request from Benefit Payment Gateway
    and returns a simple acknowledgment. This is NOT user-facing - it's for backend processing.

    According to Benefit Integration Guide:
    - Merchant acknowledge the notification request with a response page which will have only
      the keyword "REDIRECT=" followed by the response URL
    - This is server-to-server communication, not user-facing
    """

    def post(self, request):
        """Handle server-to-server notification from Benefit Pay."""

        webhook_log = ""
        start = time.time()
        transaction_obj = None

        try:
            trandata = request.POST.get("trandata")
            error_text = request.POST.get("ErrorText")
            webhook_data = request.POST.dict()
            webhook_log += f"[Notify] Raw POST: {webhook_data}\n"
            logger.info("[BenefitPay] Notification webhook: %s", webhook_data)

            if trandata:
                decrypted = BenefitPayClient.decrypt(trandata)
                decrypted_data = json.loads(decrypted)[0]
                webhook_log += f"[Notify] Decrypted trandata: {decrypted_data}\n"
                logger.info(
                    "[BenefitPay] Decrypted Notification Trandata: %s",
                    decrypted_data,
                )

                track_id = decrypted_data.get("trackId")
                result = decrypted_data.get("result")

                if track_id:
                    try:
                        transaction_obj = Transaction.objects.get(id=track_id)

                        if result == "CAPTURED":
                            transaction_obj.status = TransactionStatus.SUCCESS
                            self.update_wallet_balance(transaction_obj, webhook_log)
                            # Send invoice email to accounts for successful top-up transactions
                            if (
                                transaction_obj.transaction_type
                                == TransactionType.DEPOSIT
                            ):
                                try:
                                    from sooq_althahab.billing.transaction.invoice_utils import (
                                        send_topup_invoice_to_accounts,
                                    )

                                    organization = (
                                        transaction_obj.from_business.organization_id
                                    )
                                    if organization:
                                        send_topup_invoice_to_accounts(
                                            transaction_obj, organization
                                        )
                                except Exception as invoice_error:
                                    logger.error(
                                        f"Failed to send top-up invoice email for transaction {transaction_obj.id}: {str(invoice_error)}"
                                    )
                            webhook_status = WebhookCallStatus.SUCCESS
                        elif result in [
                            "CANCELED",
                            "FAILED",
                            "NOT CAPTURED",
                            "DENIED BY RISK",
                            "HOST TIMEOUT",
                        ]:
                            transaction_obj.status = TransactionStatus.FAILED
                            webhook_status = WebhookCallStatus.FAILURE
                        else:
                            transaction_obj.status = TransactionStatus.PENDING
                            webhook_status = WebhookCallStatus.RECEIVED

                        transaction_obj.log_details = f"{transaction_obj.log_details or ''}\n\n--- Benefit Pay Notify Webhook Log ---\n{webhook_log}"
                        transaction_obj.save()

                        # Log the webhook call
                        try:
                            WebhookCall.objects.create(
                                transaction=transaction_obj,
                                transfer_via=TransferVia.BENEFIT_PAY,
                                event_type=WebhookEventType.PAYMENT,
                                status=webhook_status,
                                request_body=webhook_data,
                                response_body=decrypted_data,
                                response_status_code=status.HTTP_200_OK,
                            )
                            webhook_log += (
                                "Notification webhook call logged successfully.\n\n"
                            )
                        except Exception as webhook_log_error:
                            webhook_log += f"Warning: Failed to log notification webhook call: {str(webhook_log_error)}\n\n"

                    except Transaction.DoesNotExist:
                        webhook_log += f"Transaction not found with ID {track_id}\n\n"
                        logger.error(
                            "[BenefitPay] No transaction found with ID = %s",
                            track_id,
                        )
            elif error_text:
                webhook_log += f"Received ErrorText in notification: {error_text}\n\n"
                track_id = webhook_data.get("trackid")

                if track_id:
                    try:
                        transaction_obj = Transaction.objects.get(id=track_id)
                        transaction_obj.status = TransactionStatus.FAILED

                        existing_notes = transaction_obj.log_details or ""
                        transaction_obj.log_details = f"{existing_notes}\n\n--- Benefit Pay Notification Error Log ---\n{webhook_log}"
                        transaction_obj.save()

                        try:
                            WebhookCall.objects.create(
                                transaction=transaction_obj,
                                transfer_via=TransferVia.BENEFIT_PAY,
                                event_type=WebhookEventType.PAYMENT,
                                status=WebhookCallStatus.FAILURE,
                                request_body=webhook_data,
                                response_body={"error_text": error_text},
                                response_status_code=status.HTTP_200_OK,
                            )
                        except Exception as webhook_log_error:
                            webhook_log += f"Warning: Failed to log notification webhook call: {str(webhook_log_error)}\n\n"
                    except Transaction.DoesNotExist:
                        webhook_log += f"Transaction not found with ID {track_id}\n\n"
                        logger.error(
                            "[BenefitPay] No transaction found with ID = %s",
                            track_id,
                        )

        except Exception as e:
            logger.exception("[BenefitPay] Notification processing failed: %s", str(e))

        logger.info(
            f"[BenefitPay] Webhook execution time: {time.time() - start:.2f} sec"
        )
        return Response(
            {"status": "OK", "message": "Notification received"},
            status=status.HTTP_200_OK,
        )

    def update_wallet_balance(self, transaction_obj, webhook_log):
        if transaction_obj.transaction_type == TransactionType.DEPOSIT:
            wallet = Wallet.objects.get(business=transaction_obj.from_business)
            webhook_log += (
                f"Wallet balance before updated: {wallet.balance} (DEPOSIT)\n\n"
            )
            logger.info(
                "[BenefitPay] Notification processing: Wallet balance before updated (DEPOSIT): %s",
                str(wallet.balance),
            )
            wallet.balance += Decimal(transaction_obj.amount or 0)
            wallet.save()

            webhook_log += (
                f"Wallet balance after updated: {wallet.balance} (DEPOSIT)\n\n"
            )
            logger.info(
                "[BenefitPay] Notification processing: Wallet balance after updated (DEPOSIT): %s",
                str(wallet.balance),
            )
            transaction_obj.current_balance = wallet.balance
            transaction_obj.save()


@method_decorator(csrf_exempt, name="dispatch")
class PaymentResultView(View):
    """
    Final result page. Supports GET (browser redirect) and POST (server redirect).
    """

    def get(self, request):
        return self._render_result(request, request.GET.get("trandata"))

    def post(self, request):
        return self._render_result(request, request.POST.get("trandata"))

    def _render_result(self, request, trandata):
        if not trandata:
            logger.error("[PaymentResultView] Missing trandata")
            try:
                return self._send_custom_redirect("sooq://payment-failure")
            except Exception as redirect_error:
                logger.error(
                    f"[PaymentResultView] Redirect to payment-failure failed: {str(redirect_error)}"
                )
                return self._render_template_with_error(
                    request, "Missing transaction data. Please try again."
                )

        logger.info(f"[PaymentResultView]-[{request.method}]: Trans data: {trandata}")

        try:
            decrypted = BenefitPayClient.decrypt(trandata)
            data = json.loads(decrypted)[0]
        except Exception as e:
            logger.error(f"[PaymentResultView] Decryption failed: {str(e)}")
            try:
                return self._send_custom_redirect("sooq://payment-failure")
            except Exception as redirect_error:
                logger.error(
                    f"[PaymentResultView] Redirect to payment-failure failed: {str(redirect_error)}"
                )
                return self._render_template_with_error(
                    request, "Payment data could not be verified. Please try again."
                )

        result = data.get("result", "").upper()
        context = {
            "data": data,
            "payment_id": data.get("paymentId"),
            "track_id": data.get("trackId"),
            "amount": data.get("amt"),
            "result": result,
            "auth_code": data.get("authCode"),
        }
        logger.info(f"[PaymentResultView]-[Success]: context data: {context}")

        # Handling success or failure
        if result == "CAPTURED":
            # Payment is successful, attempt redirect to success URI
            try:
                return self._send_custom_redirect("sooq://payment-success")
            except Exception as redirect_error:
                logger.error(
                    f"[PaymentResultView] Redirect to payment-success failed: {str(redirect_error)}"
                )
                # Fallback: Render the success template with appropriate context
                context["status"] = "success"
                context["message"] = "Payment was successful!"
                return self._render_template_with_success(request, context)
        else:
            # Payment failed, attempt redirect to failure URI
            try:
                return self._send_custom_redirect("sooq://payment-failure")
            except Exception as redirect_error:
                logger.error(
                    f"[PaymentResultView] Redirect to payment-failure failed: {str(redirect_error)}"
                )
                # Fallback: Render the failure result template
                return self._render_template_with_error(
                    request, "Payment failed. Please contact support or try again."
                )

    def _send_custom_redirect(self, scheme_url):
        """
        Sends a custom scheme URL redirect response to the client (mobile app).
        """
        response = HttpResponse(status=302)
        response["Location"] = scheme_url
        return response

    def _render_template_with_error(self, request, error_message):
        context = {
            "status": "error",
            "message": error_message,
        }
        try:
            # Render the template with the error message
            return render(request, "payment/benefit-result.html", context)
        except Exception as e:
            logger.error(f"[PaymentResultView] Template render failed: {str(e)}")
            # If template rendering fails, send a fallback response
            return HttpResponseBadRequest(
                "An error occurred while processing your request."
            )

    def _render_template_with_success(self, request, context):
        """Renders the 'benefit-result.html' template with success context."""
        try:
            # Render the template with the success context
            return render(request, "payment/benefit-result.html", context)
        except Exception as e:
            logger.error(f"[PaymentResultView] Template render failed: {str(e)}")
            # If template rendering fails, send a fallback response
            return HttpResponseBadRequest(
                "An error occurred while processing your request."
            )
