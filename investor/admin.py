from django.contrib import admin

from account.models import Transaction
from account.models import TransactionAttachment
from account.models import Wallet
from investor.models import AssetContribution
from investor.models import PreciousItemUnit
from investor.models import PreciousItemUnitMusharakahHistory
from investor.models import PurchaseRequest


@admin.register(PurchaseRequest)
class PurchaseRequestAdminModel(admin.ModelAdmin):
    list_display = [
        "id",
        "status",
        "request_type",
        "requested_quantity",
        "order_cost",
        "premium",
        "precious_item",
        "invoice_number",
        "created_by",
        "total_cost",
    ]


@admin.register(AssetContribution)
class AssetContributionAdminModel(admin.ModelAdmin):
    list_display = [
        "id",
        "quantity",
        "contribution_type",
        "purchase_request",
        "created_at",
        "status",
        "musharakah_contract_request",
        "production_payment",
    ]
    # TODO: Temporarily disabling 'readonly_fields' for developer testing.
    # Uncomment this line once functionality is finalized.
    # readonly_fields = ["id", "quantity", "contribution_type"]
    ordering = ["-created_at"]


@admin.register(Wallet)
class WalletAdminModel(admin.ModelAdmin):
    list_display = ["id", "business", "get_business_owner_email", "balance"]

    def get_business_owner_email(self, obj):
        """Returns the email of the business owner."""
        owner = (
            obj.business.user_assigned_businesses.filter(is_owner=True)
            .select_related("user")
            .first()
        )
        return owner.user.email if owner else "No Owner"

    get_business_owner_email.short_description = "Business Owner Email"
    get_business_owner_email.admin_order_field = (
        "business__user_assigned_businesses__user__email"
    )


class TransactionAttachmentInline(admin.StackedInline):
    model = TransactionAttachment
    extra = 1
    readonly_fields = ("id",)
    fields = ("id", "attachment")


class TransactionAdmin(admin.ModelAdmin):
    # Fields to display in the admin list view
    list_display = (
        "id",
        "receipt_number",
        "from_business",
        "to_business",
        "transaction_type",
        "amount",
        "status",
        "transfer_via",
        "created_at",
    )

    inlines = [TransactionAttachmentInline]
    search_fields = (
        "status",
        "transfer_via",
        "pk",
        "from_business__name",
        "to_business__name",
    )
    list_filter = ("status", "transfer_via")
    ordering = ["-created_at"]


admin.site.register(Transaction, TransactionAdmin)


@admin.register(PreciousItemUnit)
class PreciousItemUnitAdminModel(admin.ModelAdmin):
    list_display = [
        "id",
        "serial_number",
        "system_serial_number",
        "purchase_request",
        "precious_item",
        "musharakah_contract",
    ]


@admin.register(PreciousItemUnitMusharakahHistory)
class PreciousItemUnitMusharakahHistoryAdminModel(admin.ModelAdmin):
    list_display = [
        "id",
        "precious_item_unit",
        "musharakah_contract",
        "contributed_weight",
    ]
