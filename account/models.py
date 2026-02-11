import logging
import random
import re
import string
import uuid
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import BaseUserManager
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models
from django.db import transaction
from django.db.models import CheckConstraint
from django.db.models import Q
from django_softdelete.managers import SoftDeleteManager
from django_softdelete.models import SoftDeleteModel
from phonenumber_field.modelfields import PhoneNumberField
from rest_framework.serializers import ValidationError

from account.abstract import RiskLevelMixin
from account.mixins import ReceiptNumberMixin
from sooq_althahab.base_models import OwnershipMixin
from sooq_althahab.base_models import TimeStampedModelMixin
from sooq_althahab.base_models import UserTimeStampedModelMixin
from sooq_althahab.enums.account import BusinessType
from sooq_althahab.enums.account import DeviceType
from sooq_althahab.enums.account import DocumentType
from sooq_althahab.enums.account import Gender
from sooq_althahab.enums.account import Language
from sooq_althahab.enums.account import MusharakahClientType
from sooq_althahab.enums.account import MusharakahContractTerminationPaymentType
from sooq_althahab.enums.account import PlatformFeeType
from sooq_althahab.enums.account import ShareholderRole
from sooq_althahab.enums.account import SuspendingRoleChoice
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.account import TransferVia
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.account import UserStatus
from sooq_althahab.enums.account import UserType
from sooq_althahab.enums.account import WebhookCallStatus
from sooq_althahab.enums.account import WebhookEventType
from sooq_althahab.mixins import CustomIDMixin

logger = logging.getLogger(__name__)


class Organization(CustomIDMixin, TimeStampedModelMixin):
    """
    A model that represents an organization.

    Attributes:
        name (CharField): The name of the organization.
        active (BooleanField): Indicates whether the organization is active.
        description (TextField): A description of the organization.
        country (CharField): The country where the organization is located.
        address (TextField): The address of the organization.
        commercial_registration_number (CharField): The commercial registration number.
        vat_account_number (CharField): The vat account number.
        code (CharField): A unique code for the organization.
        timezone (CharField): The timezone of the country.
        created_by (ForeignKey): The user who created the organization.
        taxes (DecimalField): The tax rate as a decimal (e.g., 0.05 for 5%).
        platform_fee_rate (DecimalField): The platform fee rate as a decimal (e.g., 0.10 for 10%).
        platform_fee_amount (DecimalField): A fixed platform fee amount.
        vat (DecimalField): The VAT rate as a decimal (e.g., 0.15 for 15%).
    """

    name = models.CharField(max_length=255, unique=True)
    arabic_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Arabic name of the organization",
    )
    active = models.BooleanField(default=True)
    description = models.TextField(blank=True, null=True)
    country = models.CharField(max_length=255, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    commercial_registration_number = models.CharField(
        max_length=255, blank=True, null=True
    )
    vat_account_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="VAT account number for the organization",
    )
    # TODO: Add timezone choices maybe?
    timezone = models.CharField(max_length=255, blank=True, null=True)
    code = models.CharField(max_length=255, null=True)

    created_by = models.ForeignKey(
        "account.User",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_by%(class)s",
    )

    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0.00,
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
        help_text="Tax rate as a decimal (e.g., 0.05 for 5%)",
    )

    platform_fee_type = models.CharField(
        max_length=12,
        choices=PlatformFeeType.choices,
        help_text="Select the platform fee type (percentage or amount).",
        default=PlatformFeeType.PERCENTAGE,
    )

    platform_fee_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0.00,
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
        help_text="Platform fee rate as a decimal (e.g., 0.10 for 10%)",
    )

    platform_fee_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Fixed platform fee amount (used when fee type is amount)",
    )

    vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0.00,
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
        help_text="VAT rate as a decimal (e.g., 0.15 for 15%)",
    )

    updated_by = models.ForeignKey(
        "account.User",
        on_delete=models.SET_NULL,
        related_name="updated_by_%(class)s",
        null=True,
        blank=True,
    )

    logo = models.CharField(
        max_length=500,
        blank=True,
        null=True,
    )

    def generate_code(self):
        """Generates a unique code based on the organization's name."""
        name_parts = self.name.split()
        # Create an initial code from the first letter of each word in the name
        code = "".join([part[0].upper() for part in name_parts])
        # Append 5 random digits to the code
        randomized_code = code + "".join(random.choices(string.digits, k=5))
        return randomized_code

    def save(self, *args, **kwargs):
        # Only generate code if it's a new organization (i.e., no primary key yet)

        if not self.code:  # Generate code only if it is missing
            # Generate a unique code for the organization
            with transaction.atomic():  # Ensures uniqueness check is atomic
                randomized_code = self.generate_code()

                # Ensure that the generated code is unique
                while Organization.objects.filter(code=randomized_code).exists():
                    randomized_code = self.generate_code()
                self.code = randomized_code
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "organizations"
        verbose_name = "Organization"
        verbose_name_plural = "Organizations"


class UserManager(SoftDeleteManager, BaseUserManager):
    """Custom user manager."""

    use_in_migrations = True

    def create_user(self, email, password=None, organization_id=None, **extra_fields):
        """
        Create a user with an email and password, and set up default preferences if applicable.
        """
        if not email:
            raise ValueError("Users must have an email address.")

        # Extract language_code from extra_fields if provided, otherwise default to English
        language_code = extra_fields.pop("language_code", Language.ENGLISH)

        # Normalize email and prepare the user instance
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.is_active = True
        user.organization_id = organization_id
        user.save(using=self._db)

        # Setup user preferences if the user is associated with an organization
        if user.organization_id:
            # Fetch default or fallback currency for the organization
            default_currency = (
                OrganizationCurrency.objects.filter(
                    organization=user.organization_id, is_default=True
                ).first()
                or OrganizationCurrency.objects.filter(
                    organization=user.organization_id
                ).first()
            )

            # Fetch the organization's timezone
            timezone = (
                Organization.objects.filter(name=user.organization_id)
                .values_list("timezone", flat=True)
                .first()
                or ""
            )

            # Create user preferences
            UserPreference.objects.create(
                user=user,
                organization_currency=default_currency,
                language_code=language_code,
                timezone=timezone,
            )

        return user

    def create_superuser(self, username, email, password, organization_id):
        """Create a superuser with only email and password."""
        try:
            organization = Organization.objects.get(id=organization_id)
        except Organization.DoesNotExist:
            raise ValueError(f"Organization with ID: {organization_id} not found.")
        user = self.create_user(email, password, organization)
        user.username = username
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.first_name = "admin"
        user.last_name = "admin"
        user.middle_name = "admin"
        user.save()

        admin_role = AdminUserRole(user=user, role=UserRoleChoices.ADMIN)
        admin_role.save()

        return user


class User(
    SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin, AbstractUser, OwnershipMixin
):
    """
    A custom user model that extends Django's AbstractUser model.

    Attributes:
        phone_number (str): The user's phone number.
        phone_country_code (str): The country code for the user's phone number.
        nationality (str): The user's nationality.
        role (str): The role of the user, selected from predefined choices (e.g., Manufacturer, Jeweler, Seller, Investor, Admin).
        is_superuser (bool): Indicates if the user has superuser permissions.
        objects (UserManager): The custom manager used for creating and managing user instances.

    Note:
        Need to create username automatically
    """

    first_name = models.CharField(max_length=50)
    middle_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    username = models.CharField(max_length=150, unique=True, blank=True, null=True)
    email = models.EmailField()
    phone_number = PhoneNumberField(
        help_text="Enter the user's phone number in international format.",
        null=True,
        blank=True,
    )
    phone_country_code = models.CharField(
        max_length=10,
        null=True,
        blank=True,
    )
    account_status = models.CharField(
        max_length=20,
        choices=UserStatus.choices,
        default=UserStatus.PENDING,
        help_text="Select the user's status.",
    )
    is_superuser = models.BooleanField(
        default=False,
        help_text="Designates that this user has all permissions without explicitly assigning them.",
    )
    user_type = models.CharField(
        max_length=20,
        choices=UserType.choices,
        default=UserType.INDIVIDUAL,
    )
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(
        max_length=20,
        choices=Gender.choices,
        null=True,
        blank=True,
    )
    profile_image = models.CharField(
        max_length=500,
        blank=True,
        null=True,
    )
    remark = models.TextField(null=True, blank=True)
    suspended_by = models.CharField(
        max_length=20,
        choices=SuspendingRoleChoice.choices,
        blank=True,
        null=True,
    )
    access_token_expiration = models.DateTimeField(
        null=True,
        blank=True,
        help_text="All access tokens issued before this time will be considered expired.",
    )
    delete_reason = models.TextField(
        null=True,
        blank=True,
        help_text="The delete reason for the deletion of account.",
    )
    personal_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="The user's personal identification number.",
    )

    objects = UserManager()

    REQUIRED_FIELDS = ["email", "organization_id"]

    # Verification fields.
    face_verified = models.BooleanField(default=False)
    document_verified = models.BooleanField(default=False)
    phone_verified = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    business_aml_verified = models.BooleanField(default=False)
    due_diligence_verified = models.BooleanField(default=False)
    declined_reason = models.TextField(
        null=True,
        blank=True,
        help_text="Reason provided for declining document verification reason.",
    )
    reference_id = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="The reference ID provided by Shufti Pro for this verification request.",
    )
    verification_url = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="The URL to the Shufti Pro verification session.",
    )
    event = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="The URL to the Shufti Pro event.",
    )
    password_reset = models.BooleanField(default=False)

    class Meta:
        db_table = "users"
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["-created_at"]

    def __str__(self):
        return f"User {self.email}"

    def sanitize_string(self, input_string):
        """
        Sanitize the input string by removing any special characters except for hyphens.
        """
        return re.sub(r"[^a-zA-Z0-9-]", "", input_string)

    def generate_username(self, email):
        """
        Generate a unique username based on the email address.
        If the base username exists, append the domain name, and if both exist, append a counter until unique.
        """
        # Extract base username (before '@') and domain name (before first '.')
        base_username, domain_name = (
            email.split("@")[0],
            email.split("@")[1].split(".")[0],
        )

        sanitized_base = self.sanitize_string(base_username)
        # Check base username availability first
        username = sanitized_base
        # Check if the username already exists, including soft-deleted users
        if not User.global_objects.filter(username=username).exists():
            return username

        sanitized_domain = self.sanitize_string(domain_name)
        # Check base-username-domain variant availability
        username = f"{sanitized_base}-{sanitized_domain}"
        # Check if the username already exists, including soft-deleted users
        if not User.global_objects.filter(username=username).exists():
            return username

        # Both base username and base-username-domain exist, so append a counter
        counter = (
            User.global_objects.filter(username__startswith=f"{username}").count() + 1
        )
        return f"{username}-{counter}"

    def save(self, *args, **kwargs):
        """Override save method to automatically generate a username."""
        if not self.username:
            self.username = self.generate_username(self.email)

        super().save(*args, **kwargs)

    @property
    def fullname(self):
        """
        Returns the concatenated full name of the user.
        """
        names = [self.first_name, self.middle_name, self.last_name]
        return " ".join(filter(None, names)).strip()


class AdminUserRole(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    """
    Represents a role assigned to a user.

    Attributes:
        user (ForeignKey): The user to whom the role is assigned.
        role (CharField): The role assigned to the user, selected from predefined choices.

    Meta:
        unique_together: Ensures that each user can have only one entry for each role.

    Methods:
        __str__(): Returns a string representation of the user and their assigned role.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_roles")
    role = models.CharField(max_length=20, choices=UserRoleChoices.choices)
    is_suspended = models.BooleanField(default=False)

    class Meta:
        db_table = "organization_admin_user_roles"
        verbose_name = "Organization Admin User Role"
        verbose_name_plural = "Organization Admin User Roles"
        unique_together = ("user", "role")

    def __str__(self):
        return f"{self.user} - {self.role}"


class BankAccount(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    """
    A model to store bank account details associated with a user.

    Attributes:
        user (User): A one-to-one relationship with the User model.
        bank_name (str): The name of the bank where the account is held.
        account_number (str): The bank account number of the user.
        account_name (str): The name associated with the bank account.
    Meta:
        verbose_name (str): A human-readable name for the model class in singular form.
        verbose_name_plural (str): A human-readable name for the model class in plural form.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="bank_account",
        help_text="The user to whom this bank account belongs.",
    )
    bank_name = models.CharField(
        max_length=255,
        help_text="The name of the bank where the account is held.",
    )
    account_number = models.CharField(
        max_length=50,
        help_text="The bank account number of the user.",
    )
    account_name = models.CharField(
        max_length=255,
        help_text="The name associated with the bank account.",
    )
    iban_code = models.CharField(
        max_length=34,
        blank=True,
        null=True,
        help_text="The IBAN number for international and local transactions.",
    )

    def __str__(self):
        """
        Returns a string representation of the bank account.

        Returns:
            str: A string containing the account name and bank name.
        """
        return f"{self.account_name} - {self.bank_name}"

    class Meta:
        db_table = "bank_accounts"
        verbose_name = "Bank Account"
        verbose_name_plural = "Bank Accounts"


class RoleHistory(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    """
    Tracks the history of a user's role across different devices.

    Attributes:
        role (CharField): The role assigned to the user at a specific point in time.
        device_id (CharField): The ID of the device on which the role was active.
        user (ForeignKey): The user whose role is being tracked.

    Meta:
        unique_together: Ensures that each combination of role, device ID, and user is unique.

    Methods:
        __str__(): Returns a string representation of the role history for the user on a specific device.
    """

    role = models.CharField(
        max_length=20, choices=UserRoleChoices.choices + UserRoleBusinessChoices.choices
    )
    device_id = models.CharField(max_length=255, db_index=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="role_histories", db_index=True
    )

    def __str__(self):
        return f"Role history for {self.user} - {self.role} on device {self.device_id}"

    class Meta:
        db_table = "role_histories"
        verbose_name = "Role History"
        verbose_name_plural = "Role Histories"


class FCMToken(CustomIDMixin, TimeStampedModelMixin):
    """
    Model to store FCM (Firebase Cloud Messaging) token details for a user's device.

    Attributes:
        device_id (str): A unique identifier for the user's device.
        device_type (str): The type of device (e.g., "Android", "iOS", "Web").
        fcm_token (str): The FCM token used for sending push notifications to the device.

    Methods:
        __str__(): Returns a string representation of the FCM token object, including the device ID and type.
    """

    user = models.ForeignKey(
        User, related_name="fcm_tokens", on_delete=models.CASCADE, blank=True, null=True
    )
    device_id = models.CharField(
        max_length=255,
        help_text="An identifier provided by the user's device.",
    )
    device_type = models.CharField(
        max_length=50,
        choices=DeviceType.choices,
        help_text="The type of device (e.g., Android, iOS, Web).",
    )
    fcm_token = models.TextField(
        help_text="The FCM token used for sending push notifications.",
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "fcm_tokens"
        verbose_name = "FCM Token"
        verbose_name_plural = "FCM Tokens"

    def __str__(self):
        return f"Device {self.device_id} ({self.device_type})"


class Address(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    """
    A model representing the address of a user.

    Attributes:
        user (User): The user associated with this address.
        address_line (str): The address line of the user.
        country (str): The country of the user's address.
        pincode (str): The pincode of the user's address.

    Meta:
        verbose_name (str): A human-readable name for the model class in singular form.
        verbose_name_plural (str): A human-readable name for the model class in plural form.

    Methods:
        __str__(): Returns a string representation of the address.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    address_line = models.CharField(max_length=255)
    pincode = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=50, blank=True, null=True)
    city = models.CharField(max_length=50, blank=True, null=True)
    nationality = models.CharField(max_length=32)

    class Meta:
        db_table = "addresses"
        verbose_name = "Address"
        verbose_name_plural = "Addresses"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.address_line}"


class OrganizationRiskLevel(
    RiskLevelMixin,
    CustomIDMixin,
    UserTimeStampedModelMixin,
    OwnershipMixin,
):
    is_active = models.BooleanField(default=True)
    allowed_durations = models.ManyToManyField(
        "sooq_althahab_admin.MusharakahDurationChoices",
        related_name="risk_levels",
        help_text="Which durations are allowed for this risk level.",
    )

    class Meta:
        db_table = "risk_levels"
        verbose_name = "Risk Level"
        verbose_name_plural = "Risk Levels"
        ordering = ["risk_level"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization_id", "risk_level"],
                name="unique_org_risk_level_name",
            ),
            models.UniqueConstraint(
                fields=["organization_id", "equity_min"],
                name="unique_org_equity_min",
            ),
        ]

    def __str__(self):
        return self.risk_level


class BusinessAccount(
    SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin, OwnershipMixin
):
    """
    A class representing a business entity.

    Attributes:
        user (User): The user associated with the business.
        name (str): The name of the business.
        musharakah_client_type (str): The type of business, based on the available choices.
        is_existing_business (bool): Whether the business is an existing business or not.

    Document Type Choices:
        NEW: New business.
        GROWTH: Growth-stage business.
        REPUTABLE: Reputable business.

    """

    business_account_type = models.CharField(
        max_length=30, choices=UserRoleBusinessChoices.choices
    )
    name = models.CharField(max_length=255, blank=True, null=True)
    business_original_id = models.CharField(max_length=255, blank=True, null=True)
    musharakah_client_type = models.CharField(
        max_length=25,
        choices=MusharakahClientType.choices,
        help_text="Select the business type",
        default=MusharakahClientType.NEW,
    )
    business_type = models.CharField(
        max_length=50,
        choices=BusinessType.choices,
        default=BusinessType.ESTABLISHMENT,
        help_text="The legal structure or type of the business.",
    )
    is_existing_business = models.BooleanField(default=False)
    logo = models.CharField(
        max_length=500,
        blank=True,
        null=True,
    )
    is_suspended = models.BooleanField(default=False)
    has_received_intro_grace = models.BooleanField(
        default=False,
        help_text="Tracks if the business already received the one-time grace days.",
    )
    intro_grace_consumed_on = models.DateField(
        null=True,
        blank=True,
        help_text="Date when the one-time grace days were applied.",
    )
    vat_account_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="The VAT account number for the business.",
    )
    commercial_registration_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="The Commercial Registration number for the business.",
    )
    risk_level = models.ForeignKey(
        OrganizationRiskLevel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="businesses",
        help_text="Risk level assigned to the business. Required for jewelers/designers.",
    )
    remark = models.TextField(
        null=True,
        blank=True,
        help_text="Reason or remarks for suspending the business account.",
    )

    class Meta:
        db_table = "business_accounts"
        verbose_name = "Business Account"
        verbose_name_plural = "Business Accounts"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Business-{self.name}"


class UserAssignedBusiness(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    """
    Represents the many-to-many relationship between Users and Businesses.

    Attributes:
        user (ForeignKey): The user associated with the business.
        business (ForeignKey): The business associated with the user.
        is_owner (BooleanField): Indicates whether the user is the owner of the business.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="user_assigned_businesses"
    )
    business = models.ForeignKey(
        BusinessAccount,
        on_delete=models.CASCADE,
        related_name="user_assigned_businesses",
    )
    is_owner = models.BooleanField(default=False)

    class Meta:
        db_table = "user_assigned_businesses"
        verbose_name = "User Assigned Business"
        verbose_name_plural = "User Assigned Businesses"
        unique_together = ("user", "business")

    def __str__(self):
        return f"{self.user} - {self.business}"


class BusinessAccountDocument(SoftDeleteModel, CustomIDMixin, models.Model):
    """
    A model representing a business's document.

    Attributes:
        business (Business): The business to which the document belongs.
        doc_type (str): The type of document (e.g., VAT certificate, authorization letter).
        image (str): The document file path for the business.

    Meta:
        verbose_name (str): A human-readable name for the model class in singular form.
        verbose_name_plural (str): A human-readable name for the model class in plural form.

    Methods:
        __str__(): Returns a string representation of the business document.
    """

    business = models.ForeignKey(
        BusinessAccount, on_delete=models.CASCADE, related_name="business_documents"
    )
    doc_type = models.CharField(
        max_length=25,
        choices=DocumentType.choices,
        help_text="Select the business document type",
    )
    image = models.CharField(
        max_length=500,
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "business_documents"
        verbose_name = "BusinessDocument"
        verbose_name_plural = "BusinessDocuments"
        constraints = [
            models.UniqueConstraint(
                fields=["business", "doc_type"],
                name="unique_business_document_type",
            )
        ]

    @property
    def user_id(self):
        return self.business.user.pk


class Shareholder(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    """
    A model representing a shareholder in the business.

    Attributes:
        business (Business): The business to which the shareholder is associated.
        shareholder_name (str): The name of the shareholder.
        role (str): The role of the shareholder (e.g., Director, Authorized Signatory, or Shareholder).
        position (str): The position held by the shareholder in the business.
        id_document (FileField): The ID document of the shareholder.
    """

    business = models.ForeignKey(
        BusinessAccount,
        on_delete=models.CASCADE,
        related_name="shareholders",
        help_text="The business to which this shareholder is associated.",
    )
    name = models.CharField(max_length=255, help_text="The name of the entity.")
    role = models.CharField(
        max_length=25,
        choices=ShareholderRole.choices,
        default=ShareholderRole.SHAREHOLDER,
        help_text="The role of the shareholder in the business.",
    )
    position = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="The position held by the shareholder, if applicable.",
    )
    id_document = models.CharField(
        max_length=500,
        blank=True,
        null=True,
    )

    def __str__(self):
        return f"{self.name} - {self.role} ({self.position})"

    class Meta:
        db_table = "share_holders"
        verbose_name = "Share Holder"
        verbose_name_plural = "Share Holders"


class OrganizationCurrency(CustomIDMixin, TimeStampedModelMixin):
    """
    Model to store currencies associated with an organization.
    """

    currency_code = models.CharField(max_length=10)
    # Conversion rate for the currency.
    rate = models.DecimalField(max_digits=10, decimal_places=4)
    # By default organization will be using default currency and new user who have not set up their currency will be using organization's default currency.
    is_default = models.BooleanField(default=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="currencies"
    )

    class Meta:
        db_table = "organization_currencies"
        verbose_name = "Organization Currency"
        verbose_name_plural = "Organization Currencies"

    def __str__(self):
        return f"{self.currency_code} - {self.rate}"


class UserPreference(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    """
    Model to store user-specific preferences, including default organization currency.

    Attributes:
        user (OneToOneField): The user associated with these preferences.
        organization_currency (ForeignKey): The default currency set for the user.
        language_code (CharField): The user's language preference (Arabic or English).
        timezone (CharField): The user's timezone preference.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="user_preference",
        verbose_name="User",
        help_text="The user associated with these preferences.",
    )
    organization_currency = models.ForeignKey(
        OrganizationCurrency,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_preferences",
        verbose_name="Default Currency",
        help_text="The default organization currency for the user.",
    )
    language_code = models.CharField(
        max_length=2,
        choices=Language.choices,
        default=Language.ENGLISH,
        verbose_name="Language Preference",
        help_text="Select the user's language preference.",
    )
    timezone = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Timezone",
        help_text="The user's preferred timezone.",
    )
    notifications_enabled = models.BooleanField(default=True)
    emails_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "user_preferences"
        verbose_name = "User Preference"
        verbose_name_plural = "User Preferences"

    def __str__(self):
        currency = (
            self.organization_currency.currency_code
            if self.organization_currency
            else "No Currency Set"
        )
        return f"{self.user.username} - {currency}"


class CountryToContinent(CustomIDMixin):
    """
    Represents country and its respective continent.

    Attributes:
        country_name (str): The name of the country.
        continent_name (str): The name of the continent to which the country belongs.
    """

    country = models.CharField(max_length=255)
    continent = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.country} - {self.continent}"


class ContactSupportRequest(
    SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin, OwnershipMixin
):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="contact_supports"
    )
    title = models.CharField(max_length=255)
    query = models.TextField()

    def __str__(self):
        return f"Support Request from {self.user.email} - {self.title}"


class ContactSupportRequestAttachments(
    SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin, OwnershipMixin
):
    contact_support = models.ForeignKey(
        ContactSupportRequest,
        on_delete=models.CASCADE,
        related_name="contact_support_attachments",
    )
    attachment = models.CharField(max_length=255)

    class Meta:
        db_table = "contact_support_request_attachments"
        verbose_name = "Contact Support Request Attachment"
        verbose_name_plural = "Contact Support Request Attachments"

    def __str__(self):
        return str(self.pk)


class Wallet(SoftDeleteModel, CustomIDMixin, TimeStampedModelMixin):
    """
    Represents a user's digital wallet that holds the balance.

    A wallet is linked to a specific user and stores the balance available for deposits and withdrawals.
    The balance can be used to facilitate purchases, payments, or any other transaction within the system.

    Attributes:
        user (ForeignKey): The user who owns the wallet.
        balance (decimal): The current balance in the wallet.
    """

    business = models.ForeignKey(
        BusinessAccount, related_name="wallets", on_delete=models.CASCADE
    )
    balance = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    def __str__(self):
        return f"Wallet of {self.business} - Balance: {self.balance}"

    class Meta:
        db_table = "wallets"
        verbose_name = "Wallet"
        verbose_name_plural = "Wallets"


class Transaction(SoftDeleteModel, CustomIDMixin, ReceiptNumberMixin):
    """Represents a transaction between two business accounts."""

    from sooq_althahab_admin.models import BusinessSubscriptionPlan

    from_business = models.ForeignKey(
        BusinessAccount, related_name="transactions_from", on_delete=models.CASCADE
    )
    to_business = models.ForeignKey(
        BusinessAccount, related_name="transactions_to", on_delete=models.CASCADE
    )
    purchase_request = models.ForeignKey(
        "investor.PurchaseRequest",
        related_name="transactions",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    manufacturing_request = models.ForeignKey(
        "jeweler.ManufacturingRequest",
        related_name="transactions",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    jewelry_production = models.ForeignKey(
        "jeweler.JewelryProduction",
        on_delete=models.CASCADE,
        related_name="transactions",
        null=True,
        blank=True,
    )
    musharakah_contract = models.ForeignKey(
        "jeweler.MusharakahContractRequest",
        on_delete=models.CASCADE,
        related_name="transactions",
        null=True,
        blank=True,
    )
    profit_distribution = models.ForeignKey(
        "jeweler.JewelryProfitDistribution",
        on_delete=models.CASCADE,
        related_name="transactions",
        null=True,
        blank=True,
    )

    musharakah_contract_termination_payment_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        choices=MusharakahContractTerminationPaymentType.choices,
    )
    receipt_number = models.CharField(max_length=50, unique=True)

    # Represents the total value of the purchase request or transaction or manufacturing request
    amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.000"))],
    )

    # The tax rate (e.g., 0.05 for 5%) applied at the time of the transaction or purchase request.
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
        help_text="Tax rate as a decimal (e.g., 0.05 for 5%)",
    )

    # Represents the tax amount calculated based on the organization's tax rate at the time of the purchase request.
    taxes = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    # Represents the platform fee rate and the calculated platform fee amount
    # based on the total transaction amount, as defined by the organization's
    # platform fee settings at the time of the transaction. The rate is stored
    # only if the platform fee type is percentage-based.
    platform_fee_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    # Represents the platform fee amount calculated based on the organization's platform fee settings
    # (either a fixed amount or a percentage of the total transaction), applicable to the purchase
    # request or manufacturing request at the time of the transaction.
    platform_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    # Represents the VAT rate and the calculated VAT amount based on the total transaction amount,
    # as per the organization's VAT settings at the time of the transaction.
    vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
        help_text="VAT rate as a decimal (e.g., 0.15 for 15%)",
    )

    # Represents the VAT amount calculated from the organization's VAT rate,
    # applicable to the purchase request or manufacturing request at the time of the transaction.
    vat = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    # Represents additional service fee related to the purchase request
    service_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    additional_fee = models.DecimalField(
        max_digits=22,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MinValueValidator(Decimal("0.0000"))],
    )
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    status = models.CharField(
        max_length=15,
        choices=TransactionStatus.choices,
        default=TransactionStatus.PENDING,
    )
    reference_number = models.CharField(max_length=100, unique=True, default=uuid.uuid4)
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, related_name="transactions", on_delete=models.CASCADE
    )
    transfer_via = models.CharField(
        max_length=20, choices=TransferVia.choices, null=True, blank=True
    )
    # This field is used to store the reason for status changes, such as approval or rejection remarks.
    remark = models.TextField(null=True, blank=True)
    currency = models.CharField(max_length=20, default="BHD")

    # --- BENEFIT Pay Specific Fields ---
    benefit_payment_id = models.CharField(max_length=100, null=True, blank=True)
    benefit_result = models.CharField(max_length=20, null=True, blank=True)
    benefit_response = models.JSONField(null=True, blank=True)

    # --- Subscription related fields ---
    business_subscription = models.ForeignKey(
        "sooq_althahab_admin.BusinessSubscriptionPlan",
        related_name="transactions",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    # Previous balance before the transaction was created
    previous_balance = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="The amount before the transaction was created.",
    )
    log_details = models.TextField(
        null=True,
        blank=True,
        help_text="Detailed log information from the payment gateway.",
    )

    # Current balance after the transaction was created
    current_balance = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="The amount after the transaction was created.",
    )

    payment_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp indicating when the payment was successfully completed.",
    )

    def __str__(self):
        return f"Transaction {self.reference_number} - From: {self.from_business} To: {self.to_business}"

    class Meta:
        db_table = "transactions"
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"
        constraints = [
            CheckConstraint(
                check=Q(amount__gt=0) | Q(business_subscription__isnull=False),
                name="amount_zero_requires_subscription",
            )
        ]

    def save(self, *args, **kwargs):
        if self.amount == Decimal("0.00") and not self.business_subscription:
            raise ValidationError("Amount should be greater then '0'.")

        if not self.receipt_number:
            self.receipt_number = self.generate_receipt_number(
                users_business=self.from_business,
                transaction_type=self.transaction_type,
                model_cls=Transaction,
            )
        super().save(*args, **kwargs)


class TransactionAttachment(CustomIDMixin, TimeStampedModelMixin):
    """Represents a transaction attachment for payment."""

    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name="transaction_attachments",
        to_field="id",
        db_column="transaction_id",
    )
    attachment = models.CharField(
        max_length=500,
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "transaction_attachments"
        verbose_name = "Transaction Attachment"
        verbose_name_plural = "Transaction Attachments"


class WebhookCall(CustomIDMixin, TimeStampedModelMixin):
    transaction = models.ForeignKey(
        Transaction, related_name="webhook_calls", on_delete=models.CASCADE
    )
    transfer_via = models.CharField(
        max_length=20, choices=TransferVia.choices, default=TransferVia.BENEFIT_PAY
    )
    event_type = models.CharField(max_length=30, choices=WebhookEventType.choices)
    status = models.CharField(
        max_length=20,
        choices=WebhookCallStatus.choices,
        default=WebhookCallStatus.RECEIVED,
    )
    request_headers = models.JSONField(blank=True, null=True)
    request_body = models.JSONField()
    response_body = models.JSONField(blank=True, null=True)
    response_status_code = models.IntegerField(blank=True, null=True)

    def save(self, *args, **kwargs):
        # Run base save first so ID is available for logging
        super().save(*args, **kwargs)

        # 👇 Automatically update linked transaction based on webhook
        if self.transfer_via == TransferVia.BENEFIT_PAY:
            decrypted = self.response_body or {}

            try:
                txn = self.transaction
                result = decrypted.get("result", "").upper()

                txn.benefit_payment_id = decrypted.get("paymentId")
                txn.benefit_result = result
                txn.benefit_response = decrypted

                if result == "CAPTURED":
                    txn.status = TransactionStatus.SUCCESS
                elif self.event_type == WebhookCallStatus.FAILURE:
                    txn.status = TransactionStatus.FAILED

                txn.save(
                    update_fields=[
                        "benefit_payment_id",
                        "benefit_result",
                        "benefit_response",
                        "status",
                    ]
                )
            except Exception as e:
                logger.error(f"[WebhookCall] Failed to update transaction: {e}")

    class Meta:
        db_table = "webhook_calls"
        verbose_name = "Webhook Call"
        verbose_name_plural = "Webhook Calls"
        ordering = ["-created_at"]


class ReceiptSequence(CustomIDMixin, TimeStampedModelMixin):
    mm_yy = models.CharField(max_length=5)
    transaction_code = models.CharField(max_length=10)

    last_sequence = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "receipt_sequences"
        verbose_name = "Receipt Sequence"
        verbose_name_plural = "Receipt Sequences"
        unique_together = ("mm_yy", "transaction_code")
        ordering = ["-created_at"]
