import binascii
import json
import logging
from urllib.parse import quote
from urllib.parse import unquote_plus

import requests
from Crypto.Cipher import AES
from django.conf import settings

logger = logging.getLogger(__name__)


class BenefitPayClient:
    AES_IV = settings.BENEFIT_AES_IV
    RESOURCE_KEY = settings.BENEFIT_RESOURCE_KEY
    TRANPORTAL_ID = settings.BENEFIT_TRANPORTAL_ID
    TRANPORTAL_PASSWORD = settings.BENEFIT_TRANPORTAL_PASSWORD
    PAYMENT_URL = settings.BENEFIT_PAYMENT_URL
    SUCCESS_URL = settings.BENEFIT_SUCCESS_URL
    FAILURE_URL = settings.BENEFIT_FAILURE_URL
    NOTIFICATION_URL = getattr(settings, "BENEFIT_NOTIFICATION_URL", "")

    @classmethod
    def pad(cls, s):
        bs = AES.block_size
        return s + (bs - len(s) % bs) * chr(bs - len(s) % bs)

    @classmethod
    def unpad(cls, s):
        return s[: -ord(s[len(s) - 1 :])]

    @classmethod
    def encrypt(cls, data):
        plain_text = quote(data)
        raw = cls.pad(plain_text)
        cipher = AES.new(cls.RESOURCE_KEY.encode(), AES.MODE_CBC, cls.AES_IV)
        encrypted = cipher.encrypt(raw.encode())
        return binascii.hexlify(encrypted).decode().upper()

    @classmethod
    def decrypt(cls, encrypted_hex):
        encrypted = binascii.unhexlify(encrypted_hex)
        cipher = AES.new(cls.RESOURCE_KEY.encode(), AES.MODE_CBC, cls.AES_IV)
        decrypted = cipher.decrypt(encrypted).decode()
        return unquote_plus(cls.unpad(decrypted))

    @classmethod
    def initiate_payment(cls, amount, track_id):
        """
        Initiate a payment session with Benefit Pay.

        Args:
            amount (float): The payment amount
            track_id (str): The transaction track ID

        Returns:
            dict: The response from Benefit Pay
        """
        payload_data = [
            {
                "id": cls.TRANPORTAL_ID,
                "password": cls.TRANPORTAL_PASSWORD,
                "action": "1",  # Purchase
                "currencycode": "048",  # Bahraini Dinar
                "amt": str(amount),
                "trackId": track_id,
                "udf1": "",
                "udf2": "",
                "udf3": "",
                "udf4": "",
                "udf5": "",
                "responseURL": cls.SUCCESS_URL,
                "errorURL": cls.FAILURE_URL,
            }
        ]

        # Add notification URL if configured
        if cls.NOTIFICATION_URL:
            payload_data[0]["notificationURL"] = cls.NOTIFICATION_URL

        json_data = json.dumps(payload_data)
        trandata = cls.encrypt(json_data)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "charset": "utf-8",
        }
        body = json.dumps([{"id": cls.TRANPORTAL_ID, "trandata": trandata}])

        try:
            res = requests.post(cls.PAYMENT_URL, headers=headers, data=body, timeout=30)
            res.raise_for_status()  # Raise an exception for bad status codes
            return res.json()
        except requests.exceptions.Timeout:
            logger.error("[BenefitPay] Payment initiation timeout")
            return [{"status": "0", "errorText": "Payment initiation timeout"}]
        except requests.exceptions.RequestException as e:
            # Log the error and return a structured error response
            logger.error(f"[BenefitPay] Payment initiation failed: {str(e)}")
            return [
                {"status": "0", "errorText": f"Payment initiation failed: {str(e)}"}
            ]
