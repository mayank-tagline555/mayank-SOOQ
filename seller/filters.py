import django_filters
from django.db.models import F
from django.db.models import FloatField
from django.db.models.functions import Cast
from django.db.models.functions import Coalesce
from django.db.models.functions import Greatest
from django_filters import rest_framework as filters

from investor.models import AssetContribution
from investor.models import PurchaseRequest
from investor.utils import get_investors_total_assets
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.enums.investor import RequestType
from sooq_althahab.enums.sooq_althahab_admin import MaterialType

from .models import PreciousItem


class PreciousItemFilter(django_filters.FilterSet):
    """Filter set for PreciousItem model, allowing filtering by various fields."""

    is_enabled = django_filters.BooleanFilter(field_name="is_enabled", required=False)

    # Numeric filters for `weight` range (filter on related PreciousMetal model)
    min_weight = django_filters.NumberFilter(method="filter_min_weight", min_value=0)
    max_weight = django_filters.NumberFilter(method="filter_max_weight", min_value=1)

    # Ordering filter - allows users to order results by these fields
    ordering = django_filters.OrderingFilter(
        fields=(
            ("created_at", "created_at"),
            ("weight", "weight"),  # Enable ordering based on weight
        ),
        label="Ordering",
    )

    material_type = django_filters.CharFilter(
        field_name="material_type", lookup_expr="icontains", required=False
    )
    material_item = django_filters.CharFilter(
        field_name="material_item__pk", lookup_expr="icontains", required=False
    )

    def filter_min_weight(self, queryset, name, value):
        """Filters items where the max weight is >= min_weight."""

        return queryset.annotate(
            weight=Greatest(F("precious_metal__weight"), F("precious_stone__weight"))
        ).filter(weight__gte=value)

    def filter_max_weight(self, queryset, name, value):
        """Filters items where the max weight is <= max_weight."""

        return queryset.annotate(
            weight=Greatest(F("precious_metal__weight"), F("precious_stone__weight"))
        ).filter(weight__lte=value)

    def filter_queryset(self, queryset):
        """Ensure that weight annotation is applied globally for ordering and filtering."""

        queryset = queryset.annotate(
            weight=Greatest(F("precious_metal__weight"), F("precious_stone__weight"))
        )
        return super().filter_queryset(queryset)

    class Meta:
        model = PreciousItem
        fields = [
            "is_enabled",
            "material_type",
            "material_item",
            "min_weight",
            "max_weight",
        ]


class BusinessTypeFilter(django_filters.FilterSet):
    """Filter purchase requests based on business account type (INVESTOR or JEWELER)."""

    business_type = django_filters.CharFilter(
        field_name="business__business_account_type",
        lookup_expr="iexact",
    )

    class Meta:
        model = PurchaseRequest
        fields = ["business_type"]


class PurchaseRequestFilter(django_filters.FilterSet):
    """Filter set for the PurchaseRequest model, allowing filtering by various fields."""

    status = filters.MultipleChoiceFilter(
        choices=PurchaseRequestStatus.choices, method="filter_status"
    )
    serial_number = filters.CharFilter(
        method="filter_serial_number",
        label="Serial Number",
    )

    system_serial_number = filters.CharFilter(
        method="filter_system_serial_number",
        label="System Serial Number",
    )
    material_type = filters.MultipleChoiceFilter(
        choices=MaterialType.choices, method="filter_material_type"
    )
    request_type = filters.MultipleChoiceFilter(
        choices=RequestType.choices, method="filter_request_type"
    )
    precious_item = filters.CharFilter(
        field_name="precious_item__name", lookup_expr="icontains"
    )
    total_cost_min = filters.NumberFilter(
        field_name="total_cost", lookup_expr="gte", min_value=1
    )
    total_cost_max = filters.NumberFilter(
        field_name="total_cost", lookup_expr="lte", min_value=1
    )
    order_cost_min = filters.NumberFilter(
        field_name="order_cost", lookup_expr="gte", min_value=1
    )
    order_cost_max = filters.NumberFilter(
        field_name="order_cost", lookup_expr="lte", min_value=1
    )
    created_at_min = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_max = filters.DateTimeFilter(
        field_name="created_at__date", lookup_expr="lte"
    )

    # Ordering filter - allows users to order results by these fields
    ordering = django_filters.OrderingFilter(
        fields=(
            ("created_at", "created_at"),
            ("total_cost", "total_cost"),
        ),
        label="Ordering",
    )

    # Filter unsold assets by excluding purchase requests linked to a sale request
    unsold_assets = filters.BooleanFilter(method="filter_unsold_assets")

    weight_ordering = filters.ChoiceFilter(
        choices=(("asc", "Low to High"), ("desc", "High to Low")),
        method="filter_by_weight",
        label="Sort by Weight",
    )

    def filter_status(self, queryset, name, value):
        """Custom filtering for status field."""

        if value:
            return queryset.filter(status__in=value)
        return queryset

    def filter_material_type(self, queryset, name, value):
        """Filter assets request based on the material type (metal or stone)."""
        return queryset.filter(precious_item__material_type__in=value)

    def filter_request_type(self, queryset, name, value):
        """Filter assets request based on the request type (Purchase or Sale)."""
        return queryset.filter(request_type__in=value)

    def filter_unsold_assets(self, queryset, name, value):
        """Filter unsold assets by excluding purchase requests linked to a sale request."""
        if value:
            return get_investors_total_assets(queryset)
        return queryset

    def filter_by_weight(self, queryset, name, value):
        """
        Sorts Purchase Requests based on weight:
        - If filtered by metal → use metal weight
        - If filtered by stone → use stone weight
        - If no material_type filter applied → use coalesced weight
        """
        material_type_param = self.data.get("material_type")

        if material_type_param == MaterialType.METAL:
            queryset = queryset.annotate(
                weight=Cast("precious_item__precious_metal__weight", FloatField())
            )
        elif material_type_param == MaterialType.STONE:
            queryset = queryset.annotate(
                weight=Cast("precious_item__precious_stone__weight", FloatField())
            )
        else:
            queryset = queryset.annotate(
                weight=Coalesce(
                    Cast("precious_item__precious_metal__weight", FloatField()),
                    Cast("precious_item__precious_stone__weight", FloatField()),
                )
            )

        if value == "asc":
            return queryset.order_by("weight")
        elif value == "desc":
            return queryset.order_by("-weight")

        return queryset

    def filter_serial_number(self, queryset, name, value):
        if value:
            return queryset.filter(
                precious_item_units__serial_number__icontains=value
            ).distinct()
        return queryset

    def filter_system_serial_number(self, queryset, name, value):
        if value:
            return queryset.filter(
                precious_item_units__system_serial_number__icontains=value
            ).distinct()
        return queryset

    class Meta:
        model = PurchaseRequest
        fields = [
            "status",
            "material_type",
            "request_type",
            "precious_item",
            "total_cost_min",
            "total_cost_max",
            "created_at_min",
            "created_at_max",
            "unsold_assets",
            "weight_ordering",
            "order_cost_min",
            "order_cost_max",
            "serial_number",
            "system_serial_number",
        ]


class AssetContributionFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(
        field_name="purchase_request__status", lookup_expr="iexact"
    )

    material_item = django_filters.CharFilter(
        field_name="purchase_request__precious_item__material_item__name",
        lookup_expr="icontains",
    )

    material_type = django_filters.CharFilter(
        field_name="purchase_request__precious_item__material_type",
        lookup_expr="iexact",
    )

    request_type = django_filters.CharFilter(
        field_name="purchase_request__request_type", lookup_expr="iexact"
    )

    total_cost_min = django_filters.NumberFilter(
        field_name="purchase_request__total_cost", lookup_expr="gte", min_value=1
    )

    total_cost_max = django_filters.NumberFilter(
        field_name="purchase_request__total_cost", lookup_expr="lte", min_value=1
    )

    created_at_min = django_filters.DateTimeFilter(
        field_name="purchase_request__created_at", lookup_expr="gte"
    )

    created_at_max = django_filters.DateTimeFilter(
        field_name="purchase_request__created_at__date", lookup_expr="lte"
    )

    min_weight = django_filters.NumberFilter(method="filter_min_weight", min_value=0)
    max_weight = django_filters.NumberFilter(method="filter_max_weight", min_value=0)

    weight_ordering = django_filters.ChoiceFilter(
        choices=(("asc", "Low to High"), ("desc", "High to Low")),
        method="filter_by_weight",
        label="Sort by Weight",
    )

    ordering = django_filters.OrderingFilter(
        fields=(
            ("purchase_request__created_at", "created_at"),
            ("purchase_request__total_cost", "total_cost"),
        )
    )

    class Meta:
        model = AssetContribution
        fields = [
            "status",
            "material_type",
            "material_item",
            "request_type",
            "total_cost_min",
            "total_cost_max",
            "created_at_min",
            "created_at_max",
            "min_weight",
            "max_weight",
        ]

    def annotate_weight(self, queryset):
        return queryset.annotate(
            weight=Coalesce(
                Cast(
                    F("purchase_request__precious_item__precious_metal__weight"),
                    FloatField(),
                ),
                Cast(
                    F("purchase_request__precious_item__precious_stone__weight"),
                    FloatField(),
                ),
            )
        )

    def filter_queryset(self, queryset):
        queryset = self.annotate_weight(queryset)
        return super().filter_queryset(queryset)

    def filter_min_weight(self, queryset, name, value):
        return queryset.filter(weight__gte=value)

    def filter_max_weight(self, queryset, name, value):
        return queryset.filter(weight__lte=value)

    def filter_by_weight(self, queryset, name, value):
        queryset = self.annotate_weight(queryset)
        if value == "asc":
            return queryset.order_by("weight")
        elif value == "desc":
            return queryset.order_by("-weight")
        return queryset
