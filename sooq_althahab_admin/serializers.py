from datetime import timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.db.models import Sum
from django.utils import timezone
from phonenumber_field.phonenumber import to_python
from rest_framework import serializers

from account.message import MESSAGES as ACCOUNT_MESSAGES
from account.mixins import BusinessDetailsMixin
from account.models import AdminUserRole
from account.models import BusinessAccount
from account.models import Organization
from account.models import OrganizationCurrency
from account.models import OrganizationRiskLevel
from account.models import Transaction
from account.models import User
from account.models import UserAssignedBusiness
from account.models import Wallet
from account.utils import calculate_platform_fee
from investor.message import MESSAGES as INVESTOR_MESSAGE
from investor.models import AssetContribution
from investor.models import PreciousItemUnit
from investor.models import PreciousItemUnitMusharakahHistory
from investor.models import PurchaseRequest
from jeweler.message import MESSAGES as JEWELER_MESSAGE
from jeweler.models import InspectedRejectedJewelryProduct
from jeweler.models import InspectionRejectionAttachment
from jeweler.models import JewelryProductInspectionAttachment
from jeweler.models import JewelryProduction
from jeweler.models import JewelryProductMarketplace
from jeweler.models import JewelryProductMarketplaceImage
from jeweler.models import JewelryProductMaterial
from jeweler.models import JewelryProfitDistribution
from jeweler.models import JewelryStock
from jeweler.models import JewelryStockSale
from jeweler.models import ManufacturingProductRequestedQuantity
from jeweler.models import ManufacturingTarget
from jeweler.models import MusharakahContractDesign
from jeweler.models import MusharakahContractRenewal
from jeweler.models import MusharakahContractRequest
from jeweler.models import MusharakahContractTerminationRequest
from jeweler.models import ProductionPayment
from jeweler.models import ProductionPaymentAssetAllocation
from jeweler.serializers import BaseMusharakahContractRequestResponseSerializer
from jeweler.serializers import BaseMusharakahContractTerminationRequestDetailSerializer
from jeweler.serializers import JewelryProductResponseSerializer
from jeweler.serializers import MusharakahContractRequestResponseSerializer
from manufacturer.models import ProductManufacturingEstimatedPrice
from sooq_althahab.enums.account import MusharakahContractTerminationPaymentType
from sooq_althahab.enums.account import PlatformFeeType
from sooq_althahab.enums.account import SuspendingRoleChoice
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.account import UserStatus
from sooq_althahab.enums.account import UserType
from sooq_althahab.enums.investor import ContributionType
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.enums.investor import RequestType
from sooq_althahab.enums.jeweler import ContractTerminator
from sooq_althahab.enums.jeweler import CostRetailPaymentOption
from sooq_althahab.enums.jeweler import DeliveryRequestStatus
from sooq_althahab.enums.jeweler import DeliveryStatus
from sooq_althahab.enums.jeweler import ImpactedParties
from sooq_althahab.enums.jeweler import InspectionRejectedByChoices
from sooq_althahab.enums.jeweler import InspectionStatus
from sooq_althahab.enums.jeweler import MaterialSource
from sooq_althahab.enums.jeweler import MusharakahContractStatus
from sooq_althahab.enums.jeweler import Ownership
from sooq_althahab.enums.jeweler import RefineSellPaymentOption
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.jeweler import StockLocation
from sooq_althahab.enums.sooq_althahab_admin import BusinessAccountSuspensionStatus
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.enums.sooq_althahab_admin import Status
from sooq_althahab.enums.sooq_althahab_admin import TransactionRequest
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.utils import get_presigned_url_from_s3
from sooq_althahab_admin.models import BillingDetails
from sooq_althahab_admin.models import BusinessSavedCardToken
from sooq_althahab_admin.models import BusinessSubscriptionPlan
from sooq_althahab_admin.models import GlobalMetal
from sooq_althahab_admin.models import JewelryProductColor
from sooq_althahab_admin.models import JewelryProductType
from sooq_althahab_admin.models import MaterialItem
from sooq_althahab_admin.models import MetalCaratType
from sooq_althahab_admin.models import MetalPriceHistory
from sooq_althahab_admin.models import MusharakahDurationChoices
from sooq_althahab_admin.models import Notification
from sooq_althahab_admin.models import OrganizationBankAccount
from sooq_althahab_admin.models import Pool
from sooq_althahab_admin.models import PoolContribution
from sooq_althahab_admin.models import StoneClarity
from sooq_althahab_admin.models import StoneCutShape
from sooq_althahab_admin.models import SubscriptionPlan

from .message import MESSAGES


class BusinessWithOwnerSerializer(serializers.ModelSerializer):
    business_subscription = serializers.SerializerMethodField()
    owner = serializers.SerializerMethodField()
    total_users = serializers.IntegerField()  # Use annotated value
    logo = serializers.SerializerMethodField()

    class Meta:
        model = BusinessAccount
        fields = [
            "id",
            "name",
            "business_account_type",
            "total_users",
            "business_subscription",
            "owner",
            "is_suspended",
            "logo",
        ]

    def get_business_subscription(self, obj):
        """Returns the latest business subscription ID and status using prefetched data."""
        subscriptions = getattr(obj, "prefetched_subscriptions", [])
        if subscriptions:
            subscription = subscriptions[0]
            return {"id": subscription.id, "status": subscription.status}
        return None

    def get_owner(self, obj):
        """Returns the first owner (if any) from prefetched user_assigned_businesses."""
        user_assigned_business = next(
            (
                uab
                for uab in getattr(obj, "all_user_assigned_businesses", [])
                if uab.is_owner
            ),
            None,
        )

        if user_assigned_business and getattr(
            user_assigned_business, "prefetched_user", None
        ):
            user = user_assigned_business.prefetched_user
            return {
                "id": user.id,
                "name": user.get_full_name(),
                "email": user.email,
                "is_deleted": user.is_deleted,
                "phone_number": str(user.phone_number) if user.phone_number else None,
                "user_type": user.user_type,
                "account_status": user.account_status,
                "delete_reason": user.delete_reason,
                "personal_number": user.personal_number,
                "phone_verified": user.phone_verified,
                "email_verified": user.email_verified,
                "face_verified": user.face_verified,
                "document_verified": user.document_verified,
                "business_aml_verified": user.business_aml_verified,
                "due_diligence_verified": user.due_diligence_verified,
            }
        return None

    def get_logo(self, obj):
        """Generate a presigned URL for the logo in the model using the PresignedUrlSerializer."""
        return get_presigned_url_from_s3(obj.logo)


class InvestorBusinessWithOwnerSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for investor business listing.

    This serializer is optimized for performance and includes only essential fields:
    - Business basic information (id, name, business_account_type)
    - Owner information (id, name only)

    Excludes heavy fields like:
    - Email, phone, user_type, account_status
    - Business subscription details
    - Risk level details
    - Logo and other media files
    """

    owner = serializers.SerializerMethodField()

    class Meta:
        model = BusinessAccount
        fields = [
            "id",
            "name",
            "business_account_type",
            "owner",
        ]

    def get_owner(self, obj):
        """Returns owner information."""
        if hasattr(obj, "prefetched_owners") and obj.prefetched_owners:
            owner = obj.prefetched_owners[0]
            user = owner.user
            return {
                "id": user.id,
                "name": user.get_full_name(),
            }
        return None


class SubAdminCreateSerializer(serializers.ModelSerializer):
    role = serializers.CharField(max_length=20)

    class Meta:
        model = User
        fields = [
            "email",
            "password",
            "role",
            "first_name",
            "middle_name",
            "last_name",
            "phone_number",
            "phone_country_code",
        ]
        extra_kwargs = {
            "email": {"error_messages": {"blank": "This field is required."}},
            "password": {"error_messages": {"blank": "This field is required."}},
            "role": {"error_messages": {"blank": "This field is required."}},
        }

    def _get_organization(self):
        """Helper method to get the organization based on the provided organization code."""
        request = self.context.get("request")
        organization_code = request.auth.get("organization_code")

        try:
            return Organization.objects.get(code=organization_code)
        except Organization.DoesNotExist:
            raise serializers.ValidationError(
                ACCOUNT_MESSAGES["organization_not_found"]
            )

    def _validate_sub_admin_roles(self, role):
        """Validates the provided role to ensure it is an allowed sub-admin role."""
        allowed_roles = {
            UserRoleChoices.TAQABETH_ENFORCER,
            UserRoleChoices.JEWELLERY_INSPECTOR,
            UserRoleChoices.JEWELLERY_BUYER,
        }
        if role not in allowed_roles:
            raise serializers.ValidationError(MESSAGES["invalid_role"])

    def validate(self, data):
        """Validate that the email is unique within the organization and role is valid."""
        email = data.get("email")
        if email:
            email = email.strip().lower()
            data["email"] = email
        role = data.get("role")
        if not self.instance:  # Validation only on creation
            organization = self._get_organization()

            # Check if email already exists in the organization
            if User.global_objects.filter(
                email=email, organization_id=organization
            ).exists():
                raise serializers.ValidationError(ACCOUNT_MESSAGES["email_exists"])

            self._validate_sub_admin_roles(role)
            return data

        instance = self.instance
        if AdminUserRole.objects.filter(user=instance, role=role).exists():
            raise serializers.ValidationError(
                MESSAGES["sub_admin_already_exists_with_role"]
            )
        data["email"] = email
        return data

    def create(self, validated_data):
        """Create sub-admin user with assigned role."""
        role = validated_data.pop("role")
        password = validated_data.pop("password")
        organization = self._get_organization()

        user = User.objects.create_user(
            password=password, organization_id=organization, **validated_data
        )
        AdminUserRole.objects.create(user=user, role=role)
        return user

    def update(self, instance, validated_data):
        """Update sub-admin details and replace role."""
        role = validated_data.pop("role", None)
        password = validated_data.pop("password", None)

        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)

            if password:
                instance.set_password(password)

            if role:
                self._validate_sub_admin_roles(role)
                sub_admin_role = AdminUserRole.objects.filter(user=instance).first()
                sub_admin_role.role = role
                sub_admin_role.save()
            instance.save()

        return instance


class NotificationSerializer(serializers.ModelSerializer):
    content_data = serializers.SerializerMethodField()
    asset_related_notifications = [
        NotificationTypes.PURCHASE_REQUEST_CREATED,
        NotificationTypes.PURCHASE_REQUEST_APPROVED,
        NotificationTypes.PURCHASE_REQUEST_REJECTED,
        NotificationTypes.PURCHASE_REQUEST_COMPLETED,
        NotificationTypes.SALE_REQUEST_CREATED,
        NotificationTypes.SALE_REQUEST_APPROVED,
        NotificationTypes.SALE_REQUEST_REJECTED,
    ]

    transactions_related_notifications = [
        NotificationTypes.PURCHASE_REQUEST_PAYMENT_TRANSFER,
        NotificationTypes.PURCHASE_REQUEST_PAYMENT_RECEIVED,
        NotificationTypes.PURCHASE_REQUEST_PAYMENT_FAILED,
        NotificationTypes.WITHDRAW_REQUEST_APPROVED,
        NotificationTypes.WITHDRAW_REQUEST_CREATED,
        NotificationTypes.WITHDRAW_REQUEST_REJECTED,
        NotificationTypes.DEPOSIT_REQUEST_APPROVED,
        NotificationTypes.DEPOSIT_REQUEST_CREATED,
        NotificationTypes.DEPOSIT_REQUEST_REJECTED,
    ]

    class Meta:
        model = Notification
        fields = "__all__"

    def get_content_data(self, obj):
        from investor.serializers import TransactionResponseSerializer
        from seller.serializers import PurchaseRequestResponseSerializer

        """
        Returns serialized data for the related content object.
        """
        if obj.notification_type in self.asset_related_notifications:
            return PurchaseRequestResponseSerializer(obj.content_object).data
        elif obj.notification_type in self.transactions_related_notifications:
            return TransactionResponseSerializer(obj.content_object).data
        return None


class UserRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminUserRole
        fields = ["role"]


class SubAdminSerializer(serializers.ModelSerializer):
    user_roles = UserRoleSerializer(many=True)

    class Meta:
        model = User
        exclude = ["password", "deleted_at", "restored_at", "transaction_id"]


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["email", "phone_number", "phone_country_code"]

    def validate(self, attrs):
        phone_number = attrs.get("phone_number")
        email = None
        assigned_business = self.instance.user_assigned_businesses.first()
        role = assigned_business.business.business_account_type
        if attrs.get("email"):
            email = attrs.get("email").strip().lower()
            attrs["email"] = email

        if phone_number:
            parsed_phone_number = to_python(phone_number)
            if not parsed_phone_number or not parsed_phone_number.is_valid():
                raise serializers.ValidationError(
                    {"phone_number": ACCOUNT_MESSAGES["invalid_phone_number"]()}
                )

        users = User.objects.filter(
            (Q(email=email))
            & Q(
                phone_verified=True,
                email_verified=True,
                user_assigned_businesses__business__business_account_type=role,
            )
        )
        if users.exists():
            raise serializers.ValidationError(ACCOUNT_MESSAGES["user_already_exists"])
        return attrs

    def update(self, instance, validated_data):
        updated_fields = []

        for attr, value in validated_data.items():
            old_value = getattr(instance, attr)
            if old_value != value:
                updated_fields.append(attr)
                setattr(instance, attr, value)

        instance.save()

        # Attach updated fields to serializer for view-level logic
        self.updated_fields = updated_fields
        return instance


class UserSerializer(serializers.ModelSerializer):
    addresses = serializers.SerializerMethodField()
    businesses = serializers.SerializerMethodField()
    business_users = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()

    class Meta:
        model = User
        exclude = ["password"]

    def get_addresses(self, obj):
        from account.serializers import AddressSerializer

        return AddressSerializer(
            getattr(obj, "prefetched_addresses", []), many=True
        ).data

    def get_businesses(self, obj):
        """Retrieve businesses related to the user with subscription details"""
        from account.serializers import BankAccountSerializer
        from account.serializers import BusinessAccountResponseSerializer
        from account.serializers import WalletSerializer

        businesses = [
            uab.prefetched_business
            for uab in getattr(obj, "all_user_assigned_businesses", [])
            if getattr(uab, "prefetched_business", None)
        ]

        # Get the serialized business data
        business_data = BusinessAccountResponseSerializer(businesses, many=True).data

        # Owner's bank account (shared across businesses)
        bank_account = getattr(obj, "bank_account", None)
        bank_data = BankAccountSerializer(bank_account).data if bank_account else None

        # Add subscription details to each business
        for i, business in enumerate(businesses):
            # Subscription details
            subscription_details = self._get_business_subscription_details(business)
            business_data[i].update(subscription_details)

            # Wallet details
            wallets = getattr(business, "prefetched_wallets", [])
            business_data[i]["wallet"] = (
                WalletSerializer(wallets[0]).data if wallets else None
            )

            # Bank details (business owner)
            business_data[i]["bank_account"] = bank_data

        return business_data

    def _get_business_subscription_details(self, business):
        try:
            subscriptions = getattr(business, "prefetched_subscriptions", [])
            if subscriptions:
                latest_subscription = subscriptions[0]
                return {
                    "business_subscription_id": latest_subscription.id,
                    "business_subscription_status": latest_subscription.status,
                }
        except (AttributeError, IndexError):
            pass

        return {"business_subscription_id": None, "business_subscription_status": None}

    def get_business_users(self, obj):
        """Retrieve all users in the same business excluding the owner"""
        from account.serializers import UserBasicSerializer

        business = next(
            (
                uab.business
                for uab in getattr(obj, "all_user_assigned_businesses", [])
                if uab.is_owner
            ),
            None,
        )

        # Get businesses where the user is an owner
        owned_businesses = BusinessAccount.global_objects.filter(
            user_assigned_businesses__business=business
        ).values_list("id", flat=True)

        if not owned_businesses:
            return []

        # Get users in those businesses, excluding the owner
        users = User.global_objects.filter(
            user_assigned_businesses__business_id__in=owned_businesses
        ).distinct()

        return UserBasicSerializer(users, many=True).data

    def get_profile_image(self, obj):
        """Generate a pre-signed URL for the given image"""
        return get_presigned_url_from_s3(obj.profile_image)


class GlobalMetalSerializer(serializers.ModelSerializer):
    class Meta:
        model = GlobalMetal
        fields = ["id", "name", "symbol"]
        extra_kwargs = {"id": {"read_only": True}}


class MaterialItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaterialItem
        fields = [
            "id",
            "name",
            "material_type",
            "image",
            "global_metal",
            "is_enabled",
            "stone_origin",
        ]
        extra_kwargs = {"id": {"read_only": True}, "is_enabled": {"read_only": True}}

    def validate_global_metal(self, value):
        """
        Ensure `global_metal` is required when `material_type` is 'metal'.
        """
        if self.initial_data.get("material_type") == MaterialType.METAL and not value:
            raise serializers.ValidationError(MESSAGES["global_metal_required"])
        return value


class GlobalMetalDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = GlobalMetal
        fields = ["name", "symbol"]


class MaterialItemDetailSerializer(MaterialItemSerializer):
    global_metal = GlobalMetalDetailSerializer(read_only=True)
    image = serializers.SerializerMethodField()

    class Meta(MaterialItemSerializer.Meta):
        fields = MaterialItemSerializer.Meta.fields

    def get_image(self, obj):
        """Generate a presigned URL for the image field in the model using the PresignedUrlSerializer."""
        object_name = obj.image
        return get_presigned_url_from_s3(object_name)


class MetalPriceHistorySerializer(serializers.ModelSerializer):
    global_metal = GlobalMetalDetailSerializer(read_only=True)

    class Meta:
        model = MetalPriceHistory
        fields = ["global_metal", "price", "price_on_date", "created_at"]
        extra_kwargs = {"id": {"read_only": True}}


class MetalPriceHistoryChartSerializer(serializers.Serializer):
    global_metal_name = serializers.CharField()
    metal_symbol = serializers.CharField()
    created_date = serializers.DateField()

    open_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True
    )
    close_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True
    )
    high_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True
    )
    low_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True
    )


class UserSuspensionStatusUpdateSerializer(serializers.ModelSerializer):
    account_status = serializers.ChoiceField(
        choices=[UserStatus.APPROVED, UserStatus.SUSPEND], required=True
    )

    class Meta:
        model = User
        fields = ["account_status", "remark"]

    def update(self, instance, validated_data):
        request = self.context.get("request")
        role = request.auth.get("role")
        account_status = validated_data.get("account_status")
        remark = validated_data.get("remark")

        instance.account_status = account_status

        if role in UserRoleChoices:
            # Ensure logged in user is an ADMIN, TAQABETH_ENFORCER, JEWELLERY_INSPECTOR, JEWELLERY_BUYER
            suspended_by = SuspendingRoleChoice.ADMIN
        else:
            # Ensure logged in user is a SELLER, JEWELER, INVESTOR, MANUFACTURER
            suspended_by = SuspendingRoleChoice.BUSINESS_OWNER

        # Ensure the user is deactivated
        if account_status == UserStatus.APPROVED:
            instance.is_active = True
            instance.suspended_by = None
        elif account_status == UserStatus.SUSPEND:
            instance.remark = remark
            instance.is_active = False
            instance.suspended_by = suspended_by
            if suspended_by == SuspendingRoleChoice.ADMIN:
                businesses = BusinessAccount.objects.filter(
                    user_assigned_businesses__user=instance,
                    user_assigned_businesses__is_owner=True,
                )
                businesses.update(is_suspended=True)

        # Save the updated instance
        instance.save()
        return instance


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = "__all__"
        read_only_fields = [
            "id",
            "name",
            "active",
            "code",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]

    def validate(self, data):
        # Check if any platform fee related fields are in the incoming data
        platform_fee_fields = {
            "platform_fee_type",
            "platform_fee_rate",
            "platform_fee_amount",
        }
        if not platform_fee_fields.intersection(data.keys()):
            return data  # No platform fee fields in update, skip validation

        # Use existing instance values if fields not in data (for partial updates)
        platform_fee_type = data.get(
            "platform_fee_type", getattr(self.instance, "platform_fee_type", None)
        )
        platform_fee_rate = data.get(
            "platform_fee_rate", getattr(self.instance, "platform_fee_rate", None)
        )
        platform_fee_amount = data.get(
            "platform_fee_amount", getattr(self.instance, "platform_fee_amount", None)
        )

        if platform_fee_type == PlatformFeeType.PERCENTAGE:
            if not platform_fee_rate or platform_fee_rate <= 0:
                raise serializers.ValidationError(
                    MESSAGES["platform_fee_rate_required"]
                )
            if platform_fee_amount and platform_fee_amount > 0:
                raise serializers.ValidationError(
                    MESSAGES["invalid_platform_fee_amount"]
                )

        elif platform_fee_type == PlatformFeeType.AMOUNT:
            if not platform_fee_amount or platform_fee_amount <= 0:
                raise serializers.ValidationError(
                    MESSAGES["platform_fee_amount_required"]
                )
            if platform_fee_rate and platform_fee_rate > 0:
                raise serializers.ValidationError(MESSAGES["invalid_platform_fee_rate"])

        return data


class OrganizationResponseSerializer(OrganizationSerializer):
    logo = serializers.SerializerMethodField()

    def get_logo(self, obj):
        """Generate a presigned URL for the logo in the model using the PresignedUrlSerializer."""
        return get_presigned_url_from_s3(obj.logo)


class MaterialItemUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaterialItem
        fields = ["is_enabled", "image"]


class OrganizationCurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationCurrency
        fields = ["id", "currency_code", "rate", "is_default"]
        read_only_fields = ["id", "is_default"]
        ref_name = "AdminOrganizationCurrency"

    def validate_rate(self, value):
        """Ensure the rate is greater than zero."""
        if value <= 0:
            raise serializers.ValidationError(MESSAGES["invalid_rate"])
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        instance = getattr(self, "instance", None)
        organization_id = request.user.organization_id if request else None
        currency_code = attrs.get("currency_code")

        if organization_id:
            existing_currency = OrganizationCurrency.objects.filter(
                currency_code=currency_code, organization_id=organization_id
            ).exclude(id=instance.id if instance else None)

            if existing_currency.exists():
                raise serializers.ValidationError(
                    MESSAGES["currency_code_already_exists"]
                )

        return attrs

    def create(self, validated_data):
        validated_data["organization"] = self.context["request"].user.organization_id
        return super().create(validated_data)


class OrganizationCurrencyUpdateSerializer(OrganizationCurrencySerializer):
    class Meta:
        model = OrganizationCurrency
        fields = ["id", "currency_code", "rate", "is_default"]
        read_only_fields = ["id"]


class MusharakahDurationLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = MusharakahDurationChoices
        fields = ["id", "name", "days", "is_active"]


class MusharakahDurationChoiceSerializer(serializers.ModelSerializer):
    risk_level_ids = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
        help_text="List of risk level IDs to associate with this duration.",
    )

    class Meta:
        model = MusharakahDurationChoices
        fields = ["id", "name", "days", "is_active", "risk_level_ids"]
        extra_kwargs = {"id": {"read_only": True}}

    def validate_name(self, value):
        """Ensure the name is unique within the organization, excluding self on update."""
        request = self.context.get("request")
        organization_id = request.user.organization_id if request else None
        queryset = MusharakahDurationChoices.objects.filter(
            name=value, organization_id=organization_id
        )
        if self.instance:
            queryset = queryset.exclude(id=self.instance.id)
        if queryset.exists():
            raise serializers.ValidationError(MESSAGES["same_name_validation"])
        return value

    def create(self, validated_data):
        user = self.context["request"].user
        risk_level_ids = validated_data.pop("risk_level_ids", [])

        # Custom validation to ensure risk_level_ids is required
        if not risk_level_ids:
            raise serializers.ValidationError(
                MESSAGES["required_risk_level_for_duration"]
            )

        validated_data["organization_id"] = user.organization_id
        duration = MusharakahDurationChoices.objects.create(**validated_data)

        # Link risk levels
        for risk_level in OrganizationRiskLevel.objects.filter(
            id__in=risk_level_ids, organization_id=user.organization_id
        ):
            risk_level.allowed_durations.add(duration)

        return duration

    def update(self, instance, validated_data):
        user = self.context["request"].user
        risk_level_ids = validated_data.pop("risk_level_ids", None)

        # Check if risk_level_ids was explicitly sent in request and is empty
        if risk_level_ids is not None and len(risk_level_ids) == 0:
            raise serializers.ValidationError(
                MESSAGES["required_risk_level_for_duration"]
            )

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.organization_id = user.organization_id
        instance.save()

        if risk_level_ids is not None:
            risk_levels = OrganizationRiskLevel.objects.filter(
                id__in=risk_level_ids, organization_id=user.organization_id
            )
            instance.risk_levels.set(risk_levels)

        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["risk_levels"] = list(instance.risk_levels.values("id", "risk_level"))
        return data


class OrganizationRiskLevelSerializer(serializers.ModelSerializer):
    allowed_durations = MusharakahDurationLiteSerializer(many=True, read_only=True)
    allowed_duration_ids = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
        help_text="List of MusharakahDurationChoice IDs to assign to this risk level.",
    )

    class Meta:
        model = OrganizationRiskLevel
        fields = [
            "id",
            "risk_level",
            "equity_min",
            "equity_max",
            "max_musharakah_weight",
            "penalty_amount",
            "is_active",
            "allowed_durations",
            "allowed_duration_ids",
        ]
        read_only_fields = ["id", "allowed_durations"]

    def validate(self, attrs):
        user = self.context["request"].user
        org_id = user.organization_id
        risk_level = attrs.get("risk_level")
        equity_min = attrs.get("equity_min")
        equity_max = attrs.get("equity_max")

        # Check unique risk_level per org
        if risk_level:
            risk_level_queryset = OrganizationRiskLevel.objects.filter(
                organization_id=org_id, risk_level=risk_level
            )
            if self.instance:
                risk_level_queryset = risk_level_queryset.exclude(id=self.instance.id)
            if risk_level_queryset.exists():
                raise serializers.ValidationError(
                    MESSAGES["duplicate_risk_level_validation"].format(
                        risk_level=risk_level.replace("_", " ").title()
                    )
                )

        # Check unique equity_min per org
        if equity_min:
            risk_level_queryset = OrganizationRiskLevel.objects.filter(
                organization_id=org_id, equity_min=equity_min
            )
            if self.instance:
                risk_level_queryset = risk_level_queryset.exclude(id=self.instance.id)
            if risk_level_queryset.exists():
                raise serializers.ValidationError(
                    MESSAGES["validate_equity_min_for_risk_level"]
                )
            if equity_max and equity_min >= equity_max:
                raise serializers.ValidationError(
                    MESSAGES["validate_equity_min_max_for_risk_level"]
                )

        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        organization_id = user.organization_id
        duration_ids = validated_data.pop("allowed_duration_ids", [])

        instance = OrganizationRiskLevel.objects.create(
            organization_id=organization_id, created_by=user, **validated_data
        )

        if duration_ids:
            durations = MusharakahDurationChoices.objects.filter(
                id__in=set(duration_ids), organization_id=organization_id
            )
            instance.allowed_durations.set(durations)

        return instance

    def update(self, instance, validated_data):
        user = self.context["request"].user
        duration_ids = validated_data.pop("allowed_duration_ids", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.updated_by = user
        instance.save()

        if duration_ids is not None:
            durations = MusharakahDurationChoices.objects.filter(
                id__in=duration_ids, organization_id=user.organization_id
            )
            instance.allowed_durations.set(durations)

        return instance


class BusinessRiskLevelUpdateSerializer(serializers.ModelSerializer):
    risk_level = serializers.PrimaryKeyRelatedField(
        queryset=OrganizationRiskLevel.objects.all()
    )

    class Meta:
        model = BusinessAccount
        fields = ["id", "risk_level"]


class TransactionUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating transaction status with an approved or rejected."""

    status = serializers.ChoiceField(
        choices=TransactionRequest.choices, required=True, write_only=True
    )

    class Meta:
        model = Transaction
        fields = ["remark", "status"]

    def update(self, instance, validated_data):
        """Update transaction and handle approval status logic."""
        remark = validated_data.get("remark")
        status = validated_data.pop("status", None)

        # Fetch the wallet associated with the business
        try:
            wallet = Wallet.objects.get(business=instance.from_business)
        except Wallet.DoesNotExist:
            raise serializers.ValidationError(
                ACCOUNT_MESSAGES["business_account_not_found"]
            )
        instance.previous_balance = wallet.balance

        # If the transaction is approved, mark it as successful and update wallet balance
        if status == TransactionRequest.APPROVED:
            instance.status = TransactionStatus.APPROVED

            if instance.transaction_type == TransactionType.DEPOSIT:
                wallet.balance += instance.amount

            elif instance.transaction_type == TransactionType.WITHDRAWAL:
                wallet.balance -= instance.amount

        elif status == TransactionRequest.REJECTED:
            instance.status = TransactionStatus.REJECTED

        instance.current_balance = wallet.balance
        instance.remark = remark

        wallet.save()
        instance.save()
        return instance


class OrganizationBankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationBankAccount
        fields = "__all__"
        read_only_fields = ["id", "organization", "created_by", "updated_by"]

    def create(self, validated_data):
        user = self.context.get("request").user

        return OrganizationBankAccount.objects.create(
            organization=user.organization_id, created_by=user, **validated_data
        )


class BusinessAccountSuspensionSerializer(serializers.ModelSerializer):
    business_account_status = serializers.ChoiceField(
        choices=BusinessAccountSuspensionStatus.choices, required=True
    )

    class Meta:
        model = BusinessAccount
        fields = ["business_account_status"]

    def update(self, instance, validated_data):
        business_account_status = validated_data.get("business_account_status")

        if business_account_status == BusinessAccountSuspensionStatus.REACTIVATE:
            # Ensure the business is Reactivate
            instance.is_suspended = False
            user = User.objects.filter(
                user_assigned_businesses__business=instance,
                user_assigned_businesses__is_owner=True,
            )
            user.update(is_active=True, suspended_by=None)

        elif business_account_status == BusinessAccountSuspensionStatus.SUSPEND:
            # Ensure the business is Suspended
            instance.is_suspended = True

        # Save the updated instance
        instance.save()
        return instance


class StoneCutShapeSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoneCutShape
        fields = ["id", "name", "is_enabled"]
        extra_kwargs = {"id": {"read_only": True}}

    def validate_name(self, value):
        """Ensure the name is unique."""

        if StoneCutShape.objects.filter(name=value).exists():
            raise serializers.ValidationError(MESSAGES["stone_cut_shape_exists"])
        return value

    def create(self, validated_data):
        user = self.context["request"].user
        validated_data["organization_id"] = user.organization_id
        return StoneCutShape.objects.create(**validated_data)


class MetalCaratTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetalCaratType
        fields = ["id", "name", "purity_percentage", "is_enabled"]
        extra_kwargs = {"id": {"read_only": True}}

    def validate_name(self, value):
        """Ensure the name is unique."""
        if MetalCaratType.objects.filter(name=value).exists():
            raise serializers.ValidationError(MESSAGES["metal_carat_type_exists"])
        return value

    def create(self, validated_data):
        user = self.context["request"].user
        validated_data["organization_id"] = user.organization_id
        return MetalCaratType.objects.create(**validated_data)


class StoneClaritySerializer(serializers.ModelSerializer):
    class Meta:
        model = StoneClarity
        fields = ["id", "name", "is_enabled"]
        extra_kwargs = {"id": {"read_only": True}}

    def validate_name(self, value):
        """Ensure the name is unique."""
        if StoneClarity.objects.filter(name=value).exists():
            raise serializers.ValidationError(MESSAGES["stone_clarity_exists"])
        return value

    def create(self, validated_data):
        user = self.context["request"].user
        validated_data["organization_id"] = user.organization_id
        return StoneClarity.objects.create(**validated_data)


class JewelryProductTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = JewelryProductType
        fields = ["id", "name", "is_enabled"]
        extra_kwargs = {"id": {"read_only": True}}

    def validate_name(self, value):
        """Ensure the name is unique (case-insensitive) while preserving user casing."""
        clean_value = value.strip()
        queryset = JewelryProductType.objects.all()
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.filter(name__iexact=clean_value).exists():
            raise serializers.ValidationError(MESSAGES["jewelry_product_type_exists"])
        return clean_value

    def create(self, validated_data):
        user = self.context["request"].user
        validated_data["organization_id"] = user.organization_id
        return JewelryProductType.objects.create(**validated_data)


class JewelryProductColorSerializer(serializers.ModelSerializer):
    class Meta:
        model = JewelryProductColor
        fields = ["id", "name", "is_enabled"]
        extra_kwargs = {"id": {"read_only": True}}

    def validate_name(self, value):
        """Ensure the name is unique (case-insensitive) while preserving user casing."""
        clean_value = value.strip()
        queryset = JewelryProductColor.objects.all()
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.filter(name__iexact=clean_value).exists():
            raise serializers.ValidationError(MESSAGES["jewelry_product_color_exists"])
        return clean_value

    def create(self, validated_data):
        user = self.context["request"].user
        validated_data["organization_id"] = user.organization_id
        return JewelryProductColor.objects.create(**validated_data)


class PreciousItemAttributes(serializers.Serializer):
    """Serializer to combine StoneCutShape, MetalCaratType, and MaterialItem data"""

    stone_cut_shapes = StoneCutShapeSerializer(many=True)
    metal_carat_types = MetalCaratTypeSerializer(many=True)
    material_items = MaterialItemDetailSerializer(many=True)
    jewelry_product_types = JewelryProductTypeSerializer(many=True)
    jewelry_product_colors = JewelryProductColorSerializer(many=True)
    musharakah_duration_choices = MusharakahDurationChoiceSerializer(many=True)
    stone_clarity = StoneClaritySerializer(many=True)


########################################################################################
########################## Pools Serializer's ##########################################
########################################################################################


class PoolCreateSerializer(serializers.ModelSerializer):
    risk_level = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = Pool
        fields = [
            "name",
            "musharakah_contract_request",
            "material_type",
            "material_item",
            "carat_type",
            "cut_shape",
            "target",
            "quantity",
            "expected_return_percentage",
            "risk_level",
            "minimum_investment_grams_per_participant",
            "management_fee_rate",
            "performance_fee_rate",
            "logo",
            "participation_duration",
            "authority_information",
            "fund_manager",
            "pool_duration",
            "fund_objective",
            "terms_and_conditions",
        ]

    def validate(self, attrs):
        musharakah_contract_request = attrs.get("musharakah_contract_request")
        material_type = attrs.get("material_type")
        material_item = attrs.get("material_item")
        carat_type = attrs.get("carat_type")
        cut_shape = attrs.get("cut_shape")

        # If no contract request, validate material fields manually
        if not musharakah_contract_request:
            if (
                not material_item
                or not MaterialItem.objects.filter(pk=material_item.pk).exists()
            ):
                raise serializers.ValidationError(MESSAGES["material_item_not_found"])

            if material_type == MaterialType.METAL:
                if (
                    not carat_type
                    or not MetalCaratType.objects.filter(pk=carat_type.pk).exists()
                ):
                    raise serializers.ValidationError(
                        MESSAGES["metal_carat_type_not_found"]
                    )
            elif material_type == MaterialType.STONE:
                if (
                    not cut_shape
                    or not StoneCutShape.objects.filter(pk=cut_shape.pk).exists()
                ):
                    raise serializers.ValidationError(
                        MESSAGES["stone_cut_shape_not_found"]
                    )

        # If contract exists and already has investor, raise error
        if musharakah_contract_request and musharakah_contract_request.investor:
            raise serializers.ValidationError(
                MESSAGES[
                    "pool_creation_denied_investor_already_asssigned_in_musharakah_contract_request"
                ]
            )
        return attrs

    def create(self, validated_data):
        """Create a new pool instance."""

        user = self.context["request"].user
        risk_level = validated_data.pop("risk_level", None)

        if not risk_level:
            raise serializers.ValidationError(MESSAGES["risk_level_required"])

        try:
            org_risk_level = OrganizationRiskLevel.objects.get(
                id=risk_level,
                organization_id=user.organization_id,
            )
        except OrganizationRiskLevel.DoesNotExist:
            raise serializers.ValidationError(MESSAGES["risk_level_required"])

        # Copy RiskLevelMixin fields into the pool
        validated_data.update(
            {
                "risk_level": org_risk_level.risk_level,
                "equity_min": org_risk_level.equity_min,
                "equity_max": org_risk_level.equity_max,
                "penalty_amount": org_risk_level.penalty_amount,
                "organization_id": user.organization_id,
                "created_by": user,
            }
        )

        return Pool.objects.create(**validated_data)


class PoolContributionDetailsSerializer(serializers.ModelSerializer):
    """Serializer to include business name and asset contribution in the pool."""

    assets_contributed = serializers.SerializerMethodField()
    participant = serializers.SerializerMethodField()
    signature = serializers.SerializerMethodField()

    class Meta:
        model = PoolContribution
        fields = [
            "id",
            "participant",
            "assets_contributed",
            "weight",
            "status",
            "signature",
            "fund_status",
            "approved_at",
        ]

    def get_assets_contributed(self, obj):
        from investor.models import AssetContribution
        from investor.serializers import AssetContributionResponseSerializer

        contributions = AssetContribution.global_objects.filter(
            business=obj.participant, pool=obj.pool, pool_contributor=obj
        )
        serializer = AssetContributionResponseSerializer(contributions, many=True)
        return serializer.data

    def get_participant(self, obj):
        """Return the name of the participant business."""
        user_assigned = UserAssignedBusiness.global_objects.filter(
            business=obj.participant, is_owner=True
        ).first()
        if not user_assigned or not user_assigned.user:
            return None

        user = user_assigned.user
        phone = str(user.phone_number) if user.phone_number else None

        base_data = {
            "id": obj.participant.id,
            "owner_name": user.fullname,
            "owner_email": user.email,
            "owner_phone": phone,
            "user_type": user.user_type,
            "owner_status": user.account_status,
        }

        if user.user_type == UserType.BUSINESS:
            base_data["business_name"] = obj.participant.name

        return base_data

    def get_signature(self, obj):
        """Generate a presigned URL for accessing the signature."""
        return get_presigned_url_from_s3(obj.signature)


class PoolResponseSerializer(BusinessDetailsMixin, serializers.ModelSerializer):
    musharakah_contract_request = MusharakahContractRequestResponseSerializer()
    stone_origin = serializers.CharField(
        source="material_item.stone_origin", read_only=True
    )
    remaining_target = serializers.SerializerMethodField()
    organization_logo = serializers.SerializerMethodField()
    logo = serializers.SerializerMethodField()
    participation_duration_date = serializers.SerializerMethodField()
    pool_duration_date = serializers.SerializerMethodField()
    material_item = serializers.SerializerMethodField()
    carat_type = serializers.SerializerMethodField()
    cut_shape = serializers.SerializerMethodField()

    class Meta:
        model = Pool
        exclude = [
            "updated_at",
            "transaction_id",
            "restored_at",
            "deleted_at",
            "updated_by",
        ]

    def get_organization_logo(self, obj):
        user = self.context.get("request").user
        organization_logo = user.organization_id.logo
        return (
            get_presigned_url_from_s3(organization_logo) if organization_logo else None
        )

    def get_logo(self, obj):
        """Generate a presigned URL for the pool logo using the PresignedUrlSerializer."""
        return get_presigned_url_from_s3(obj.logo) if obj.logo else None

    def get_material_item(self, obj):
        return {"id": obj.material_item.id, "name": obj.material_item.name}

    def get_cut_shape(self, obj):
        if obj.cut_shape:
            return {"id": obj.cut_shape.id, "name": obj.cut_shape.name}
        return None

    def get_carat_type(self, obj):
        if obj.carat_type:
            return {"id": obj.carat_type.id, "name": obj.carat_type.name}
        return None

    def get_remaining_target(self, obj):
        return obj.remaining_target

    def get_participation_duration_date(self, obj):
        if not obj.created_at or not obj.participation_duration:
            return None
        return obj.created_at + timedelta(days=obj.participation_duration)

    def get_pool_duration_date(self, obj):
        if not obj.created_at or not obj.pool_duration:
            return None
        return obj.created_at + timedelta(days=obj.pool_duration)


class PoolDetailsSerializer(PoolResponseSerializer):
    pool_contributions = serializers.SerializerMethodField()
    actual_remaining_for_user = serializers.SerializerMethodField()

    def get_pool_contributions(self, obj):
        request = self.context["request"]
        role = request.auth.get("role")
        pool_contribution = PoolContribution.global_objects
        if role in UserRoleChoices:
            # Ensure logged in user is an ADMIN, TAQABETH_ENFORCER, JEWELLERY_INSPECTOR, JEWELLERY_BUYER
            # Use global_objects to include soft-deleted pool contributions
            contributions = pool_contribution.filter(pool=obj)
        else:  # Ensure logged in user is an INVESTOR
            business = get_business_from_user_token(request, "business")
            contributions = pool_contribution.filter(
                pool=obj,
                participant=business,
                status__in=[Status.PENDING, Status.APPROVED],
            )

        return PoolContributionDetailsSerializer(contributions, many=True).data

    def get_actual_remaining_for_user(self, obj):
        """
        Calculate actual remaining target accounting for ALL PENDING contributions
        from all users. This is used to determine if minimum contribution exception should apply.

        The logic: If actual remaining (after all pending) < minimum, allow contribution
        less than minimum to complete the pool.
        """
        from investor.utils import get_total_weight_of_all_asset_contributed

        request = self.context.get("request")
        if not request:
            return None

        business = get_business_from_user_token(request, "business")
        if not business:
            return None

        remaining_target = obj.remaining_target

        # Only calculate for simple pools (with total_remaining)
        if "total_remaining" not in remaining_target:
            return None

        remaining_weight = remaining_target.get("total_remaining")
        if remaining_weight is None:
            return None

        # Get ALL PENDING contributions from ALL users for this pool
        # This is important because we need to know the true remaining after all pending contributions
        all_pending_contributions = obj.pool_contributions.filter(
            status=RequestStatus.PENDING
        )

        # Get asset contributions from all pending pool contributions
        all_pending_asset_contributions = AssetContribution.objects.filter(
            pool_contributor__in=all_pending_contributions, pool=obj
        )

        # Calculate total weight of ALL pending contributions (from all users)
        all_pending_weight = Decimal("0.00")
        if all_pending_asset_contributions.exists():
            all_pending_weight = get_total_weight_of_all_asset_contributed(
                all_pending_asset_contributions
            )

        # Calculate actual remaining after considering ALL pending contributions
        # This gives the true remaining that can still be contributed
        actual_remaining = remaining_weight - all_pending_weight

        return {"total_remaining": max(actual_remaining, Decimal("0.00"))}


class PoolUpdateSerializer(serializers.ModelSerializer):
    risk_level = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Pool
        fields = [
            "name",
            "material_type",
            "material_item",
            "carat_type",
            "cut_shape",
            "quantity",
            "target",
            "status",
            "expected_return_percentage",
            "actual_return_percentage",
            "return_amount",
            "is_active",
            "minimum_investment_grams_per_participant",
            "logo",
            "authority_information",
            "fund_objective",
            "fund_manager",
            "participation_duration",
            "pool_duration",
            "terms_and_conditions",
            "management_fee_rate",
            "performance_fee_rate",
            # Risk level ID - when provided, will populate risk level fields from OrganizationRiskLevel
            "risk_level",
        ]

    def update(self, instance, validated_data):
        """Update pool instance, handling risk level update from OrganizationRiskLevel if provided."""
        user = self.context["request"].user
        risk_level_id = validated_data.pop("risk_level", None)

        # If risk_level ID is provided, look up OrganizationRiskLevel and populate fields
        if risk_level_id:
            try:
                org_risk_level = OrganizationRiskLevel.objects.get(
                    id=risk_level_id,
                    organization_id=user.organization_id,
                )
                # Copy RiskLevelMixin fields from OrganizationRiskLevel to validated_data
                # (matching the create method pattern)
                validated_data.update(
                    {
                        "risk_level": org_risk_level.risk_level,
                        "equity_min": org_risk_level.equity_min,
                        "equity_max": org_risk_level.equity_max,
                        "penalty_amount": org_risk_level.penalty_amount,
                    }
                )
            except OrganizationRiskLevel.DoesNotExist:
                raise serializers.ValidationError(MESSAGES["risk_level_required"])

        # Update all model fields safely
        for field, value in validated_data.items():
            setattr(instance, field, value)

        instance.save(update_fields=list(validated_data.keys()))
        return instance


class PreciousItemUnitUpdateSerializer(serializers.Serializer):
    id = serializers.CharField(required=True, help_text="PreciousItemUnit id")
    system_serial_number = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional system serial number to set/replace",
    )


class PoolContributionUpdateSerializer(serializers.ModelSerializer):
    precious_item_units = PreciousItemUnitUpdateSerializer(
        many=True, write_only=True, required=False
    )
    asset_contribution = serializers.ListField(
        child=serializers.CharField(), required=False
    )

    class Meta:
        model = PoolContribution
        fields = ["fund_status", "status", "precious_item_units", "asset_contribution"]

    def validate(self, attrs):
        fund_status = attrs.get("fund_status")
        if fund_status:
            return attrs
        instance = getattr(self, "instance", None)
        new_status = attrs.get("status")

        asset_contribution = attrs.get("asset_contribution")
        if instance and new_status:
            current_status = instance.status

            if current_status == Status.APPROVED:
                raise serializers.ValidationError(
                    {"status": MESSAGES["already_approved"]}
                )

            if current_status == Status.REJECTED:
                raise serializers.ValidationError(
                    {"status": MESSAGES["already_rejected"]}
                )

        if new_status == Status.APPROVED:
            precious_item_units_payload = attrs.get("precious_item_units", [])

            if not precious_item_units_payload:
                raise serializers.ValidationError(
                    MESSAGES["precious_item_units_required"]
                )

            # Normalize provided ids and collect system serials
            provided_ids = []
            provided_system_serials = []
            for item in precious_item_units_payload:
                unit_id = item.get("id")
                provided_ids.append(str(unit_id))
                system_serial = item.get("system_serial_number")
                if system_serial is not None and system_serial != "":
                    provided_system_serials.append(str(system_serial))

            # Calculate sum of all contributed asset quantities for this musharakah contract request
            total_contributed_quantity = (
                instance.pool.asset_contributions.filter(
                    id__in=asset_contribution
                ).aggregate(total_quantity=Sum("quantity"))["total_quantity"]
                or 0
            )

            if total_contributed_quantity != len(provided_ids):
                raise serializers.ValidationError(
                    MESSAGES["precious_item_units_count_mismatch"].format(
                        provided_count=len(provided_ids),
                        total_contributed_quantity=total_contributed_quantity,
                    )
                )

            # Validate provided system serial numbers are unique within request
            if provided_system_serials:
                if len(provided_system_serials) != len(set(provided_system_serials)):
                    raise serializers.ValidationError(
                        MESSAGES["system_serial_number_validation"]
                    )

                # Check for existing system_serial_numbers in DB excluding units being updated
                existing_conflicts = (
                    PreciousItemUnit.objects.filter(
                        system_serial_number__in=provided_system_serials
                    )
                    .exclude(id__in=provided_ids)
                    .values_list("system_serial_number", flat=True)
                )

                if existing_conflicts:
                    # Use investor messages for this error text
                    raise serializers.ValidationError(
                        INVESTOR_MESSAGE["system_serial_number_already_exist"].format(
                            system_serial_numbers=", ".join(set(existing_conflicts))
                        )
                    )
            self._provided_precious_item_units = {
                str(item.get("id")): item for item in precious_item_units_payload
            }

        return attrs

    def update(self, instance, validated_data):
        """
        Custom update logic:
        - Auto-set approved_at if status becomes APPROVED
        - Clear approved_at if REJECTED
        - Update other fields
        """
        fund_status = validated_data.get("fund_status")
        new_status = validated_data.get("status", instance.status)
        asset_contribution = validated_data.pop("asset_contribution", None)
        # Automatically set or clear approval timestamp
        if not fund_status:
            if new_status == RequestStatus.ADMIN_APPROVED:
                validated_data["approved_at"] = timezone.now()
            elif new_status == RequestStatus.APPROVED:
                provided_map = getattr(self, "_provided_precious_item_units", {})
                provided_ids = list(provided_map.keys())

                if provided_ids:
                    # Fetch the actual PreciousItemUnit objects ensuring they belong to the investor
                    precious_item_units = PreciousItemUnit.objects.filter(
                        id__in=provided_ids,
                        purchase_request__business=instance.participant,
                    )
                    # Ensure all provided IDs were found and eligible
                    if precious_item_units.count() != len(provided_ids):
                        raise serializers.ValidationError(
                            MESSAGES.get(
                                "precious_item_units_not_found",
                                "Some precious item units were not found or are not eligible.",
                            )
                        )
                    bulk_update_precious_item_units = []
                    for precious_item_unit in precious_item_units:
                        # Associate the unit with the musharakah contract
                        precious_item_unit.pool = instance.pool

                        payload = provided_map.get(str(precious_item_unit.id), {})

                        # If admin supplied a system_serial_number, update it. If not, keep existing.
                        if "system_serial_number" in payload:
                            precious_item_unit.system_serial_number = payload.get(
                                "system_serial_number"
                            )

                        bulk_update_precious_item_units.append(precious_item_unit)

                    if bulk_update_precious_item_units:
                        PreciousItemUnit.objects.bulk_update(
                            bulk_update_precious_item_units,
                            ["pool", "system_serial_number"],
                        )

            elif new_status == Status.REJECTED:
                validated_data["approved_at"] = None

                # Clear pool FK from precious item units that were linked when THIS specific contribution was approved
                # Only clear if the contribution was previously approved (units are only linked to pool when contribution is approved)
                if instance.status in [
                    RequestStatus.APPROVED,
                    RequestStatus.ADMIN_APPROVED,
                ]:
                    # Get asset contributions for THIS specific pool contribution
                    # This ensures we only clear units from THIS contribution, not from other contributions by the same participant
                    asset_contributions = AssetContribution.objects.filter(
                        pool_contributor=instance,
                        pool=instance.pool,
                    )

                    # Get purchase request IDs from these asset contributions
                    purchase_request_ids = asset_contributions.values_list(
                        "purchase_request_id", flat=True
                    ).distinct()

                    # Clear pool FK only from units that:
                    # 1. Belong to purchase requests used in THIS contribution
                    # 2. Belong to this participant
                    # 3. Are linked to this pool
                    #
                    # This ensures:
                    # - Previous approved contributions (e.g., 2kg from contribution #1) remain in the pool
                    # - Only the rejected contribution's units (e.g., 1kg from contribution #2) are freed
                    # - The rejected contribution's weight is not counted in the pool's approved target
                    # - The contributor can contribute again in the future
                    #
                    # Note: If multiple contributions use the same purchase request, this might clear
                    # units from other contributions. In practice, each contribution typically uses
                    # different purchase requests, so this is acceptable. For perfect precision, we would
                    # need to track which specific units belong to which contribution (e.g., via a many-to-many
                    # relationship), but that would require a database migration.
                    if purchase_request_ids:
                        PreciousItemUnit.objects.filter(
                            pool=instance.pool,
                            purchase_request_id__in=purchase_request_ids,
                            purchase_request__business=instance.participant,
                        ).update(pool=None)

            if asset_contribution:
                AssetContribution.objects.filter(id__in=asset_contribution).update(
                    status=new_status
                )

        # Perform update
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance


########################################################################################
########################## Musharakah Contract Request Serializer's ###################
########################################################################################


class MusharakahContractRequestPreApprovalSerializer(serializers.ModelSerializer):
    """Serializer for intermediate approval of musharakah contract request."""

    class Meta:
        model = MusharakahContractRequest
        fields = ["status"]

    def validate(self, attrs):
        musharakah_contract_request = self.instance
        status = attrs.get("status")

        # Validate status is ADMIN_APPROVED
        if status not in [RequestStatus.ADMIN_APPROVED, RequestStatus.REJECTED]:
            raise serializers.ValidationError(
                MESSAGES.get(
                    "invalid_status_for_admin_approval",
                    "Status must be ADMIN_APPROVED or REJECTED for intermediate approval.",
                )
            )

        # Check if already approved or rejected
        if musharakah_contract_request.status == RequestStatus.APPROVED:
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_already_approved"]
            )
        if musharakah_contract_request.status == RequestStatus.REJECTED:
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_already_rejected"]
            )

        # Check if investor is assigned
        if not musharakah_contract_request.investor:
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_investor_not_assigned"]
            )

        return attrs


class MusharakahContractRequestSerializer(
    BaseMusharakahContractRequestResponseSerializer
):
    asset_contributions = serializers.SerializerMethodField()
    precious_item_units = serializers.SerializerMethodField()
    musharakah_contract_termination_request = serializers.SerializerMethodField()

    def get_asset_contributions(self, obj):
        """
        Return asset contributions filtered to exclude invalid quantities.
        When jeweler creates contract initially, there are no asset contributions yet.
        When investor views/creates, only contributions (> 0.01) should be returned.
        """
        from investor.serializers import AssetContributionResponseSerializer

        # Filter out asset contributions with quantity <= 0 or None
        # This handles cases where contract is created but investor hasn't contributed yet,
        # or where contributions exist in the database
        contributions = obj.asset_contributions.filter(quantity__gt=Decimal("0.00"))

        if not contributions.exists():
            return []

        return AssetContributionResponseSerializer(contributions, many=True).data

    def get_precious_item_units(self, obj):
        """
        Return available precious item units that are linked to this musharakah contract.
        Only returns units with remaining_weight > 0 (not fully used).

        Includes only units that are actually linked to this contract:
        - Units directly linked via FK (musharakah_contract=obj)
        - Units linked via PreciousItemUnitMusharakahHistory for this contract

        Does NOT include units from purchase requests that are not linked to this contract.
        """
        from seller.serializers import PreciousItemUnitResponseSerializer
        from sooq_althahab.enums.jeweler import MusharakahContractStatus

        # 2. Get purchase requests from asset contributions for this contract
        purchase_request_ids = list(
            obj.asset_contributions.values_list(
                "purchase_request_id", flat=True
            ).distinct()
        )

        if not purchase_request_ids:
            return []

        # 3. Get units from those purchase requests that are:
        #    - Linked to this contract (via FK or history)
        #    - Not sold (sale_request is null)
        #    - Not in pools
        #    - Not in other active musharakah contracts (via FK or history)
        #    - Have remaining_weight > 0
        #    Note: A unit should only have ONE relationship: sale_request, musharakah_contract, or pool
        from investor.models import PreciousItemUnitMusharakahHistory

        # Get units linked to THIS contract (via FK or history) - these should NOT be excluded
        # We need to know which units belong to THIS contract before we exclude others
        history_linked_unit_ids_for_this = list(
            PreciousItemUnitMusharakahHistory.objects.filter(musharakah_contract=obj)
            .values_list("precious_item_unit_id", flat=True)
            .distinct()
        )

        fk_linked_unit_ids_for_this = list(
            PreciousItemUnit.objects.filter(musharakah_contract=obj).values_list(
                "id", flat=True
            )
        )

        # Units that belong to THIS contract (should NOT be excluded)
        this_contract_unit_ids = set(history_linked_unit_ids_for_this) | set(
            fk_linked_unit_ids_for_this
        )

        # Exclude units in OTHER active musharakah contracts (not THIS contract)
        # BUT only exclude if they're NOT also linked to THIS contract
        active_contract_ids = list(
            PreciousItemUnitMusharakahHistory.objects.filter(
                musharakah_contract__musharakah_contract_status__in=[
                    MusharakahContractStatus.ACTIVE,
                    MusharakahContractStatus.RENEW,
                    MusharakahContractStatus.UNDER_TERMINATION,
                ]
            )
            .exclude(musharakah_contract=obj)
            .values_list("precious_item_unit_id", flat=True)
            .distinct()
        )

        # Remove units that belong to THIS contract from the exclusion list
        active_contract_ids = [
            uid for uid in active_contract_ids if uid not in this_contract_unit_ids
        ]

        # Also exclude units in OTHER active contracts via FK (but include units for THIS contract)
        active_fk_unit_ids = list(
            PreciousItemUnit.objects.filter(
                musharakah_contract__isnull=False,
                musharakah_contract__musharakah_contract_status__in=[
                    MusharakahContractStatus.ACTIVE,
                    MusharakahContractStatus.RENEW,
                    MusharakahContractStatus.UNDER_TERMINATION,
                ],
            )
            .exclude(musharakah_contract=obj)
            .values_list("id", flat=True)
        )

        # Remove units that belong to THIS contract from the exclusion list
        active_fk_unit_ids = [
            uid for uid in active_fk_unit_ids if uid not in this_contract_unit_ids
        ]

        # Combine excluded unit IDs (exclude units in OTHER contracts, but include THIS contract's units)
        # Note: We don't exclude units in production allocations here because they might still have remaining weight
        # The remaining_weight check later will filter out fully used units
        all_excluded_ids = set(active_contract_ids) | set(active_fk_unit_ids)

        # 4. Get units that are actually linked to THIS musharakah contract
        # Units can be linked via:
        # - Direct FK: musharakah_contract=obj
        # - History: PreciousItemUnitMusharakahHistory entries for this contract

        # Use the already fetched IDs (no need to query again)
        history_linked_unit_ids = history_linked_unit_ids_for_this

        # Build the query condition for linked units
        # Include units directly linked via FK OR linked via history
        if history_linked_unit_ids:
            linked_condition = Q(musharakah_contract=obj) | Q(
                id__in=history_linked_unit_ids
            )
        else:
            # If no history entries, only check FK link
            linked_condition = Q(musharakah_contract=obj)

        # Get units linked to THIS contract (via FK or history)
        # Only show units that are actually contributed/linked to this contract
        # A unit should only have ONE relationship: sale_request, musharakah_contract, or pool
        # So we exclude units that are sold (sale_request is set) or in a pool
        source_units = (
            PreciousItemUnit.objects.filter(
                purchase_request_id__in=purchase_request_ids,
                sale_request__isnull=True,  # Not sold
                pool__isnull=True,  # Not in pool
            )
            .filter(linked_condition)
            .exclude(id__in=all_excluded_ids)
            .distinct()
        )

        # 5. Filter to only include units with remaining weight > 0
        # This ensures we don't show fully used units (remaining_weight = 0)
        available_units = []
        for unit in source_units:
            remaining = unit.remaining_weight or Decimal("0.00")
            if remaining > Decimal("0.00"):
                available_units.append(unit)

        return PreciousItemUnitResponseSerializer(available_units, many=True).data

    def get_musharakah_contract_termination_request(self, obj):
        """Return the first pending termination request (single object, not list)."""

        pending_request = obj.musharakah_contract_termination_requests.filter(
            status__in=[RequestStatus.PENDING, RequestStatus.APPROVED]
        ).first()

        if not pending_request:
            return None

        return BaseMusharakahContractTerminationRequestDetailSerializer(
            pending_request
        ).data


class MusharakahContractRequestStatusUpdateSerializer(serializers.ModelSerializer):
    precious_item_units = PreciousItemUnitUpdateSerializer(
        many=True, write_only=True, required=True
    )

    class Meta:
        model = MusharakahContractRequest
        fields = [
            "status",
            "storage_box_number",
            "precious_item_units",
        ]

    def validate(self, attrs):
        if attrs.get("status") == RequestStatus.REJECTED:
            return attrs
        musharakah_contract_request = self.instance
        storage_box_number = attrs.get("storage_box_number")
        precious_item_units_payload = attrs.get("precious_item_units", [])

        if not storage_box_number:
            raise serializers.ValidationError(MESSAGES["storage_box_number_required"])

        if not precious_item_units_payload:
            raise serializers.ValidationError(MESSAGES["precious_item_units_required"])

        # Normalize provided ids and collect system serials
        provided_ids = []
        provided_system_serials = []
        for item in precious_item_units_payload:
            unit_id = item.get("id")
            provided_ids.append(str(unit_id))
            system_serial = item.get("system_serial_number")
            if system_serial is not None and system_serial != "":
                provided_system_serials.append(str(system_serial))

        # Calculate sum of all contributed asset quantities for this musharakah contract request
        total_contributed_quantity = (
            musharakah_contract_request.asset_contributions.aggregate(
                total_quantity=Sum("quantity")
            )["total_quantity"]
            or 0
        )

        if total_contributed_quantity != len(provided_ids):
            raise serializers.ValidationError(
                MESSAGES["precious_item_units_count_mismatch"].format(
                    provided_count=len(provided_ids),
                    total_contributed_quantity=total_contributed_quantity,
                )
            )

        # Validate provided system serial numbers are unique within request
        if provided_system_serials:
            if len(provided_system_serials) != len(set(provided_system_serials)):
                raise serializers.ValidationError(
                    MESSAGES["system_serial_number_validation"]
                )

            # Check for existing system_serial_numbers in DB excluding units being updated
            existing_conflicts = (
                PreciousItemUnit.objects.filter(
                    system_serial_number__in=provided_system_serials
                )
                .exclude(id__in=provided_ids)
                .values_list("system_serial_number", flat=True)
            )

            if existing_conflicts:
                # Use investor messages for this error text
                raise serializers.ValidationError(
                    INVESTOR_MESSAGE["system_serial_number_already_exist"].format(
                        system_serial_numbers=", ".join(set(existing_conflicts))
                    )
                )

        if musharakah_contract_request.status == RequestStatus.APPROVED:
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_already_approved"]
            )
        if musharakah_contract_request.status == RequestStatus.REJECTED:
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_already_rejected"]
            )
        if musharakah_contract_request.status != RequestStatus.ADMIN_APPROVED:
            raise serializers.ValidationError(
                MESSAGES.get(
                    "musharakah_contract_request_not_admin_approved",
                    "Musharakah contract request must be admin-approved before final approval.",
                )
            )
        if not musharakah_contract_request.investor:
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_investor_not_assigned"]
            )

        self._provided_precious_item_units = {
            str(item.get("id")): item for item in precious_item_units_payload
        }

        return attrs

    def save(self, **kwargs):
        # Remove non-model fields before saving
        self.validated_data.pop("precious_item_units", None)
        instance = super().save(**kwargs)

        status = self.validated_data.get("status")
        organization = self.context.get("request").user.organization_id

        default_currency = OrganizationCurrency.objects.filter(
            organization=organization,
            is_default=True,
        ).first()

        # -----------------------------------------------------------
        # 1. HANDLE APPROVAL (CREATE HISTORY, NOT FK UPDATE)
        # -----------------------------------------------------------
        if status == RequestStatus.APPROVED:
            with transaction.atomic():
                instance.approved_at = timezone.now()
                instance.save(update_fields=["approved_at"])

                provided_map = getattr(self, "_provided_precious_item_units", {})
                provided_ids = list(provided_map.keys())

                if provided_ids:
                    # Fetch units belonging to this investor
                    precious_item_units = PreciousItemUnit.objects.filter(
                        id__in=provided_ids,
                        purchase_request__business=instance.investor,
                    )

                    # Verify all units exist and allowed
                    if precious_item_units.count() != len(provided_ids):
                        raise serializers.ValidationError(
                            MESSAGES.get(
                                "precious_item_units_not_found",
                                "Some precious item units were not found or are not eligible.",
                            )
                        )

                    # Bulk update list for system_serial_number and musharakah_contract
                    bulk_update_units = []

                    for unit in precious_item_units:
                        payload = provided_map.get(str(unit.id), {})

                        # Update system_serial_number if provided
                        if "system_serial_number" in payload:
                            unit.system_serial_number = payload.get(
                                "system_serial_number"
                            )

                        # Set musharakah_contract FK to track allocation
                        unit.musharakah_contract = instance
                        bulk_update_units.append(unit)

                        # Create HISTORY ENTRY for tracking weight contributions
                        PreciousItemUnitMusharakahHistory.objects.create(
                            precious_item_unit=unit,
                            musharakah_contract=instance,
                            contributed_weight=unit.remaining_weight,
                        )

                    # Bulk update units for system_serial_number and musharakah_contract
                    if bulk_update_units:
                        PreciousItemUnit.objects.bulk_update(
                            bulk_update_units,
                            ["system_serial_number", "musharakah_contract"],
                        )

        contributions = AssetContribution.objects.filter(
            musharakah_contract_request=instance,
            business=instance.investor,
            contribution_type=ContributionType.MUSHARAKAH,
        ).select_related(
            "purchase_request__precious_item__material_item__global_metal",
            "purchase_request__precious_item__carat_type",
            "purchase_request__precious_item__precious_metal",
        )

        bulk_update_assets = []

        for asset in contributions:
            asset.status = status
            precious_item = asset.purchase_request.precious_item

            # Stones → lock order_cost
            if precious_item.material_type == MaterialType.STONE:
                asset.price_locked = round(asset.purchase_request.order_cost, 4)
            else:
                # Metals → dynamic metal price calculation
                asset.price_locked = round(
                    self._calculate_metal_price(asset, default_currency), 4
                )

            bulk_update_assets.append(asset)

        if bulk_update_assets:
            AssetContribution.objects.bulk_update(
                bulk_update_assets, ["status", "price_locked"]
            )

        return instance

    def _calculate_metal_price(self, asset, currency_obj):
        """Fetch real-time price for contributed metals and compute total value."""
        try:
            if not currency_obj:
                return Decimal(0)

            symbol = (
                asset.purchase_request.precious_item.material_item.global_metal.symbol
            )
            carat_type = asset.purchase_request.precious_item.carat_type
            weight = asset.purchase_request.precious_item.precious_metal.weight
            session = requests.Session()
            headers = {
                "x-access-token": settings.GOLD_API_ACCESS_KEY,
                "Content-Type": "application/json",
            }
            base_url = settings.GOLD_API_BASE_URL
            currency = settings.CURRENCY

            response = session.get(f"{base_url}/{symbol}/{currency}", headers=headers)
            response_data = response.json()

            price_per_gram = Decimal(
                str(response_data.get(f"price_gram_{carat_type.name}", 0))
            )
            exchange_rate = Decimal(str(currency_obj.rate))
            total_metal_price = price_per_gram * exchange_rate * weight * asset.quantity

            return total_metal_price
        except:
            raise serializers.ValidationError(INVESTOR_MESSAGE["something_wrong"])


class MusharakahContractRequestTerminationUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MusharakahContractRequest
        fields = ["termination_reason", "impacted_party"]

    def validate(self, attrs):
        impacted_party = attrs.get("impacted_party")
        termination_request = MusharakahContractTerminationRequest.objects.filter(
            musharakah_contract_request=self.instance, status=RequestStatus.PENDING
        )

        if termination_request:
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_termination_request_already_exists"]
            )

        if self.instance.status != RequestStatus.APPROVED:
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_must_be_approved"]
            )

        if (
            self.instance.musharakah_contract_status
            == MusharakahContractStatus.TERMINATED
        ):
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_already_terminated"]
            )

        if self.instance.musharakah_contract_status != MusharakahContractStatus.ACTIVE:
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_inactive"]
            )

        if not impacted_party:
            raise serializers.ValidationError(MESSAGES["impacted_party_required"])

        return attrs

    def update(self, instance, validated_data):
        """Terminate the Musharakah contract request."""

        impacted_party = validated_data.get("impacted_party")

        # Update Musharakah contract status and termination details
        instance.musharakah_contract_status = MusharakahContractStatus.TERMINATED
        instance.termination_reason = validated_data.get("termination_reason")
        instance.terminated_by = ContractTerminator.ADMIN
        instance.impacted_party = impacted_party
        instance.save()

        # Clear musharakah_contract FK only for units with remaining weight (returned units)
        # This includes:
        # - Fully unused units (remaining_weight = full weight)
        # - Partially used units (remaining_weight > 0 but < full weight)
        # Units that are fully used (remaining_weight = 0) should keep the FK to maintain allocation history
        with transaction.atomic():
            # Get all units allocated to this contract
            allocated_units = PreciousItemUnit.objects.filter(
                musharakah_contract=instance
            )

            # Clear FK only for units that have remaining weight (are being returned)
            # This handles both:
            # - Fully unused units: remaining_weight = full weight (e.g., 10g for 10g unit)
            # - Partially used units: remaining_weight > 0 but < full weight (e.g., 5g remaining from 10g unit)
            # Fully used units (remaining_weight = 0) keep the FK to show they were allocated
            units_to_clear = []
            for unit in allocated_units:
                remaining = unit.remaining_weight or Decimal("0.00")
                # If unit has any remaining weight/quantity, clear the FK (it's being returned)
                # Partially used units will still be excluded from sale due to payment_allocations filter
                # but they'll be available for other operations (like new musharakah contributions)
                if remaining > Decimal("0.00"):
                    unit.musharakah_contract = None
                    units_to_clear.append(unit)

            # Bulk update to clear FK for returned units (both fully and partially returned)
            if units_to_clear:
                PreciousItemUnit.objects.bulk_update(
                    units_to_clear, ["musharakah_contract"]
                )

        # Determine which business account (Investor/Jeweler) is impacted
        if impacted_party == ImpactedParties.INVESTOR:
            business = instance.investor
        else:
            business = instance.jeweler

        # Suspend the impacted business account and log the remark
        business.is_suspended = True
        business.remark = "Your business account has been suspended due to the termination of the Musharakah Contract by the Sooq Al Thahab."
        business.save()

        return instance


class MusharakahContractRequestFromTerminatedCreateSerializer(
    serializers.ModelSerializer
):
    """Serializer for creating a new musharakah contract request from a terminated contract."""

    class Meta:
        model = MusharakahContractRequest
        fields = ["terminated_musharakah_contract"]

    def validate(self, attrs):
        terminated_musharakah_contract = attrs.get("terminated_musharakah_contract")

        musharakah_contract_request = (
            MusharakahContractTerminationRequest.objects.filter(
                musharakah_contract_request=terminated_musharakah_contract,
                status=RequestStatus.PENDING,
                termination_request_by=ContractTerminator.INVESTOR,
            ).exists()
        )

        if not musharakah_contract_request:
            raise serializers.ValidationError(
                MESSAGES["no_pending_termination_request_found"]
            )

        return attrs

    def create(self, validated_data):
        """Create a new musharakah contract request by copying details from terminated contract."""
        terminated_musharakah_contract = validated_data.pop(
            "terminated_musharakah_contract", {}
        )

        # Create new contract with same details but investor set to None
        musharakah_contract_request = MusharakahContractRequest.objects.create(
            jeweler=terminated_musharakah_contract.jeweler,
            investor=None,  # Set investor to None as requested
            target=terminated_musharakah_contract.target,
            musharakah_equity=terminated_musharakah_contract.musharakah_equity,
            design_type=terminated_musharakah_contract.design_type,
            duration_in_days=terminated_musharakah_contract.duration_in_days,
            description=terminated_musharakah_contract.description,
            jeweler_signature=terminated_musharakah_contract.jeweler_signature,
            terminated_musharakah_contract=terminated_musharakah_contract,
            status=RequestStatus.PENDING,
            musharakah_contract_status=MusharakahContractStatus.NOT_ASSIGNED,
            organization_id=terminated_musharakah_contract.organization_id,
            created_by=terminated_musharakah_contract.created_by,
            risk_level=terminated_musharakah_contract.risk_level,
            equity_min=terminated_musharakah_contract.equity_min,
            equity_max=terminated_musharakah_contract.equity_max,
            penalty_amount=terminated_musharakah_contract.penalty_amount,
        )

        designs = terminated_musharakah_contract.musharakah_contract_designs.all()

        MusharakahContractDesign.objects.bulk_create(
            [
                MusharakahContractDesign(
                    design=design.design if hasattr(design, "design") else design,
                    musharakah_contract_request=musharakah_contract_request,
                )
                for design in designs
            ]
        )

        # Copy related quantities
        for (
            quantity
        ) in (
            terminated_musharakah_contract.musharakah_contract_request_quantities.all()
        ):
            musharakah_contract_request.musharakah_contract_request_quantities.create(
                jewelry_product=quantity.jewelry_product, quantity=quantity.quantity
            )

        # Copy related attachments
        for (
            attachment
        ) in (
            terminated_musharakah_contract.musharakah_contract_request_attachments.all()
        ):
            musharakah_contract_request.musharakah_contract_request_attachments.create(
                image=attachment.image
            )

        return musharakah_contract_request


class MusharakahContractTerminationRequestUpdateStatusSerializer(
    serializers.ModelSerializer
):
    class Meta:
        model = MusharakahContractTerminationRequest
        fields = [
            "status",
            "logistics_cost",
            "insurance_fee",
            "logistics_cost_payable_by",
            "refining_cost",
            "refine_sell_payment_option",
            "cost_retail_payment_option",
            "retail_price",
            "manufacturing_cost",
            "sell_cost",
        ]

    def validate(self, attrs):
        """Ensure the termination request is in a valid state to be updated."""

        # Check instance status
        if self.instance.status != RequestStatus.PENDING:
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_already_handled"]
            )

        if (
            self.instance.musharakah_contract_request.musharakah_contract_status
            == MusharakahContractStatus.TERMINATED
        ):
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_already_terminated"]
            )

        provided_fields = set(attrs.keys())

        # Rule 1: only one of status or payment_option can be updated at a time
        if (
            "status" in provided_fields
            or "refine_sell_payment_option" in provided_fields
        ):
            forbidden_fields = {
                "logistics_cost",
                "insurance_fee",
            } & provided_fields
            if (
                len(provided_fields & {"status", "payment_option"}) > 1
                or forbidden_fields
            ):
                raise serializers.ValidationError(
                    "When updating 'status' or 'payment_option', no other fields are allowed."
                )

        return attrs

    def update(self, instance, validated_data):
        """Update the status and terminate the Musharakah contract if approved."""
        with transaction.atomic():
            instance.status = validated_data.get("status", instance.status)
            logistics_cost = validated_data.get("logistics_cost")
            insurance_fee = validated_data.get("insurance_fee")

            refine_sell_payment_option = validated_data.get(
                "refine_sell_payment_option", None
            )
            retail_price = validated_data.get("retail_price", None)
            manufacturing_cost = validated_data.get("manufacturing_cost", None)
            cost_retail_payment_option = validated_data.get(
                "cost_retail_payment_option", None
            )

            logistics_cost_payable_by = validated_data.get(
                "logistics_cost_payable_by", None
            )
            refining_cost = validated_data.get("refining_cost", None)
            sell_cost = validated_data.get("sell_cost", None)
            request = self.context.get("request")
            user = request.user
            musharakah_contract = instance.musharakah_contract_request
            # Case 1: If termination request is approved → Terminate the Musharakah contract
            if instance.status == RequestStatus.APPROVED:
                musharakah_contract.musharakah_contract_status = (
                    MusharakahContractStatus.TERMINATED
                )
                musharakah_contract.terminated_by = instance.termination_request_by
                musharakah_contract.updated_by = user
                musharakah_contract.save()

                JewelryProduction.objects.filter(
                    payment__musharakah_contract=musharakah_contract
                ).update(ownership=Ownership.INVESTOR)
                self.create_purchase_request_of_manufactured_jewelry(
                    musharakah_contract, musharakah_contract.investor, user
                )

            if instance.status == RequestStatus.PENDING:
                # If Jeweler Early Termination then Logistics & insurance cost must be provided
                if logistics_cost and insurance_fee:
                    instance.logistics_cost = logistics_cost
                    instance.insurance_fee = insurance_fee
                    instance.logistics_cost_payable_by = logistics_cost_payable_by
                    if logistics_cost_payable_by == ContractTerminator.INVESTOR:
                        musharakah_contract_termination_payment_type = (
                            MusharakahContractTerminationPaymentType.INVESTOR_LOGISTIC_FEE_PAYMENT_TRANSACTION
                        )
                        self.create_transaction(
                            user,
                            musharakah_contract.investor,
                            musharakah_contract,
                            musharakah_contract_termination_payment_type,
                            logistics_cost,
                        )
                        musharakah_contract_termination_payment_type = (
                            MusharakahContractTerminationPaymentType.JEWELER_SETTLEMENT_PAYMENT_TRANSACTION
                        )
                        self.create_transaction(
                            user,
                            musharakah_contract.jeweler,
                            musharakah_contract,
                            musharakah_contract_termination_payment_type,
                            insurance_fee,
                        )
                    else:
                        amount = logistics_cost + insurance_fee
                        musharakah_contract_termination_payment_type = (
                            MusharakahContractTerminationPaymentType.JEWELER_SETTLEMENT_PAYMENT_TRANSACTION
                        )
                        self.create_transaction(
                            user,
                            musharakah_contract.jeweler,
                            musharakah_contract,
                            musharakah_contract_termination_payment_type,
                            amount,
                        )

                #  If Investor Early Termination Cost or retail price payment option
                elif cost_retail_payment_option:
                    instance.cost_retail_payment_option = cost_retail_payment_option
                    if cost_retail_payment_option == CostRetailPaymentOption.PAY_COST:
                        instance.manufacturing_cost = manufacturing_cost
                        amount = max(
                            musharakah_contract.penalty_amount, manufacturing_cost
                        )
                    else:
                        instance.retail_price = retail_price
                        amount = max(musharakah_contract.penalty_amount, retail_price)
                    musharakah_contract_termination_payment_type = (
                        MusharakahContractTerminationPaymentType.INVESTOR_EARLY_TERMINATION_PAYMENT_TRANSACTION
                    )
                    self.create_transaction(
                        user,
                        musharakah_contract.investor,
                        musharakah_contract,
                        musharakah_contract_termination_payment_type,
                        amount,
                    )

                # If Refine payment & Sell by admin option
                elif refine_sell_payment_option:
                    instance.refine_sell_payment_option = refine_sell_payment_option
                    if refine_sell_payment_option == RefineSellPaymentOption.REFINE:
                        instance.refining_cost = refining_cost
                        musharakah_contract_termination_payment_type = (
                            MusharakahContractTerminationPaymentType.INVESTOR_REFINING_COST_PAYMENT_TRANSACTION
                        )
                        self.create_transaction(
                            user,
                            musharakah_contract.investor,
                            musharakah_contract,
                            musharakah_contract_termination_payment_type,
                            refining_cost,
                        )
                    else:
                        instance.sell_cost = sell_cost
                        instance.status = RequestStatus.APPROVED
                        musharakah_contract.musharakah_contract_status = (
                            MusharakahContractStatus.TERMINATED
                        )

            if instance.status == RequestStatus.REJECTED:
                musharakah_contract.musharakah_contract_status = (
                    MusharakahContractStatus.ACTIVE
                )

            musharakah_contract.save()
            instance.save()
            return instance

    def create_transaction(
        self,
        user,
        business,
        musharakah_contract,
        musharakah_contract_termination_payment_type,
        amount,
    ):
        organization = user.organization_id
        vat = organization.vat_rate * amount
        platform_fee = calculate_platform_fee(amount, organization)
        total_amount = vat + platform_fee + amount
        Transaction.objects.create(
            from_business=business,
            to_business=business,
            musharakah_contract=musharakah_contract,
            amount=total_amount,
            vat=vat,
            platform_fee=platform_fee,
            platform_fee_rate=organization.platform_fee_rate,
            vat_rate=organization.vat_rate,
            transaction_type=TransactionType.PAYMENT,
            status=TransactionStatus.PENDING,
            created_by=user,
            musharakah_contract_termination_payment_type=musharakah_contract_termination_payment_type,
        )

    def create_purchase_request_of_manufactured_jewelry(
        self, musharakah_contract, business, user
    ):
        # Step 1: get all relevant productions
        jewelry_productions = JewelryProduction.objects.filter(
            payment__musharakah_contract=musharakah_contract
        )

        # Step 2: extract manufacturing request IDs
        manufacturing_request_ids = jewelry_productions.values_list(
            "manufacturing_request_id", flat=True
        )

        # Step 3: fetch all requested quantities for those manufacturing requests
        requested_product_quantities = (
            ManufacturingProductRequestedQuantity.objects.filter(
                manufacturing_request_id__in=manufacturing_request_ids
            ).select_related("jewelry_product")
        )

        # Step 4: prepare all PurchaseRequest instances (but don't save yet)
        purchase_requests = []
        for product in requested_product_quantities:
            total_cost = (
                product.jewelry_product.price + product.jewelry_product.premium_price
            )
            purchase_requests.append(
                PurchaseRequest(
                    status=PurchaseRequestStatus.APPROVED,
                    created_by=user,
                    request_type=RequestType.JEWELRY_DESIGN,
                    premium=product.jewelry_product.premium_price,
                    total_cost=total_cost,
                    requested_quantity=product.quantity,
                    jewelry_product=product.jewelry_product,
                    business=business,
                    organization_id=user.organization_id,
                    order_cost=product.jewelry_product.price,
                )
            )

        # Step 5: bulk create all at once (single DB hit)
        PurchaseRequest.objects.bulk_create(purchase_requests)


class MusharakahContractTerminationPaymentTransactionsSerializer(
    serializers.ModelSerializer
):
    class Meta:
        model = Transaction
        fields = [
            "id",
            "from_business",
            "amount",
            "vat",
            "status",
            "created_at",
            "platform_fee",
            "musharakah_contract_termination_payment_type",
            "musharakah_contract",
            "vat_rate",
            "platform_fee_rate",
        ]


class MusharakahContractTerminationRequestResponseSerializer(
    serializers.ModelSerializer
):
    musharakah_contract_request = BaseMusharakahContractRequestResponseSerializer()
    new_musharakah_contract_request_created_at = serializers.SerializerMethodField()
    unsold_jewelry_count = serializers.SerializerMethodField()
    musharakah_contract_termination_transactions = serializers.SerializerMethodField()

    class Meta:
        model = MusharakahContractTerminationRequest
        exclude = ["updated_at"]

    def get_new_musharakah_contract_request_created_at(self, obj):
        """
        Return created_at of the MusharakahContractRequest that was created
        as a replacement for the terminated one.
        """
        terminated_contract = obj.musharakah_contract_request

        # Get the new contract(s) created referencing this terminated one
        new_musharakah_contract_request = (
            MusharakahContractRequest.objects.filter(
                terminated_musharakah_contract=terminated_contract
            )
            .order_by("created_at")  # in case multiple exist
            .first()
        )

        return (
            new_musharakah_contract_request.created_at
            if new_musharakah_contract_request
            else None
        )

    def get_unsold_jewelry_count(self, obj):
        payments = ProductionPayment.objects.filter(
            musharakah_contract=obj.musharakah_contract_request
        )

        total_unsold_jewelry_count = 0
        for payment in payments:
            production = payment.jewelry_production

            total_product = (
                ManufacturingProductRequestedQuantity.objects.filter(
                    manufacturing_request=production.manufacturing_request
                )
                .select_related("jewelry_product")
                .aggregate(
                    total_quantity=Sum("quantity"),
                )
            )
            total_unsold_jewelry_count += total_product.get("total_quantity") or 0

        return total_unsold_jewelry_count

    def get_musharakah_contract_termination_transactions(self, obj):
        transaction = Transaction.objects.filter(
            musharakah_contract=obj.musharakah_contract_request
        )
        return MusharakahContractTerminationPaymentTransactionsSerializer(
            transaction, many=True
        ).data


class MusharakahContractRenewalSerializer(serializers.ModelSerializer):
    class Meta:
        model = MusharakahContractRenewal
        fields = [
            "id",
            "musharakah_contract_request",
            "duration_in_days",
            "reason",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        musharakah_contract_request = attrs.get("musharakah_contract_request")
        if musharakah_contract_request.status != RequestStatus.APPROVED:
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_not_approved"]
            )

        if musharakah_contract_request.musharakah_contract_status not in [
            MusharakahContractStatus.ACTIVE,
            MusharakahContractStatus.RENEW,
        ]:
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_not_active"]
            )
        return attrs

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        musharakah_contract_request = validated_data.get("musharakah_contract_request")
        musharakah_contract_request.musharakah_contract_status = (
            MusharakahContractStatus.RENEW
        )
        musharakah_contract_request.save()
        return MusharakahContractRenewal.objects.create(**validated_data)


########################################################################################
############################### Subscription Serializer's #############################
########################################################################################


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        exclude = [
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
            "deleted_at",
            "restored_at",
            "transaction_id",
            "organization_id",
        ]

    def validate(self, data):
        if data.get("pro_rata_rate") and not data.get("role") == "INVESTOR":
            raise serializers.ValidationError(
                {"pro_rata_rate": "Pro rata rate only allowed for investor roles."}
            )

        # Validate that billing_frequency and payment_interval are consistent
        billing_frequency = data.get("billing_frequency")
        payment_interval = data.get("payment_interval")

        # Warn if billing_frequency is MONTHLY but payment_interval is YEARLY
        # This is allowed but may cause confusion - document it
        if billing_frequency == "MONTHLY" and payment_interval == "YEARLY":
            # This is allowed but should be used carefully
            # billing_frequency controls RECURRING billing after initial period
            # payment_interval defines the initial payment term
            pass

        return data


class BusinessSavedCardTokenDetailSerializer(serializers.ModelSerializer):
    """Serializer for business saved card token details."""

    class Meta:
        model = BusinessSavedCardToken
        fields = ["number", "expiry_month", "expiry_year", "card_type", "card_brand"]


class BusinessSubscriptionPlanSerializer(serializers.ModelSerializer):
    subscription_plan = SubscriptionPlanSerializer(read_only=True)
    pending_subscription_plan = SubscriptionPlanSerializer(read_only=True)
    payment_card = serializers.SerializerMethodField()

    class Meta:
        model = BusinessSubscriptionPlan
        exclude = [
            "updated_by",
            "created_at",
            "updated_at",
            "deleted_at",
            "restored_at",
            "transaction_id",
            "business_saved_card_token",
        ]

    def get_payment_card(self, obj):
        """Get transaction attachments with presigned URLs."""

        return BusinessSavedCardTokenDetailSerializer(
            obj.business_saved_card_token
        ).data


class BusinessBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessAccount
        fields = ["id", "name"]


class BillingDetailsSerializer(serializers.ModelSerializer):
    business = BusinessBasicSerializer(read_only=True)

    class Meta:
        model = BillingDetails
        fields = [
            "id",
            "business",
            "period_start_date",
            "period_end_date",
            "base_amount",
            "commission_fee",
            "service_fee",
            "vat_amount",
            "tax_amount",
            "payment_status",
            "notes",
            "invoice_number",
        ]


########################################################################################
############################ Jewelry Inspector Serializer's ###########################
########################################################################################


class JewelryProductionInspectionStatusUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = JewelryProduction
        fields = ["id", "admin_inspection_status", "manufacturing_request"]
        read_only_fields = ["id", "manufacturing_request"]

    def validate(self, attrs):
        instance = self.instance
        current_production_status = instance.admin_inspection_status
        new_production_status = attrs.get("admin_inspection_status")

        allowed_transitions = {
            InspectionStatus.PENDING: [
                InspectionStatus.IN_PROGRESS,
                InspectionStatus.ADMIN_APPROVAL,
            ],
            InspectionStatus.IN_PROGRESS: [InspectionStatus.COMPLETED],
            InspectionStatus.COMPLETED: [],
            InspectionStatus.ADMIN_APPROVAL: [],
        }

        # Validate production_status transition.
        if new_production_status and new_production_status != current_production_status:
            allowed_next_status = allowed_transitions.get(current_production_status, [])

            if new_production_status not in allowed_next_status:
                raise serializers.ValidationError(
                    MESSAGES[
                        "jewelry_production_inspection_invalid_status_change"
                    ].format(
                        current=current_production_status.replace("_", " ").title(),
                        new=new_production_status.replace("_", " ").title(),
                    )
                )

        return attrs

    def update(self, instance, validated_data):
        request = self.context.get("request")
        admin_inspection_status = validated_data.get("admin_inspection_status")
        instance.admin_inspection_status = admin_inspection_status
        current_time = timezone.now()

        if admin_inspection_status == InspectionStatus.IN_PROGRESS:
            instance.admin_inspected_at = current_time

        if admin_inspection_status == InspectionStatus.COMPLETED:
            instance.admin_approved_at = current_time
            instance.is_inspected = True

        if admin_inspection_status == InspectionStatus.ADMIN_APPROVAL:
            instance.admin_approved_at = current_time
            instance.is_inspected = True
            instance.admin_inspected_at = current_time
            manufacturing_request = instance.manufacturing_request

            # Update all related records for same manufacturing request
            with transaction.atomic():
                ManufacturingProductRequestedQuantity.objects.filter(
                    manufacturing_request=manufacturing_request
                ).update(
                    admin_inspection_status=RequestStatus.APPROVED,
                )

        instance.inspected_by = request.user
        instance.save()
        return instance


class JewelryProductionProductInspectionStatusUpdateSerializer(
    serializers.ModelSerializer
):
    reason = serializers.CharField(write_only=True, required=False)
    attachments = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False
    )

    class Meta:
        model = ManufacturingProductRequestedQuantity
        fields = ["id", "admin_inspection_status", "reason", "attachments"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        if self.instance.admin_inspection_status != RequestStatus.PENDING:
            raise serializers.ValidationError(
                MESSAGES["jewelry_product_inspection_status_must_be_pending"]
            )
        return attrs

    def update(self, instance, validated_data):
        reason = validated_data.pop("reason", None)
        attachments = validated_data.pop("attachments", [])
        admin_inspection_status = validated_data.get("admin_inspection_status")

        instance = super().update(instance, validated_data)

        if admin_inspection_status == RequestStatus.REJECTED and reason:
            inspected_rejected_product = InspectedRejectedJewelryProduct.objects.create(
                manufacturing_product=instance,
                rejected_by=InspectionRejectedByChoices.JEWELLERY_INSPECTOR,
                reason=reason,
            )

            InspectionRejectionAttachment.objects.bulk_create(
                [
                    InspectionRejectionAttachment(
                        inspected_rejected_product=inspected_rejected_product,
                        file=file,
                        created_by=self.context["request"].user,
                    )
                    for file in attachments
                ]
            )
        return instance


class JewelryProductionDeliveryStatusUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = JewelryProduction
        fields = ["id", "delivery_status"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        instance = self.instance
        current_delivery_status = instance.delivery_status
        new_delivery_status = attrs.get("delivery_status")

        if not instance.is_payment_completed:
            raise serializers.ValidationError(
                MESSAGES["jewelry_production_payment_not_completed"]
            )

        if new_delivery_status == current_delivery_status:
            raise serializers.ValidationError(
                MESSAGES["jewelry_products_same_delivery_status"].format(
                    status=new_delivery_status.replace("_", " ").title()
                )
            )

        allowed_transitions = {
            DeliveryStatus.PENDING: [DeliveryStatus.OUT_FOR_DELIVERY],
            DeliveryStatus.OUT_FOR_DELIVERY: [DeliveryStatus.DELIVERED],
            DeliveryStatus.DELIVERED: [],
        }

        # Validate production_status transition.
        if new_delivery_status and new_delivery_status != current_delivery_status:
            allowed_next_status = allowed_transitions.get(current_delivery_status, [])

            if new_delivery_status not in allowed_next_status:
                raise serializers.ValidationError(
                    MESSAGES["jewelry_products_invalid_delivery_status_change"].format(
                        current=current_delivery_status.replace("_", " ").title(),
                        new=new_delivery_status.replace("_", " ").title(),
                    )
                )

        return attrs

    def update(self, instance, validated_data):
        from decimal import Decimal

        from sooq_althahab.enums.jeweler import DeliveryStatus
        from sooq_althahab.enums.jeweler import StockLocation
        from sooq_althahab.enums.jeweler import StockStatus

        new_delivery_status = validated_data.get("delivery_status")
        instance.delivery_status = new_delivery_status
        instance.save()
        manufacturing_request = instance.manufacturing_request

        # Auto-create stock when delivery status is DELIVERED
        if new_delivery_status == DeliveryStatus.DELIVERED:
            # Get all manufacturing products for this production
            manufacturing_products = (
                ManufacturingProductRequestedQuantity.objects.filter(
                    manufacturing_request=manufacturing_request,
                    admin_inspection_status=RequestStatus.APPROVED,
                )
            )

            for manufacturing_product in manufacturing_products:
                # Check if stock already exists
                stock_exists = JewelryStock.objects.filter(
                    jewelry_product=manufacturing_product.jewelry_product,
                    manufacturing_product=manufacturing_product,
                    organization_id=instance.organization_id,
                ).exists()

                if not stock_exists:
                    # Create stock entry with showroom quantity
                    JewelryStock.objects.create(
                        business=manufacturing_request.business,
                        jewelry_product=manufacturing_product.jewelry_product,
                        manufacturing_product=manufacturing_product,
                        showroom_quantity=manufacturing_product.quantity
                        or Decimal("0.00"),
                        marketplace_quantity=Decimal("0.00"),
                        showroom_status=(
                            StockStatus.IN_STOCK
                            if (manufacturing_product.quantity or 0) > 0
                            else StockStatus.OUT_OF_STOCK
                        ),
                        marketplace_status=StockStatus.OUT_OF_STOCK,
                        location=StockLocation.SHOWROOM,
                        created_by=instance.created_by,
                        organization_id=instance.organization_id,
                    )

        return instance


class JewelryProductInspectionAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = JewelryProductInspectionAttachment
        fields = ["file"]


class JewelryProductionProductCommentUpdateSerializer(serializers.ModelSerializer):
    attachments = JewelryProductInspectionAttachmentSerializer(
        many=True, write_only=True, required=False
    )
    jewelry_production_id = serializers.CharField(write_only=True, required=True)
    comment = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = ManufacturingProductRequestedQuantity
        fields = ["comment", "jewelry_production_id", "attachments"]

    def validate_jewelry_production_id(self, value):
        if not JewelryProduction.objects.filter(id=value).exists():
            raise serializers.ValidationError("Invalid jewelry_production ID.")
        return value

    def update(self, instance, validated_data):
        # Get jewelry_production_id (already validated to exist)
        request = self.context.get("request")
        jewelry_production_id = validated_data.pop("jewelry_production_id")
        jewelry_production = JewelryProduction.objects.get(id=jewelry_production_id)

        # Update comment if provided
        comment = validated_data.get("comment")
        if comment is not None:
            instance.comment = comment
            instance.save()

        # Handle bulk attachment creation
        attachments_data = validated_data.get("attachments", [])
        uploaded_by = request.auth.get("role")

        if attachments_data:
            attachments = [
                JewelryProductInspectionAttachment(
                    manufacturing_jewelry_product=instance,
                    jewelry_production=jewelry_production,
                    uploaded_by=uploaded_by,
                    created_by=request.user,
                    **data,
                )
                for data in attachments_data
            ]
            JewelryProductInspectionAttachment.objects.bulk_create(attachments)

        return instance


class DashboardSerializer(serializers.Serializer):
    new = serializers.CharField()
    completed = serializers.CharField()
    in_progress = serializers.CharField()


####################################################################################
############################ Serial Number Serializer's ############################
####################################################################################


class PreciousItemUnitSerializer(serializers.ModelSerializer):
    id = serializers.CharField(write_only=True)

    class Meta:
        model = PreciousItemUnit
        fields = ["id", "system_serial_number"]


class PurchaseRequestUpdateSerializer(serializers.ModelSerializer):
    precious_item_unit = PreciousItemUnitSerializer(many=True)

    class Meta:
        model = PurchaseRequest
        fields = ["storage_box_number", "precious_item_unit"]

    def validate(self, attrs):
        value = attrs.get("storage_box_number")
        if not value:
            raise serializers.ValidationError(MESSAGES["storage_box_number_required"])
        return attrs

    def update(self, instance, validated_data):
        """
        Update PurchaseRequest along with related PreciousItemUnit objects.
        """

        instance.storage_box_number = validated_data.get(
            "storage_box_number", instance.storage_box_number
        )
        instance.save()

        # Handle nested PreciousItemUnit updates
        precious_item_units_data = validated_data.get("precious_item_unit", [])
        for unit_data in precious_item_units_data:
            unit_id = unit_data.get("id")
            try:
                unit_instance = PreciousItemUnit.objects.get(id=unit_id)
            except PreciousItemUnit.DoesNotExist:
                continue

            unit_instance.system_serial_number = unit_data.get(
                "system_serial_number", unit_instance.system_serial_number
            )
            unit_instance.save()

        return instance


######################################################################################
############################### Admin Transaction Serializers ########################
######################################################################################


class SubscriptionPlanDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = ["id", "subscription_code"]


class BusinessSubscriptionPlanResponseSerializer(serializers.ModelSerializer):
    subscription_plan = SubscriptionPlanDetailsSerializer(read_only=True)
    payment_card = serializers.SerializerMethodField()

    class Meta:
        model = BusinessSubscriptionPlan
        fields = [
            "id",
            "subscription_plan",
            "payment_card",
            "subscription_name",
            "start_date",
            "expiry_date",
            "subscription_fee",
            "commission_rate",
            "cancelled_date",
            "status",
            "is_auto_renew",
            "payment_type",
            "created_at",
            "pro_rata_rate",
            "payment_interval",
        ]

    def get_payment_card(self, obj):
        """Get transaction attachments with presigned URLs."""

        return BusinessSavedCardTokenDetailSerializer(
            obj.business_saved_card_token
        ).data


class BillingDetailsResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingDetails
        fields = [
            "id",
            "payment_status",
            "invoice_number",
            "period_start_date",
            "period_end_date",
        ]


class BusinessAccountSerializer(serializers.ModelSerializer):
    owner = serializers.SerializerMethodField()
    logo = serializers.SerializerMethodField()

    class Meta:
        model = BusinessAccount
        fields = ["id", "name", "business_account_type", "owner", "logo"]

    def get_owner(self, obj):
        owners = getattr(obj, "prefetched_owners", [])
        if owners:
            owner = owners[0]  # is_owner=True, so only one
            return {
                "id": owner.user.id,
                "name": owner.user.get_full_name(),
                "user_type": owner.user.user_type,
            }
        return None

    def get_logo(self, obj):
        """Generate a presigned URL for the logo in the model using the PresignedUrlSerializer."""
        logo = obj.logo
        return get_presigned_url_from_s3(logo)


class SubscriptionTransactionListSerializer(serializers.ModelSerializer):
    """Enhanced transaction serializer for admin list view with subscription details."""

    from_business = serializers.SerializerMethodField()
    transaction_source_type = serializers.CharField(read_only=True)
    billing_details = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            "id",
            "reference_number",
            "receipt_number",
            "from_business",
            "amount",
            "currency",
            "status",
            "transaction_type",
            "created_at",
            "transaction_source_type",
            "billing_details",
        ]

    def get_from_business(self, obj):
        return BusinessAccountSerializer(obj.from_business).data

    def get_billing_details(self, obj):
        billing_details = getattr(obj.from_business, "prefetched_billing_details", [])
        if billing_details:
            return BillingDetailsResponseSerializer(billing_details[0]).data
        return None


class SubscriptionTransactionDetailSerializer(serializers.ModelSerializer):
    """Enhanced transaction serializer for admin detail view with full subscription and card details."""

    from_business = serializers.SerializerMethodField()
    business_subscription = BusinessSubscriptionPlanResponseSerializer(read_only=True)
    transaction_source_type = serializers.CharField(read_only=True)
    billing_details = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            "id",
            "reference_number",
            "receipt_number",
            "from_business",
            "amount",
            "currency",
            "status",
            "transaction_type",
            "created_at",
            "transaction_source_type",
            "business_subscription",
            "billing_details",
            "created_by",
            "transfer_via",
            "vat",
            "remark",
        ]

    def get_from_business(self, obj):
        return BusinessAccountSerializer(obj.from_business).data

    def get_billing_details(self, obj):
        billing_details = getattr(obj.from_business, "prefetched_billing_details", [])
        if billing_details:
            return BillingDetailsResponseSerializer(billing_details[0]).data
        return None


class MusharakahContractManufacturingCostCreateSerializer(serializers.Serializer):
    musharakah_contract_id = serializers.CharField()


class MusharakahContractManufacturingCostResponseSerializer(serializers.Serializer):
    total_manufacturing_cost = serializers.CharField()
    total_retail_price = serializers.CharField()


class AdminMusharakahContractTerminationRequestSerializer(serializers.ModelSerializer):
    """Handles serializers for Musharakah Contract Termination Request."""

    class Meta:
        model = MusharakahContractTerminationRequest
        fields = ["musharakah_contract_request", "termination_request_by"]

    def validate(self, attrs):
        musharakah_contract_request = attrs.get("musharakah_contract_request")

        if (
            musharakah_contract_request.musharakah_contract_status
            == MusharakahContractStatus.TERMINATED
        ):
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_already_terminated"]
            )

        if musharakah_contract_request.musharakah_contract_status not in [
            MusharakahContractStatus.ACTIVE,
            MusharakahContractStatus.RENEW,
        ]:
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_inactive"]
            )

        if musharakah_contract_request.status != RequestStatus.APPROVED:
            raise serializers.ValidationError(
                MESSAGES["musharakah_contract_request_must_be_approved"]
            )
        if MusharakahContractTerminationRequest.objects.filter(
            musharakah_contract_request=musharakah_contract_request,
            status=RequestStatus.PENDING,
        ).exists():
            raise serializers.ValidationError(
                JEWELER_MESSAGE["musharakah_contract_termination_request_exists"]
            )

        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        musharakah_contract = validated_data.get("musharakah_contract_request")

        musharakah_contract_termination_request = (
            MusharakahContractTerminationRequest.objects.create(
                created_by=request.user,
                organization_id=request.user.organization_id,
                **validated_data,
            )
        )

        musharakah_contract.musharakah_contract_status = (
            MusharakahContractStatus.UNDER_TERMINATION
        )
        musharakah_contract.save()
        return musharakah_contract_termination_request


class PreciousItemUnitAdminUpdateSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=50)
    serial_number = serializers.CharField(max_length=50, required=False)
    system_serial_number = serializers.CharField(
        max_length=50, required=False, allow_blank=True
    )


class PreciousItemUnitBulkAdminUpdateSerializer(serializers.Serializer):
    storage_box_number = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    units = PreciousItemUnitAdminUpdateSerializer(many=True, required=False)

    def validate(self, attrs):
        """
        Ensure at least one field is provided:
        - storage_box_number OR
        - units
        """
        if not attrs.get("storage_box_number") and not attrs.get("units"):
            raise serializers.ValidationError(
                MESSAGES["storage_box_number_or_units_required"]
            )
        return attrs


######################################################################################
############################### Admin Transaction Serializers ########################
######################################################################################


class ManufacturingProductRequestedQuantityDetailSerializer(
    serializers.ModelSerializer
):
    jewelry_product = JewelryProductResponseSerializer()

    class Meta:
        model = ManufacturingProductRequestedQuantity
        fields = [
            "id",
            "manufacturing_request",
            "jewelry_product",
            "quantity",
        ]


######################################################################################
############################### Jewelry Buyer Serializers ###########################
######################################################################################


class JewelryStockListSerializer(serializers.ModelSerializer):
    """Serializer for listing jewelry stocks with product details."""

    jewelry_product = JewelryProductResponseSerializer(read_only=True)
    total_quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = JewelryStock
        fields = [
            "id",
            "jewelry_product",
            "showroom_quantity",
            "marketplace_quantity",
            "total_quantity",
            "showroom_status",
            "marketplace_status",
            "location",
            "is_published_to_marketplace",
            "created_at",
        ]


class JewelryStockDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for jewelry stock with all related information."""

    jewelry_product = JewelryProductResponseSerializer(read_only=True)
    total_quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    business = serializers.SerializerMethodField()
    manufacturing_product = ManufacturingProductRequestedQuantityDetailSerializer(
        read_only=True
    )

    class Meta:
        model = JewelryStock
        exclude = ["deleted_at", "restored_at", "transaction_id"]

    def get_business(self, obj):
        return BusinessBasicSerializer(obj.business).data


class JewelryStockUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating jewelry stock quantities."""

    class Meta:
        model = JewelryStock
        fields = [
            "showroom_quantity",
            "marketplace_quantity",
        ]

    def validate(self, attrs):
        showroom_quantity = attrs.get("showroom_quantity")
        marketplace_quantity = attrs.get("marketplace_quantity")

        if showroom_quantity is not None and showroom_quantity < 0:
            raise serializers.ValidationError(
                {"showroom_quantity": "Showroom quantity cannot be negative."}
            )
        if marketplace_quantity is not None and marketplace_quantity < 0:
            raise serializers.ValidationError(
                {"marketplace_quantity": "Marketplace quantity cannot be negative."}
            )

        return attrs

    def update(self, instance, validated_data):
        instance.showroom_quantity = validated_data.get(
            "showroom_quantity", instance.showroom_quantity
        )
        instance.marketplace_quantity = validated_data.get(
            "marketplace_quantity", instance.marketplace_quantity
        )
        instance.update_stock_status()
        instance.save()
        return instance


class JewelryProductMarketplaceImageSerializer(serializers.ModelSerializer):
    """Serializer for marketplace product images."""

    image = serializers.SerializerMethodField()

    class Meta:
        model = JewelryProductMarketplaceImage
        fields = ["id", "image", "created_at"]

    def get_image(self, obj):
        """Generate a presigned URL for the image field using the PresignedUrlSerializer."""
        image = obj.image
        return get_presigned_url_from_s3(image)


class JewelryProductMarketplaceSerializer(serializers.ModelSerializer):
    """Serializer for marketplace product entries."""

    jewelry_product = JewelryProductResponseSerializer(read_only=True)
    marketplace_images = JewelryProductMarketplaceImageSerializer(
        many=True, read_only=True
    )

    class Meta:
        model = JewelryProductMarketplace
        fields = [
            "id",
            "jewelry_product",
            "jewelry_stock",
            "published_quantity",
            "description",
            "is_active",
            "published_at",
            "unpublished_at",
            "marketplace_images",
        ]


class JewelryProductMarketplaceCreateSerializer(serializers.ModelSerializer):
    """Serializer for publishing products to marketplace."""

    images = serializers.ListField(
        child=serializers.CharField(max_length=500),
        required=False,
        allow_empty=True,
        help_text="List of image file paths/URLs to upload.",
    )

    class Meta:
        model = JewelryProductMarketplace
        fields = [
            "jewelry_product",
            "jewelry_stock",
            "published_quantity",
            "description",
            "images",
        ]

    def validate(self, attrs):
        jewelry_product = attrs.get("jewelry_product")
        jewelry_stock = attrs.get("jewelry_stock")
        published_quantity = attrs.get("published_quantity")

        # Auto-find stock if not provided
        if not jewelry_stock and jewelry_product:
            from jeweler.models import JewelryStock

            jewelry_stock = (
                JewelryStock.objects.filter(
                    jewelry_product=jewelry_product,
                    organization_id=self.context.get("request").user.organization_id,
                )
                .order_by("-created_at")
                .first()
            )

            if jewelry_stock:
                attrs["jewelry_stock"] = jewelry_stock
            else:
                raise serializers.ValidationError(
                    {
                        "jewelry_stock": "No stock found for this product. Please ensure the product has been delivered to showroom first."
                    }
                )

        if jewelry_stock and published_quantity:
            # Check showroom quantity (we're moving from showroom to marketplace)
            if published_quantity > jewelry_stock.showroom_quantity:
                raise serializers.ValidationError(
                    {
                        "published_quantity": f"Published quantity cannot exceed available showroom quantity ({jewelry_stock.showroom_quantity})."
                    }
                )

        return attrs

    def create(self, validated_data):
        from django.db import transaction

        request = self.context.get("request")
        jewelry_stock = validated_data.get("jewelry_stock")
        images = validated_data.pop("images", [])
        published_quantity = validated_data.get("published_quantity", 0)

        with transaction.atomic():
            marketplace_entry = JewelryProductMarketplace.objects.create(
                created_by=request.user,
                organization_id=request.user.organization_id,
                **validated_data,
            )

            # Create image entries
            for image_path in images:
                JewelryProductMarketplaceImage.objects.create(
                    marketplace=marketplace_entry,
                    image=image_path,
                )

            # Update stock to mark as published and update marketplace quantity
            if jewelry_stock and published_quantity > 0:
                # Move quantity from showroom to marketplace
                # Ensure we don't exceed available showroom quantity
                available_qty = jewelry_stock.showroom_quantity
                if published_quantity > available_qty:
                    published_quantity = available_qty

                jewelry_stock.showroom_quantity -= published_quantity
                jewelry_stock.marketplace_quantity += published_quantity
                jewelry_stock.is_published_to_marketplace = True
                jewelry_stock.update_stock_status()
                jewelry_stock.save()

        return marketplace_entry


######################################################################################
############################### Jewelry Sales Serializers ##########################
######################################################################################


class JewelrySaleListSerializer(serializers.ModelSerializer):
    """Serializer for listing jewelry sales."""

    jewelry_product = JewelryProductResponseSerializer(read_only=True)
    unit_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = JewelryStockSale
        fields = [
            "id",
            "manufacturing_request",
            "jewelry_product",
            "sale_location",
            "quantity",
            "sale_price",
            "unit_price",
            "sale_date",
            "customer_name",
            "created_at",
            "status",
            "delivered_at",
            "delivery_date",
        ]


class JewelrySaleDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for jewelry sale with all related information."""

    jewelry_product = JewelryProductResponseSerializer(read_only=True)
    jewelry_stock = JewelryStockListSerializer(read_only=True)
    unit_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = JewelryStockSale
        fields = "__all__"


class JewelrySaleUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = JewelryStockSale
        fields = ["status", "delivery_date", "delivery_address"]

    def update(self, instance, validated_data):
        """
        Update sale fields cleanly and safely.
        """

        # Update allowed fields
        instance.status = validated_data.get("status", instance.status)
        instance.delivered_at = (
            timezone.now()
            if instance.status == DeliveryRequestStatus.DELIVERED
            else None
        )
        instance.delivery_date = validated_data.get(
            "delivery_date", instance.delivery_date
        )
        instance.delivery_address = validated_data.get(
            "delivery_address", instance.delivery_address
        )

        # Save changes
        instance.save()

        return instance


class JewelrySaleCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a jewelry sale."""

    class Meta:
        model = JewelryStockSale
        fields = [
            "manufacturing_request",
            "jewelry_product",
            "jewelry_stock",
            "sale_location",
            "quantity",
            "sale_price",
            "sale_date",
            "customer_name",
            "customer_email",
            "customer_phone",
            "notes",
            "delivery_address",
            "delivery_date",
        ]

    def validate(self, attrs):
        jewelry_stock = attrs.get("jewelry_stock")
        sale_location = attrs.get("sale_location")
        quantity = attrs.get("quantity")

        if jewelry_stock and quantity:
            # Check available quantity based on location
            if sale_location == StockLocation.SHOWROOM:
                available_qty = jewelry_stock.showroom_quantity
                if quantity > available_qty:
                    raise serializers.ValidationError(
                        {
                            "quantity": f"Sale quantity cannot exceed available showroom quantity ({available_qty})."
                        }
                    )
            elif sale_location == StockLocation.MARKETPLACE:
                available_qty = jewelry_stock.marketplace_quantity
                if quantity > available_qty:
                    raise serializers.ValidationError(
                        {
                            "quantity": f"Sale quantity cannot exceed available marketplace quantity ({available_qty})."
                        }
                    )

        return attrs

    def create(self, validated_data):
        from django.db import transaction

        request = self.context.get("request")
        jewelry_product = validated_data.get("jewelry_product")
        jewelry_stock = validated_data.get("jewelry_stock")
        manufacturing_request = validated_data.get("manufacturing_request")
        sale_location = validated_data.get("sale_location")
        quantity = validated_data.get("quantity")
        distributed_at = timezone.now()
        with transaction.atomic():
            # Create Sale Record
            sale = JewelryStockSale.objects.create(
                created_by=request.user,
                organization_id=request.user.organization_id,
                **validated_data,
            )

            # Update Jewelry Stock Quantities
            if jewelry_stock:
                if sale_location == StockLocation.SHOWROOM:
                    jewelry_stock.showroom_quantity -= quantity
                elif sale_location == StockLocation.MARKETPLACE:
                    jewelry_stock.marketplace_quantity -= quantity

                jewelry_stock.update_stock_status()
                jewelry_stock.save()

            # Fetch Manufacturing & Cost Details
            jewelry_production = manufacturing_request.jewelry_production
            jewelry_payment = jewelry_production.payment

            # Requested manufacturing quantity for this product
            manufacturing_product = (
                ManufacturingProductRequestedQuantity.objects.filter(
                    manufacturing_request=manufacturing_request,
                    jewelry_product=jewelry_product,
                ).first()
            )

            # Estimated manufacturing price of the product
            manufacturing_price = ProductManufacturingEstimatedPrice.objects.filter(
                estimation_request__manufacturing_request=manufacturing_request,
                requested_product__jewelry_product=jewelry_product,
            ).first()

            # Manufacturing cost per item
            manufacturing_price_per_product = (
                manufacturing_price.estimated_price / manufacturing_product.quantity
            )

            # Total manufacturing cost for this sold batch
            sold_product_manufacturing_cost = manufacturing_price_per_product * quantity

            # Metal price consumed in manufacturing
            manufacturing_metal_price = (
                sale.quantity * manufacturing_product.metal_amount
            )

            sale_price = sale.sale_price

            # Calculate Profit
            profit = (
                sale_price - manufacturing_metal_price - sold_product_manufacturing_cost
            )

            musharakah_contract = jewelry_payment.musharakah_contract
            profit_distribution_data = []
            notification_data = {
                "jeweler_business": None,
                "investor_business": None,
                "jeweler_profit_amount": None,
                "investor_profit_amount": None,
                "investor_transaction_id": None,
                "jeweler_transaction_id": None,
            }
            # PROFIT DISTRIBUTION – Based on payment source
            # Case 1: MUSHARAKAH contribution
            if jewelry_payment.payment_type == MaterialSource.MUSHARAKAH:
                # Investor's share
                investor_profit = Decimal("0.00")
                if musharakah_contract.investor:
                    investor_profit = profit * (
                        musharakah_contract.musharakah_equity / 100
                    )

                if musharakah_contract.investor:
                    profit_distribution_investor = {
                        "jewelry_sale": sale,
                        "musharakah_contract": musharakah_contract,
                        "recipient_business": musharakah_contract.investor,
                        "recipient_type": musharakah_contract.investor.business_account_type,
                        "cost_of_repurchasing_metal": manufacturing_metal_price,
                        "revenue": sale.sale_price,
                        "profit_share_percentage": musharakah_contract.musharakah_equity,
                        "profit_amount": investor_profit,
                        "distributed_at": distributed_at,
                        "transaction_amount": investor_profit
                        + manufacturing_metal_price,
                        "user": request.user,
                        "organization_id": request.user.organization_id,
                    }
                    # Only add if transaction amount is positive
                    if profit_distribution_investor["transaction_amount"] > 0:
                        notification_data[
                            "investor_business"
                        ] = musharakah_contract.investor
                        notification_data[
                            "investor_profit_amount"
                        ] = profit_distribution_investor["transaction_amount"]
                        profit_distribution_data.append(profit_distribution_investor)

                # Jeweler's share (remaining %)
                jeweler_profit_share_percentage = Decimal("0.00")
                jeweler_profit = Decimal("0.00")
                if musharakah_contract.jeweler:
                    jeweler_profit_share_percentage = (
                        100 - musharakah_contract.musharakah_equity
                    )
                    jeweler_profit = profit * (jeweler_profit_share_percentage / 100)

                if musharakah_contract.jeweler:
                    profit_distribution_jeweler = {
                        "jewelry_sale": sale,
                        "musharakah_contract": musharakah_contract,
                        "recipient_business": musharakah_contract.jeweler,
                        "recipient_type": musharakah_contract.jeweler.business_account_type,
                        "cost_of_repurchasing_metal": manufacturing_metal_price,
                        "revenue": sale.sale_price,
                        "profit_share_percentage": jeweler_profit_share_percentage,
                        "profit_amount": jeweler_profit,
                        "distributed_at": distributed_at,
                        "transaction_amount": jeweler_profit
                        + sold_product_manufacturing_cost,
                        "user": request.user,
                        "organization_id": request.user.organization_id,
                    }
                    # Only add if transaction amount is positive
                    if profit_distribution_jeweler["transaction_amount"] > 0:
                        notification_data[
                            "jeweler_business"
                        ] = musharakah_contract.jeweler
                        notification_data[
                            "jeweler_profit_amount"
                        ] = profit_distribution_jeweler["transaction_amount"]
                        profit_distribution_data.append(profit_distribution_jeweler)

            # Case 2: CASH payment (100% profit to jeweler)
            elif jewelry_payment.payment_type == MaterialSource.CASH:
                profit_distribution_jeweler = {
                    "jewelry_sale": sale,
                    "musharakah_contract": musharakah_contract,
                    "recipient_business": manufacturing_request.business,
                    "recipient_type": manufacturing_request.business.business_account_type,
                    "cost_of_repurchasing_metal": manufacturing_metal_price,
                    "revenue": sale_price,
                    "profit_share_percentage": 100,
                    "profit_amount": profit,
                    "distributed_at": distributed_at,
                    "transaction_amount": sale_price,
                    "user": request.user,
                    "organization_id": request.user.organization_id,
                }
                notification_data["jeweler_business"] = manufacturing_request.business
                notification_data[
                    "jeweler_profit_amount"
                ] = profit_distribution_jeweler["transaction_amount"]
                profit_distribution_data.append(profit_distribution_jeweler)

            # Case 3: ASSET payment
            elif jewelry_payment.payment_type == MaterialSource.ASSET:
                profit_distribution_jeweler = {
                    "jewelry_sale": sale,
                    "musharakah_contract": musharakah_contract,
                    "recipient_business": manufacturing_request.business,
                    "recipient_type": manufacturing_request.business.business_account_type,
                    "cost_of_repurchasing_metal": manufacturing_metal_price,
                    "revenue": sale_price,
                    "profit_share_percentage": 100,
                    "profit_amount": profit,
                    "distributed_at": distributed_at,
                    "transaction_amount": sale_price,
                    "user": request.user,
                    "organization_id": request.user.organization_id,
                }
                notification_data["jeweler_business"] = manufacturing_request.business
                notification_data[
                    "jeweler_profit_amount"
                ] = profit_distribution_jeweler["transaction_amount"]
                profit_distribution_data.append(profit_distribution_jeweler)

            # Case 4: MUSHARAKAH + ASSET hybrid
            elif jewelry_payment.payment_type == MaterialSource.MUSHARAKAH_AND_ASSET:
                # Handling additional metal consumption for hybrid contribution
                jewelry_product_materials = JewelryProductMaterial.objects.filter(
                    material_type=MaterialType.METAL, jewelry_product=jewelry_product
                )

                product_additional_material_per_quantity = Decimal("0.00")
                product_additional_material_price = Decimal("0.00")

                for material in jewelry_product_materials:
                    manufacturing_product = ManufacturingProductRequestedQuantity.objects.filter(
                        manufacturing_request=manufacturing_request,
                        jewelry_product__product_materials__material_item=material.material_item,
                        jewelry_product__product_materials__carat_type=material.carat_type,
                    )

                    request_product_quantity = 0

                    # Calculate total produced quantity
                    if manufacturing_product.exists():
                        for product in manufacturing_product:
                            request_product_quantity += product.quantity

                    manufacturing_target = ManufacturingTarget.objects.filter(
                        manufacturing_request_id=manufacturing_request.id,
                        material_type=MaterialType.METAL,
                        material_item_id=material.material_item_id,
                        carat_type_id=material.carat_type_id,
                    ).first()
                    metal_price = manufacturing_target.metal_amount
                    product_additional_material_per_quantity += (
                        metal_price / request_product_quantity
                    )
                    product_additional_material_price += (
                        product_additional_material_per_quantity * quantity
                    )

                # Adjust profit for asset additional material
                profit_from_sold_product = profit - product_additional_material_price

                # Investor share
                investor_profit = Decimal("0.00")
                if musharakah_contract.investor:
                    investor_profit = profit_from_sold_product * (
                        musharakah_contract.musharakah_equity / 100
                    )

                    profit_distribution_investor = {
                        "jewelry_sale": sale,
                        "musharakah_contract": musharakah_contract,
                        "recipient_business": musharakah_contract.investor,
                        "recipient_type": musharakah_contract.investor.business_account_type,
                        "cost_of_repurchasing_metal": manufacturing_metal_price,
                        "revenue": sale.sale_price,
                        "profit_share_percentage": musharakah_contract.musharakah_equity,
                        "profit_amount": investor_profit,
                        "distributed_at": distributed_at,
                        "transaction_amount": investor_profit
                        + manufacturing_metal_price,
                        "user": request.user,
                        "organization_id": request.user.organization_id,
                    }
                    # Only add if transaction amount is positive
                    if profit_distribution_investor["transaction_amount"] > 0:
                        notification_data[
                            "investor_business"
                        ] = musharakah_contract.investor
                        notification_data[
                            "investor_profit_amount"
                        ] = profit_distribution_investor["transaction_amount"]
                        profit_distribution_data.append(profit_distribution_investor)

                # Jeweler share
                jeweler_profit_share_percentage = Decimal("0.00")
                jeweler_profit = Decimal("0.00")
                if musharakah_contract.jeweler:
                    jeweler_profit_share_percentage = (
                        100 - musharakah_contract.musharakah_equity
                    )
                    jeweler_profit = profit * (jeweler_profit_share_percentage / 100)
                    profit_distribution_jeweler = {
                        "jewelry_sale": sale,
                        "musharakah_contract": musharakah_contract,
                        "recipient_business": musharakah_contract.jeweler,
                        "recipient_type": musharakah_contract.jeweler.business_account_type,
                        "cost_of_repurchasing_metal": manufacturing_metal_price,
                        "revenue": sale.sale_price,
                        "profit_share_percentage": jeweler_profit_share_percentage,
                        "profit_amount": jeweler_profit,
                        "distributed_at": distributed_at,
                        "transaction_amount": jeweler_profit
                        + sold_product_manufacturing_cost
                        + product_additional_material_price,
                        "user": request.user,
                        "organization_id": request.user.organization_id,
                    }
                    # Only add if transaction amount is positive
                    if profit_distribution_jeweler["transaction_amount"] > 0:
                        notification_data[
                            "jeweler_business"
                        ] = musharakah_contract.jeweler
                        notification_data[
                            "jeweler_profit_amount"
                        ] = profit_distribution_jeweler["transaction_amount"]
                        profit_distribution_data.append(profit_distribution_jeweler)

            self.notification_data = notification_data
            # Save Transactions + Profit Distribution Records
            transaction_data = self.create_transaction_record_for_profit_distribution(
                profit_distribution_data
            )
            notification_data["investor_transaction_id"] = transaction_data.get(
                "investor_transaction_id"
            )
            notification_data["jeweler_transaction_id"] = transaction_data.get(
                "jeweler_transaction_id"
            )

        return sale

    def create_transaction_record_for_profit_distribution(
        self, profit_distribution_data
    ):
        transaction_data = {}

        for profit_distribution in profit_distribution_data:
            # Skip distributions with zero or negative amounts to avoid constraint violations
            if profit_distribution["transaction_amount"] <= 0:
                continue

            jewelry_profit_distribution = JewelryProfitDistribution.objects.create(
                jewelry_sale=profit_distribution["jewelry_sale"],
                musharakah_contract=profit_distribution["musharakah_contract"],
                recipient_business=profit_distribution["recipient_business"],
                recipient_type=profit_distribution["recipient_type"],
                cost_of_repurchasing_metal=profit_distribution[
                    "cost_of_repurchasing_metal"
                ],
                revenue=profit_distribution["revenue"],
                profit_share_percentage=profit_distribution["profit_share_percentage"],
                profit_amount=profit_distribution["profit_amount"],
                distributed_at=profit_distribution["distributed_at"],
                created_by=profit_distribution["user"],
                organization_id=profit_distribution["organization_id"],
            )

            if profit_distribution["profit_amount"] > Decimal("0.00"):
                # Update Business Wallet Balance
                business_wallet = Wallet.objects.get(
                    business=profit_distribution["recipient_business"]
                )
                previous_balance = business_wallet.balance
                business_wallet.balance += profit_distribution["transaction_amount"]
                business_wallet.save()
                current_balance = business_wallet.balance
                transaction = Transaction.objects.create(
                    from_business=profit_distribution["recipient_business"],
                    to_business=profit_distribution["recipient_business"],
                    created_by=profit_distribution["user"],
                    profit_distribution=jewelry_profit_distribution,
                    transaction_type=TransactionType.PAYMENT,
                    status=TransactionStatus.SUCCESS,
                    amount=profit_distribution["transaction_amount"],
                    previous_balance=previous_balance,
                    current_balance=current_balance,
                )
                if (
                    profit_distribution["recipient_business"].business_account_type
                    == UserRoleBusinessChoices.INVESTOR
                ):
                    transaction_data["investor_transaction_id"] = transaction.id
                elif (
                    profit_distribution["recipient_business"].business_account_type
                    == UserRoleBusinessChoices.JEWELER
                ):
                    transaction_data["jeweler_transaction_id"] = transaction.id

        return transaction_data


class JewelryProfitDistributionSerializer(
    BusinessDetailsMixin, serializers.ModelSerializer
):
    recipient_business = serializers.SerializerMethodField()
    jewelry_sale = JewelrySaleDetailSerializer(read_only=True)

    class Meta:
        model = JewelryProfitDistribution
        fields = [
            "id",
            "jewelry_sale",
            "musharakah_contract",
            "recipient_business",
            "recipient_type",
            "cost_of_repurchasing_metal",
            "revenue",
            "profit_share_percentage",
            "profit_amount",
            "distributed_at",
            "created_at",
            "updated_at",
        ]

    def get_recipient_business(self, obj):
        return self.serialize_business(obj, "recipient_business")
