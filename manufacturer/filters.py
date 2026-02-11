import django_filters
from django.db.models import Q
from django_filters import rest_framework as filters

from jeweler.models import JewelryProduction
from jeweler.models import ManufacturingRequest
from sooq_althahab.enums.jeweler import InspectionStatus
from sooq_althahab.enums.jeweler import ProductionStatus
from sooq_althahab.enums.manufacturer import ManufactureRequestStatus
from sooq_althahab.querysets.purchase_request import get_business_from_user_token


class ManufacturingRequestFilter(django_filters.FilterSet):
    estimation_status = django_filters.MultipleChoiceFilter(
        method="filter_by_estimation_status",
        choices=ManufactureRequestStatus.choices,
        label="Estimation Status",
    )

    created_at_min = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_max = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    business_name = django_filters.CharFilter(
        method="filter_by_business_name_or_user_fullname",
        label="Business Name or User Full Name",
    )
    ordering = django_filters.OrderingFilter(
        fields=(("created_at", "created_at"),),
    )

    class Meta:
        model = ManufacturingRequest
        fields = [
            "estimation_status",
            "created_at_min",
            "created_at_max",
            "business_name",
        ]

    def filter_by_estimation_status(self, queryset, name, value):
        """
        Filter by the current user's estimation status, not all estimation statuses.
        This ensures that each manufacturer only sees their own estimation status.
        """
        if not value:
            return queryset

        # Get the current user's business from the request
        request = self.request
        if not request:
            return queryset

        business = get_business_from_user_token(request, "business")
        if not business:
            return queryset

        # Filter by estimation status for the current user's business only
        return queryset.filter(
            estimation_requests__status__in=value,
            estimation_requests__business=business,
        ).distinct()

    def filter_by_business_name_or_user_fullname(self, queryset, name, value):
        if not value:
            return queryset

        # Create search criteria for different fields
        search_criteria = []

        # Business name search (exclude null and empty strings)
        search_criteria.append(
            Q(business__name__icontains=value)
            & Q(business__name__isnull=False)
            & ~Q(business__name="")
        )

        # User name searches (exclude null values)
        search_criteria.append(
            Q(created_by__first_name__icontains=value)
            & Q(created_by__first_name__isnull=False)
        )
        search_criteria.append(
            Q(created_by__middle_name__icontains=value)
            & Q(created_by__middle_name__isnull=False)
        )
        search_criteria.append(
            Q(created_by__last_name__icontains=value)
            & Q(created_by__last_name__isnull=False)
        )

        # Estimation requests business name search (exclude null and empty strings)
        search_criteria.append(
            Q(estimation_requests__business__name__icontains=value)
            & Q(estimation_requests__business__name__isnull=False)
            & ~Q(estimation_requests__business__name="")
        )

        # Combine all search criteria with OR
        combined_query = search_criteria[0]
        for criteria in search_criteria[1:]:
            combined_query |= criteria

        return queryset.filter(combined_query).distinct()


class JewelryProductionFilter(django_filters.FilterSet):
    production_status = django_filters.MultipleChoiceFilter(
        method="filter_by_production_status",
        choices=ProductionStatus.choices,
        label="Production Status",
    )
    admin_inspection_status = django_filters.MultipleChoiceFilter(
        method="filter_by_admin_inspection_status",
        choices=InspectionStatus.choices,
        label="Inspection Status",
    )
    is_jeweler_approved = django_filters.BooleanFilter(
        field_name="is_jeweler_approved",
        label="Is Jeweler Approved",
    )
    is_payment_completed = django_filters.BooleanFilter(
        field_name="is_payment_completed",
        label="Is Payment Completed",
    )
    ordering = django_filters.OrderingFilter(
        fields=(("created_at", "created_at"),),
    )
    created_at_min = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_max = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    business_name = django_filters.CharFilter(
        method="filter_by_business_name_or_user_fullname",
        label="Business Name or User Full Name",
    )

    class Meta:
        model = JewelryProduction
        fields = [
            "production_status",
            "admin_inspection_status",
            "is_jeweler_approved",
            "created_at_min",
            "created_at_max",
            "business_name",
            "is_payment_completed",
        ]

    def filter_by_production_status(self, queryset, name, value):
        if value:
            return queryset.filter(production_status__in=value)
        return queryset

    def filter_by_admin_inspection_status(self, queryset, name, value):
        if value:
            return queryset.filter(admin_inspection_status__in=value)
        return queryset

    def filter_by_business_name_or_user_fullname(self, queryset, name, value):
        if not value:
            return queryset

        # Create search criteria for different fields
        search_criteria = []

        # Manufacturer name search (exclude null and empty strings)
        search_criteria.append(
            Q(manufacturer__name__icontains=value)
            & Q(manufacturer__name__isnull=False)
            & ~Q(manufacturer__name="")
        )

        # User name searches (exclude null values)
        search_criteria.append(
            Q(manufacturing_request__created_by__first_name__icontains=value)
            & Q(manufacturing_request__created_by__first_name__isnull=False)
        )
        search_criteria.append(
            Q(manufacturing_request__created_by__middle_name__icontains=value)
            & Q(manufacturing_request__created_by__middle_name__isnull=False)
        )
        search_criteria.append(
            Q(manufacturing_request__created_by__last_name__icontains=value)
            & Q(manufacturing_request__created_by__last_name__isnull=False)
        )

        # Combine all search criteria with OR
        combined_query = search_criteria[0]
        for criteria in search_criteria[1:]:
            combined_query |= criteria

        return queryset.filter(combined_query).distinct()
