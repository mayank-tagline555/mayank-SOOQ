import os
import random
import uuid
from base64 import b64decode
from base64 import b64encode

from Crypto.Cipher import PKCS1_OAEP
from Crypto.PublicKey import RSA
from django.conf import settings
from django.utils.deconstruct import deconstructible
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from rest_framework_simplejwt.tokens import RefreshToken

from account.models import AdminUserRole
from account.models import BusinessAccount
from account.models import Organization
from account.models import OrganizationRiskLevel
from account.models import UserAssignedBusiness
from account.models import Wallet
from sooq_althahab.billing.subscription.helpers import get_file_url
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.account import UserType
from sooq_althahab.enums.seller import PremiumValueType
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.utils import get_presigned_url_from_s3


@deconstructible
class SafeUpload:
    """
    A callable class used for generating unique and safe file names for uploaded files.

    This class is designed to be used with Django's `upload_to` attribute in a model's
    file field. It ensures that uploaded files have unique and sanitized names by
    combining a slugified version of the original file name with a UUID.

    Attributes:
        upload_folder (str): The directory path where the uploaded files will be stored.

    Methods:
        __call__(instance, filename):
            Generates a new file name by slugifying the original file name, appending
            a UUID, and joining it with the specified upload folder.
    """

    def __init__(
        self,
        upload_folder,
        key=None,
        custom_path_format=False,
        randomize_file_name=True,
    ) -> None:
        self.upload_folder = upload_folder
        self.key = key
        self.custom_path_format = custom_path_format
        self.randomize_file_name = randomize_file_name

    def __call__(self, instance, filename):
        splited_file_name = os.path.splitext(filename)
        safe_name = slugify(splited_file_name[0])
        if self.randomize_file_name:
            safe_name += "_" + uuid.uuid4().hex
        new_filename = f"{safe_name}{splited_file_name[1]}"

        if self.custom_path_format and self.key:
            # Fetch the dynamic value from the instance
            value = getattr(instance, self.key, "default")
            # Replace placeholders in the upload folder path
            folder_path = self.upload_folder.format(key=value)
        else:
            folder_path = self.upload_folder

        return os.path.join(folder_path, new_filename)


def get_latest_user_role(user):
    """
    Fetch the latest role of a user from allowed roles across AdminUserRole
    and UserAssignedBusiness models.
    """

    admin_role = AdminUserRole.objects.filter(user=user).order_by("-updated_at").first()
    if admin_role:
        return admin_role.role

    business_role = (
        UserAssignedBusiness.objects.filter(user=user)
        .select_related("business")
        .order_by("-updated_at")
        .first()
    )
    if business_role:
        return business_role.business.business_account_type
    return None


def generate_otp():
    """
    Generate a numeric OTP (One-Time Password) of the specified length.
    Args:
        length (int): The length of the OTP to be generated. Default is 6.
    Returns:
        str: A randomly generated OTP consisting of numeric characters.
    """

    otp = "".join(random.choices("0123456789", k=settings.OTP_LENGTH))
    return otp


def encrypt_data(plaintext):
    public_key = RSA.importKey(settings.RSA_PUBLIC_KEY_PEM)
    cipher = PKCS1_OAEP.new(public_key)

    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")

    ciphertext = cipher.encrypt(plaintext)
    return b64encode(ciphertext).decode("utf-8")


def decrypt_data(ciphertext):
    private_key = RSA.importKey(settings.RSA_PRIVATE_KEY_PEM)
    cipher = PKCS1_OAEP.new(private_key)

    # Ensure correct padding
    padding_needed = len(ciphertext) % 4
    if padding_needed:
        ciphertext += "=" * (4 - padding_needed)

    decoded_ciphertext = b64decode(ciphertext)
    decrypted_data = cipher.decrypt(decoded_ciphertext)

    return decrypted_data.decode("utf-8").strip()


def create_and_assign_business_to_user(
    user, role, organization, business_name, user_type
):
    business_data = {
        "business_account_type": role,
        "organization_id": organization,
    }

    if role == UserRoleBusinessChoices.JEWELER:
        risk_level = OrganizationRiskLevel.objects.filter(
            organization_id=organization, risk_level="HIGH"
        ).first()
        if risk_level:
            business_data["risk_level"] = risk_level

    if user_type == UserType.BUSINESS and business_name:
        business_data["name"] = business_name

    # Create business
    business = BusinessAccount.objects.create(**business_data)

    # Assigned business to user
    assigned_business = UserAssignedBusiness.objects.create(
        user=user, business=business, is_owner=True
    )

    # Create wallet for business
    Wallet.objects.create(business=business)
    return assigned_business


def generate_tokens(user, email, role, assigned_business=None, organization_code=None):
    refresh = RefreshToken.for_user(user)
    access_token = refresh.access_token
    access_token["role"] = refresh["role"] = role
    access_token["email"] = refresh["email"] = email
    access_token["organization_code"] = refresh["organization_code"] = organization_code
    access_token["current_business"] = refresh["current_business"] = assigned_business

    return {
        "access_token": str(access_token),
        "refresh_token": str(refresh),
    }


def calculate_platform_fee(base_amount, organization):
    """Calculate the platform fee based on the organization's fee type percentage or fixed amount."""

    if organization.platform_fee_type == PremiumValueType.PERCENTAGE:
        return base_amount * organization.platform_fee_rate
    return organization.platform_fee_amount


def get_user_or_business_name(request):
    """Returns the business name if the user has a business or else user's full name."""

    if request.user.user_type == UserType.BUSINESS:
        return get_business_from_user_token(request, "business_name")
    return request.user.fullname


def get_business_display_name(business):
    """
    Get display name for business.
    If business.name is None or empty, use owner's fullname.

    Args:
        business: BusinessAccount instance

    Returns:
        str: Display name for the business
    """
    # If business has a name, use it
    if business.name:
        return business.name

    # For businesses without name, get owner's fullname
    owner_assignment = (
        UserAssignedBusiness.objects.filter(business=business, is_owner=True)
        .select_related("user")
        .first()
    )

    if owner_assignment and owner_assignment.user:
        return (
            owner_assignment.user.fullname or owner_assignment.user.email or "Customer"
        )

    # Fallback: try to get any user's name
    user_assignment = (
        UserAssignedBusiness.objects.filter(business=business)
        .select_related("user")
        .first()
    )

    if user_assignment and user_assignment.user:
        return user_assignment.user.fullname or user_assignment.user.email or "Customer"

    return "Customer"


def get_organization_logo_url_by_code(organization_code):
    """
    Returns organization logo URL for templates.
    Falls back to default image if logo or organization not found.
    """
    default_logo_url = get_file_url("static/images/sqa_golden_logo.png")

    try:
        organization = Organization.objects.get(code=organization_code)
        if organization.logo:
            logo_url = get_presigned_url_from_s3(organization.logo)
            if logo_url and logo_url.get("url"):
                return logo_url.get("url")
    except Organization.DoesNotExist:
        pass

    return default_logo_url
