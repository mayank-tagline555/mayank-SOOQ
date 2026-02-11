import logging

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import generics
from rest_framework import serializers
from rest_framework import status
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.tokens import UntypedToken

from account import serializers
from account.message import MESSAGES
from account.models import Address
from account.models import AdminUserRole
from account.models import BankAccount
from account.models import BusinessAccountDocument
from account.models import ContactSupportRequest
from account.models import FCMToken
from account.models import Organization
from account.models import OrganizationCurrency
from account.models import RoleHistory
from account.models import Shareholder
from account.models import User
from account.models import UserAssignedBusiness
from account.models import UserPreference
from account.serializers import AddressSerializer
from account.serializers import AdminLoginSerializer
from account.serializers import AppVersionSerializer
from account.serializers import BankAccountSerializer
from account.serializers import BusinessAccountDocumentCreateSerializer
from account.serializers import BusinessAccountDocumentSerializer
from account.serializers import BusinessAccountUpdateSerializer
from account.serializers import BusinessSavedCardCreateSerializer
from account.serializers import BusinessSavedCardSessionSerializer
from account.serializers import BusinessSavedCardSetDefaultSerializer
from account.serializers import BusinessSavedCardTokenSerializer
from account.serializers import BusinessUserSerializer
from account.serializers import ChangePasswordSerializer
from account.serializers import ContactSupportRequestResponseSerializer
from account.serializers import ContactSupportRequestSerializer
from account.serializers import FCMDetailsSerializer
from account.serializers import ForgetPasswordSendOTPSerializer
from account.serializers import ForgetPasswordVerifyOTPSerializer
from account.serializers import OrganizationCurrencySerializer
from account.serializers import OrganizationFeesTaxesSerializer
from account.serializers import ResetPasswordSerializer
from account.serializers import ShareholderCreateSerializer
from account.serializers import ShareholderResponseSerializer
from account.serializers import SubUserSerializer
from account.serializers import SwitchRoleSerializer
from account.serializers import UserDeleteSerializer
from account.serializers import UserLoginSerializer
from account.serializers import UserPartialUpdateSerializer
from account.serializers import UserPreferenceSerializer
from account.serializers import UserRolesSerializer
from account.serializers import UserSessionSerializer
from account.utils import create_and_assign_business_to_user
from account.utils import decrypt_data
from account.utils import encrypt_data
from account.utils import generate_otp
from account.utils import generate_tokens
from account.utils import get_user_or_business_name
from investor.models import PurchaseRequest
from sooq_althahab.billing.subscription.helpers import get_subscription_usage_info
from sooq_althahab.constants import BANK_ACCOUNT_CHANGE_PERMISSION
from sooq_althahab.constants import BUSINESS_SAVED_CARDS_CHANGE_PERMISSION
from sooq_althahab.constants import BUSINESS_SAVED_CARDS_CREATE_PERMISSION
from sooq_althahab.constants import BUSINESS_SAVED_CARDS_VIEW_PERMISSION
from sooq_althahab.constants import CURRENCY_CHANGE_PERMISSION
from sooq_althahab.constants import CURRENCY_CREATE_PERMISSION
from sooq_althahab.constants import CURRENCY_VIEW_PERMISSION
from sooq_althahab.constants import NOTIFICATION_VIEW_PERMISSION
from sooq_althahab.constants import SHARE_HOLDER_CHANGE_PERMISSION
from sooq_althahab.constants import SHARE_HOLDER_CREATE_PERMISSION
from sooq_althahab.constants import SHARE_HOLDER_DELETE_PERMISSION
from sooq_althahab.constants import SHARE_HOLDER_VIEW_PERMISSION
from sooq_althahab.constants import SUB_USER_CREATE_PERMISSION
from sooq_althahab.constants import SUB_USER_VIEW_PERMISSION
from sooq_althahab.constants import USER_PROFILE_CHANGE_PERMISSION
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.account import UserStatus
from sooq_althahab.enums.account import UserType
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.helper import PermissionManager
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.tasks import send_mail
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import CustomModelViewSet
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab.utils import send_notification_count_to_users
from sooq_althahab_admin.models import AppVersion
from sooq_althahab_admin.models import BusinessSavedCardToken
from sooq_althahab_admin.models import Notification
from sooq_althahab_admin.serializers import NotificationSerializer

logger = logging.getLogger(__name__)


class RegistrationAPIView(generics.CreateAPIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = serializers.UserRegistrationSerializer

    def create(self, request, *args, **kwargs):
        with transaction.atomic():
            email = request.data.get("email").strip().lower()
            role = request.data.get("role")
            organization_code = request.data.get("organization_code")
            user_type = request.data.get("user_type")
            business_name = request.data.get("business_name")
            phone_number = request.data.get("phone_number")

            try:
                organization = Organization.objects.get(code=organization_code)
            except Organization.DoesNotExist:
                return generic_response(
                    status_code=status.HTTP_404_NOT_FOUND,
                    error_message=MESSAGES["organization_not_found"],
                )

            existing_user = User.global_objects.filter(
                email=email,
                organization_id=organization,
                phone_verified=True,
                email_verified=True,
                user_assigned_businesses__business__business_account_type=role,
            ).first()

            if existing_user:
                # For business users, include business_aml_verified in the unverified check
                is_unverified = (
                    not existing_user.face_verified
                    or not existing_user.document_verified
                )

                if existing_user.user_type == UserType.BUSINESS:
                    is_unverified = (
                        is_unverified or not existing_user.business_aml_verified
                    )

                if is_unverified:
                    return generic_response(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        error_message=MESSAGES["email_registered_but_not_verified"],
                    )

                return generic_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_message=MESSAGES["user_already_exists"],
                )

            # TODO: We currently allow only one email per business.
            # Although we have code in place to support a single user accessing multiple business roles with the same email, this functionality is not yet enabled.
            # At present, the same email cannot be used for multiple business roles—each business must have a unique email.

            # # If the user already exists and tries to use the same role and the same email.
            # if existing_user:
            #     user_roles = set(
            #         user_role.business.business_account_type
            #         for user_role in existing_user.user_assigned_businesses.all()
            #     )
            #     if role in user_roles:
            #         return generic_response(
            #             status_code=status.HTTP_400_BAD_REQUEST,
            #             error_message=MESSAGES["user_already_exists"],
            #         )
            #     # Check if the user exists but with a different role.
            #     else:
            #         assigned_business = create_and_assign_business_to_user(
            #             existing_user, role, organization, business_name, user_type
            #         )
            #         existing_user.role = role
            #         user_data = self.get_serializer_class()(existing_user).data

            #         tokens = generate_tokens(
            #             existing_user,
            #             email,
            #             role,
            #             assigned_business.pk,
            #             organization.code,
            #         )
            #         return generic_response(
            #             status_code=status.HTTP_201_CREATED,
            #             message=MESSAGES["user_created"],
            #             data={**user_data, **tokens},
            #         )
            return self.create_new_user(request, organization)

    def create_new_user(self, request, organization):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        validated_data = serializer.validated_data
        password = validated_data.pop("password", None)
        role = validated_data.pop("role", None)
        validated_data.pop("organization_code", None)
        business_name = validated_data.pop("business_name", None)
        validated_data.get("language_code")
        user_type = validated_data.get("user_type")
        email = validated_data.get("email").strip().lower()
        phone_number = validated_data.get("phone_number")

        # NOTE: If env is not a production and phone number is in given list then make phone verified
        if settings.PAYMENT_ENV != "prod":
            if phone_number in settings.DUMMY_PHONE_NUMBERS:
                validated_data["phone_verified"] = True
                validated_data["email_verified"] = True
                validated_data["face_verified"] = True
                validated_data["document_verified"] = True
                validated_data["business_aml_verified"] = True
                validated_data["due_diligence_verified"] = True

        # Create the new user
        validated_data["email"] = email
        user = User.objects.create_user(
            password=password, organization_id=organization, **validated_data
        )
        assigned_business = create_and_assign_business_to_user(
            user, role, organization, business_name, user_type
        )

        tokens = generate_tokens(
            user, email, role, assigned_business.pk, organization.code
        )
        validated_data["role"] = role
        return generic_response(
            status_code=status.HTTP_201_CREATED,
            message=MESSAGES["user_created"],
            data={**serializer.data, **tokens},
        )


class BackUpUserLoginAPIView(generics.CreateAPIView):
    serializer_class = UserLoginSerializer
    permission_classes = []
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        # serializer = self.get_serializer(data=request.data)
        # if not serializer.is_valid():
        #     return handle_serializer_errors(serializer)

        fcm_details = request.data.get("fcm_details")
        email = request.data.get("email", "").strip().lower()
        password = request.data.get("password")
        device_id = fcm_details.get("device_id")
        organization_code = request.data.get("organization_code")
        role = request.data.get("role")

        try:
            organization = Organization.objects.get(code=organization_code)
        except Organization.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["organization_not_found"],
            )

        # Authenticate user with email and password
        user = authenticate(
            username=email,
            password=password,
            organization_id=organization,
            # role=role,
        )

        if user is None:
            user = User.objects.filter(
                email=email,
                phone_verified=True,
                email_verified=True,
                # user_assigned_businesses__business__business_account_type=role,
                organization_id=organization,
            ).first()

            if not user:
                error_message = MESSAGES["user_not_found"]  # "User not found."
            else:
                error_message = MESSAGES[
                    "invalid_password"
                ]  # "Incorrect password. Please try again."

            return generic_response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_message=error_message,
            )

        # role_history_exists = (
        #     RoleHistory.objects.filter(user=user, device_id=device_id)
        #     .order_by("-updated_at")
        #     .first()
        # )
        # if role_history_exists:
        #     role = role_history_exists.role
        # else:
        #     # Get the user latest role, if no role history exists
        #     latest_user_role = get_latest_user_role(user)

        #     if not latest_user_role:
        #         return generic_response(
        #             status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        #             error_message=MESSAGES["role_not_found"],
        #         )

        #     Create a new role history entry if role is found
        #     RoleHistory.objects.create(
        #         role=latest_user_role, user=user, device_id=device_id
        #     )
        #     role = latest_user_role

        # Create or update existing FCM token using serializer
        if fcm_details:
            existing_fcm_token, created = FCMToken.objects.get_or_create(
                user=user, device_id=device_id, defaults=fcm_details
            )

            fcm_serializer = FCMDetailsSerializer(
                existing_fcm_token,
                data=fcm_details,
                partial=True,
                context={"user": user},
            )

            if fcm_serializer.is_valid():
                fcm_serializer.save()
            else:
                return generic_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_message=MESSAGES["invalid_fcm_details"],
                )

        assigned_business = (
            UserAssignedBusiness.objects.filter(
                user=user,
            )
            .select_related("business")
            .first()
        )

        role = (
            assigned_business.business.business_account_type
            if assigned_business
            else None
        )
        # Generate token after successful validation and creation
        token = generate_tokens(
            user=user,
            email=email,
            role=role,
            assigned_business=(assigned_business.pk if assigned_business else None),
            organization_code=organization.code,
        )

        user.last_login = timezone.now()
        user.save()

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["login_successful"],
            data={"token": token},
        )


class UserLoginAPIView(generics.CreateAPIView):
    serializer_class = UserLoginSerializer
    permission_classes = []
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        fcm_details = request.data.get("fcm_details")
        email = request.data.get("email", "").strip().lower()
        password = request.data.get("password")
        device_id = fcm_details.get("device_id")
        organization_code = request.data.get("organization_code")
        role = request.data.get("role")

        try:
            organization = Organization.objects.get(code=organization_code)
        except Organization.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["organization_not_found"],
            )

        # Authenticate user with email and password
        user = authenticate(
            username=email,
            password=password,
            organization_id=organization,
            role=role,
        )

        if user is None:
            user = User.objects.filter(
                email=email,
                phone_verified=True,
                email_verified=True,
                user_assigned_businesses__business__business_account_type=role,
                organization_id=organization,
            ).first()

            if not user:
                error_message = MESSAGES["user_not_found"]  # "User not found."
            else:
                error_message = MESSAGES[
                    "invalid_password"
                ]  # "Incorrect password. Please try again."

            return generic_response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_message=error_message,
            )

        # role_history_exists = (
        #     RoleHistory.objects.filter(user=user, device_id=device_id)
        #     .order_by("-updated_at")
        #     .first()
        # )
        # if role_history_exists:
        #     role = role_history_exists.role
        # else:
        #     # Get the user latest role, if no role history exists
        #     latest_user_role = get_latest_user_role(user)

        #     if not latest_user_role:
        #         return generic_response(
        #             status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        #             error_message=MESSAGES["role_not_found"],
        #         )

        #     Create a new role history entry if role is found
        #     RoleHistory.objects.create(
        #         role=latest_user_role, user=user, device_id=device_id
        #     )
        #     role = latest_user_role

        # Create or update existing FCM token using serializer
        if fcm_details:
            existing_fcm_token, created = FCMToken.objects.get_or_create(
                user=user, device_id=device_id, defaults=fcm_details
            )

            fcm_serializer = FCMDetailsSerializer(
                existing_fcm_token,
                data=fcm_details,
                partial=True,
                context={"user": user},
            )

            if fcm_serializer.is_valid():
                fcm_serializer.save()
            else:
                return generic_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_message=MESSAGES["invalid_fcm_details"],
                )

        assigned_business = (
            UserAssignedBusiness.objects.filter(
                user=user,
            )
            .select_related("business")
            .first()
        )

        # Generate token after successful validation and creation
        token = generate_tokens(
            user=user,
            email=email,
            role=role,
            assigned_business=(assigned_business.pk if assigned_business else None),
            organization_code=organization.code,
        )

        user.last_login = timezone.now()
        user.save()

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["login_successful"],
            data={"token": token},
        )


class AdminLoginAPIView(generics.CreateAPIView):
    serializer_class = AdminLoginSerializer
    permission_classes = []
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        email = request.data.get("email", "").strip().lower()
        password = request.data.get("password")
        organization_code = request.data.get("organization_code")

        try:
            organization = Organization.objects.get(code=organization_code)
        except Organization.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["organization_not_found"],
            )

        # Authenticate user with email and password
        user = authenticate(
            username=email,
            password=password,
            organization_id=organization,
        )

        if user is None:
            user = User.objects.filter(
                email=email, organization_id=organization
            ).first()
            if not user:
                error_message = MESSAGES["user_not_found"]  # "User not found."
            else:
                error_message = MESSAGES[
                    "invalid_password"
                ]  # "Incorrect password. Please try again."

            return generic_response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_message=error_message,
            )

        admin_user = AdminUserRole.global_objects.filter(user=user).first()
        role = admin_user.role

        # Generate token after successful validation and creation
        token = generate_tokens(
            user=user,
            email=email,
            role=role,
            assigned_business=(admin_user.pk if admin_user else None),
            organization_code=organization.code,
        )

        user.last_login = timezone.now()
        user.save()

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["login_successful"],
            data={"token": token},
        )


class SwitchUserRoleAPI(generics.GenericAPIView):
    """
    API to handle switching of user roles.

    Response:
        200 OK: Returns a new access token for the switched role.
        400 Bad Request: If validation fails.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = SwitchRoleSerializer

    def post(self, request, *args, **kwargs):
        user = request.user
        # get the organization_code from the existing token.
        organization_code = request.auth.get("organization_code", None)
        serializer = self.get_serializer(data=request.data, context={"user": user})
        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        role = request.data.get("role", None)

        assigned_business = UserAssignedBusiness.objects.filter(
            user=user, business__business_account_type=role
        ).first()
        if (
            not AdminUserRole.objects.filter(user=user, role=role).exists()
            and not assigned_business
        ):
            return generic_response(
                error_message=MESSAGES["role_mismatch"],
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        device_id = serializer.validated_data["device_id"]
        # Check if RoleHistory exists for the user and device_id
        user_last_login_role = (
            RoleHistory.objects.filter(user=user, device_id=device_id)
            .order_by("-created_at")
            .first()
        )
        # Check if the role is the same as the last login role
        if user_last_login_role is not None and role == user_last_login_role.role:
            return generic_response(
                error_message=MESSAGES["already_assigned_role"].format(role=role),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        role_to_switch = serializer.validated_data["role"]
        RoleHistory.objects.create(user=user, role=role_to_switch, device_id=device_id)

        # Generate new tokens using the helper function
        tokens = generate_tokens(
            user=user,
            email=user.email,
            role=role_to_switch,
            assigned_business=(assigned_business.pk if assigned_business else None),
            organization_code=organization_code,
        )

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["switch_role_successful"].format(
                role_to_switch=role_to_switch
            ),
            data={"token": tokens},
        )


class SessionAPI(APIView):
    """
    API to fetch user details based on the provided token.

    Response:
        200 OK: Returns the user's details.
        401 Unauthorized: If the token is invalid or expired.
    """

    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Fetch user details based on the provided token.",
        responses={
            200: openapi.Response(
                schema=UserSessionSerializer,
                description="User session details retrieved successfully.",
            ),
        },
    )
    def get(self, request, *args, **kwargs):
        user = request.user
        role = request.auth.get("role", None)
        user.role = role
        business = request.auth.get("current_business", None)
        if role in UserRoleChoices.values:
            business = None
        serializer = UserSessionSerializer(user, context={"business": business})

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["session_success"],
            data=serializer.data,
        )


class ChangePasswordAPIView(generics.GenericAPIView):
    """
    API to handle password change for authenticated users.

    Response:
        200 OK: Password changed successfully.
        400 Bad Request: If validation fails.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request, *args, **kwargs):
        user = request.user
        serializer = self.get_serializer(data=request.data, context={"user": user})

        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        serializer.save()
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["password_changed_success"],
        )


class ForgetPasswordBaseView:
    """Shared helper methods for ForgetPassword APIs."""

    @staticmethod
    def get_user_by_email_and_role(email: str, role: str = None):
        """
        Fetch user based on email and role.
        If role is provided -> match user businesses.
        Else -> check admin user.
        """
        email = email.strip().lower()
        if role:
            user = User.objects.filter(
                email=email,
                email_verified=True,
                phone_verified=True,
                user_assigned_businesses__business__business_account_type=role,
            ).first()
            if not user:
                return None
        else:
            user = User.objects.filter(email=email).first()
            if not user or not AdminUserRole.global_objects.filter(user=user).exists():
                return None
        return user


class ForgetpasswordSendOtpAPIView(ForgetPasswordBaseView, generics.CreateAPIView):
    serializer_class = ForgetPasswordSendOTPSerializer
    permission_classes = []
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        email = serializer.validated_data["email"]
        role = serializer.validated_data.get("role")

        # Resolve user
        user = self.get_user_by_email_and_role(email, role)
        if not user:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["email_not_found"],
            )

        # Generate OTP
        otp = generate_otp()
        encoded_otp, encoded_email = encrypt_data(otp), encrypt_data(email)
        encoded_role = encrypt_data(role) if role else None

        # Generate token
        refresh = RefreshToken.for_user(user)
        access_token = refresh.access_token
        access_token["email"] = encoded_email
        access_token["otp"] = encoded_otp
        if role:
            access_token["role"] = encoded_role
        access_token.set_exp(lifetime=settings.OTP_EXPIRY_TIME)

        # Send email
        send_mail.delay(
            _("Reset password OTP"),
            "templates/forget-password-otp.html",
            {"fullname": user.fullname or _("User"), "otp": otp},
            email,
            user.user_preference.language_code if user else "en",
            organization_code=user.organization_id.code,
        )

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["sent_otp_success"],
            data={"token": str(access_token)},
        )


class ForgetPasswordVerifyOTPAPIView(ForgetPasswordBaseView, generics.CreateAPIView):
    serializer_class = ForgetPasswordVerifyOTPSerializer
    permission_classes = []
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        token = request.query_params.get("token")
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        user_otp = serializer.validated_data["otp"]

        # Decode token
        try:
            decoded_token = UntypedToken(token)
        except TokenError:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["invalid_token"],
            )

        email = decrypt_data(decoded_token.get("email"))
        otp = decrypt_data(decoded_token.get("otp"))
        role = (
            decrypt_data(decoded_token.get("role"))
            if decoded_token.get("role")
            else None
        )

        # Validate user
        user = self.get_user_by_email_and_role(email, role)
        if not user:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["email_not_found"],
            )

        # Validate OTP
        if user_otp != otp:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["invalid_otp"],
            )

        # Success -> issue login token
        refresh = RefreshToken.for_user(user)
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["otp_verify_success"],
            data={"token": str(refresh.access_token)},
        )


class ResetPasswordApiView(generics.CreateAPIView):
    serializer_class = ResetPasswordSerializer
    permission_classes = []
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        token = request.query_params.get("token")
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        password = serializer.validated_data.get("password")
        try:
            payload = UntypedToken(token)
            user = User.objects.get(id=payload["user_id"])

        except TokenError:
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["invalid_token"],
            )
        user.set_password(password)
        user.access_token_expiration = timezone.now()
        user.is_active = True
        user.save()
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["password_changed_success"],
        )


class BankAccountUpdateView(generics.UpdateAPIView):
    """
    Update bank account details for a requested user.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = BankAccountSerializer
    http_method_names = ["patch"]

    @PermissionManager(BANK_ACCOUNT_CHANGE_PERMISSION)
    def patch(self, request):
        user = request.user

        bank_account, created = BankAccount.objects.update_or_create(
            user=user,
            defaults=request.data,
        )
        serializer = self.serializer_class(
            bank_account, data=request.data, partial=True
        )
        if serializer.is_valid():
            serializer.save(user=user)
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["bank_account_updated"],
                data=serializer.data,
            )

        return handle_serializer_errors(serializer)


class UserProfilePartialUpdateView(generics.UpdateAPIView):
    """
    Update user profile details for a requested user.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = UserPartialUpdateSerializer
    http_method_names = ["patch"]
    queryset = User.objects.all()

    @PermissionManager(USER_PROFILE_CHANGE_PERMISSION)
    def patch(self, request, pk=None):
        user_profile = self.get_object()
        # Serialize and update the user profile data
        serializer = self.get_serializer(user_profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["user_profile_updated"],
                data=serializer.data,
            )

        return handle_serializer_errors(serializer)

    def get_object(self):
        """
        Ensure the user can only update their own profile.
        """
        user = self.request.user
        try:
            user_profile = User.objects.get(id=user.id)
        except User.DoesNotExist:
            raise generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["user_profile_not_exists"],
            )
        return user_profile


class AddressViewSet(CustomModelViewSet):
    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    queryset = Address.objects.all()

    def get_queryset(self):
        """Get the queryset for the current user."""
        user = self.request.user
        if user.is_authenticated:
            return Address.objects.filter(user=self.request.user)
        return self.queryset.none()

    def perform_create(self, serializer):
        """Save the address with the current user."""
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        """Update the address with the current user."""
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        """Create a new address."""
        serializer = self.serializer_class(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            self.perform_create(serializer)
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["address_created"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)

    def retrieve(self, request, *args, **kwargs):
        """Retrieve an address."""
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["address_retrieved"],
            data=serializer.data,
        )

    def partial_update(self, request, *args, **kwargs):
        """Partially update an address."""
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            self.perform_update(serializer)
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["address_updated"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)

    def update(self, request, *args, **kwargs):
        """Update an address."""
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data)
        if serializer.is_valid():
            self.perform_update(serializer)
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["address_updated"],
                data=serializer.data,
            )
        return handle_serializer_errors(serializer)

    def destroy(self, request, *args, **kwargs):
        """Delete an address."""
        instance = self.get_object()
        instance.delete()
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["address_deleted"],
            data={},
        )

    def list(self, request, *args, **kwargs):
        """List all addresses."""
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["address_fetched"],
            data=response_data,
        )


class ShareholderListCreateAPIView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ShareholderCreateSerializer
    queryset = Shareholder.objects.all()
    http_method_names = ["get", "post"]
    pagination_class = CommonPagination

    def get_queryset(self):
        """
        Restrict the queryset to shareholders belonging to the authenticated user's assigned businesses.
        """
        user = self.request.user
        if user.is_authenticated:
            try:
                user_role = self.request.auth.get("role", None)
                # Get business assigned to the authenticated user
                assigned_business = UserAssignedBusiness.objects.get(
                    user=user, business__business_account_type=user_role
                )
            except:
                return self.queryset.none()
            # Filter shareholders by those businesses
            return self.queryset.filter(business__id=assigned_business.pk)
        return self.queryset.none()

    @PermissionManager(SHARE_HOLDER_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            shareholder = serializer.save()

            # Use ShareholderResponseSerializer for the response data
            response_serializer = ShareholderResponseSerializer(shareholder)
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["share_holder_added"],
                data=response_serializer.data,
            )
        return handle_serializer_errors(serializer)

    @PermissionManager(SHARE_HOLDER_VIEW_PERMISSION)
    def list(self, request, *args, **kwargs):
        """
        Handles the GET request to list Shareholder instances.
        """
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        # Replace ShareholderSerializer with ShareholderResponseSerializer here
        serializer = ShareholderResponseSerializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["share_holder_fetched"],
            data=response_data,
        )


class ShareholderRetrieveUpdateDeleteAPIView(generics.RetrieveUpdateDestroyAPIView):
    """
    API view to retrieve a specific Shareholder instance by its ID.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ShareholderResponseSerializer
    queryset = Shareholder.objects.all()
    http_method_names = ["get", "patch", "delete"]

    def get_queryset(self):
        """
        Restrict the queryset to shareholders belonging to the authenticated user's assigned businesses.
        """
        user = self.request.user
        if user.is_authenticated:
            try:
                user_role = self.request.auth.get("role", None)
                # Get business assigned to the authenticated user
                assigned_business = UserAssignedBusiness.objects.get(
                    user=user, business__business_account_type=user_role
                )
            except:
                return self.queryset.none()
            # Filter shareholders by those businesses
            return self.queryset.filter(business__id=assigned_business.pk)
        return self.queryset.none()

    @PermissionManager(SHARE_HOLDER_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """
        Handles the GET request to retrieve a Shareholder instance.
        """
        try:
            return super().get(request, *args, **kwargs)
        except Shareholder.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["share_holder_not_found"],
            )

    @PermissionManager(SHARE_HOLDER_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        """
        Handles the PATCH request to partially update a Shareholder instance.
        """
        try:
            return super().patch(request, *args, **kwargs)
        except Shareholder.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["share_holder_not_found"],
            )

    @PermissionManager(SHARE_HOLDER_DELETE_PERMISSION)
    def delete(self, request, *args, **kwargs):
        """
        Handles the DELETE request to delete a Shareholder instance.
        """
        try:
            instance = self.get_object()
            instance.delete()
            return generic_response(
                status_code=status.HTTP_200_OK,
                message=MESSAGES["share_holder_deleted"],
            )
        except Shareholder.DoesNotExist:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["share_holder_not_found"],
            )


class OrganizationCurrenciesViewSet(viewsets.ModelViewSet):
    """
    ViewSet to handle listing, creating, updating, and deleting currencies for an organization.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = OrganizationCurrencySerializer
    queryset = OrganizationCurrency.objects

    def get_queryset(self):
        """
        Restrict the queryset to the logged-in user's organization.
        """
        user = self.request.user
        if user.is_authenticated:
            user_organization_id = user.organization_id
            return self.queryset.filter(organization=user_organization_id)
        return self.queryset.none()

    @PermissionManager(CURRENCY_VIEW_PERMISSION)
    def list(self, request, *args, **kwargs):
        """
        Handle GET request to retrieve currencies for the authenticated user's organization.
        """

        instance = self.get_queryset()
        serializer = self.serializer_class(instance=instance, many=True)
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["currencies_fetched"],
            data=serializer.data,
        )

    @PermissionManager(CURRENCY_CREATE_PERMISSION)
    def create(self, request, *args, **kwargs):
        """
        Handle POST request to create a new currency for the authenticated user's organization.
        Prevent duplicate entries based on currency code and organization.
        """
        user_organization_id = self.request.user.organization_id
        currency_code = request.data.get("currency_code")

        # Check for duplicates
        if OrganizationCurrency.objects.filter(
            organization=user_organization_id, currency_code=currency_code
        ).exists():
            return generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["currency_already_exists"].format(
                    currency_code=currency_code
                ),
            )

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(organization=user_organization_id)
        return generic_response(
            status_code=status.HTTP_201_CREATED,
            message=MESSAGES["currency_created"],
            data=serializer.data,
        )

    @PermissionManager(CURRENCY_CHANGE_PERMISSION)
    def partial_update(self, request, *args, **kwargs):
        """
        Handle PATCH request to partially update a specific organization currency.
        """
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["currency_updated"],
            data=serializer.data,
        )


class UserPreferenceViewSet(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserPreferenceSerializer
    http_method_names = ["get", "patch"]

    def get(self, request, *args, **kwargs):
        """
        Retrieve the user's preferences.
        """
        user_preference = get_object_or_404(UserPreference, user=request.user)
        serializer = self.get_serializer(user_preference, context={"request": request})
        return generic_response(
            data=serializer.data,
            message=MESSAGES["user_preferences_fetched"],
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, *args, **kwargs):
        """
        Update the user's preferences.
        """
        user_preference, _ = UserPreference.objects.get_or_create(user=request.user)
        serializer = self.get_serializer(
            user_preference,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        if serializer.is_valid():
            serializer.save()
            return generic_response(
                data=serializer.data,
                message=MESSAGES["user_preferences_upadated"],
                status_code=status.HTTP_200_OK,
            )
        return handle_serializer_errors(serializer)


class NotificationListAPIView(generics.ListAPIView):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination

    def get_queryset(self):
        """Restrict the queryset to the logged-in user."""

        user = self.request.user
        if not user.is_authenticated:
            return self.queryset.none()
        return self.queryset.filter(user=self.request.user)

    @PermissionManager(NOTIFICATION_VIEW_PERMISSION)
    def list(self, request, *args, **kwargs):
        """Handles the GET request to list"""

        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["notifications_fetched"],
            data=response_data,
        )


class BusinessSavedCardListAPIView(generics.ListAPIView):
    serializer_class = BusinessSavedCardTokenSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination

    def get_queryset(self):
        """Filter cards by business."""
        if self.request.user.is_anonymous:
            return BusinessSavedCardToken.objects.none()

        # Check if auth exists (for Swagger documentation)
        if not hasattr(self.request, "auth") or not self.request.auth:
            return BusinessSavedCardToken.objects.none()

        current_business_id = self.request.auth.get("current_business")
        if not current_business_id:
            return BusinessSavedCardToken.objects.none()

        try:
            business = UserAssignedBusiness.objects.get(id=current_business_id).business
        except UserAssignedBusiness.DoesNotExist:
            raise Http404(MESSAGES["business_account_not_found"])

        return BusinessSavedCardToken.objects.filter(business=business).order_by(
            "-created_at"
        )

    @PermissionManager(BUSINESS_SAVED_CARDS_VIEW_PERMISSION)
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["business_saved_cards_fetched"],
            data=response_data,
        )


class BusinessSavedCardSessionCreateAPIView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BusinessSavedCardSessionSerializer
    queryset = BusinessSavedCardToken.objects.none()

    @PermissionManager(BUSINESS_SAVED_CARDS_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            session_data = serializer.save()
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["business_saved_card_session_created"],
                data=session_data,
            )

        return handle_serializer_errors(serializer)


class BusinessSavedCardCreateAPIView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BusinessSavedCardCreateSerializer
    queryset = BusinessSavedCardToken.objects.none()

    @PermissionManager(BUSINESS_SAVED_CARDS_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            saved_card = serializer.save()
            response_data = BusinessSavedCardTokenSerializer(saved_card).data

            # Add redirect URL for mobile app after successful card addition
            response_data[
                "redirect_url"
            ] = settings.CREDIMAX_CARD_ADDITION_SUCCESS_REDIRECT_URL

            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["business_saved_card_added"],
                data=response_data,
            )

        # Format error response - remove field name prefixes for cleaner UX
        errors = serializer.errors
        error_messages = []

        for field, messages in errors.items():
            if isinstance(messages, list):
                message_text = ", ".join(str(msg) for msg in messages)
            else:
                message_text = str(messages)

            # Don't include field name prefix - just show the error message
            error_messages.append(message_text)

        error_message = " | ".join(error_messages)

        # Add redirect URL for failure cases (card authentication failed)
        error_response = generic_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_message=error_message,
            data={"redirect_url": settings.CREDIMAX_CARD_ADDITION_FAILURE_REDIRECT_URL},
        )
        return error_response


class BusinessSavedCardSetDefaultAPIView(APIView):
    """
    API view to set a business saved card as the default card for subscriptions and transactions.
    The card ID is provided in the URL path parameter.
    """

    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Set a business saved card as the default card for subscriptions and transactions.",
        manual_parameters=[
            openapi.Parameter(
                "id",
                openapi.IN_PATH,
                description="The ID of the card to set as default",
                type=openapi.TYPE_STRING,
                required=True,
            ),
        ],
        responses={
            200: openapi.Response(
                description="Card successfully set as default",
                schema=BusinessSavedCardTokenSerializer,
            ),
            400: openapi.Response(description="Bad request"),
            404: openapi.Response(description="Card not found"),
        },
    )
    @PermissionManager(BUSINESS_SAVED_CARDS_CHANGE_PERMISSION)
    def post(self, request, pk, *args, **kwargs):
        """Set a card as default using the card ID from URL path."""
        # Use serializer to set card as default (this will also verify and update Credimax agreements)
        # The serializer's validate method will get the card_id from view.kwargs
        # Pass pk in context as well to ensure it's available
        serializer = BusinessSavedCardSetDefaultSerializer(
            data={}, context={"request": request, "view": self, "pk": pk}
        )

        try:
            serializer.is_valid(raise_exception=True)
            card = serializer.save()
        except serializers.ValidationError as e:
            # Handle validation errors
            error_message = str(e.detail) if hasattr(e, "detail") else str(e)
            status_code = status.HTTP_400_BAD_REQUEST

            # Check if it's a 404 error (card not found)
            if "business_saved_card_not_found" in error_message.lower():
                status_code = status.HTTP_404_NOT_FOUND

            return generic_response(
                error_message=error_message,
                status_code=status_code,
            )

        response_data = BusinessSavedCardTokenSerializer(card).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["business_default_card_updated"],
            data=response_data,
        )


class BusinessSavedCardDeleteAPIView(generics.DestroyAPIView):
    """API view to soft delete a business saved card."""

    permission_classes = [IsAuthenticated]
    queryset = BusinessSavedCardToken.objects.all()
    http_method_names = ["delete"]

    def get_queryset(self):
        """Filter cards by business."""
        if self.request.user.is_anonymous:
            return self.queryset.none()

        # Check if auth exists (for Swagger documentation)
        if not hasattr(self.request, "auth") or not self.request.auth:
            return BusinessSavedCardToken.objects.none()

        current_business_id = self.request.auth.get("current_business")
        if not current_business_id:
            return BusinessSavedCardToken.objects.none()

        try:
            business = UserAssignedBusiness.objects.get(id=current_business_id).business
        except UserAssignedBusiness.DoesNotExist:
            raise Http404(MESSAGES["business_account_not_found"])

        return BusinessSavedCardToken.objects.filter(business=business).order_by(
            "-created_at"
        )

    @PermissionManager(BUSINESS_SAVED_CARDS_CHANGE_PERMISSION)
    def delete(self, request, *args, **kwargs):
        """Soft delete a business saved card."""
        try:
            card = self.get_object()
        except Http404:
            return generic_response(
                error_message=MESSAGES["business_saved_card_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Prevent deletion of the default card used for subscription
        if card.is_used_for_subscription:
            return generic_response(
                error_message=MESSAGES["business_saved_card_cannot_delete_default"],
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Soft delete the card
        card.delete()

        return generic_response(
            message=MESSAGES["business_saved_card_deleted"],
            status_code=status.HTTP_200_OK,
        )


class SubUserCreateAPIView(generics.CreateAPIView):
    serializer_class = SubUserSerializer
    permission_classes = [IsAuthenticated]
    queryset = User.objects.all()

    @PermissionManager(SUB_USER_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        """Handle POST request to create a sub user for ther business"""

        serializer = self.get_serializer(data=request.data)
        business = get_business_from_user_token(request, "business")
        organization_code = request.auth.get("organization_code")

        # business name or else if not business then user fullname
        name = get_user_or_business_name(request)

        if not business:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["business_account_not_found"],
            )

        if serializer.is_valid():
            sub_user = serializer.save()

            # Assigned business to sub user.
            UserAssignedBusiness.objects.create(
                user=sub_user,
                business=business,
            )

            context = {
                "name": sub_user.get_full_name(),
                "email": sub_user.email,
                "password": request.data.get("password"),
                "business_name": name,
            }
            send_mail.delay(
                "Your Sub-User Account Has Been Created",
                "templates/sub-user-create.html",
                context,
                [sub_user.email],
                organization_code=organization_code,
            )
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["sub_user_created"],
                data=self.serializer_class(sub_user).data,
            )

        return handle_serializer_errors(serializer)


class BusinessUserListAPIView(generics.ListAPIView):
    serializer_class = BusinessUserSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    queryset = User.objects.all()

    def get_queryset(self):
        """Retrieve an active user, ensuring they belong to an organization (if applicable)."""

        if self.request.user.is_anonymous:
            return self.queryset.none()

        user = self.request.user
        return self.queryset.filter(
            organization_id=user.organization_id,
            is_active=True,
            account_status__in=[UserStatus.PENDING, UserStatus.APPROVED],
        )

    @PermissionManager(SUB_USER_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Handle GET request to list of business users"""
        try:
            # Get users connected to the logged-in user's business.
            business = get_business_from_user_token(self.request, "business")
            if not business:
                return generic_response(
                    status_code=status.HTTP_404_NOT_FOUND,
                    error_message=MESSAGES["business_account_not_found"],
                )

            queryset = self.get_queryset().filter(
                user_assigned_businesses__business=business
            )
            page = self.paginate_queryset(queryset)
            serializer = self.get_serializer(
                page, many=True, context={"business": business}
            )
            response_data = self.get_paginated_response(serializer.data).data
            return generic_response(
                status_code=status.HTTP_200_OK,
                data=response_data,
                message=MESSAGES["business_user_fetched"],
            )
        except:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["business_account_not_found"],
            )


class BusinessAccountDocumentCreateAPIView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    queryset = BusinessAccountDocument.objects.all()
    serializer_class = BusinessAccountDocumentCreateSerializer
    response_serializer_class = BusinessAccountDocumentSerializer

    def post(self, request, *args, **kwargs):
        """Handle POST request to create of business document"""

        business_document_serializer = self.get_serializer(data=request.data)
        if business_document_serializer.is_valid():
            business_documents = business_document_serializer.save()

            return generic_response(
                data=self.response_serializer_class(business_documents, many=True).data,
                status_code=status.HTTP_201_CREATED,
            )
        return handle_serializer_errors(business_document_serializer)


class OrganizationFeesTaxesAPIView(generics.RetrieveAPIView):
    """API endpoint to retrieve VAT, taxes, and platform fee of an organization."""

    serializer_class = OrganizationFeesTaxesSerializer
    permission_classes = [IsAuthenticated]
    queryset = Organization.objects.all()

    def get_object(self):
        """Retrieve the organization instance. Modify logic as needed."""

        organization_code = self.request.auth.get("organization_code")
        return self.queryset.get(code=organization_code)


class ContactSupportRequestCreateAPIView(generics.CreateAPIView):
    queryset = ContactSupportRequest.objects.select_related("user").prefetch_related(
        "contact_support_attachments"
    )
    serializer_class = ContactSupportRequestSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        """Handle POST request to create of business document"""

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            contact_support_request = serializer.save()

            user = contact_support_request.user
            organization_code = request.auth.get("organization_code")

            full_name = user.get_full_name()
            user_email = user.email

            # Email to support team
            support_subject = f"New Contact Support Request from {user_email}"
            support_context = {
                "full_name": full_name,
                "email": user_email,
                "title": contact_support_request.title,
                "query": contact_support_request.query,
            }
            send_mail.delay(
                support_subject,
                "templates/contact-support.html",
                support_context,
                [settings.CONTACT_SUPPORT_EMAIL],
                organization_code=organization_code,
            )

            # Confirmation email to user
            user_subject = f"Your Support Request has been successfully sent to {settings.CONTACT_SUPPORT_EMAIL}"
            user_context = {
                "full_name": full_name,
                "support_contact_number": settings.SUPPORT_CONTACT_NUMBER,
            }
            send_mail.delay(
                user_subject,
                "templates/support-request-confirmation.html",
                user_context,
                [user_email],
                organization_code=organization_code,
            )

            # Refresh the instance to get the related attachments
            contact_support_request.refresh_from_db()

            # Use response serializer to include attachments
            response_serializer = ContactSupportRequestResponseSerializer(
                contact_support_request
            )

            return generic_response(
                data=response_serializer.data,
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["contact_support_request_created"],
            )

        return handle_serializer_errors(serializer)


class FCMTokenUpdateAPIView(generics.UpdateAPIView):
    serializer_class = FCMDetailsSerializer
    permission_classes = [IsAuthenticated]
    queryset = FCMToken.objects.all()

    def update(self, request, *args, **kwargs):
        user = request.user
        device_id = request.data.get("device_id")

        try:
            instance = self.queryset.get(user=user, device_id=device_id)
            serializer = self.get_serializer(instance, data=request.data, partial=True)
        except FCMToken.DoesNotExist:
            serializer = self.get_serializer(
                data=request.data, context={"user": request.user}
            )

        if serializer.is_valid():
            serializer.save()
            return generic_response(
                data=serializer.data,
                status_code=status.HTTP_200_OK,
                message=MESSAGES["fcm_token_updated"],
            )

        return handle_serializer_errors(serializer)


class NotificationReadUnreadStatusUpdateAPIView(APIView):
    permission_classes = [IsAuthenticated]
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer

    def get_queryset(self):
        """Handle queryset by user."""
        if self.request.user.is_anonymous:
            return self.queryset.none()

        user = self.request.user
        return self.queryset.filter(user=user)

    def get_object(self):
        """Retrieve the notification instance."""

        try:
            return self.get_queryset().get(pk=self.kwargs.get("pk"))
        except:
            raise Http404

    @PermissionManager(NOTIFICATION_VIEW_PERMISSION)
    def patch(self, request, *arg, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                error_message=MESSAGES["notification_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

        instance.is_read = True
        instance.save()

        serializer = self.serializer_class(instance)
        send_notification_count_to_users([request.user])
        return generic_response(
            message=MESSAGES["notification_read_unread_status_updated"],
            status_code=status.HTTP_200_OK,
            data=serializer.data,
        )


class UserProfileDeleteView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserDeleteSerializer
    http_method_names = ["delete"]
    queryset = User.objects.all()

    def delete(self, request, pk=None):
        user_profile = self.get_object()
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        delete_reason = serializer.validated_data["delete_reason"]
        user_profile.delete_reason = delete_reason
        # Mark user as deleted
        user_profile.account_status = UserStatus.DELETED
        user_profile.save()

        # Fetch all businesses where this user is an owner
        user_owned_businesses = UserAssignedBusiness.objects.filter(
            user=user_profile, is_owner=True
        )

        for assigned in user_owned_businesses:
            business = assigned.business

            # Count how many owners this business has (excluding the current user)
            other_owners_count = (
                UserAssignedBusiness.objects.filter(business=business, is_owner=True)
                .exclude(user=user_profile)
                .count()
            )

            if other_owners_count == 0:
                # Delete all users assigned to this business, as the owner and it's business is being removed
                assigned_users = UserAssignedBusiness.objects.filter(
                    business=business, is_owner=False
                )

                for assigned_user in assigned_users:
                    assigned_user = assigned_user.user
                    # Mark user as deleted
                    assigned_user.account_status = UserStatus.DELETED
                    assigned_user.save()
                    assigned_user.delete()

                # Delete all pending purchase requests related to this business
                PurchaseRequest.objects.filter(
                    business=business, status=PurchaseRequestStatus.PENDING
                ).hard_delete()

                # This user is the sole owner, delete the business
                business.delete()

        # Finally delete the user
        user_profile.delete()

        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["user_deleted"],
        )

    def get_object(self):
        """Ensure the user can only update their own profile."""
        user = self.request.user
        try:
            return User.objects.get(id=user.id)
        except User.DoesNotExist:
            raise generic_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_message=MESSAGES["user_profile_not_exists"],
            )


class BusinessAccountUpdateView(generics.UpdateAPIView):
    """Update business name and logo for the authenticated user's business."""

    permission_classes = [IsAuthenticated]
    serializer_class = BusinessAccountUpdateSerializer
    http_method_names = ["patch"]

    def get_object(self):
        assigned_business = self.request.user.user_assigned_businesses.filter(
            is_owner=True
        ).first()

        if not assigned_business or not assigned_business.business:
            raise Http404(MESSAGES["business_account_not_found"])

        return assigned_business.business

    def patch(self, request, *args, **kwargs):
        try:
            business = self.get_object()
            serializer = self.serializer_class(
                business, data=request.data, partial=True
            )

            if serializer.is_valid():
                serializer.save()
                return generic_response(
                    status_code=status.HTTP_200_OK,
                    message=MESSAGES["business_account_updated"],
                    data=serializer.data,
                )
            return handle_serializer_errors(serializer)
        except Http404:
            return generic_response(
                status_code=status.HTTP_404_NOT_FOUND,
                error_message=MESSAGES["business_account_not_found"],
            )


class SubscriptionUsageAPIView(APIView):
    """API endpoint to get subscription usage information including free trial limitations."""

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        """Get subscription usage information."""
        business = get_business_from_user_token(request, "business")
        if not business:
            return generic_response(
                message=MESSAGES["business_account_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

        usage_info = get_subscription_usage_info(business)

        return generic_response(
            data=usage_info,
            message=MESSAGES["subscription_usage_information_retrieved"],
            status_code=status.HTTP_200_OK,
        )


class AllNotificationRead(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        Notification.objects.filter(user=self.request.user).update(is_read=True)
        send_notification_count_to_users([request.user])
        return generic_response(status_code=status.HTTP_200_OK)


class UserRolesAPIView(generics.CreateAPIView):
    serializer_class = UserRolesSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            validated_data = serializer.validated_data
            email = validated_data["email"].strip().lower()
            organization_code = validated_data["organization_code"]

            try:
                organization = Organization.objects.get(code=organization_code)
            except Organization.DoesNotExist:
                return generic_response(
                    status_code=status.HTTP_404_NOT_FOUND,
                    error_message=MESSAGES["organization_not_found"],
                )

            users = User.objects.filter(
                email__icontains=email,
                organization_id=organization,
                phone_verified=True,
                email_verified=True,
            )

            if not users:
                return generic_response(
                    status_code=status.HTTP_404_NOT_FOUND,
                    error_message=MESSAGES["user_not_found"],
                )

            roles = []
            for user in users:
                business_roles = list(
                    UserAssignedBusiness.objects.filter(user=user)
                    .select_related("business")
                    .values_list("business__business_account_type", flat=True)
                    .distinct()
                )
                roles.extend(business_roles)  # extend instead of append

            # remove duplicates while keeping order
            roles = list(dict.fromkeys(roles))

            response_data = {
                "roles": roles,
                "email": email,
                "organization_code": organization_code,
            }

            return generic_response(
                data=self.serializer_class(response_data).data,
                message=MESSAGES["user_role_fetched"],
                status_code=status.HTTP_200_OK,
            )

        return handle_serializer_errors(serializer)


class CheckVersionView(APIView):
    @swagger_auto_schema(
        operation_description="Retrieve a list of Precious Metals with applied filters.",
        manual_parameters=[
            openapi.Parameter(
                "platform",
                openapi.IN_QUERY,
                description="Platform name.\n\n**Example**: `IOS`, `ANDROID`",
                type=openapi.TYPE_STRING,
            ),
        ],
        responses={200: AppVersionSerializer},
    )
    def post(self, request, *args, **kwargs):
        platform = request.data.get("platform")

        app_version = (
            AppVersion.objects.filter(platform=platform).order_by("-created_at").first()
        )

        serializer = AppVersionSerializer(app_version)

        return generic_response(
            data=serializer.data,
            message=MESSAGES["app_version_fetched"],
            status_code=status.HTTP_200_OK,
        )
