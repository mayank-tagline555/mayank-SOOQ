from django.contrib import admin

from manufacturer.models import CorrectionValue
from manufacturer.models import ManufacturingEstimationRequest
from manufacturer.models import ProductManufacturingEstimatedPrice

# # Register your models here.
admin.site.register(CorrectionValue)


@admin.register(ManufacturingEstimationRequest)
class ManufacturingEstimationRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "manufacturing_request", "status", "duration")
    ordering = ("-created_at",)


@admin.register(ProductManufacturingEstimatedPrice)
class ProductManufacturingEstimatedPriceAdmin(admin.ModelAdmin):
    list_display = ("id", "estimation_request", "requested_product", "estimated_price")
    ordering = ("-created_at",)
