import hashlib
import logging

from django.conf import settings
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView

from account.models import BusinessAccount
from account.models import User
from account.models import UserAssignedBusiness

logger = logging.getLogger(__name__)

# Mapping of verification result keys to user model fields
SHUFTI_WEBHOOK_RESPONSE_KEYS = {
    "face": {"response_field": None, "db_field": "face_verified"},
    "document": {"response_field": "document", "db_field": "document_verified"},
    "document_two": {"response_field": "document", "db_field": "document_verified"},
    "phone": {"response_field": None, "db_field": "phone_verified"},
    "email_verify": {"response_field": "verify_email", "db_field": "email_verified"},
    "questionnaire": {"response_field": None, "db_field": "due_diligence_verified"},
    "aml_for_businesses": {"response_field": None, "db_field": "business_aml_verified"},
}


class ShuftiWebhookView(APIView):
    def post(self, request, *args, **kwargs):
        # Decode the request body
        request_body = request.body.decode()
        data = request.data

        # Retrieve the user object
        user = self.get_user(data)
        if not user:
            return Response(status=404)

        # Extract verification result
        verification_result = data.get("verification_result")
        signature = request.headers.get("Signature")
        event = data.get("event")
        declined_reason = data.get("declined_reason")
        reference = data.get("reference")
        verification_url = data.get("verification_url")

        # If no verification result, return 204 No Content
        if not verification_result or declined_reason:
            user.declined_reason = declined_reason
            user.event = event
            user.reference_id = reference
            user.verification_url = verification_url
            user.save()
            return Response(status=204)

        # Validate the signature
        if not self.is_signature_valid(request_body, signature):
            return Response(status=204)

        # Update user fields based on verification result

        updated_fields = self.update_user_fields(user, verification_result)
        user.save()

        # Log updated fields if any
        if updated_fields:
            logger.info(
                f"User with id {user.id} updated successfully with the following fields: {', '.join(updated_fields)}."
            )

        # Delete all users and business with the same email and phone number as the current user, if both are verified
        try:
            if user.email_verified and user.phone_number:
                draft_users = User.global_objects.filter(
                    Q(email=user.email)
                    & (Q(email_verified=False) | Q(phone_verified=False))
                )

                draft_users_business = BusinessAccount.global_objects.filter(
                    user_assigned_businesses__user__in=draft_users
                ).distinct()

                draft_users_business.delete()
                draft_users.delete()

        except Exception as e:
            logger.error(
                f"Failed to delete users with email: {user.email} and phone number: {user.phone_number}."
            )

        return Response(status=204)

    def is_signature_valid(self, request_body, signature):
        # Generate hashed secret key
        hashed_secret_key = hashlib.sha256(
            settings.SHUFTI_SECRET_KEY.encode()
        ).hexdigest()
        # Calculate signature using request body and hashed secret key
        calculated_signature = hashlib.sha256(
            f"{request_body}{hashed_secret_key}".encode()
        ).hexdigest()

        return signature == calculated_signature

    def get_user(self, data):
        reference_key = data.get("reference", "")
        user_id = reference_key.split("&")[0] or None

        # Retrieve user object by ID, log error if not found
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            logger.error(f"User with id {user_id}{reference_key} does not exist.")
            return None

    def update_user_fields(self, user, verification_result):
        updated_fields = []
        # Iterate through the verification result items
        for key, value in verification_result.items():
            if key in SHUFTI_WEBHOOK_RESPONSE_KEYS:
                db_field = SHUFTI_WEBHOOK_RESPONSE_KEYS[key]["db_field"]
                response_field = SHUFTI_WEBHOOK_RESPONSE_KEYS[key]["response_field"]
                if response_field:
                    value = value.get(response_field)

                if value == 1:
                    # Update the user fields based on the verification result
                    setattr(user, db_field, value)
                    updated_fields.append(db_field)
        return updated_fields
