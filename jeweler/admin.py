from django.contrib import admin

from sooq_althahab_admin.models import MusharakahDurationChoices

# Register your models here.
from .models import InspectedRejectedJewelryProduct
from .models import InspectionRejectionAttachment
from .models import JewelryDesign
from .models import JewelryProduct
from .models import JewelryProductAttachment
from .models import JewelryProductInspectionAttachment
from .models import JewelryProduction
from .models import JewelryProductMarketplace
from .models import JewelryProductMarketplaceImage
from .models import JewelryProductMaterial
from .models import JewelryProductStonePrice
from .models import JewelryProfitDistribution
from .models import JewelryStock
from .models import JewelryStockRestockRequest
from .models import JewelryStockSale
from .models import ManufacturingProductRequestedQuantity
from .models import ManufacturingRequest
from .models import ManufacturingTarget
from .models import MusharakahContractDesign
from .models import MusharakahContractRenewal
from .models import MusharakahContractRequest
from .models import MusharakahContractRequestAttachment
from .models import MusharakahContractRequestQuantity
from .models import MusharakahContractTerminationRequest
from .models import ProductionPayment
from .models import ProductionPaymentAssetAllocation


@admin.register(JewelryDesign)
class JewelryDesignAdmin(admin.ModelAdmin):
    list_display = ("id", "business", "design_type", "name", "description", "duration")
    list_filter = ("design_type",)
    ordering = ("-created_at",)


class JewelryProductAttachmentInline(admin.StackedInline):
    model = JewelryProductAttachment
    extra = 1


class JewelryProductMaterialInline(admin.StackedInline):
    model = JewelryProductMaterial
    extra = 1


@admin.register(JewelryProduct)
class JewelryProductAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "jewelry_design",
        "product_name",
        "product_type",
        "premium_price",
        "metal_price",
    )
    list_filter = ("product_type",)
    ordering = ("-created_at",)

    # Add inline models
    inlines = [JewelryProductAttachmentInline, JewelryProductMaterialInline]


class MusharakahContractRequestAttachmentInline(admin.StackedInline):
    model = MusharakahContractRequestAttachment
    extra = 1


class MusharakahContractRequestQuantityInline(admin.StackedInline):
    model = MusharakahContractRequestQuantity
    extra = 1


@admin.register(MusharakahContractRequest)
class MusharakahContractRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "musharakah_contract_status",
        "created_at",
        "terminated_musharakah_contract",
    )
    list_filter = ("status",)
    ordering = ("-created_at",)

    # Add inline models
    inlines = [
        MusharakahContractRequestAttachmentInline,
        MusharakahContractRequestQuantityInline,
    ]


@admin.register(MusharakahContractDesign)
class MusharakahContractDesignAdmin(admin.ModelAdmin):
    list_display = ("id", "musharakah_contract_request", "design")
    ordering = ("-created_at",)


@admin.register(MusharakahContractRequestQuantity)
class MusharakahContractRequestQuantityAdmin(admin.ModelAdmin):
    list_display = ("id", "musharakah_contract_request", "jewelry_product", "quantity")
    ordering = ("-created_at",)


@admin.register(MusharakahContractTerminationRequest)
class MusharakahContractTerminationRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "musharakah_contract_request",
        "status",
        "logistics_cost",
        "insurance_fee",
    )
    ordering = ("-created_at",)


@admin.register(MusharakahContractRenewal)
class MusharakahContractRenewalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "musharakah_contract_request",
        "duration_in_days",
    )
    ordering = ("-created_at",)


@admin.register(MusharakahDurationChoices)
class MusharakahDurationChoicesAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "days", "is_active")
    ordering = ("-created_at",)


class ManufacturingProductRequestedQuantityInline(admin.StackedInline):
    model = ManufacturingProductRequestedQuantity
    extra = 1


class ManufacturingTargetInline(admin.StackedInline):
    model = ManufacturingTarget
    extra = 1


@admin.register(ManufacturingRequest)
class ManufacturingRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "business",
        "status",
        "design",
        "manufacturer_type",
    )
    list_filter = ("status",)
    ordering = ("-created_at",)
    inlines = [ManufacturingProductRequestedQuantityInline, ManufacturingTargetInline]


@admin.register(JewelryProduction)
class JewelryProductionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "manufacturing_request",
        "design",
        "manufacturer",
        "production_status",
        "is_jeweler_approved",
        "admin_inspection_status",
        "is_payment_completed",
    )
    ordering = ("-created_at",)


admin.site.register(JewelryProductStonePrice)
admin.site.register(JewelryProductInspectionAttachment)
admin.site.register(InspectedRejectedJewelryProduct)
admin.site.register(InspectionRejectionAttachment)


@admin.register(ProductionPayment)
class ProductionPaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "musharakah_contract",
        "jewelry_production",
        "payment_type",
    )
    ordering = ("-created_at",)


@admin.register(ProductionPaymentAssetAllocation)
class ProductionPaymentAssetAllocationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "production_payment",
        "precious_item_unit_asset",
        "precious_item_unit_musharakah",
        "musharakah_contract",
        "weight",
    )
    ordering = ("-created_at",)


#######################################################################################
############################### Jewelry Stock Management Admin ######################
#######################################################################################


@admin.register(JewelryStock)
class JewelryStockAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "jewelry_product",
        "showroom_quantity",
        "marketplace_quantity",
        "showroom_status",
        "marketplace_status",
        "location",
        "is_published_to_marketplace",
        "created_at",
    )
    list_filter = (
        "showroom_status",
        "marketplace_status",
        "location",
        "is_published_to_marketplace",
    )
    search_fields = (
        "jewelry_product__product_name",
        "jewelry_product__jewelry_design__name",
    )
    ordering = ("-created_at",)
    readonly_fields = ("total_quantity",)

    fieldsets = (
        (
            "Product Information",
            {
                "fields": (
                    "jewelry_product",
                    "manufacturing_product",
                )
            },
        ),
        (
            "Stock Quantities",
            {
                "fields": (
                    "showroom_quantity",
                    "marketplace_quantity",
                    "total_quantity",
                )
            },
        ),
        (
            "Stock Status",
            {
                "fields": (
                    "showroom_status",
                    "marketplace_status",
                    "location",
                    "is_published_to_marketplace",
                )
            },
        ),
    )


class JewelryProductMarketplaceImageInline(admin.StackedInline):
    model = JewelryProductMarketplaceImage
    extra = 1
    fields = ("image",)


@admin.register(JewelryProductMarketplace)
class JewelryProductMarketplaceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "jewelry_product",
        "published_quantity",
        "is_active",
        "published_at",
        "unpublished_at",
    )
    list_filter = ("is_active",)
    search_fields = (
        "jewelry_product__product_name",
        "description",
    )
    ordering = ("-published_at",)
    date_hierarchy = "published_at"
    inlines = [JewelryProductMarketplaceImageInline]

    fieldsets = (
        (
            "Product Information",
            {
                "fields": (
                    "jewelry_product",
                    "jewelry_stock",
                )
            },
        ),
        (
            "Marketplace Details",
            {
                "fields": (
                    "published_quantity",
                    "description",
                    "is_active",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "published_at",
                    "unpublished_at",
                )
            },
        ),
    )


@admin.register(JewelryStockRestockRequest)
class JewelryStockRestockRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "jewelry_stock",
        "requested_quantity",
        "restock_location",
        "status",
        "requested_date",
        "created_at",
    )
    list_filter = (
        "status",
        "restock_location",
    )
    search_fields = (
        "jewelry_stock__jewelry_product__product_name",
        "notes",
    )
    ordering = ("-created_at",)
    date_hierarchy = "requested_date"

    fieldsets = (
        (
            "Stock Information",
            {"fields": ("jewelry_stock",)},
        ),
        (
            "Restock Details",
            {
                "fields": (
                    "requested_quantity",
                    "restock_location",
                    "requested_date",
                    "notes",
                )
            },
        ),
        (
            "Status",
            {"fields": ("status",)},
        ),
    )


#######################################################################################
############################### Sales & Profit Distribution Admin ####################
#######################################################################################


@admin.register(JewelryStockSale)
class JewelryStockSaleAdmin(admin.ModelAdmin):
    list_display = (
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
    )
    list_filter = (
        "sale_location",
        "sale_date",
    )
    search_fields = (
        "jewelry_product__product_name",
        "customer_name",
        "customer_email",
        "customer_phone",
    )
    ordering = ("-sale_date", "-created_at")
    date_hierarchy = "sale_date"
    readonly_fields = ("unit_price",)

    fieldsets = (
        (
            "Product Information",
            {
                "fields": (
                    "manufacturing_request",
                    "jewelry_product",
                    "jewelry_stock",
                )
            },
        ),
        (
            "Sale Details",
            {
                "fields": (
                    "sale_location",
                    "quantity",
                    "sale_price",
                    "unit_price",
                    "sale_date",
                )
            },
        ),
        (
            "Customer Information",
            {
                "fields": (
                    "customer_name",
                    "customer_email",
                    "customer_phone",
                    "notes",
                )
            },
        ),
        (
            "Delivery Information",
            {
                "fields": (
                    "status",
                    "delivery_date",
                    "delivery_address",
                    "delivered_at",
                )
            },
        ),
    )


@admin.register(JewelryProfitDistribution)
class JewelryProfitDistributionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "jewelry_sale",
        "recipient_business",
        "recipient_type",
        "revenue",
        "profit_share_percentage",
        "profit_amount",
        "distributed_at",
        "created_at",
    )

    list_filter = ("recipient_type",)

    search_fields = (
        "jewelry_sale__jewelry_product__product_name",
        "recipient_business__name",
        "musharakah_contract__id",
    )

    ordering = ("-created_at",)

    date_hierarchy = "distributed_at"

    readonly_fields = ("revenue", "profit_amount")

    fieldsets = (
        (
            "Sale & Contract Information",
            {
                "fields": (
                    "jewelry_sale",
                    "musharakah_contract",
                )
            },
        ),
        (
            "Recipient Information",
            {
                "fields": (
                    "recipient_business",
                    "recipient_type",
                )
            },
        ),
        (
            "Financial Details",
            {
                "fields": (
                    "cost_of_repurchasing_metal",
                    "revenue",
                    "profit_share_percentage",
                    "profit_amount",
                )
            },
        ),
        (
            "Distribution Status",
            {"fields": ("distributed_at",)},
        ),
    )
