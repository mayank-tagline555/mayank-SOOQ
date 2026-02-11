import json
import logging
import os
import sys
from datetime import datetime
from typing import Any
from typing import Dict
from typing import Optional

from django.conf import settings


def _slugify(value: Optional[str]) -> str:
    """Lightweight slugifier to keep log paths filesystem-safe."""
    if not value:
        return "unknown"
    cleaned = str(value).strip().lower()
    # Replace spaces and disallowed chars with hyphens
    return (
        "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in cleaned).strip(
            "-"
        )
        or "unknown"
    )


def _strip_business_id(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Remove business identifiers from payloads to reduce noise in per-business logs."""
    if not data:
        return {}
    if not isinstance(data, dict):
        return {}
    cleaned = dict(data)
    cleaned.pop("business_id", None)
    return cleaned


class PaymentLogger:
    """
    Centralized payment logger for tracking all payment gateway transactions.
    Creates consolidated log files per business, provider, and month for easy monitoring.
    """

    def __init__(
        self,
        provider: str,
        transaction_id: Optional[str] = None,
        business_id: Optional[str] = None,
        log_datetime: Optional[datetime] = None,
    ):
        """
        Initialize payment logger.

        Args:
            provider: Payment provider name (e.g., 'credimax', 'benefit_pay')
            transaction_id: Transaction ID for logging identification
            business_id: Business identifier to segment logs
            log_datetime: Optional datetime for backfilled logs
        """
        self.provider = provider.lower()
        self.transaction_id = transaction_id
        self.business_slug = _slugify(business_id)
        self.log_datetime = log_datetime or datetime.now()
        self.logs_dir = self._ensure_logs_directory()

        # Create provider+business specific logger to avoid handler reuse across businesses
        self.logger = logging.getLogger(f"payment_{self.provider}_{self.business_slug}")
        self.logger.setLevel(logging.INFO)

        # Clear existing handlers to avoid duplicates
        self.logger.handlers.clear()

        # Create monthly log file organized by year and business/gateway
        # Format: logs/payments/2025/<business>/<gateway>/<month>.log
        month_name = self.log_datetime.strftime("%B").lower()  # e.g., 'october'
        log_file = os.path.join(self.logs_dir, f"{month_name}.log")

        # Store log file path for reference
        self.log_file_path = log_file

        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.INFO)

            # Create formatter
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            file_handler.setFormatter(formatter)

            self.logger.addHandler(file_handler)
        except (PermissionError, OSError) as e:
            # If we can't write to log file (permission denied, disk full, etc.),
            # fall back to console handler to prevent application crash
            # Log the error to console/stderr instead
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setLevel(logging.WARNING)
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
            self.logger.warning(
                f"PaymentLogger: Cannot write to log file {log_file} due to: {e}. "
                f"Falling back to console logging. Please check file permissions."
            )
        except Exception as e:
            # Catch any other unexpected errors in logger initialization
            # Use NullHandler to prevent crashes
            self.logger.addHandler(logging.NullHandler())
            import sys

            sys.stderr.write(
                f"PaymentLogger: Unexpected error initializing file handler for {log_file}: {e}\n"
            )

    def _ensure_logs_directory(self) -> str:
        """Ensure logs directory exists with year/business/provider subfolders."""
        current_year = self.log_datetime.strftime("%Y")
        logs_dir = os.path.join(
            settings.BASE_DIR,
            "logs",
            "payments",
            current_year,
            self.business_slug,
            self.provider,
        )
        try:
            os.makedirs(logs_dir, exist_ok=True)
        except (PermissionError, OSError) as e:
            # If directory creation fails, return the directory path anyway
            # File handler creation will handle the error gracefully
            sys.stderr.write(
                f"PaymentLogger: Cannot create log directory {logs_dir} due to: {e}\n"
            )
            # Return the directory path anyway - file handler creation will handle the error
        return logs_dir

    def log_transaction_start(
        self,
        transaction_type: str,
        business_id: str,
        amount: float,
        additional_data: Dict[str, Any] = None,
    ):
        """Log the start of a payment transaction."""

        self.logger.info(f"=== PAYMENT TRANSACTION STARTED ===")
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Provider: {self.provider}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Transaction Type: {transaction_type}"
        )
        self.logger.info(f"[TX_ID: {self.transaction_id or 'N/A'}] Amount: {amount}")
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Additional Data: {json.dumps(_strip_business_id(additional_data) or {}, indent=2)}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Timestamp: {datetime.now().isoformat()}"
        )
        self.logger.info(f"==========================================")

    def log_api_request(
        self,
        endpoint: str,
        method: str,
        payload: Dict[str, Any],
        headers: Dict[str, str] = None,
    ):
        """Log outgoing API requests to payment gateways."""
        self.logger.info(f"--- API REQUEST ---")
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Endpoint: {endpoint}"
        )
        self.logger.info(f"[TX_ID: {self.transaction_id or 'N/A'}] Method: {method}")
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Headers: {json.dumps(headers or {}, indent=2)}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Payload: {json.dumps(payload, indent=2)}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Timestamp: {datetime.now().isoformat()}"
        )
        self.logger.info(f"-------------------")

    def log_api_response(
        self,
        status_code: int,
        response_data: Dict[str, Any],
        response_time_ms: float = None,
    ):
        """Log API responses from payment gateways."""
        self.logger.info(f"--- API RESPONSE ---")
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Status Code: {status_code}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Response Time: {response_time_ms}ms"
            if response_time_ms
            else f"[TX_ID: {self.transaction_id or 'N/A'}] Response Time: N/A"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Response Data: {json.dumps(response_data, indent=2)}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Timestamp: {datetime.now().isoformat()}"
        )
        self.logger.info(f"--------------------")

    def log_webhook_received(
        self, webhook_data: Dict[str, Any], source: str = "unknown"
    ):
        """Log incoming webhook data."""
        self.logger.info(f"--- WEBHOOK RECEIVED ---")
        self.logger.info(f"[TX_ID: {self.transaction_id or 'N/A'}] Source: {source}")
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Webhook Data: {json.dumps(webhook_data, indent=2)}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Timestamp: {datetime.now().isoformat()}"
        )
        self.logger.info(f"-----------------------")

    def log_webhook_processing(self, step: str, data: Dict[str, Any]):
        """Log webhook processing steps."""
        self.logger.info(f"--- WEBHOOK PROCESSING: {step} ---")
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Step Data: {json.dumps(data, indent=2)}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Timestamp: {datetime.now().isoformat()}"
        )
        self.logger.info(f"--------------------------------")

    def log_transaction_update(
        self,
        old_status: str,
        new_status: str,
        reason: str = None,
        additional_data: Dict[str, Any] = None,
    ):
        """Log transaction status updates."""
        self.logger.info(f"--- TRANSACTION STATUS UPDATE ---")
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Old Status: {old_status}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] New Status: {new_status}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Reason: {reason or 'No reason provided'}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Additional Data: {json.dumps(_strip_business_id(additional_data) or {}, indent=2)}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Timestamp: {datetime.now().isoformat()}"
        )
        self.logger.info(f"----------------------------------")

    def log_error(
        self,
        error_type: str,
        error_message: str,
        exception_details: str = None,
        context: Dict[str, Any] = None,
    ):
        """Log errors and exceptions."""
        self.logger.error(f"--- ERROR OCCURRED ---")
        self.logger.error(f"Error Type: {error_type}")
        self.logger.error(f"Error Message: {error_message}")
        self.logger.error(f"Exception Details: {exception_details or 'N/A'}")
        self.logger.error(
            f"Context: {json.dumps(_strip_business_id(context) or {}, indent=2)}"
        )
        self.logger.error(f"Timestamp: {datetime.now().isoformat()}")
        self.logger.error(f"Transaction ID: {self.transaction_id}")
        self.logger.error(f"Provider: {self.provider}")
        self.logger.error(f"---------------------")

    def log_warning(self, warning_message: str, context: Dict[str, Any] = None):
        """Log warnings."""
        self.logger.warning(f"--- WARNING ---")
        self.logger.warning(f"Message: {warning_message}")
        self.logger.warning(
            f"Context: {json.dumps(_strip_business_id(context) or {}, indent=2)}"
        )
        self.logger.warning(f"Timestamp: {datetime.now().isoformat()}")
        self.logger.warning(f"Transaction ID: {self.transaction_id}")
        self.logger.warning(f"Provider: {self.provider}")
        self.logger.warning(f"---------------")

    def log_business_logic(self, action: str, data: Dict[str, Any]):
        """Log business logic operations."""
        self.logger.info(f"--- BUSINESS LOGIC: {action} ---")
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Action Data: {json.dumps(_strip_business_id(data), indent=2)}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Timestamp: {datetime.now().isoformat()}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Provider: {self.provider}"
        )
        self.logger.info(f"------------------------------")

    def log_transaction_completion(self, final_status: str, summary: Dict[str, Any]):
        """Log transaction completion."""
        self.logger.info(f"=== PAYMENT TRANSACTION COMPLETED ===")
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Final Status: {final_status}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Provider: {self.provider}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Summary: {json.dumps(_strip_business_id(summary), indent=2)}"
        )
        self.logger.info(
            f"[TX_ID: {self.transaction_id or 'N/A'}] Timestamp: {datetime.now().isoformat()}"
        )
        self.logger.info(f"=====================================")

    def get_log_file_path(self) -> str:
        """Get the current log file path."""
        return self.log_file_path


# Convenience functions for quick access
def get_credimax_logger(
    transaction_id: Optional[str] = None,
    business_id: Optional[str] = None,
    log_datetime: Optional[datetime] = None,
) -> PaymentLogger:
    """Get Credimax payment logger instance segmented by business and month."""
    return PaymentLogger("credimax", transaction_id, business_id, log_datetime)


def get_benefit_pay_logger(
    transaction_id: Optional[str] = None,
    business_id: Optional[str] = None,
    log_datetime: Optional[datetime] = None,
) -> PaymentLogger:
    """Get Benefit Pay payment logger instance segmented by business and month."""
    return PaymentLogger("benefit_pay", transaction_id, business_id, log_datetime)


def log_payment_error(
    provider: str,
    transaction_id: str,
    error_type: str,
    error_message: str,
    exception_details: str = None,
    context: Dict[str, Any] = None,
    business_id: Optional[str] = None,
    log_datetime: Optional[datetime] = None,
):
    """Quick function to log payment errors."""
    logger = PaymentLogger(provider, transaction_id, business_id, log_datetime)
    logger.log_error(error_type, error_message, exception_details, context)
    return logger.get_log_file_path()
