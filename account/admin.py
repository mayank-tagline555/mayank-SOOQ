from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from account.forms import UserChangeForm
from account.forms import UserCreationForm
from account.models import Address
from account.models import AdminUserRole
from account.models import BankAccount
from account.models import BusinessAccount
from account.models import BusinessAccountDocument
from account.models import ContactSupportRequest
from account.models import ContactSupportRequestAttachments
from account.models import CountryToContinent
from account.models import FCMToken
from account.models import Organization
from account.models import OrganizationCurrency
from account.models import OrganizationRiskLevel
from account.models import RoleHistory
from account.models import Shareholder
from account.models import User
from account.models import UserAssignedBusiness
from account.models import UserPreference
from account.models import WebhookCall
from sooq_althahab_admin.models import AppVersion
from sooq_althahab_admin.models import Notification


# Register your models here.
class AddressInline(admin.StackedInline):
    model = Address
    extra = 1


class UserAdmin(BaseUserAdmin):
    add_form = UserCreationForm
    form = UserChangeForm
    model = User

    list_display = (
        "id",
        "email",
        "phone_number",
        "get_business_account_type",
        "is_staff",
        "is_active",
    )
    list_filter = ("email", "phone_number", "is_staff", "is_superuser")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Personal info",
            {
                "fields": (
                    "username",
                    "first_name",
                    "last_name",
                    "middle_name",
                    "phone_number",
                    "phone_country_code",
                    "account_status",
                    "organization_id",
                    "personal_number",
                    "profile_image",
                    "user_type",
                    "suspended_by",
                    "access_token_expiration",
                    "deleted_at",
                    "face_verified",
                    "document_verified",
                    "phone_verified",
                    "email_verified",
                    "business_aml_verified",
                    "due_diligence_verified",
                )
            },
        ),
        ("Permissions", {"fields": ("is_staff", "is_active", "is_superuser")}),
        ("Important Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
    )
    search_fields = ("email",)
    ordering = ("email",)
    inlines = [AddressInline]

    def get_business_account_type(self, obj):
        """Returns all user's business account types."""
        business_types = obj.user_assigned_businesses.select_related(
            "business"
        ).values_list("business__business_account_type", flat=True)
        return ", ".join(filter(None, business_types))

    get_business_account_type.short_description = "Business Account Type"
    get_business_account_type.admin_order_field = (
        "user_assigned_businesses__business__business_account_type"
    )


admin.site.register(User, UserAdmin)


class BusinessAccountDocumentInline(admin.TabularInline):
    model = BusinessAccountDocument


@admin.register(BusinessAccount)
class BusinessAccountAdminModel(admin.ModelAdmin):
    """
    Admin view for managing driver profiles.

    Attributes:
        list_display (list): A list of fields to display in the admin list view.
        inlines (list): A list of inline models to include in the admin edit view.
    """

    list_display = [
        "id",
        "name",
        "business_account_type",
        "get_business_owner_email",
        "get_business_verification_status",
        "is_existing_business",
        "vat_account_number",
        "commercial_registration_number",
    ]
    inlines = [BusinessAccountDocumentInline]

    def get_business_owner_email(self, obj):
        """Returns the email of the business owner."""
        owner = (
            obj.user_assigned_businesses.filter(is_owner=True)
            .select_related("user")
            .first()
        )
        return owner.user.email if owner else "No Owner"

    get_business_owner_email.short_description = "Business Owner Email"
    get_business_owner_email.admin_order_field = "user_assigned_businesses__user__email"

    def get_business_verification_status(self, obj):
        """Returns True if business owner is verified (both phone and email verified), False otherwise."""
        owner = (
            obj.user_assigned_businesses.filter(is_owner=True)
            .select_related("user")
            .first()
        )
        if owner and owner.user:
            return owner.user.phone_verified and owner.user.email_verified
        return False

    get_business_verification_status.short_description = "Verified"
    get_business_verification_status.boolean = True
    get_business_verification_status.admin_order_field = (
        "user_assigned_businesses__user__phone_verified"
    )


admin.site.register(AdminUserRole)
admin.site.register(Shareholder)
admin.site.register(RoleHistory)
admin.site.register(CountryToContinent)
admin.site.register(AppVersion)


class ContactSupportRequestAttachmentsInline(admin.TabularInline):
    model = ContactSupportRequestAttachments
    extra = 1


@admin.register(ContactSupportRequest)
class ContactSupportRequestAdminModel(admin.ModelAdmin):
    """
    Admin view for managing driver profiles.

    Attributes:
        list_display (list): A list of fields to display in the admin list view.
        inlines (list): A list of inline models to include in the admin edit view.
    """

    list_display = [
        "id",
        "user",
        "title",
        "query",
    ]
    inlines = [ContactSupportRequestAttachmentsInline]


@admin.register(UserPreference)
class UserPreferenceAdminModel(admin.ModelAdmin):
    list_display = [
        "id",
        "user",
        "language_code",
        "notifications_enabled",
        "emails_enabled",
    ]


@admin.register(WebhookCall)
class WebhookCallAdminModel(admin.ModelAdmin):
    list_display = [
        "id",
        "transaction",
        "event_type",
        "transfer_via",
        "status",
        "created_at",
    ]


@admin.register(BankAccount)
class BankAccountAdminModel(admin.ModelAdmin):
    list_display = ["user", "bank_name", "account_name", "account_number"]


@admin.register(UserAssignedBusiness)
class UserAssignedBusinessAdminModel(admin.ModelAdmin):
    list_display = ["id", "user", "business", "business__business_account_type"]


class FCMTokenAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "device_id", "fcm_token")
    list_filter = ("user",)
    search_fields = ("user__email", "device_id", "fcm_token")
    ordering = ("-id",)


admin.site.register(FCMToken, FCMTokenAdmin)


@admin.register(Notification)
class NotificationAdminModel(admin.ModelAdmin):
    list_display = ["id", "user", "title", "message", "notification_type", "created_at"]
    search_fields = ("user__email",)


@admin.register(OrganizationRiskLevel)
class OrganizationRiskLevelAdminModel(admin.ModelAdmin):
    list_display = [
        "id",
        "risk_level",
        "equity_min",
        "equity_max",
        "max_musharakah_weight",
        "penalty_amount",
        "is_active",
    ]


class OrganizationCurrencyInline(admin.StackedInline):
    model = OrganizationCurrency
    extra = 1


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_at")
    search_fields = ("name",)
    inlines = [OrganizationCurrencyInline]
