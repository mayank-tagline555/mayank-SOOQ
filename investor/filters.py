import django_filters
from django.core.exceptions import ValidationError
from django.db.models import Q
from django_filters import rest_framework as filters

from investor.models import AssetContribution
from sooq_althahab.enums.investor import ContributionType
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.sooq_althahab_admin import Status
from sooq_althahab_admin.message import MESSAGES as ADMIN_MESSAGES


class OccupiedStockFilter(django_filters.FilterSet):
    """Filter set for OccupiedStockListAPIView to filter occupied asset contributions."""

    # Date range filters
    created_at_min = django_filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr="gte",
        label="Created From",
        help_text="Filter contributions created from this date (YYYY-MM-DD HH:MM:SS)",
    )

    serial_number = filters.CharFilter(
        method="filter_serial_number",
        label="Serial Number",
    )

    system_serial_number = filters.CharFilter(
        method="filter_system_serial_number",
        label="System Serial Number",
    )

    created_at_max = django_filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr="lte",
        label="Created To",
        help_text="Filter contributions created up to this date (YYYY-MM-DD HH:MM:SS)",
    )

    # Contribution type filter
    contribution_type = django_filters.ChoiceFilter(
        choices=ContributionType.choices,
        field_name="contribution_type",
        label="Contribution Type",
        help_text="Filter by contribution type (POOL, MUSHARAKAH, PRODUCTION_PAYMENT)",
    )

    # Status filters for different contribution types
    musharakah_status = django_filters.MultipleChoiceFilter(
        choices=RequestStatus.choices,
        field_name="musharakah_contract_request__status",
        label="Musharakah Status",
        help_text="Filter by musharakah contract request status",
    )

    pool_status = django_filters.MultipleChoiceFilter(
        choices=Status.choices,
        field_name="pool_contributor__status",
        label="Pool Status",
        help_text="Filter by pool contributor status",
    )

    # Business filters
    business_name = django_filters.CharFilter(
        field_name="business__name",
        lookup_expr="icontains",
        label="Business Name",
        help_text="Filter by business name (case-insensitive search)",
    )

    # Ordering filter
    ordering = django_filters.OrderingFilter(
        fields=(
            ("created_at", "created_at"),
            ("updated_at", "updated_at"),
            ("quantity", "quantity"),
            ("business__name", "business_name"),
        ),
        label="Ordering",
        help_text="Order results by specified fields",
    )

    class Meta:
        model = AssetContribution
        fields = [
            "created_at_min",
            "created_at_max",
            "contribution_type",
            "musharakah_status",
            "pool_status",
            "business_name",
            "serial_number",
            "system_serial_number",
        ]

    def filter_queryset(self, queryset):
        """Override to validate date range before filtering."""
        # Get the filter values
        created_at_min = self.form.cleaned_data.get("created_at_min")
        created_at_max = self.form.cleaned_data.get("created_at_max")

        # Validate date range
        if created_at_min and created_at_max and created_at_min > created_at_max:
            raise ValidationError(ADMIN_MESSAGES["invalid_date_range"])

        return super().filter_queryset(queryset)

    def filter_serial_number(self, queryset, name, value):
        if not value:
            return queryset

        return queryset.filter(
            Q(
                contribution_type=ContributionType.MUSHARAKAH,
                musharakah_contract_request__precious_item_units__serial_number__icontains=value,
            )
            | Q(
                contribution_type=ContributionType.POOL,
                pool__precious_item_units__serial_number__icontains=value,
            )
        ).distinct()

    def filter_system_serial_number(self, queryset, name, value):
        if not value:
            return queryset

        return queryset.filter(
            Q(
                contribution_type=ContributionType.MUSHARAKAH,
                musharakah_contract_request__precious_item_units__system_serial_number__icontains=value,
            )
            | Q(
                contribution_type=ContributionType.POOL,
                pool__precious_item_units__system_serial_number__icontains=value,
            )
        ).distinct()
