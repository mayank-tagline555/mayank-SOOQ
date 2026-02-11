from django.contrib.auth import get_user_model
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from account.message import MESSAGES
from account.models import AdminUserRole
from account.models import UserAssignedBusiness
from sooq_althahab.enums.account import UserStatus

User = get_user_model()


class CustomJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        """
        Custom authentication method that manually retrieves and validates the JWT token
        without calling Django's default `authenticate()` method.
        """

        header = self.get_header(request)

        # No Authorization header found, return None instead of causing an error
        if not header:
            return None

        raw_token = self.get_raw_token(header)
        if not raw_token:
            return None

        try:
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)
        except InvalidToken:
            raise AuthenticationFailed(
                detail=MESSAGES["invalid_token"], code="token_invalid"
            )
        except User.DoesNotExist:
            raise AuthenticationFailed(
                detail={
                    "message": MESSAGES["session_expired"],
                    "status": "SESSION_EXPIRED",
                },
                code="session_expired",
            )

        # Ensure the token has an 'iat' (issued at), required for token expiration validation.
        token_iat = validated_token.get("iat")
        if not token_iat:
            raise AuthenticationFailed("Token missing 'iat' claim.")

        if user:
            # Convert user's expire_time to a timestamp
            if user.access_token_expiration:
                expire_timestamp = int(user.access_token_expiration.timestamp())
                if token_iat < expire_timestamp:
                    raise AuthenticationFailed(
                        detail={
                            "message": MESSAGES["session_expired"],
                            "status": "SESSION_EXPIRED",
                        },
                        code="session_expired",
                    )

            # Check if the user is suspended
            if not user.is_active and user.account_status == UserStatus.SUSPEND:
                raise AuthenticationFailed(
                    detail={
                        "message": MESSAGES["user_suspended"],
                        "status": "USER_SUSPENDED",
                    },
                    code="user_suspended",
                )

            # Check if the user's business or admin role is suspended
            if self.is_user_business_suspended(user):
                raise AuthenticationFailed(
                    detail={
                        "message": MESSAGES["user_business_account_suspended"],
                        "status": "BUSINESS_SUSPENDED",
                    },
                    code="business_suspended",
                )

        return user, validated_token

    def get_user(self, validated_token):
        """Override default `get_user` to allow users with `is_active=False`"""

        user_id = validated_token.get("user_id")

        if not user_id:
            raise AuthenticationFailed(
                detail=MESSAGES["invalid_token"], code="token_invalid"
            )

        user = User.objects.get(id=user_id)

        return user

    def is_user_business_suspended(self, user):
        """Check if the user's business or admin role is suspended."""

        admin_role = (
            AdminUserRole.objects.filter(user=user).order_by("-updated_at").first()
        )
        if admin_role and admin_role.is_suspended:
            return True

        business_role = (
            UserAssignedBusiness.objects.filter(user=user)
            .order_by("-updated_at")
            .first()
        )
        if business_role and business_role.business.is_suspended:
            return True

        return False
