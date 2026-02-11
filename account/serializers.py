import logging

from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.db.models import Case
from django.db.models import DecimalField
from django.db.models import F
from django.db.models import Sum
from django.db.models import Value
from django.db.models import When
from django.db.models.functions import Coalesce
from django.utils import timezone
from phonenumber_field.phonenumber import to_python
from rest_framework import serializers

logger = logging.getLogger(__name__)

from account.message import MESSAGES
from account.models import Address
from account.models import AdminUserRole
from account.models import BankAccount
from account.models import BusinessAccount
from account.models import BusinessAccountDocument
from account.models import ContactSupportRequest
from account.models import ContactSupportRequestAttachments
from account.models import FCMToken
from account.models import Organization
from account.models import OrganizationCurrency
from account.models import RoleHistory
from account.models import Shareholder
from account.models import Transaction
from account.models import User
from account.models import UserAssignedBusiness
from account.models import UserPreference
from account.models import Wallet
from investor.utils import get_total_hold_amount_for_investor
from investor.utils import get_total_withdrawal_pending_amount
from sooq_althahab.constants import ROLE_AND_PERMISSIONS
from sooq_althahab.enums.account import BusinessType
from sooq_althahab.enums.account import SubscriptionStatusChoices
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.account import UserType
from sooq_althahab.payment_gateway_services.credimax.subscription.credimax_client import (
    CredimaxClient,
)
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.utils import get_presigned_url_from_s3
from sooq_althahab.utils import validate_card_expiry_date
from sooq_althahab_admin.models import AppVersion
from sooq_althahab_admin.models import BusinessSavedCardToken
from sooq_althahab_admin.models import BusinessSubscriptionPlan
from sooq_althahab_admin.models import MetalPriceHistory
from sooq_althahab_admin.serializers import BusinessSubscriptionPlanSerializer
from sooq_althahab_admin.serializers import MetalPriceHistorySerializer
from sooq_althahab_admin.serializers import OrganizationResponseSerializer
from sooq_althahab_admin.serializers import OrganizationRiskLevelSerializer


class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = ["bank_name", "account_number", "account_name", "iban_code"]


class FCMDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = FCMToken
        fields = ["fcm_token", "device_id", "device_type"]

    def create(self, validated_data):
        """
        Create and return the FCM token associated with the user.
        """
        validated_data["user"] = self.context["user"]
        return FCMToken.objects.create(**validated_data)


class BaseUserSerializer(serializers.ModelSerializer):
    """
    Base serializer for user common details.
    This serializer can be extended for specific use cases.
    """

    bank_details = serializers.SerializerMethodField()
    role = serializers.ChoiceField(
        choices=UserRoleBusinessChoices.choices, required=True
    )
    full_name = serializers.CharField(source="fullname", read_only=True)
    language_code = serializers.CharField(
        required=False,
        help_text="Language code for the user's preferences",
    )

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "first_name",
            "middle_name",
            "last_name",
            "language_code",
            "phone_number",
            "phone_country_code",
            "role",
            "user_type",
            "bank_details",
            "date_of_birth",
            "gender",
            "personal_number",
        ]

    def get_bank_details(self, obj):
        try:
            if not obj:
                return None

            assigned_business = obj.user_assigned_businesses.first()
            if not assigned_business:
                return None

            business_owner = UserAssignedBusiness.global_objects.filter(
                business=assigned_business.business, is_owner=True
            ).first()

            if not business_owner or not business_owner.user:
                return None

            owner_details = business_owner.user

            if not hasattr(owner_details, "bank_account"):
                return None
            bank_account = owner_details.bank_account

        except:
            if obj and hasattr(obj, "bank_account"):
                bank_account = obj.bank_account
            return None

        serializer = BankAccountSerializer(bank_account)
        return serializer.data


class UserRegistrationSerializer(BaseUserSerializer):
    """
    Serializer for user registration, extending BaseUserSerializer
    to include password and FCM details.
    """

    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )
    organization_code = serializers.CharField(write_only=True, required=True)
    business_name = serializers.CharField(
        write_only=True, required=False, allow_blank=True, allow_null=True
    )

    class Meta(BaseUserSerializer.Meta):
        fields = BaseUserSerializer.Meta.fields + [
            "password",
            "organization_code",
            "business_name",
        ]

    def validate(self, data):
        user_type = data.get("user_type")
        business_name = data.get("business_name")
        phone_number = data.get("phone_number")
        organization_code = data.get("organization_code")
        email = data.get("email")

        if user_type == UserType.BUSINESS and not business_name:
            raise serializers.ValidationError(MESSAGES["business_name_required"])

        # Fetch the organization based on the organization code
        try:
            organization = Organization.objects.get(code=organization_code)
        except Organization.DoesNotExist:
            raise serializers.ValidationError(MESSAGES["organization_not_found"])

        if phone_number:
            parsed_phone_number = to_python(phone_number)
            if not parsed_phone_number or not parsed_phone_number.is_valid():
                raise serializers.ValidationError(
                    {"phone_number": MESSAGES["invalid_phone_number"]()}
                )

        return data


class OrganizationCurrenciesSerializer(serializers.ModelSerializer):
    """Serializer for the organization currencies."""

    class Meta:
        model = OrganizationCurrency
        fields = ["id", "currency_code", "rate", "is_default"]


class UserSessionSerializer(BaseUserSerializer):
    # Business Subscription plan details
    business_subscription = serializers.SerializerMethodField()
    # All the user roles.
    user_roles = serializers.SerializerMethodField()
    # All the permissions of the user based on user's role.
    user_permissions = serializers.SerializerMethodField()
    # All the user preferences.
    user_preferences = serializers.SerializerMethodField()
    # Get business of the user.
    business = serializers.SerializerMethodField()
    # Get image url of the user.
    profile_image = serializers.SerializerMethodField()
    wallet = serializers.SerializerMethodField()
    # Latest metal prices
    metal_prices = serializers.SerializerMethodField()
    # Organization currency
    organization_currency = OrganizationCurrenciesSerializer(
        source="organization_id.currencies", many=True, read_only=True
    )
    # Check if the login user is a business owner
    is_business_owner = serializers.SerializerMethodField()
    # Previous days live metal prices
    previous_day_live_metal_prices = serializers.SerializerMethodField()
    organization = serializers.SerializerMethodField()
    # Check if user has previously used free trial subscription
    has_used_free_trial = serializers.SerializerMethodField()

    class Meta(BaseUserSerializer.Meta):
        fields = BaseUserSerializer.Meta.fields + [
            "business_subscription",
            "user_roles",
            "user_permissions",
            "business",
            "user_preferences",
            "face_verified",
            "document_verified",
            "phone_verified",
            "email_verified",
            "business_aml_verified",
            "due_diligence_verified",
            "profile_image",
            "wallet",
            "metal_prices",
            "organization_currency",
            "is_business_owner",
            "previous_day_live_metal_prices",
            "organization",
            "has_used_free_trial",
            "declined_reason",
            "reference_id",
            "verification_url",
            "event",
            "password_reset",
        ]

    def get_organization(self, obj):
        return OrganizationResponseSerializer(obj.organization_id).data

    def get_business_subscription(self, obj):
        try:
            user_assigned_business = obj.user_assigned_businesses.select_related(
                "business"
            ).first()
            if not user_assigned_business:
                return None

            business = user_assigned_business.business

            business_subscription = (
                BusinessSubscriptionPlan.objects.select_related("subscription_plan")
                .filter(business=business)
                .order_by("-created_at")
                .first()
            )

            if business_subscription:
                return BusinessSubscriptionPlanSerializer(business_subscription).data

        except Exception:
            return None

    def get_metal_prices(self, obj):
        """Fetches the latest price for each metal from MetalPriceHistory."""
        latest_prices = MetalPriceHistory.objects.order_by(
            "global_metal_id", "-created_at"
        ).distinct("global_metal_id")

        return [
            {
                "metal": price.global_metal.name,
                "symbol": price.global_metal.symbol,
                "latest_price": price.price,
            }
            for price in latest_prices
        ]

    def get_user_roles(self, obj):
        # Fetch roles from assigned businesses
        business_roles = [
            business_role.business.business_account_type
            for business_role in UserAssignedBusiness.objects.filter(user=obj.id)
        ]

        # Fetch admin roles directly as a list
        admin_roles = list(
            AdminUserRole.objects.filter(user=obj.id).values_list("role", flat=True)
        )

        combined_roles = set(business_roles + admin_roles)

        return list(combined_roles)

    def get_user_permissions(self, obj):
        user_role = getattr(UserRoleChoices, obj.role, None) or getattr(
            UserRoleBusinessChoices, obj.role, None
        )
        user_permissions = None
        if user_role:
            user_permissions = ROLE_AND_PERMISSIONS.get(user_role.label, None)
        return user_permissions

    def get_user_preferences(self, obj):
        user_preference = getattr(obj, "user_preference", None)
        if user_preference:
            return UserPreferenceSerializer(user_preference).data
        return None

    def get_business(self, obj):
        current_business_id = self.context.get("business")
        if not current_business_id:
            return None

        try:
            business = UserAssignedBusiness.objects.get(id=current_business_id).business
            return BusinessAccountResponseSerializer(business).data
        except BusinessAccount.DoesNotExist:
            return None

    def get_profile_image(self, obj):
        """Generate a presigned URL for the image field in the model using the PresignedUrlSerializer."""
        profile_image = obj.profile_image
        return get_presigned_url_from_s3(profile_image)

    def get_wallet(self, obj):
        current_business_id = self.context.get("business")
        if not current_business_id:
            return None

        try:
            business = UserAssignedBusiness.objects.get(id=current_business_id).business
            wallet = Wallet.objects.get(business=business)
            return WalletSerializer(wallet).data
        except:
            return None

    def get_is_business_owner(self, obj):
        """Check if the user is an owner in the current business."""

        current_business_id = self.context.get("business")
        # Get users in those businesses, excluding the owner
        try:
            return UserAssignedBusiness.objects.get(id=current_business_id).is_owner
        except:
            return None

    def get_previous_day_live_metal_prices(self, obj):
        """Get the previous day's latest metal price per metal using serializer (simplified)."""
        yesterday = timezone.now().date() - timezone.timedelta(days=1)

        previous_day_prices = (
            MetalPriceHistory.objects.filter(created_at__date=yesterday)
            .order_by("global_metal_id", "-created_at")
            .distinct("global_metal_id")
            .select_related("global_metal")
        )

        serializer = MetalPriceHistorySerializer(previous_day_prices, many=True)
        return serializer.data

    def get_has_used_free_trial(self, obj):
        """
        Check if the business has ever used a free trial subscription.
        This helps prevent users from purchasing free trial subscriptions multiple times.

        Returns:
            bool: True if the business has ever had a free trial subscription, False otherwise
        """
        from sooq_althahab.enums.sooq_althahab_admin import (
            SubscriptionPaymentTypeChoices,
        )

        try:
            user_assigned_business = obj.user_assigned_businesses.select_related(
                "business"
            ).first()
            if not user_assigned_business:
                return False

            business = user_assigned_business.business

            # Check if business has ever had a free trial subscription (any status)
            has_free_trial = BusinessSubscriptionPlan.objects.filter(
                business=business,
                subscription_plan__payment_type=SubscriptionPaymentTypeChoices.FREE_TRIAL,
            ).exists()

            return has_free_trial

        except Exception:
            return False


class UserBasicSerializer(serializers.ModelSerializer):
    """Basic user details serializer for listing users in the same business"""

    is_owner = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()

    class Meta:
        model = User
        exclude = ["password"]

    def get_profile_image(self, obj):
        """Generate a presigned URL for the image field in the model using the PresignedUrlSerializer."""
        profile_image = obj.profile_image
        return get_presigned_url_from_s3(profile_image)

    def get_is_owner(self, obj):
        """Check if the user is an owner in business"""

        return obj.user_assigned_businesses.filter(is_owner=True).exists()


class AdminLoginSerializer(serializers.Serializer):
    email = serializers.EmailField(
        max_length=255,
        error_messages={"required": MESSAGES["field_required"]},
    )
    password = serializers.CharField(
        write_only=True,
        error_messages={"required": MESSAGES["field_required"]},
    )
    organization_code = serializers.CharField(write_only=True, required=True)


class UserLoginSerializer(AdminLoginSerializer):
    role = serializers.ChoiceField(
        choices=UserRoleBusinessChoices.choices, required=True
    )
    fcm_details = FCMDetailsSerializer(write_only=True, required=True)


class SwitchRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoleHistory
        fields = ["role", "device_id"]


class ChangePasswordSerializer(serializers.Serializer):
    """
    Serializer for changing the user password.
    """

    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )

    def validate(self, data):
        user = self.context["user"]
        old_password = data.get("old_password")

        # Check if the old password is correct
        if not user.check_password(old_password):
            raise serializers.ValidationError(MESSAGES["incorrect_password"])

        return data

    def save(self):
        user = self.context["user"]
        new_password = self.validated_data["new_password"]
        user.set_password(new_password)
        user.access_token_expiration = timezone.now()
        user.password_reset = True
        user.save()


class ForgetPasswordSendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True, write_only=True)
    role = serializers.ChoiceField(
        choices=UserRoleBusinessChoices.choices, required=False
    )


class ForgetPasswordVerifyOTPSerializer(serializers.Serializer):
    otp = serializers.CharField(required=True)


class ResetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )


class UserPartialUpdateSerializer(serializers.ModelSerializer):
    profile_image = serializers.CharField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "middle_name",
            "last_name",
            "phone_number",
            "phone_country_code",
            "profile_image",
            "gender",
            "date_of_birth",
            "personal_number",
        ]

    def validate(self, attrs):
        """Ensure phone number is unique within the organization."""
        instance = self.instance
        request = self.context.get("request")
        email = attrs.get("email")
        phone_number = attrs.get("phone_number")
        role = request.auth.get("role")

        if email and instance.email_verified:
            raise serializers.ValidationError(MESSAGES["email_already_verified"])

        if phone_number and instance.phone_verified:
            raise serializers.ValidationError(MESSAGES["phone_number_already_verified"])

        filters = {"email": email}
        if role in UserRoleBusinessChoices.values:
            filters.update(
                {
                    "phone_verified": True,
                    "email_verified": True,
                    "user_assigned_businesses__business__business_account_type": role,
                }
            )
        else:
            filters.update({"user_roles__role": role})

        if User.objects.filter(**filters).exists():
            raise serializers.ValidationError(MESSAGES["user_already_exists"])

        return attrs

    def to_representation(self, instance):
        """Modify representation to return a presigned URL instead of the actual image field."""
        representation = super().to_representation(instance)

        if instance.profile_image:
            representation["profile_image"] = get_presigned_url_from_s3(
                instance.profile_image
            )

        return representation


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        exclude = [
            "created_at",
            "updated_at",
            "deleted_at",
            "restored_at",
            "transaction_id",
        ]
        read_only_fields = ["user"]


class BusinessAccountDetailsSerializer(serializers.ModelSerializer):
    owner = serializers.SerializerMethodField()
    logo = serializers.SerializerMethodField()

    class Meta:
        model = BusinessAccount
        fields = [
            "id",
            "name",
            "business_account_type",
            "business_original_id",
            "vat_account_number",
            "commercial_registration_number",
            "business_type",
            "is_existing_business",
            "owner",
            "logo",
        ]

    def get_owner(self, obj):
        """Fetches the main owner of the business."""
        owner = UserAssignedBusiness.global_objects.filter(
            business=obj, is_owner=True
        ).first()
        if owner:
            return {
                "id": owner.user.id,
                "name": owner.user.get_full_name(),
                "email": owner.user.email,
                "phone_number": (
                    str(owner.user.phone_number) if owner.user.phone_number else None
                ),
                "user_type": owner.user.user_type,
                "personal_number": owner.user.personal_number,
                "is_deleted": owner.user.is_deleted,
                "account_status": owner.user.account_status,
            }
        return None

    def get_logo(self, obj):
        """
        Generate a presigned URL for the logo.
        - If jeweler is BUSINESS: return business logo
        - If jeweler is INDIVIDUAL: return owner's profile_image
        """
        from sooq_althahab.enums.account import UserType

        # Get the owner to check user_type
        owner = (
            UserAssignedBusiness.global_objects.filter(business=obj, is_owner=True)
            .select_related("user")
            .first()
        )

        # If owner exists and is INDIVIDUAL, return profile_image
        if owner and owner.user and owner.user.user_type == UserType.INDIVIDUAL:
            profile_image = owner.user.profile_image
            return get_presigned_url_from_s3(profile_image) if profile_image else None

        # Otherwise, return business logo
        logo = obj.logo
        return get_presigned_url_from_s3(logo) if logo else None


class BusinessAccountUpdateSerializer(serializers.ModelSerializer):
    logo = serializers.CharField(required=False, allow_null=True)

    class Meta:
        model = BusinessAccount
        fields = ["name", "logo"]

    def to_representation(self, instance):
        """Return presigned URL instead of raw logo path."""
        representation = super().to_representation(instance)
        if instance.logo:
            representation["logo"] = get_presigned_url_from_s3(instance.logo)
        return representation


class BusinessAccountDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessAccountDocument
        fields = ["id", "doc_type", "image"]


class BusinessAccountDocumentCreateSerializer(serializers.Serializer):
    business_documents = BusinessAccountDocumentSerializer(many=True)
    vat_account_number = serializers.CharField(required=False)
    commercial_registration_number = serializers.CharField(required=False)

    def create(self, validated_data):
        request = self.context.get("request")

        # Fetch the business instance linked to the user
        business = get_business_from_user_token(request, "business")
        if not business:
            raise serializers.ValidationError(MESSAGES["business_account_not_found"])

        commercial_registration_number = request.data.pop(
            "commercial_registration_number", None
        )
        vat_account_number = request.data.pop("vat_account_number", None)

        if commercial_registration_number:
            business.commercial_registration_number = commercial_registration_number
        if vat_account_number:
            business.vat_account_number = vat_account_number
        business.save()

        # Handle business documents
        business_documents = validated_data.get("business_documents", [])

        # Delete old documents of same doc_type before inserting new document
        delete_doc = [doc["doc_type"] for doc in business_documents]
        BusinessAccountDocument.objects.filter(
            doc_type__in=delete_doc, business=business
        ).hard_delete()

        documents = [
            BusinessAccountDocument(
                business=business,
                doc_type=doc["doc_type"],
                image=doc.get("image"),
            )
            for doc in business_documents
        ]

        return BusinessAccountDocument.objects.bulk_create(documents)


class BusinessAccountDocumentResponseSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = BusinessAccountDocument
        fields = ["id", "doc_type", "image"]

    def get_image(self, obj):
        """Generate a presigned URL for the image field in the model using the PresignedUrlSerializer."""
        object_name = obj.image
        return get_presigned_url_from_s3(object_name)


class BusinessAccountResponseSerializer(serializers.ModelSerializer):
    business_documents = BusinessAccountDocumentResponseSerializer(
        many=True, required=False
    )
    risk_level = OrganizationRiskLevelSerializer(required=False)
    logo = serializers.SerializerMethodField()

    class Meta:
        model = BusinessAccount
        fields = [
            "id",
            "name",
            "business_original_id",
            "business_type",
            "vat_account_number",
            "commercial_registration_number",
            "musharakah_client_type",
            "is_existing_business",
            "business_documents",
            "business_account_type",
            "logo",
            "is_suspended",
            "risk_level",
            "has_received_intro_grace",
            "intro_grace_consumed_on",
        ]

    def get_logo(self, obj):
        """Generate a presigned URL for accessing the image associated with the business account."""
        return get_presigned_url_from_s3(obj.logo)


class ShareholderCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating and validating Shareholder instances.
    """

    class Meta:
        model = Shareholder
        fields = [
            "id",
            "business",
            "name",
            "role",
            "position",
            "id_document",
        ]
        read_only_fields = ["id"]

    def validate(self, data):
        business = data.get("business")
        user = self.context["request"].user

        if not UserAssignedBusiness.objects.filter(
            user=user, business=business
        ).exists():
            raise serializers.ValidationError(MESSAGES["business_error"])

        if business.business_type != BusinessType.WLL:
            raise serializers.ValidationError(MESSAGES["invalid_business_type"])
        return data

    def create(self, validated_data):
        shareholder = Shareholder.objects.create(**validated_data)
        return shareholder


class ShareholderResponseSerializer(serializers.ModelSerializer):
    """
    Serializer for creating and validating Shareholder instances.
    """

    id_document = serializers.SerializerMethodField()

    class Meta:
        model = Shareholder
        fields = [
            "id",
            "business",
            "name",
            "role",
            "position",
            "id_document",
        ]

    def get_id_document(self, obj):
        """Generate a presigned URL for the id document field in the model using the PresignedUrlSerializer."""
        # Pass the image field to the PresignedUrlSerializer
        object_name = obj.id_document
        return get_presigned_url_from_s3(object_name)


class OrganizationCurrencySerializer(serializers.ModelSerializer):
    """
    Serializer for the organization currencies.
    """

    class Meta:
        model = OrganizationCurrency
        fields = ["organization", "id", "currency_code", "rate", "is_default"]
        read_only_fields = ["organization", "id"]


class UserPreferenceSerializer(serializers.ModelSerializer):
    organization_currency = serializers.PrimaryKeyRelatedField(
        queryset=OrganizationCurrency.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )
    current_currency = serializers.CharField(
        source="organization_currency.currency_code", read_only=True
    )

    class Meta:
        model = UserPreference
        fields = [
            "id",
            "user",
            "organization_currency",
            "current_currency",
            "language_code",
            "timezone",
            "notifications_enabled",
            "emails_enabled",
        ]
        read_only_fields = ["id", "user"]


class SubUserSerializer(serializers.ModelSerializer):
    """
    Serializer for creating sub-user.
    Ensures password validation returns a single error message as a string instead of a list.
    """

    password = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ["first_name", "middle_name", "last_name", "email", "password"]

    def validate(self, data):
        password = data.get("password")
        email = data.get("email")
        user = user = self.context["request"].user

        # Check if the email already exists within the organization
        if User.global_objects.filter(
            email=email, organization_id=user.organization_id
        ).exists():
            raise serializers.ValidationError(MESSAGES["email_exists"])

        try:
            validate_password(password)
        except:
            raise serializers.ValidationError(MESSAGES["password_too_short"])

        return data

    def create(self, validated_data):
        """Create a sub-user."""

        user = self.context["request"].user
        email = validated_data.pop("email")
        password = validated_data.pop("password")
        return User.objects.create_user(
            email=email,
            password=password,
            organization_id=user.organization_id,
            user_type=user.user_type,
            face_verified=True,
            document_verified=True,
            phone_verified=True,
            email_verified=True,
            business_aml_verified=True,
            due_diligence_verified=True,
            **validated_data,
        )


class BusinessUserSerializer(serializers.ModelSerializer):
    is_owner = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()

    class Meta:
        model = User
        exclude = ["password"]

    def get_is_owner(self, obj):
        # Fetch the related UserAssignedBusiness record to check if the user is an owner
        business = self.context.get("business")
        try:
            user_assigned_business = UserAssignedBusiness.objects.get(
                user=obj, business=business
            )
            return user_assigned_business.is_owner
        except UserAssignedBusiness.DoesNotExist:
            return False

    def get_profile_image(self, obj):
        """Generate a pre-signed URL for the given image"""
        return get_presigned_url_from_s3(obj.profile_image)


class OrganizationFeesTaxesSerializer(serializers.ModelSerializer):
    """Serializer to return only VAT, taxes, and platform fee of an organization."""

    class Meta:
        model = Organization
        fields = [
            "vat_rate",
            "tax_rate",
            "platform_fee_type",
            "platform_fee_rate",
            "platform_fee_amount",
        ]


class ContactSupportRequestAttachmentsSerializer(serializers.ModelSerializer):
    """Serializer for ContactSupportRequestAttachments model."""

    class Meta:
        model = ContactSupportRequestAttachments
        fields = ["attachment"]


class ContactSupportRequestAttachmentsResponseSerializer(serializers.ModelSerializer):
    """Serializer for ContactSupportRequestAttachments model."""

    url = serializers.SerializerMethodField()

    class Meta:
        model = ContactSupportRequestAttachments
        fields = ["url"]

    def get_url(self, obj):
        """Generate a presigned URL for the attachment field in the model using the PresignedUrlSerializer."""
        object_name = obj.attachment
        return get_presigned_url_from_s3(object_name)


class ContactSupportRequestResponseSerializer(serializers.ModelSerializer):
    """Serializer for ContactSupportRequest responses including attachments."""

    attachments = ContactSupportRequestAttachmentsResponseSerializer(
        many=True, read_only=True, source="contact_support_attachments"
    )

    class Meta:
        model = ContactSupportRequest
        fields = ["id", "title", "query", "attachments", "created_at"]


class ContactSupportRequestSerializer(serializers.ModelSerializer):
    attachments = ContactSupportRequestAttachmentsSerializer(many=True, required=False)

    class Meta:
        model = ContactSupportRequest
        fields = ["title", "query", "attachments"]

    def create(self, validated_data):
        request = self.context.get("request")
        user = request.user
        organization = request.auth.get("organization_code")

        try:
            organization = Organization.objects.get(code=organization)
        except Organization.DoesNotExist:
            raise serializers.ValidationError(MESSAGES["organization_not_found"])

        # Extract attachments data
        attachments_data = validated_data.pop("attachments", [])

        validated_data["user"] = user
        validated_data["organization_id"] = organization
        contact_support_request = ContactSupportRequest.objects.create(**validated_data)

        # Create attachments if provided
        if attachments_data:
            for attachment_data in attachments_data:
                ContactSupportRequestAttachments.objects.create(
                    contact_support=contact_support_request, **attachment_data
                )

        return contact_support_request


class UserDeleteSerializer(serializers.Serializer):
    delete_reason = serializers.CharField(required=True)


class WalletSerializer(serializers.ModelSerializer):
    available_balance = serializers.SerializerMethodField()
    monthly_spending = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = ["id", "business", "balance", "available_balance", "monthly_spending"]

    def get_available_balance(self, obj):
        """Calculate the available balance for the investor business."""

        # Total pending withdrawals for business
        total_withdrawal_pending_amount = get_total_withdrawal_pending_amount(
            obj.business
        )

        # If the business account type is not an investor, return the wallet balance
        if obj.business.business_account_type not in [
            UserRoleBusinessChoices.INVESTOR,
            UserRoleBusinessChoices.JEWELER,
        ]:
            return obj.balance - total_withdrawal_pending_amount

        # Calculate the total hold amount for pending purchase requests for the logged-in user's business
        total_hold_amount_for_investor = get_total_hold_amount_for_investor(
            obj.business
        )
        return (
            obj.balance
            - total_hold_amount_for_investor
            - total_withdrawal_pending_amount
        )

    def get_monthly_spending(self, obj):
        """
        Calculate the total spending for the current month for a business wallet.

        This method currently handles monthly spending for INVESTOR and SELLER roles only:
        - For INVESTOR: sums the 'amount' from outgoing PAYMENT transactions.
        - For SELLER: sums the 'order_cost' associated with PAYMENT transactions.

        TODO:
        If new business account types (e.g., JEWELER, MANUFACTURER) are added in the future,
        update this logic accordingly to include their relevant transaction calculations.
        Ensure each role has a clearly defined spending behavior, and extend this method
        to support those distinctions.
        """

        business = obj.business
        now = timezone.now()
        current_year, current_month = now.year, now.month

        filters = {
            "from_business": business,
            "transaction_type": TransactionType.PAYMENT,
            "status__in": [TransactionStatus.APPROVED, TransactionStatus.SUCCESS],
            "created_at__year": current_year,
            "created_at__month": current_month,
        }

        if business.business_account_type in [
            UserRoleBusinessChoices.INVESTOR,
            UserRoleBusinessChoices.JEWELER,
            UserRoleBusinessChoices.MANUFACTURER,
        ]:
            total = Transaction.objects.filter(**filters).aggregate(
                total=Sum("amount")
            )["total"]
        else:
            # For SELLER: Calculate spending based on transaction type
            # If purchase_request exists: use order_cost only
            # If purchase_request is null (e.g., subscription payments): use amount only
            total = Transaction.objects.filter(**filters).aggregate(
                total=Sum(
                    Case(
                        When(purchase_request__isnull=True, then=F("amount")),
                        default=Coalesce(
                            F("purchase_request__order_cost"),
                            Value(0),
                            output_field=DecimalField(),
                        ),
                        output_field=DecimalField(max_digits=20, decimal_places=2),
                    )
                )
            )["total"]

        return total or 0


class BusinessSavedCardTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessSavedCardToken
        fields = [
            "id",
            "token",
            "number",
            "card_type",
            "card_brand",
            "expiry_year",
            "expiry_month",
            "is_used_for_subscription",
        ]


class BusinessSavedCardSessionSerializer(serializers.Serializer):
    """
    Create a Credimax hosted session so the frontend can collect card details.
    """

    session_id = serializers.CharField(read_only=True)

    def validate(self, attrs):
        request = self.context["request"]
        current_business_id = (
            request.auth.get("current_business") if request.auth else None
        )

        if not current_business_id:
            raise serializers.ValidationError(MESSAGES["business_account_not_found"])

        try:
            business = UserAssignedBusiness.objects.get(id=current_business_id).business
        except UserAssignedBusiness.DoesNotExist:
            raise serializers.ValidationError(MESSAGES["business_account_not_found"])

        attrs["business"] = business
        return attrs

    def save(self, **kwargs):
        import uuid

        business = self.validated_data["business"]
        client = CredimaxClient()

        try:
            session_response = client.create_session()
        except Exception as exc:
            raise serializers.ValidationError(
                {"detail": f"Failed to create Credimax session: {exc}"}
            )

        session_id = session_response.get("session", {}).get("id")
        if not session_id:
            raise serializers.ValidationError(
                {"detail": "Credimax session response did not include a session ID."}
            )

        # Create a temporary order ID and transaction ID for card addition flow
        # Credimax requires an order with currency and transaction in the session
        # This order and transaction must exist before the frontend can perform 3DS authentication
        order_id = f"card_add_{uuid.uuid4().hex[:16]}"
        transaction_id = f"txn_{uuid.uuid4().hex[:12]}"

        try:
            # Update session with zero-amount order and transaction for card addition
            # This is required by Credimax API - order must have currency
            # Transaction ID is needed for Initiate Authentication and Authenticate Payer operations
            update_response = client.update_session_for_card_addition(
                session_id, order_id, transaction_id
            )
            logger.info(
                f"Successfully updated session {session_id} with order {order_id} "
                f"and transaction {transaction_id} for card addition"
            )
        except Exception as exc:
            logger.error(
                f"Failed to update session {session_id} with order for card addition: {exc}"
            )
            raise serializers.ValidationError(
                {
                    "detail": f"Failed to initialize card addition session: {exc}. "
                    "Credimax requires an order with currency in the session."
                }
            )

        return {
            "session_id": session_id,
            "order_id": order_id,
            "transaction_id": transaction_id,
        }


def verify_and_update_credimax_agreements(business, card_token, session_id=None):
    """
    Helper function to verify a card with Credimax and update agreements.
    This ensures that when a card is set as default for subscription,
    all relevant Credimax agreements are updated with the new card token.

    Args:
        business: BusinessAccount instance
        card_token: BusinessSavedCardToken instance that should be linked to agreements
        session_id: Optional Credimax session ID (for card addition flow)

    Returns:
        tuple: (success_count, failed_count) - number of agreements successfully updated and failed
    """
    logger.info(
        f"verify_and_update_credimax_agreements called - business: {business.id}, "
        f"card_token: {card_token.id if card_token else None}, "
        f"is_used_for_subscription: {card_token.is_used_for_subscription if card_token else False}"
    )

    if not card_token or not card_token.is_used_for_subscription:
        logger.info(
            f"Skipping agreement update - card_token is None or not used for subscription. "
            f"business: {business.id}"
        )
        return 0, 0

    try:
        client = CredimaxClient()
        # Find active, pending, or suspended subscriptions for this business
        subscriptions = BusinessSubscriptionPlan.objects.filter(
            business=business,
            status__in=[
                SubscriptionStatusChoices.ACTIVE,
                SubscriptionStatusChoices.PENDING,
                SubscriptionStatusChoices.SUSPENDED,
            ],
        ).order_by("-created_at")

        subscription_count = subscriptions.count()
        token_display = (
            f"{card_token.token[:4]}...{card_token.token[-4:]}"
            if len(card_token.token) > 8
            else "****"
        )
        logger.info(
            f"Found {subscription_count} subscription(s) for business {business.id} "
            f"to verify/update with card token {token_display}"
        )

        if subscription_count == 0:
            logger.info(
                f"No subscriptions found for business {business.id} to update with card token"
            )
            return 0, 0

        success_count = 0
        failed_count = 0

        # Determine which subscription should get the card token assigned
        # Priority: ACTIVE > PENDING > SUSPENDED, then most recent
        subscription_to_assign_card = None
        for sub in subscriptions:
            if sub.status == SubscriptionStatusChoices.ACTIVE:
                subscription_to_assign_card = sub
                break
        if not subscription_to_assign_card:
            for sub in subscriptions:
                if sub.status == SubscriptionStatusChoices.PENDING:
                    subscription_to_assign_card = sub
                    break
        if not subscription_to_assign_card:
            subscription_to_assign_card = subscriptions.first()

        logger.info(
            f"Will assign card token to subscription: {subscription_to_assign_card.id if subscription_to_assign_card else 'None'}"
        )

        for subscription in subscriptions:
            try:
                token_display = (
                    f"{card_token.token[:4]}...{card_token.token[-4:]}"
                    if len(card_token.token) > 8
                    else "****"
                )
                logger.info(
                    f"Verifying card with Credimax for agreement {subscription.id} "
                    f"using token {token_display}"
                )
                # First verify the card with Credimax using VERIFY operation
                verify_payload, verify_response = client.verify_card_with_agreement(
                    agreement=subscription,
                    token=card_token.token,
                    session_id=session_id,
                )

                verification_result = verify_response.get("result")
                gateway_code = verify_response.get("response", {}).get("gatewayCode")
                error_message = verify_response.get("response", {}).get(
                    "acquirerMessage"
                ) or verify_response.get("error", {}).get(
                    "explanation", "Unknown error"
                )

                logger.info(
                    f"Verification response for agreement {subscription.id}: "
                    f"result={verification_result}, gatewayCode={gateway_code}"
                )

                verification_successful = verification_result == "SUCCESS"

                if not verification_successful:
                    logger.warning(
                        f"Card verification failed for agreement {subscription.id}: {error_message}. "
                        f"Will still attempt to update agreement directly. "
                        f"Full response: {verify_response}"
                    )

                # Update the Credimax agreement with the new card token
                # This is the critical step - even if verification failed, we still update the agreement
                try:
                    update_response = client.update_agreement_with_card(
                        agreement=subscription,
                        token=card_token.token,
                    )
                    token_display = (
                        f"{card_token.token[:4]}...{card_token.token[-4:]}"
                        if len(card_token.token) > 8
                        else "****"
                    )
                    logger.info(
                        f"Updated Credimax agreement {subscription.id} with card token {token_display}"
                    )

                    # Verify the agreement was updated by retrieving it from Credimax
                    try:
                        agreement_details = client.get_agreement_details(subscription)
                        stored_token = agreement_details.get("sourceOfFunds", {}).get(
                            "token"
                        )
                        if stored_token == card_token.token:
                            logger.info(
                                f"Verified: Agreement {subscription.id} has been updated with card token {token_display}"
                            )
                        else:
                            stored_token_display = (
                                f"{stored_token[:4]}...{stored_token[-4:]}"
                                if stored_token and len(stored_token) > 8
                                else "****"
                            )
                            logger.warning(
                                f"Warning: Agreement {subscription.id} token mismatch. "
                                f"Expected: {token_display}, Found: {stored_token_display}"
                            )
                    except Exception as verify_error:
                        logger.warning(
                            f"Could not verify agreement update for {subscription.id}: {str(verify_error)}"
                        )

                    # Update local subscription with the card token
                    # Only assign the card to the selected subscription (due to OneToOneField constraint)
                    # All other subscriptions will have their Credimax agreements updated but won't have the card assigned
                    # The recurring payment task will use the default card if a subscription doesn't have one
                    if subscription.id == subscription_to_assign_card.id:
                        old_card_id = (
                            subscription.business_saved_card_token.id
                            if subscription.business_saved_card_token
                            else None
                        )

                        # Check if this card is already assigned to another subscription
                        existing_subscription = (
                            BusinessSubscriptionPlan.objects.filter(
                                business_saved_card_token=card_token
                            )
                            .exclude(id=subscription.id)
                            .first()
                        )

                        if existing_subscription:
                            token_display = (
                                f"{card_token.token[:4]}...{card_token.token[-4:]}"
                                if len(card_token.token) > 8
                                else "****"
                            )
                            logger.info(
                                f"Card token {token_display} is already assigned to subscription "
                                f"{existing_subscription.id}. Unassigning from previous subscription."
                            )
                            # Unassign from previous subscription
                            existing_subscription.business_saved_card_token = None
                            existing_subscription.save(
                                update_fields=["business_saved_card_token"]
                            )

                        # Update the subscription with the new card token
                        subscription.business_saved_card_token = card_token
                        subscription.save(update_fields=["business_saved_card_token"])

                        # Verify the save worked
                        subscription.refresh_from_db()
                        new_card_id = (
                            subscription.business_saved_card_token.id
                            if subscription.business_saved_card_token
                            else None
                        )
                        logger.info(
                            f"Subscription {subscription.id} card updated: {old_card_id} -> {new_card_id}"
                        )
                    else:
                        logger.info(
                            f"Subscription {subscription.id} Credimax agreement updated, "
                            f"but card not assigned (will use default card for payments)"
                        )

                    if verification_successful:
                        logger.info(
                            f"Successfully verified and updated agreement {subscription.id} "
                            f"with card token {token_display} for business {business.id}"
                        )
                    else:
                        logger.info(
                            f"Updated agreement {subscription.id} with card token {token_display} "
                            f"(verification failed but agreement update succeeded) for business {business.id}"
                        )
                    success_count += 1
                except Exception as update_error:
                    failed_count += 1
                    # Check if this is a validation error (4xx) or server error (5xx)
                    error_message = str(update_error)
                    # Validation errors from Credimax (400, 404, etc.) should be warnings, not errors
                    if (
                        "validation error" in error_message.lower()
                        or "HTTP 4" in error_message
                    ):
                        logger.warning(
                            f"Failed to update Credimax agreement {subscription.id} with card token (validation error): {error_message}"
                        )
                    else:
                        # Server errors or unexpected errors should be logged as errors
                        logger.error(
                            f"Failed to update Credimax agreement {subscription.id} with card token: {error_message}",
                            exc_info=True,
                        )
            except Exception as e:
                failed_count += 1
                # Check if this is a validation error (4xx) or server error (5xx)
                error_message = str(e)
                # Validation errors from Credimax (400, 404, etc.) should be warnings, not errors
                if (
                    "validation error" in error_message.lower()
                    or "HTTP 4" in error_message
                ):
                    logger.warning(
                        f"Error verifying/updating agreement {subscription.id} with card token (validation error): {error_message}"
                    )
                else:
                    # Server errors or unexpected errors should be logged as errors
                    logger.error(
                        f"Error verifying/updating agreement {subscription.id} with card token: {error_message}"
                    )

        logger.info(
            f"Agreement update completed for business {business.id}: "
            f"{success_count} successful, {failed_count} failed"
        )
        return success_count, failed_count

    except Exception as e:
        # Log error but don't fail the card save operation
        logger.error(
            f"Error processing subscription agreements for card token {card_token.token} "
            f"for business {business.id}: {str(e)}",
            exc_info=True,
        )
        return 0, 0


class BusinessSavedCardCreateSerializer(serializers.Serializer):
    """
    Serializer responsible for verifying a card with Credimax and storing it
    against the current business.
    """

    session_id = serializers.CharField()
    make_default = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        request = self.context["request"]
        current_business_id = (
            request.auth.get("current_business") if request.auth else None
        )

        if not current_business_id:
            raise serializers.ValidationError(MESSAGES["business_account_not_found"])

        try:
            user_business = UserAssignedBusiness.objects.get(
                id=current_business_id
            ).business
        except UserAssignedBusiness.DoesNotExist:
            raise serializers.ValidationError(MESSAGES["business_account_not_found"])

        attrs["business"] = user_business
        return attrs

    def save(self):
        request = self.context["request"]
        business = self.validated_data["business"]
        session_id = self.validated_data["session_id"]
        make_default = self.validated_data.get("make_default", False)
        request_user = request.user

        client = CredimaxClient()

        try:
            credimax_response = client.tokenize_card(session_id)
        except Exception as exc:
            raise serializers.ValidationError(
                {"session_id": f"Failed to verify card with Credimax: {exc}"}
            )

        result = credimax_response.get("result")
        if result and result != "SUCCESS":
            raise serializers.ValidationError(
                {"session_id": "Credimax was unable to verify the provided card."}
            )

        token = credimax_response.get("token")
        card_info = (
            credimax_response.get("sourceOfFunds", {})
            .get("provided", {})
            .get("card", {})
        )

        if not token or not card_info:
            raise serializers.ValidationError(
                {"session_id": "Unable to retrieve card information from Credimax."}
            )

        expiry = card_info.get("expiry") or ""
        expiry_month = expiry[:2]
        expiry_year = expiry[2:4] if len(expiry) >= 4 else ""
        card_number = card_info.get("number")

        # Validate card expiry date
        if expiry_month and expiry_year:
            is_valid, error_message = validate_card_expiry_date(
                expiry_month, expiry_year
            )
            if not is_valid:
                raise serializers.ValidationError({"session_id": error_message})

        # Automatically set as default if this is the first saved card
        if not BusinessSavedCardToken.objects.filter(business=business).exists():
            make_default = True

        with transaction.atomic():
            # CRITICAL: Check for existing card by TOKEN first (token is globally unique)
            # This prevents duplicate entries even if card number format differs slightly
            existing_card_by_token = (
                BusinessSavedCardToken.objects.select_for_update()
                .filter(token=token)
                .first()
            )

            if existing_card_by_token:
                # Token already exists - check if it belongs to the same business
                if existing_card_by_token.business != business:
                    raise serializers.ValidationError(
                        {
                            "session_id": "This card token is already registered with another business."
                        }
                    )

                # Token exists for same business - this is a duplicate request
                # Update the existing card with latest information from Credimax
                existing_card = existing_card_by_token
                existing_card.number = card_info.get("number", existing_card.number)
                existing_card.expiry_month = expiry_month or existing_card.expiry_month
                existing_card.expiry_year = expiry_year or existing_card.expiry_year
                existing_card.card_type = card_info.get(
                    "fundingMethod", existing_card.card_type
                )
                existing_card.card_brand = card_info.get(
                    "brand", existing_card.card_brand
                )
                existing_card.updated_by = request_user

                if make_default and not existing_card.is_used_for_subscription:
                    BusinessSavedCardToken.objects.filter(
                        business=business, is_used_for_subscription=True
                    ).exclude(id=existing_card.id).update(
                        is_used_for_subscription=False, updated_by=request_user
                    )
                    existing_card.is_used_for_subscription = True

                existing_card.save()
                saved_card = existing_card
            else:
                # Token doesn't exist - check for duplicate by card number
                # This handles cases where same card gets different tokens (unlikely but possible)
                existing_card_by_number = None
                if card_number:
                    existing_card_by_number = (
                        BusinessSavedCardToken.objects.select_for_update()
                        .filter(
                            business=business,
                            number=card_number,
                        )
                        .first()
                    )

                if existing_card_by_number:
                    # Card number already exists for this business - update it with new token
                    # Only update token if it's not already used by another card
                    if existing_card_by_number.token != token:
                        # Double-check token is not used elsewhere (race condition protection)
                        token_conflict = (
                            BusinessSavedCardToken.objects.filter(token=token)
                            .exclude(id=existing_card_by_number.id)
                            .exists()
                        )
                        if token_conflict:
                            raise serializers.ValidationError(
                                {
                                    "session_id": "This card token is already registered with another card."
                                }
                            )
                        existing_card_by_number.token = token

                    # Update card metadata from Credimax response
                    existing_card_by_number.number = card_info.get(
                        "number", existing_card_by_number.number
                    )
                    existing_card_by_number.expiry_month = (
                        expiry_month or existing_card_by_number.expiry_month
                    )
                    existing_card_by_number.expiry_year = (
                        expiry_year or existing_card_by_number.expiry_year
                    )
                    existing_card_by_number.card_type = card_info.get(
                        "fundingMethod", existing_card_by_number.card_type
                    )
                    existing_card_by_number.card_brand = card_info.get(
                        "brand", existing_card_by_number.card_brand
                    )
                    existing_card_by_number.updated_by = request_user

                    if (
                        make_default
                        and not existing_card_by_number.is_used_for_subscription
                    ):
                        BusinessSavedCardToken.objects.filter(
                            business=business, is_used_for_subscription=True
                        ).exclude(id=existing_card_by_number.id).update(
                            is_used_for_subscription=False, updated_by=request_user
                        )
                        existing_card_by_number.is_used_for_subscription = True

                    existing_card_by_number.save()
                    saved_card = existing_card_by_number
                else:
                    # New card - ensure token is not used elsewhere (final safety check)
                    # This handles any race conditions
                    token_conflict = BusinessSavedCardToken.objects.filter(
                        token=token
                    ).exists()
                    if token_conflict:
                        # Token was created between our check and create attempt
                        raise serializers.ValidationError(
                            {
                                "session_id": "This card has already been added. Please refresh and try again."
                            }
                        )

                    if make_default:
                        BusinessSavedCardToken.objects.filter(
                            business=business, is_used_for_subscription=True
                        ).update(
                            is_used_for_subscription=False, updated_by=request_user
                        )

                    # Create new card entry
                    try:
                        saved_card = BusinessSavedCardToken.objects.create(
                            business=business,
                            token=token,
                            number=card_info.get("number"),
                            expiry_month=expiry_month,
                            expiry_year=expiry_year,
                            card_type=card_info.get("fundingMethod"),
                            card_brand=card_info.get("brand"),
                            is_used_for_subscription=make_default,
                            created_by=request_user,
                            updated_by=request_user,
                        )
                    except Exception as e:
                        # Handle database integrity errors (e.g., unique constraint violation)
                        if "token" in str(e).lower() or "unique" in str(e).lower():
                            raise serializers.ValidationError(
                                {
                                    "session_id": "This card has already been added. Please refresh and try again."
                                }
                            )
                        raise

            try:
                client.update_session_with_token(session_id, token)
            except Exception as exc:
                raise serializers.ValidationError(
                    {
                        "session_id": f"Failed to finalize card verification with Credimax: {exc}"
                    }
                )

        # If card is set as default for subscription, verify and update Credimax agreements
        # Do this outside the atomic block to avoid transaction errors
        if saved_card.is_used_for_subscription:
            verify_and_update_credimax_agreements(
                business=business,
                card_token=saved_card,
                session_id=session_id,
            )

        return saved_card


class BusinessSavedCardSetDefaultSerializer(serializers.Serializer):
    """
    Serializer to set a saved business card as the default (used for subscription/transactions).
    Note: card_id is obtained from the URL path parameter, not from the request body.
    """

    def validate(self, attrs):
        request = self.context["request"]
        # Get card_id from view kwargs (URL path parameter) or directly from context
        view = self.context.get("view")
        card_id = self.context.get("pk") or (view.kwargs.get("pk") if view else None)

        if not card_id:
            raise serializers.ValidationError(
                {"card_id": "Card ID is required in the URL path."}
            )

        current_business_id = (
            request.auth.get("current_business") if request.auth else None
        )

        if not current_business_id:
            raise serializers.ValidationError(MESSAGES["business_account_not_found"])

        try:
            business = UserAssignedBusiness.objects.get(id=current_business_id).business
        except UserAssignedBusiness.DoesNotExist:
            raise serializers.ValidationError(MESSAGES["business_account_not_found"])

        try:
            card = BusinessSavedCardToken.objects.get(id=card_id, business=business)
        except BusinessSavedCardToken.DoesNotExist:
            raise serializers.ValidationError(MESSAGES["business_saved_card_not_found"])

        attrs["business"] = business
        attrs["card"] = card
        return attrs

    def save(self):
        business = self.validated_data["business"]
        card = self.validated_data["card"]
        request_user = self.context["request"].user

        with transaction.atomic():
            BusinessSavedCardToken.objects.filter(
                business=business, is_used_for_subscription=True
            ).exclude(id=card.id).update(
                is_used_for_subscription=False, updated_by=request_user
            )

            update_fields = ["updated_by"]
            card.updated_by = request_user

            if not card.is_used_for_subscription:
                card.is_used_for_subscription = True
                update_fields.append("is_used_for_subscription")

            card.save(update_fields=update_fields)

        # If card is set as default for subscription, verify and update Credimax agreements
        # Do this outside the atomic block to avoid transaction errors
        if card.is_used_for_subscription:
            verify_and_update_credimax_agreements(
                business=business,
                card_token=card,
            )

        return card


class UserRolesSerializer(serializers.Serializer):
    roles = serializers.ListField(read_only=True)
    email = serializers.EmailField()
    organization_code = serializers.CharField()


class AppVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppVersion
        fields = ["platform", "min_required_version", "app_url"]
