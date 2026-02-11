from django.contrib import admin

from seller.models import PreciousItem
from seller.models import PreciousItemImage
from seller.models import PreciousMetal
from seller.models import PreciousStone

# Register your models here.


class PreciousMetalInline(admin.StackedInline):
    model = PreciousMetal
    extra = 1


class PreciousStoneInline(admin.StackedInline):
    model = PreciousStone
    extra = 1


class PreciousItemImageInline(admin.StackedInline):
    model = PreciousItemImage
    extra = 1


class PreciousItemAdmin(admin.ModelAdmin):
    # Fields to display in the list
    list_display = (
        "id",
        "name",
        "material_type",
        "material_item__name",
        "premium_price_rate",
        "premium_price_amount",
        "is_enabled",
        "created_by",
    )

    # Filters for the admin
    list_filter = (
        "precious_metal__precious_item__material_item",
        "precious_stone__precious_item__material_item",
    )

    # Search fields
    search_fields = ("name", "is_enabled", "material_item__name")

    # Add inline models
    inlines = [
        PreciousMetalInline,
        PreciousStoneInline,
        PreciousItemImageInline,
    ]


admin.site.register(PreciousItem, PreciousItemAdmin)
