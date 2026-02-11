from datetime import datetime
from datetime import time

import django_filters
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django_filters import rest_framework as filters

from account.models import BusinessAccount
from sooq_althahab.enums.account import RiskLevel
from sooq_althahab.enums.jeweler import DesignType
from sooq_althahab.enums.jeweler import ManufacturingStatus
from sooq_althahab.enums.jeweler import MusharakahContractStatus
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab_admin.models import MusharakahDurationChoices

from .models import JewelryDesign
from .models import ManufacturingRequest
from .models import MusharakahContractRequest


class JewelryDesignFilter(django_filters.FilterSet):
    design_type = django_filters.CharFilter(lookup_expr="exact")
    name = django_filters.CharFilter(lookup_expr="icontains")
    ordering = django_filters.OrderingFilter(
        fields=(("created_at", "created_at")),
        label="Ordering",
    )

    class Meta:
        model = JewelryDesign
        fields = ["design_type", "name"]


class MusharakahContractRequestFilter(django_filters.FilterSet):
    business_name = django_filters.CharFilter(
        method="filter_by_business_name", label="Jeweler or Investor Business Name"
    )

    design_type = django_filters.ChoiceFilter(
        choices=DesignType.choices, field_name="design_type", required=False
    )

    status = filters.MultipleChoiceFilter(
        choices=RequestStatus.choices, method="filter_status"
    )

    musharakah_contract_status = filters.MultipleChoiceFilter(
        choices=MusharakahContractStatus.choices,
        method="filter_musharakah_contract_status",
    )

    min_target = django_filters.NumberFilter(
        field_name="target", lookup_expr="gte", label="Minimum Target Weight"
    )

    max_target = django_filters.NumberFilter(
        field_name="target", lookup_expr="lte", label="Maximum Target Weight"
    )

    ordering = django_filters.OrderingFilter(
        fields=(("created_at", "created_at")),
        label="Ordering",
    )

    risk_level = filters.MultipleChoiceFilter(
        choices=RiskLevel.choices,
        method="filter_risk_level",
    )

    history_data = django_filters.BooleanFilter(
        method="filter_history_data",
        label="Include History Data (only boolean value (true/false))",
        help_text="Include history data in the results.",
    )

    duration_in_days = django_filters.ModelChoiceFilter(
        queryset=MusharakahDurationChoices.objects.all(),
        field_name="duration_in_days",
        label="Duration (in days)",
        help_text="Select duration from available admin-defined options.",
    )

    class Meta:
        model = MusharakahContractRequest
        fields = [
            "business_name",
            "design_type",
            "status",
            "musharakah_contract_status",
            "min_target",
            "max_target",
            "history_data",
            "risk_level",
            "duration_in_days",
        ]

    def filter_status(self, queryset, name, value):
        """Custom filtering for status field."""

        if value:
            return queryset.filter(status__in=value)
        return queryset

    def filter_musharakah_contract_status(self, queryset, name, value):
        """Custom filtering for musharakah contract status field."""

        if value:
            return queryset.filter(musharakah_contract_status__in=value)
        return queryset

    def filter_by_business_name(self, queryset, name, value):
        return queryset.filter(
            Q(jeweler__name__icontains=value) | Q(investor__name__icontains=value)
        )

    def filter_history_data(self, queryset, name, value):
        if value:
            return queryset.filter(
                Q(status=RequestStatus.REJECTED)
                | Q(
                    musharakah_contract_status__in=[
                        MusharakahContractStatus.TERMINATED,
                        MusharakahContractStatus.COMPLETED,
                    ]
                )
            )
        return queryset

    def filter_risk_level(self, queryset, name, value):
        """Custom filtering for risk level field."""

        if value:
            return queryset.filter(risk_level__in=value)
        return queryset


class ManufacturerBusinessFilter(django_filters.FilterSet):
    """Filter for manufacturer business accounts."""

    name = django_filters.CharFilter(lookup_expr="icontains", label="Business Name")

    class Meta:
        model = BusinessAccount
        fields = ["name"]


class ManufacturingRequestFilter(django_filters.FilterSet):
    status = filters.MultipleChoiceFilter(
        choices=ManufacturingStatus.choices, method="filter_status"
    )
    design_type = django_filters.CharFilter(
        field_name="design__design_type", lookup_expr="iexact"
    )
    ordering = django_filters.OrderingFilter(
        fields=(("created_at", "created_at"),),
    )

    class Meta:
        model = ManufacturingRequest
        fields = ["status", "design_type"]

    def filter_status(self, queryset, name, value):
        """Custom filtering for status field."""

        if value:
            return queryset.filter(status__in=value)
        return queryset
