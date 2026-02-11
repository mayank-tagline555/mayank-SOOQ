from django.contrib import admin

from sooq_althahab_admin.models import BillingDetails
from sooq_althahab_admin.models import BusinessSavedCardToken
from sooq_althahab_admin.models import BusinessSubscriptionPlan
from sooq_althahab_admin.models import GlobalMetal
from sooq_althahab_admin.models import JewelryProductColor
from sooq_althahab_admin.models import JewelryProductType
from sooq_althahab_admin.models import MaterialItem
from sooq_althahab_admin.models import MetalCaratType
from sooq_althahab_admin.models import MetalPriceHistory
from sooq_althahab_admin.models import OrganizationBankAccount
from sooq_althahab_admin.models import Pool
from sooq_althahab_admin.models import PoolContribution
from sooq_althahab_admin.models import StoneClarity
from sooq_althahab_admin.models import StoneCutShape
from sooq_althahab_admin.models import SubscriptionPlan


@admin.register(MaterialItem)
class MaterialTypeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "material_type",
        "created_at",
        "is_enabled",
    )
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(GlobalMetal)
class GlobalMetalAdmin(admin.ModelAdmin):
    list_display = ("name", "symbol", "created_at")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(MetalPriceHistory)
class MetalPriceHistoryAdmin(admin.ModelAdmin):
    list_display = ("global_metal", "price", "price_on_date", "created_at")
    search_fields = ("global_metal__name",)
    ordering = ("-created_at",)


@admin.register(OrganizationBankAccount)
class OrganizationBankAccountAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "bank_name",
        "account_number",
        "account_name",
        "iban_code",
        "swift_code",
    )
    ordering = ("-created_at",)


@admin.register(StoneCutShape)
class StoneCutShapeAdmin(admin.ModelAdmin):
    list_display = ("id", "organization_id", "name", "is_enabled")
    ordering = ("-created_at",)


@admin.register(MetalCaratType)
class MetalCaratTypeAdmin(admin.ModelAdmin):
    list_display = ("id", "organization_id", "name", "purity_percentage", "is_enabled")
    ordering = ("-created_at",)


@admin.register(Pool)
class PoolAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "material_item__name",
        "carat_type__name",
        "musharakah_contract_request__id",
    )
    ordering = ("-created_at",)
    search_fields = ("name",)


@admin.register(PoolContribution)
class PoolContributionAdmin(admin.ModelAdmin):
    list_display = ("id", "pool", "participant", "status")
    ordering = ("-created_at",)


@admin.register(JewelryProductColor)
class JewelryProductColorAdmin(admin.ModelAdmin):
    list_display = ("id", "organization_id", "name", "is_enabled")
    ordering = ("-created_at",)


@admin.register(StoneClarity)
class StoneClarityAdmin(admin.ModelAdmin):
    list_display = ("id", "organization_id", "name", "is_enabled")
    ordering = ("-created_at",)


@admin.register(JewelryProductType)
class JewelryProductTypeAdmin(admin.ModelAdmin):
    list_display = ("id", "organization_id", "name", "is_enabled")
    ordering = ("-created_at",)


@admin.register(BillingDetails)
class BillingDetailsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "business",
        "receipt_number",
        "period_start_date",
        "period_end_date",
        "payment_status",
        "base_amount",
        "vat_amount",
        "total_amount",
    )
    ordering = ("-created_at",)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "role",
        "translated_names",
        "subscription_code",
        "business_type",
        "payment_type",
        "pro_rata_rate",
    )
    fieldsets = (
        (
            "Basic Information",
            {
                "fields": (
                    "name",
                    "translated_names",
                    "role",
                    "business_type",
                    "subscription_code",
                    "description",
                    "is_active",
                    "created_by",
                    "organization_id",
                )
            },
        ),
        (
            "Billing Configuration",
            {
                "fields": (
                    "duration",
                    "billing_frequency",
                    "payment_interval",
                    "payment_amount_variability",
                    "payment_type",
                )
            },
        ),
        (
            "Pricing",
            {
                "fields": (
                    "subscription_fee",
                    "discounted_fee",
                    "commission_rate",
                    "pro_rata_rate",
                )
            },
        ),
        (
            "Free Trial Limitations (JEWELER role only)",
            {
                "fields": (
                    "musharakah_request_max_weight",
                    "metal_purchase_max_weight",
                    "max_design_count",
                    "features",
                ),
                "description": "These fields only apply to JEWELER role with FREE_TRIAL payment type.",
            },
        ),
    )
    ordering = ("-created_at",)


@admin.register(BusinessSubscriptionPlan)
class BusinessSubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "get_business_owner_email",
        "subscription_plan",
        "start_date",
        "expiry_date",
        "next_billing_date",
        "payment_interval",
        "billing_frequency",
        "status",
        "subscription_fee",
        "commission_rate",
        "pro_rata_rate",
    )
    list_filter = (
        "status",
        "payment_type",
        "billing_frequency",
        "payment_interval",
        "start_date",
        "next_billing_date",
        "expiry_date",
    )
    ordering = ("-created_at",)

    def get_queryset(self, request):
        """Optimize queryset with select_related and prefetch_related for better performance."""
        return (
            super()
            .get_queryset(request)
            .select_related("business", "subscription_plan")
            .prefetch_related("business__user_assigned_businesses__user")
        )

    def get_business_owner_email(self, obj):
        """Returns the email of the business owner with business name."""
        if not obj.business:
            return "No Business"
        owner = (
            obj.business.user_assigned_businesses.filter(is_owner=True)
            .select_related("user")
            .first()
        )
        if not owner:
            # If business name is not available, assume Individual user
            if obj.business.name:
                return f"No Owner ({obj.business.name})"
            return "No Owner"

        email = owner.user.email
        # If business name is not available, assume Individual user - show only email
        if obj.business.name:
            return f"{email} ({obj.business.name})"
        return email

    get_business_owner_email.short_description = "Business Owner"
    get_business_owner_email.admin_order_field = (
        "business__user_assigned_businesses__user__email"
    )


@admin.register(BusinessSavedCardToken)
class BusinessSavedCardTokenAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "business_display",
        "masked_number",
        "card_brand",
        "card_type",
        "expiry_date",
        "is_used_for_subscription",
        "created_at",
        "updated_at",
        "created_by",
    )
    list_filter = (
        "card_brand",
        "card_type",
        "is_used_for_subscription",
    )
    search_fields = (
        "business__name",
        "token",
        "number",
        "card_brand",
        "card_type",
    )
    readonly_fields = (
        "id",
        "token",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)
    list_per_page = 25

    fieldsets = (
        (
            "Card Information",
            {
                "fields": (
                    "id",
                    "business",
                    "token",
                    "number",
                    "expiry_month",
                    "expiry_year",
                    "card_type",
                    "card_brand",
                    "is_used_for_subscription",
                    "created_by",
                )
            },
        ),
        (
            "Audit Information",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def masked_number(self, obj):
        """Display masked card number for security."""
        if obj.number and len(obj.number) >= 4:
            return f"**** **** **** {obj.number[-4:]}"
        return "****"

    masked_number.short_description = "Card Number"
    masked_number.admin_order_field = "number"

    def expiry_date(self, obj):
        """Display formatted expiry date."""
        if obj.expiry_month and obj.expiry_year:
            return f"{obj.expiry_month}/{obj.expiry_year}"
        return "-"

    expiry_date.short_description = "Expiry Date"
    expiry_date.admin_order_field = "expiry_year"

    def get_queryset(self, request):
        """Optimize queryset with select_related for better performance."""
        return (
            super()
            .get_queryset(request)
            .select_related("business")
            .filter(business__isnull=False)  # Filter out orphaned records
        )

    def business_display(self, obj):
        """Display business name with error handling for deleted businesses."""
        try:
            return obj.business.name if obj.business else "DELETED BUSINESS"
        except:
            return "DELETED BUSINESS"

    business_display.short_description = "Business"
    business_display.admin_order_field = "business__name"

    def get_actions(self, request):
        """Add custom actions for cleaning up orphaned records."""
        actions = super().get_actions(request)
        actions["cleanup_orphaned_tokens"] = (
            self.cleanup_orphaned_tokens,
            "cleanup_orphaned_tokens",
            "Clean up orphaned card tokens (where business is deleted)",
        )
        return actions

    def cleanup_orphaned_tokens(self, request, queryset):
        """Action to clean up orphaned card tokens."""
        from django.db import transaction

        with transaction.atomic():
            # Find tokens where business is null or deleted
            orphaned_count = queryset.filter(business__isnull=True).count()
            queryset.filter(business__isnull=True).delete()

        self.message_user(
            request,
            f"Successfully cleaned up {orphaned_count} orphaned card tokens.",
            level="SUCCESS",
        )

    cleanup_orphaned_tokens.short_description = "Clean up orphaned card tokens"
